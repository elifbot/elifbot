"""Anahtarsız sinyal tarayıcı — tüm sembolleri tarar, tablo + CSV + Telegram.

`python main.py scan` ile çalışır; fetch_ohlcv/funding/OI public uçlar olduğu
için API anahtarı GEREKMEZ.
"""
import csv
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from core.strategy import ConfluenceStrategy, mtf_trend_series
from core.risk import RiskManager
from core.notify import Notifier

log = logging.getLogger('bot')

SIDE_TXT = {1: 'LONG', -1: 'SHORT', 0: '-'}


class SignalScanner:
    def __init__(self, ex, cfg, tf=None):
        self.ex = ex
        self.cfg = cfg
        self.tf = tf or cfg['timeframe']
        self.strat = ConfluenceStrategy(cfg['strategy'])
        self.risk = RiskManager(cfg['risk'])
        self.notifier = Notifier()
        self.csv_path = cfg.get('scan', {}).get('csv', 'signals.csv')
        st = cfg['strategy']
        self.mtf_tf = st['mtf_timeframe']
        self.mtf_fast = int(st['mtf_fast'])
        self.mtf_slow = int(st['mtf_slow'])

    def scan_once(self):
        rows = []
        for sym in self.cfg['symbols']:
            try:
                df = self.ex.ohlcv(sym, self.tf, 400).iloc[:-1]
                dh = self.ex.ohlcv(sym, self.mtf_tf, self.mtf_slow + 120).iloc[:-1]
            except Exception as e:
                log.warning(f'{sym}: veri alınamadı: {e}')
                continue
            tser = mtf_trend_series(dh, df.index, self.mtf_fast, self.mtf_slow)
            v = tser.iloc[-1] if len(tser) else None
            mtf = None if v is None or pd.isna(v) else int(v)
            sig = self.strat.evaluate(df, mtf_trend=mtf)
            fr = self.ex.funding_rate(sym)
            oi = self.ex.open_interest_delta(sym)
            atr_pct = sig.atrv / sig.price * 100 if sig.price else None

            row = {
                'zaman': datetime.now(timezone.utc).strftime('%m-%d %H:%M'),
                'sembol': sym,
                'fiyat': round(sig.price, 6) if sig.price else None,
                'atr%': round(atr_pct, 2) if atr_pct else None,
                'sinyal': SIDE_TXT.get(sig.side),
                'puan': sig.score,
                'mtf': {1: '↑', -1: '↓', 0: '='}.get(mtf, '?'),
                'funding%': round(fr * 100, 4) if fr is not None else None,
                'OIΔ%': round(oi, 1) if oi is not None else None,
                'gerekce': ','.join(sig.reasons) or '-',
            }
            if sig.side != 0 and sig.atrv > 0:
                lb = int(self.cfg['risk'].get('swing_lookback', 20))
                sl_out = self.risk.plan(
                    sig.price, sig.side, sig.atrv,
                    float(df['low'].rolling(lb).min().iloc[-1]),
                    float(df['high'].rolling(lb).max().iloc[-1]),
                    base_lev=int(self.cfg['leverage']))
                if sl_out:
                    sl, lev = sl_out
                    risk0 = abs(sig.price - sl)
                    tp1, tp2 = self.risk.tp_prices(sig.price, sig.side, risk0)
                    row['sl'] = round(sl, 6)
                    row['tp1'] = round(tp1, 6)
                    row['tp2'] = round(tp2, 6)
                    row['lev'] = lev
            rows.append(row)

        dfr = pd.DataFrame(rows)
        print('\n' + dfr.to_string(index=False))
        fired = [r for r in rows if r['sinyal'] in ('LONG', 'SHORT')]
        if fired:
            self._append_csv(fired)
            for r in fired:
                self.notifier.send(
                    f"📡 SİNYAL {r['sembol']} {r['sinyal']} (puan {r['puan']}, "
                    f"{r.get('lev', '?')}x)\n"
                    f"giriş≈{r['fiyat']} sl={r.get('sl')} "
                    f"tp1={r.get('tp1')} tp2={r.get('tp2')}\n"
                    f"funding={r['funding%']}% OIΔ={r['OIΔ']}%\n"
                    f"{r['gerekce']}")
        return rows

    def _append_csv(self, fired):
        new = not os.path.exists(self.csv_path)
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(fired[0].keys()))
            if new:
                w.writeheader()
            w.writerows(fired)
        log.info(f"{len(fired)} sinyal → {self.csv_path}")
