"""Backtest — gerçek geçmiş veriyle test (komisyon + slipaj + kısmi TP + kilitler).

Kullanım:
  python backtest.py --symbol BTC/USDT:USDT --timeframe 15m --bars 1000
  python backtest.py --symbol ETH/USDT:USDT --folds 4    # fold-bazlı rapor
"""
import argparse

import numpy as np
import pandas as pd
import yaml

from core.strategy import ConfluenceStrategy, mtf_trend_series
from core.indicators import atr as atr_series


def _chunk_pnl(entry, px, qty, side, tk):
    """Bir kapanış parçasının net PnL'i (komisyon dahil)."""
    return (px - entry) * qty * side - (entry + px) * qty * tk


def run_backtest(df, dh, cfg, fees):
    """Kapalı mumda sinyal, sonraki mum açılışında giriş.
    Aynı mumda hem SL hem TP denk gelirse SL sayılır (ihtiyatlı).
    trades listesi: pozisyon başına TAM yaşam döngüsü net PnL'i (USDT)."""
    strat = ConfluenceStrategy(cfg['strategy'])
    rc = cfg['risk']
    tk = float(fees.get('taker', 0.0004))
    slip = float(fees.get('slippage', 0.0002))
    thr = int(cfg['strategy']['score_threshold'])

    trend = mtf_trend_series(dh, df.index,
                             int(cfg['strategy']['mtf_fast']),
                             int(cfg['strategy']['mtf_slow']))
    atrv = atr_series(df.high, df.low, df.close, cfg['strategy']['atr_len'])
    lb = int(rc.get('swing_lookback', 20))
    swing_low = df['low'].rolling(lb).min()
    swing_high = df['high'].rolling(lb).max()

    equity = eq0 = float(cfg.get('paper_equity', 10000))
    trades, pos = [], None
    start = int(cfg['strategy']['ema_trend']) + 5

    for i in range(start, len(df) - 1):
        if pos:
            bar = df.iloc[i]
            side = int(pos['side'])
            long = side > 0
            done = False

            hit_sl = bar.low <= pos['sl'] if long else bar.high >= pos['sl']
            hit_tp2 = bar.high >= pos['tp2'] if long else bar.low <= pos['tp2']
            if hit_sl:                                  # ihtiyatlı: SL önce
                px = pos['sl'] * (1 - slip * side)
                equity += _chunk_pnl(pos['entry'], px, pos['qty'], side, tk)
                pos['pnl'] += _chunk_pnl(pos['entry'], px, pos['qty'], side, tk)
                trades.append(pos['pnl'])
                pos = None
                done = True
            elif hit_tp2:
                px = pos['tp2'] * (1 - slip * side)
                equity += _chunk_pnl(pos['entry'], px, pos['qty'], side, tk)
                pos['pnl'] += _chunk_pnl(pos['entry'], px, pos['qty'], side, tk)
                trades.append(pos['pnl'])
                pos = None
                done = True
            if done:
                continue

            if (not pos['tp1_done']) and (
                    bar.high >= pos['tp1'] if long else bar.low <= pos['tp1']):
                px = pos['tp1'] * (1 - slip * side)
                part = float(rc['tp1_close_pct']) / 100.0
                closed = pos['qty'] * part
                pnl = _chunk_pnl(pos['entry'], px, closed, side, tk)
                equity += pnl
                pos['pnl'] += pnl
                pos['qty'] -= closed
                pos['sl'] = float(pos['entry'])
                pos['tp1_done'] = True

            # kilit merdiveni + ATR trailing
            atrv_i = float(atrv.iloc[i])
            entry = float(pos['entry'])
            risk0 = float(pos['risk0'])
            if long:
                pos['peak'] = max(float(pos['peak']), float(bar.high))
                mfe_r = (float(pos['peak']) - entry) / risk0
            else:
                pos['trough'] = min(float(pos['trough']), float(bar.low))
                mfe_r = (entry - float(pos['trough'])) / risk0
            for trig, lock in (rc.get('profit_lock') or []):
                if mfe_r >= trig:
                    cand = entry + side * lock * risk0
                    pos['sl'] = max(pos['sl'], cand) if long else min(pos['sl'], cand)
            trail = (float(pos['peak']) - rc['trailing_atr_mult'] * atrv_i) if long \
                else (float(pos['trough']) + rc['trailing_atr_mult'] * atrv_i)
            if long and trail > pos['sl']:
                pos['sl'] = trail
            if (not long) and trail < pos['sl']:
                pos['sl'] = trail
            continue

        if pd.isna(atrv.iloc[i]) or pd.isna(atrv.iloc[i - 1]):
            continue
        tv = trend.iloc[i] if len(trend) else None
        mtf = None if tv is None or pd.isna(tv) else int(tv)
        sig = strat.evaluate(df.iloc[:i + 1], mtf_trend=mtf)
        if sig.side == 0 or sig.score < thr:
            continue
        entry = float(df.iloc[i + 1]['open']) * (1 + slip * sig.side)
        plan = _plan_from(cfg, float(swing_low.iloc[i]), float(swing_high.iloc[i]),
                          entry, sig.side, float(atrv.iloc[i]))
        if plan is None:
            continue
        sl, lev = plan
        dist = abs(entry - sl)
        if dist <= 0 or equity <= 0:
            continue
        qty = min(equity * rc['risk_per_trade_pct'] / 100 / dist,
                  equity * lev / entry)
        if qty <= 0:
            continue
        pos = dict(side=int(sig.side), entry=entry, sl=sl,
                   tp1=entry + sig.side * rc['tp1_r'] * dist,
                   tp2=entry + sig.side * rc['tp2_r'] * dist,
                   tp1_done=False, qty=qty, qty0=qty, risk0=dist,
                   peak=entry, trough=entry, pnl=0.0)

    return summarize(trades, equity, eq0), trades


