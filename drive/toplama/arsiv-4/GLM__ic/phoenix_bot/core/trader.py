"""İşlem motoru: paper/canlı pozisyon yaşam döngüsü, kısmi TP, kilit merdiveni,
mutabakat, kalıcılık, günlük ve devre kesici.

Yaşam döngüsü:
  sinyal → vetolar (funding/OI/limit/soğuma) → stop planı (ATR+swing, kaldıraç
  merdiveni) → boyutlandırma → giriş + koruma emirleri (SL, TP1, TP2)
  → TP1 (1R, %50) → stop başabaşa → MFE kilit merdiveni → ATR trailing
  → TP2 (2R) veya SL.
"""
import csv
import json
import logging
import os
import time
from datetime import datetime, timezone

import pandas as pd

from core.strategy import ConfluenceStrategy, mtf_trend_series
from core.risk import RiskManager
from core.indicators import atr as atr_series
from core.notify import Notifier

log = logging.getLogger('bot')


class Trader:
    def __init__(self, ex, cfg, tf_override=None):
        self.ex = ex
        self.cfg = cfg
        self.tf = tf_override or cfg['timeframe']
        self.tf_sec = pd.Timedelta(self.tf).total_seconds()
        self.strat = ConfluenceStrategy(cfg['strategy'])
        self.risk = RiskManager(cfg['risk'])
        self.notifier = Notifier()
        self.state_path = f'state_{self.tf}.json'
        self.journal_path = f'trades_{self.tf}.csv'
        self.state = {}
        self.day = None
        self.day_equity0 = 0.0
        self.week = None
        self.week_equity0 = 0.0
        self.last_loss = {}          # symbol -> unix ts (soğuma)
        self.order_errors = 0
        self.tripped = False         # devre kesici
        self._load()

    # ================= kalıcılık =================
    def _load(self):
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            bak = self.state_path + '.bozuk'
            try:
                os.replace(self.state_path, bak)
                log.error(f'durum dosyası bozuk, yedeklendi: {bak} ({e})')
            except OSError:
                log.error(f'durum dosyası okunamadı: {e}')
            return
        try:
            self.day = data.get('day')
            self.day_equity0 = float(data.get('day_equity0') or 0)
            self.week = data.get('week')
            self.week_equity0 = float(data.get('week_equity0') or 0)
            self.last_loss = {k: float(v) for k, v in
                              (data.get('last_loss') or {}).items()}
            if self.ex.dry:
                self.ex.paper = float(data.get('equity') or self.ex.paper)
            self.state = data.get('positions') or {}
            log.info(f'durum yüklendi: {self.state_path} | pozisyon={len(self.state)}'
                     + (f' | paper sermaye={self.ex.paper:.2f}' if self.ex.dry else ''))
        except Exception as e:
            log.warning(f'durum okuma uyarısı: {e}')

    def _save(self):
        data = {
            'equity': self.ex.paper if self.ex.dry else None,
            'day': self.day, 'day_equity0': self.day_equity0,
            'week': self.week, 'week_equity0': self.week_equity0,
            'last_loss': self.last_loss,
            'positions': self.state,
        }
        try:
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning(f'durum kaydedilemedi: {e}')

    # ================= limitler =================
    def _roll(self, equity):
        now = datetime.now(timezone.utc)
        d = str(now.date())
        iso = now.isocalendar()
        w = f'{iso.year}-W{iso.week:02d}'
        changed = False
        if self.day != d:
            self.day, self.day_equity0 = d, equity
            changed = True
        if self.week != w:
            self.week, self.week_equity0 = w, equity
            changed = True
        if changed:
            self._save()

    def _limits_ok(self, equity):
        rc = self.cfg['risk']
        msgs = []
        if self.day_equity0 > 0:
            dl = (equity - self.day_equity0) / self.day_equity0 * 100
            if dl <= -rc['max_daily_loss_pct']:
                msgs.append(f'günlük zarar {dl:.1f}% ≥ %{rc["max_daily_loss_pct"]}')
        if self.week_equity0 > 0:
            wl = (equity - self.week_equity0) / self.week_equity0 * 100
            if wl <= -rc['max_weekly_loss_pct']:
                msgs.append(f'haftalık zarar {wl:.1f}% ≥ %{rc["max_weekly_loss_pct"]}')
        return (not msgs), '; '.join(msgs)

    # ================= emir hatası sigortası =================
    def _guarded(self, fn, symbol, what):
        try:
            fn()
            self.order_errors = 0
            return True
        except Exception as e:
            self.order_errors += 1
            limit = int(self.cfg['risk'].get('order_error_limit', 3))
            log.error(f'[{symbol}] emir hatası ({what}) '
                      f'{self.order_errors}/{limit}: {e}')
            if self.order_errors >= limit:
                self.tripped = True
                log.critical('DEVRE KESİCİ: art arda emir hataları. '
                             'Yeni işlem açılmayacak; sorunu çözüp yeniden başlatın.')
                self.notifier.send(f'🚨 {symbol}: devre kesici tetiklendi '
                                   f'({what}: {e})')
            return False

    # ================= ana yönetim =================
    def manage(self, symbol, df):
        equity = self.ex.balance_usdt()
        self._roll(equity)
        self._reconcile(symbol, df)

        pos = self.state.get(symbol)
        bar = df.iloc[-1]
        if pos:
            atrv = float(atr_series(df.high, df.low, df.close,
                                    self.cfg['strategy']['atr_len']).iloc[-1])
            self._manage_position(symbol, pos, bar, atrv)
            return

        if self.tripped:
            log.warning(f'[{symbol}] devre kesici aktif → giriş yok')
            return
        ok, why = self._limits_ok(equity)
        if not ok:
            log.info(f'[{symbol}] giriş engelli: {why}')
            return
        n_same = sum(1 for p in self.state.values()
                     if int(p.get('side', 0)) == self._last_side_hint(df))
        ok, why = self.risk.can_open(len(self.state), n_same,
                                     self._day_loss(equity), self._week_loss(equity))
        if not ok:
            log.info(f'[{symbol}] giriş engelli: {why}')
            return
        cd = float(self.cfg['risk'].get('cooldown_bars', 0)) * self.tf_sec
        ll = self.last_loss.get(symbol, 0.0)
        if cd and time.time() - ll < cd:
            log.info(f'[{symbol}] soğuma: ~{int((cd - (time.time() - ll)) / 60)} dk')
            return

        mtf = self._mtf(symbol, df)
        sig = self.strat.evaluate(df, mtf_trend=mtf)
        if sig.side == 0 or sig.score < int(self.cfg['strategy']['score_threshold']):
            return

        fr = self.ex.funding_rate(symbol)
        ok, why = self.risk.funding_ok(sig.side, fr)
        if not ok:
            log.info(f'[{symbol}] sinyal var ama atlandı: {why}')
            return
        oi = self.ex.open_interest_delta(symbol)
        ok, why = self.risk.oi_ok(sig.side, oi)
        if not ok:
            log.info(f'[{symbol}] sinyal var ama atlandı: {why}')
            return

        self._open(symbol, sig, df)

    # ================= yardımcılar =================
    @staticmethod
    def _last_side_hint(df):
        return 1 if float(df.iloc[-1]['close']) > float(df.iloc[-1]['open']) else -1

    def _day_loss(self, equity):
        if self.day_equity0 <= 0:
            return 0.0
        return (equity - self.day_equity0) / self.day_equity0 * 100

    def _week_loss(self, equity):
        if self.week_equity0 <= 0:
            return 0.0
        return (equity - self.week_equity0) / self.week_equity0 * 100

    def _mtf(self, symbol, df):
        st = self.cfg['strategy']
        try:
            dh = self.ex.ohlcv(symbol, st['mtf_timeframe'],
                               int(st['mtf_slow']) + 120).iloc[:-1]
            tser = mtf_trend_series(dh, df.index,
                                    int(st['mtf_fast']), int(st['mtf_slow']))
            v = tser.iloc[-1] if len(tser) else None
            return None if v is None or pd.isna(v) else int(v)
        except Exception as e:
            log.warning(f'[{symbol}] MTF verisi alınamadı: {e}')
            return None

    # ================= açılış =================
    def _open(self, symbol, sig, df):
        rc = self.cfg['risk']
        side = int(sig.side)
        lb = int(rc.get('swing_lookback', 20))
        swing_low = float(df['low'].rolling(lb).min().iloc[-1])
        swing_high = float(df['high'].rolling(lb).max().iloc[-1])
        plan = self.risk.plan(sig.price, side, sig.atrv, swing_low, swing_high,
                              base_lev=int(self.cfg['leverage']))
        if plan is None:
            log.info(f'[{symbol}] stop planı reddi (mesafe > %{rc["max_stop_pct"]})')
            return
        sl, lev = plan

        slip = float(self.cfg['fees'].get('slippage', 0.0))
        entry = sig.price * (1 + slip * side)          # gerçekçi giriş (slipaj)
        risk0 = abs(entry - sl)
        tp1, tp2 = self.risk.tp_prices(entry, side, risk0)

        equity = self.ex.balance_usdt()
        qty = self.risk.position_size(equity, entry, sl, lev)
        if qty <= 0:
            return
        qty = self.ex.amount_precision(symbol, qty)
        if qty <= 0:
            return
        self.ex.ensure_leverage(symbol, lev)
        side_close = 'sell' if side > 0 else 'buy'
        ok1 = self._guarded(lambda: self.ex.market_order(
            symbol, 'buy' if side > 0 else 'sell', qty), symbol, 'giriş')
        if not ok1 and not self.ex.dry:
            return
        tp1_qty = self.ex.amount_precision(symbol, qty * rc['tp1_close_pct'] / 100.0)
        self._guarded(lambda: self.ex.stop_orders(
            symbol, side_close, qty, sl, tp2, tp1, tp1_qty), symbol, 'koruma')

        s_txt = 'LONG' if side > 0 else 'SHORT'
        log.info(f'[{symbol}] AÇ {s_txt} puan={sig.score} qty={qty} lev={lev}x '
                 f'giriş≈{entry:.6g} sl={sl:.6g} tp1={tp1:.6g} tp2={tp2:.6g} '
                 f'| {",".join(sig.reasons)}')
        self.notifier.send(
            f'🚀 {symbol} {s_txt} (puan {sig.score}, {lev}x)\n'
            f'giriş≈{entry:.6g}\nSL={sl:.6g} | TP1={tp1:.6g} | TP2={tp2:.6g}\n'
            f'{",".join(sig.reasons)}')
        self.state[symbol] = dict(
            side=side, qty=float(qty), qty0=float(qty), entry=float(entry),
            sl=float(sl), tp1=float(tp1), tp2=float(tp2), tp1_done=False,
            risk0=float(risk0), peak=float(entry), trough=float(entry),
            lev=int(lev), opened=datetime.now(timezone.utc).isoformat())
        self._save()

    # ================= pozisyon yönetimi =================
    def _manage_position(self, symbol, pos, bar, atrv):
        side = int(pos['side'])
        long = side > 0
        if self.ex.dry:
            # --- paper: dolguları simüle et (ihtiyatlı sıra: SL önce) ---
            slip = float(self.cfg['fees'].get('slippage', 0.0))
            hit_sl = bar.low <= pos['sl'] if long else bar.high >= pos['sl']
            hit_tp2 = bar.high >= pos['tp2'] if long else bar.low <= pos['tp2']
            if hit_sl:
                self._close(symbol, pos, pos['sl'] * (1 - slip * side), 'SL')
                return
            if hit_tp2:
                self._close(symbol, pos, pos['tp2'] * (1 - slip * side), 'TP2')
                return
            if (not pos.get('tp1_done')) and (
                    bar.high >= pos['tp1'] if long else bar.low <= pos['tp1']):
                px = pos['tp1'] * (1 - slip * side)
                self._close_partial(symbol, pos, px, 'TP1',
                                    float(self.cfg['risk']['tp1_close_pct']) / 100.0)
        self._update_locks(symbol, pos, bar, atrv)

    def _update_locks(self, symbol, pos, bar, atrv):
        rc = self.cfg['risk']
        side = int(pos['side'])
        entry = float(pos['entry'])
        risk0 = float(pos['risk0'])
        if side > 0:
            pos['peak'] = max(float(pos['peak']), float(bar.high))
            mfe_r = (float(pos['peak']) - entry) / risk0
        else:
            pos['trough'] = min(float(pos['trough']), float(bar.low))
            mfe_r = (entry - float(pos['trough'])) / risk0
        pos['sl'] = self.risk.lock_stop(entry, side, risk0, mfe_r, float(pos['sl']))
        trail = (float(pos['peak']) - rc['trailing_atr_mult'] * atrv) if side > 0 \
            else (float(pos['trough']) + rc['trailing_atr_mult'] * atrv)
        if side > 0 and trail > pos['sl']:
            pos['sl'] = trail
        if side < 0 and trail < pos['sl']:
            pos['sl'] = trail
        # canlıda stop fiyatını borsaya yansıt (anlamlı değişimde, gürültüyü önle)
        if abs(float(pos['sl']) - float(pos.get('sl_placed', pos['sl']))) > 0.15 * atrv:
            if not self.ex.dry:
                side_close = 'sell' if side > 0 else 'buy'
                tp1 = None if pos.get('tp1_done') else float(pos['tp1'])
                tp1_qty = self.ex.amount_precision(
                    symbol, float(pos['qty0']) *
                    float(self.cfg['risk']['tp1_close_pct']) / 100.0) \
                    if tp1 else 0.0
                ok = self._guarded(lambda: (
                    self.ex.cancel_stops(symbol),
                    self.ex.stop_orders(symbol, side_close, float(pos['qty']),
                                        float(pos['sl']), float(pos['tp2']),
                                        tp1, tp1_qty)), symbol, 'stop güncelleme')
                if ok:
                    pos['sl_placed'] = float(pos['sl'])
            else:
                pos['sl_placed'] = float(pos['sl'])

    # ================= kapanışlar =================
    def _record(self, symbol, pos, exit_price, reason, closed_qty) -> float:
        tk = float(self.cfg['fees']['taker'])
        side = int(pos['side'])
        entry = float(pos['entry'])
        gross = (exit_price - entry) * closed_qty * side
        fee = (entry + exit_price) * closed_qty * tk
        net = gross - fee
        if self.ex.dry:
            self.ex.paper += net
            if net < 0:
                self.last_loss[symbol] = time.time()
        new = not os.path.exists(self.journal_path)
        with open(self.journal_path, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if new:
                w.writerow(['zaman', 'sembol', 'yon', 'miktar', 'giris',
                            'cikis', 'pnl_usdt', 'sebep'])
            w.writerow([datetime.now(timezone.utc).isoformat(), symbol,
                        'LONG' if side > 0 else 'SHORT',
                        round(closed_qty, 8), round(entry, 8),
                        round(exit_price, 8), round(net, 4), reason])
        return net

    def _close(self, symbol, pos, exit_price, reason):
        net = self._record(symbol, pos, exit_price, reason, float(pos['qty']))
        self.ex.cancel_stops(symbol)
        eq = self.ex.balance_usdt()
        log.info(f'[{symbol}] KAPAN ({reason}) çıkış={exit_price:.6g} '
                 f'PnL={net:+.2f} | sermaye≈{eq:.2f}')
        self.notifier.send(f'✅ {symbol} kapandı ({reason})\n'
                           f'çıkış={exit_price:.6g}\nPnL: {net:+.2f} USDT\n'
                           f'Sermaye≈{eq:.2f}')
        self.state.pop(symbol, None)
        self._save()

    def _close_partial(self, symbol, pos, exit_price, reason, fraction):
        closed = float(pos['qty']) * fraction
        net = self._record(symbol, pos, exit_price, reason, closed)
        pos['qty'] = float(pos['qty']) - closed
        pos['sl'] = float(pos['entry'])        # başabaşa çek
        pos['tp1_done'] = True
        pos['sl_placed'] = float(pos['sl'])
        log.info(f'[{symbol}] KISMİ ({reason}) %{fraction*100:.0f} '
                 f'çıkış={exit_price:.6g} PnL={net:+.2f} | kalan={pos["qty"]:.6g} '
                 f'| stop başabaşa çekildi')
        self.notifier.send(f'💰 {symbol} TP1 doldu: %{fraction*100:.0f} kapatıldı '
                           f'(PnL {net:+.2f}), stop başabaşta, kalan={pos["qty"]:.6g}')
        if pos['qty'] <= 0:
            self.state.pop(symbol, None)
        self._save()

    # ================= mutabakat (canlı) =================
    def _reconcile(self, symbol, df):
        if self.ex.dry:
            return
        ps = self.ex.positions(symbol)
        px = float(df.iloc[-1]['close'])
        if ps and symbol not in self.state:
            # borsada var, kayıtta yok → sahiplen
            p = ps[0]
            side = 1 if (p.get('side') or 'long') == 'long' else -1
            entry = float(p.get('entryPrice') or px)
            qty = float(p.get('contracts') or 0)
            if qty <= 0:
                return
            atrv = float(atr_series(df.high, df.low, df.close,
                                    self.cfg['strategy']['atr_len']).iloc[-1])
            sl, lev = self.risk.plan(entry, side, atrv,
                                     base_lev=int(self.cfg['leverage'])) or \
                (entry - side * atrv * self.cfg['risk']['sl_atr_mult'],
                 int(self.cfg['leverage']))
            risk0 = abs(entry - sl)
            tp1, tp2 = self.risk.tp_prices(entry, side, risk0)
            log.warning(f'[{symbol}] borsada tanımsız pozisyon SAHİPLENİLDİ: '
                        f'{"LONG" if side > 0 else "SHORT"} qty={qty} giriş={entry}')
            self.ex.ensure_leverage(symbol, lev)
            side_close = 'sell' if side > 0 else 'buy'
            tp1_qty = self.ex.amount_precision(
                symbol, qty * float(self.cfg['risk']['tp1_close_pct']) / 100.0)
            self._guarded(lambda: self.ex.stop_orders(
                symbol, side_close, qty, sl, tp2, tp1, tp1_qty),
                symbol, 'sahiplenme koruması')
            self.state[symbol] = dict(
                side=side, qty=qty, qty0=qty, entry=entry, sl=float(sl),
                tp1=float(tp1), tp2=float(tp2), tp1_done=False, risk0=float(risk0),
                peak=entry, trough=entry, lev=int(lev),
                opened=datetime.now(timezone.utc).isoformat(), adopted=True)
            self._save()
        elif (not ps) and symbol in self.state:
            pos = self.state.pop(symbol)
            log.info(f'[{symbol}] borsada pozisyon yok → kayıt kapandı '
                     f'(SL/TP borsada dolmuş)')
            self._record(symbol, pos, px, 'borsa-kapanış', float(pos['qty']))
            self._save()
        elif ps and symbol in self.state:
            ex_qty = float(ps[0].get('contracts') or 0)
            pos = self.state[symbol]
            if (not pos.get('tp1_done')) and ex_qty < float(pos['qty']) * 0.95:
                # TP1 borsada dolmuş → kalan için stop başabaşa + TP2 yeniden
                pos['tp1_done'] = True
                pos['qty'] = ex_qty
                pos['sl'] = float(pos['entry'])
                side = int(pos['side'])
                side_close = 'sell' if side > 0 else 'buy'
                ok = self._guarded(lambda: (
                    self.ex.cancel_stops(symbol),
                    self.ex.stop_orders(symbol, side_close, ex_qty,
                                        float(pos['sl']), float(pos['tp2']))),
                    symbol, 'TP1 sonrası koruma')
                if ok:
                    pos['sl_placed'] = float(pos['sl'])
                self._save()
                log.info(f'[{symbol}] TP1 dolu (borsa) → kalan {ex_qty} için '
                         f'stop başabaşa çekildi')
            elif abs(ex_qty - float(pos['qty'])) / max(float(pos['qty']), 1e-9) > 0.02:
                log.warning(f'[{symbol}] miktar uyuşmazlığı: borsa={ex_qty} '
                            f'kayıt={pos["qty"]}')