def _plan_from(cfg, sw_low, sw_high, price, side, atrv):
    """Backtest içinde RiskManager.plan ile aynı mantık."""
    rc = cfg['risk']
    if atrv <= 0 or price <= 0:
        return None
    if side > 0:
        sl = price - rc['sl_atr_mult'] * atrv
        if sw_low and sw_low > 0:
            sl = min(sl, sw_low - rc.get('swing_buffer_atr', 0.2) * atrv)
    else:
        sl = price + rc['sl_atr_mult'] * atrv
        if sw_high and sw_high > 0:
            sl = max(sl, sw_high + rc.get('swing_buffer_atr', 0.2) * atrv)
    dist_pct = abs(price - sl) / price * 100
    if dist_pct > rc['max_stop_pct']:
        return None
    dist = abs(price - sl) / price
    safe = int(1.0 / (dist * 1.4)) if dist > 0 else 1
    lev = max(1, min(int(cfg['leverage']), int(rc['max_leverage']), safe))
    return sl, lev


def summarize(trades, equity, eq0):
    if not trades:
        return {'islem': 0}
    t = np.array(trades)
    wins, losses = t[t > 0], t[t <= 0]
    curve = eq0 + np.cumsum(t)
    peak = np.maximum.accumulate(curve)
    mdd = float(((curve - peak) / peak).min() * 100)
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and \
        losses.sum() != 0 else float('inf')
    return {
        'islem': len(t),
        'kazanma_%': round(100 * len(wins) / len(t), 1),
        'kar_faktoru': round(pf, 2),
        'ort_kar': round(float(wins.mean()), 2) if len(wins) else 0.0,
        'ort_zarar': round(float(losses.mean()), 2) if len(losses) else 0.0,
        'net': round(equity - eq0, 2),
        'getiri_%': round((equity / eq0 - 1) * 100, 2),
        'max_dusus_%': round(mdd, 1),
        'son_sermaye': round(equity, 2),
    }


def fetch_data(symbol, tf, bars, mtf_tf, mtf_slow, exchange='binanceusdm'):
    import ccxt
    x = getattr(ccxt, exchange)({'enableRateLimit': True})   # kamu verisi, anahtar yok

    def pull(tf_, limit):
        raw = x.fetch_ohlcv(symbol, tf_, limit=min(limit, 1500))
        d = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        d['ts'] = pd.to_datetime(d.ts, unit='ms', utc=True)
        return d.set_index('ts').iloc[:-1]            # oluşan mumu at

    return pull(tf, bars), pull(mtf_tf, mtf_slow + 120)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbol', default='BTC/USDT:USDT')
    ap.add_argument('--timeframe', default='15m')
    ap.add_argument('--bars', type=int, default=1000)
    ap.add_argument('--folds', type=int, default=0,
                    help='böl ve raporla: N parçada ayrı sonuç (sağlamlık kontrolü)')
    ap.add_argument('--config', default='config.yaml')
    a = ap.parse_args()

    with open(a.config, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    st = cfg['strategy']
    df, dh = fetch_data(a.symbol, a.timeframe, a.bars, st.get('mtf_timeframe', '1h'),
                        int(st.get('mtf_slow', 200)), exchange=cfg['exchange'])
    fees = cfg.get('fees', {'taker': 0.0004, 'slippage': 0.0002})

    print(f'\n=== BACKTEST {a.symbol} {a.timeframe} ({len(df)} mum) ===')
    if a.folds > 1:
        n = len(df)
        chunk = n // a.folds
        need = int(st['ema_trend']) + 60
        for k in range(a.folds):
            seg = df.iloc[k * chunk:(k + 1) * chunk]
            if len(seg) < need:
                print(f'  fold {k+1}: yetersiz veri ({len(seg)} mum), atlandı')
                continue
            seg_dh = dh[dh.index <= seg.index[-1]]
            m, _ = run_backtest(seg, seg_dh, cfg, fees)
            print(f'  fold {k+1} [{seg.index[0].date()}..{seg.index[-1].date()}]: {m}')
    else:
        m, _ = run_backtest(df, dh, cfg, fees)
        for k, v in m.items():
            print(f'  {k:14}: {v}')
