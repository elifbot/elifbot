"""Phoenix Bot v2 — ÖZ TEST
Tüm bileşenleri sentetik veriyle doğrular. Canlıya çıkmadan önce çalıştırın:
  python selftest.py     → tümü [OK] olmalı, aksi halde çıkış kodu 1
"""
import os
import sys
import time

import numpy as np
import pandas as pd

from core.indicators import ema, rsi, atr, adx, macd, bollinger
from core.strategy import ConfluenceStrategy, Signal, mtf_trend_series
from core.risk import RiskManager
from core.config import load_config, DEFAULTS

FAIL = []


def check(name, cond, extra=''):
    print(f"  [{'OK' if cond else 'HATA'}] {name} {extra}")
    if not cond:
        FAIL.append(name)


def synth(n=500, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    openp = np.roll(close, 1)
    openp[0] = close[0]
    vol = rng.uniform(100, 1000, n)
    idx = pd.date_range('2024-01-01', periods=n, freq='15min', tz='UTC')
    return pd.DataFrame({'open': openp, 'high': high, 'low': low,
                         'close': close, 'volume': vol}, index=idx)


print('== PHOENIX BOT ÖZ TEST ==')
df = synth()

print('-- göstergeler --')
e = ema(df.close, 21)
check('EMA boyut', len(e) == len(df))
r = rsi(df.close, 14)
check('RSI 0-100 aralık', bool(((r.dropna() >= 0) & (r.dropna() <= 100)).all()))
a = atr(df.high, df.low, df.close, 14)
check('ATR > 0', bool((a.dropna() > 0).all()))
x, pdi, mdi = adx(df.high, df.low, df.close, 14)
check('ADX sonlu', bool(np.isfinite(x.dropna()).all()))
_, _, mh = macd(df.close)
check('MACD hist boyut', len(mh) == len(df))
bu, bm, bl = bollinger(df.close)
check('BB üst ≥ alt', bool((bu.dropna() >= bl.dropna()).all()))

print('-- strateji --')
strat = ConfluenceStrategy(DEFAULTS['strategy'])
sig = strat.evaluate(df.iloc[:300])
check('sinyal tipi geçerli', sig.side in (-1, 0, 1))
check('puan 0-7 aralık', 0 <= sig.score <= 7, f'skor={sig.score}')
sig2 = strat.evaluate(df)
check('ATR dolu', sig2.atrv > 0)

print('-- MTF --')
dh = df.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min',
                            'close': 'last', 'volume': 'sum'}).dropna()
ts = mtf_trend_series(dh, df.index, 20, 50)
check('MTF serisi üretildi', len(ts) == len(df))
check('MTF değerleri -1/0/1 veya NaN',
      bool(ts.dropna().isin([-1.0, 0.0, 1.0]).all()))

print('-- risk: boyutlandırma --')
rm = RiskManager(DEFAULTS['risk'])
q = rm.position_size(10000, 100, 99, 5)
check('qty = risk/mesafe', abs(q - 100) < 1e-6, f'qty={q:.2f}')
q2 = rm.position_size(10000, 100, 99.9, 5)
check('notional/kaldıraç tavanı', abs(q2 - 500) < 1e-6, f'qty={q2:.2f}')

print('-- risk: stop planı + kaldıraç merdiveni --')
p = rm.plan(100, 1, 1.0, swing_low=97.0, base_lev=10)
check('plan üretildi', p is not None)
sl, lev = p
check('long stop < fiyat', sl < 100, f'sl={sl:.3f}')
check('swing stop daha genişse seçilir', sl <= 100 - 1.5, f'sl={sl:.3f}')
p_wide = rm.plan(100, 1, 4.8, swing_low=93.0, base_lev=10)
check('kaldıraç merdiveni (geniş stop → kaldıraç düşer)',
      p_wide is not None and p_wide[1] == 8, f'lev={p_wide[1] if p_wide else None}')
p2 = rm.plan(100, 1, 0.1, swing_low=99.9, base_lev=10)
check('dar stop → taban kaldıraç (tavan)', p2 is not None and p2[1] == 10,
      f'lev={p2[1] if p2 else None}')
p3 = rm.plan(100, 1, 20.0, base_lev=10)   # %30 stop → max_stop_pct reddi
check('aşırı geniş stop reddedilir', p3 is None)

print('-- risk: TP / kilit --')
tp1, tp2 = rm.tp_prices(100, 1, 1.0)
check('TP1/TP2 R-planı', abs(tp1 - 101) < 1e-9 and abs(tp2 - 102) < 1e-9)
s_lock = rm.lock_stop(100, 1, 1.0, mfe_r=1.5, cur_sl=99.0)
check('kilit +1R MFE\'de başabaş', abs(s_lock - 100.5) < 1e-9, f'sl={s_lock}')
s_lock2 = rm.lock_stop(100, -1, 1.0, mfe_r=1.5, cur_sl=101.0)
check('short kilitleme yönü doğru', abs(s_lock2 - 99.5) < 1e-9, f'sl={s_lock2}')

print('-- risk: izinler / vetolar --')
ok, _ = rm.can_open(2, 1, -2.0, -3.0)
check('giriş serbest', ok)
ok2, why2 = rm.can_open(3, 0, 0.0, 0.0)
check('max pozisyon engel', not ok2, why2)
ok3, why3 = rm.can_open(1, 2, 0.0, 0.0)
check('aynı yön limiti', not ok3, why3)
ok4, why4 = rm.can_open(1, 0, -6.0, 0.0)
check('günlük devre kesici', not ok4, why4)
ok5, why5 = rm.can_open(1, 0, 0.0, -15.0)
check('haftalık limit', not ok5, why5)
f1, _ = rm.funding_ok(1, 0.001)
check('funding veto long', not f1)
f2, _ = rm.funding_ok(-1, 0.001)
check('funding short serbest', f2)
f3, _ = rm.funding_ok(1, None)
check('funding None → serbest', f3)
o1, _ = rm.oi_ok(1, -8.0)
check('OI çöküş vetosu', not o1)
o2, _ = rm.oi_ok(1, 2.0)
check('OI normal → serbest', o2)

print('-- paper yaşam döngüsü (stub borsa) --')


class StubEx:
    def __init__(self):
        self.paper = 10000.0
        self.dry = True

    def ohlcv(self, sym, tf, limit=400):
        return df

    def balance_usdt(self):
        return self.paper

    def funding_rate(self, sym):
        return None

    def open_interest_delta(self, sym):
        return None

    def ensure_leverage(self, *a, **k):
        pass

    def amount_precision(self, sym, q):
        return q

    def market_order(self, *a, **k):
        return {'id': 'x'}

    def stop_orders(self, *a, **k):
        pass

    def cancel_stops(self, *a, **k):
        pass

    def positions(self, sym):
        return []


from core.trader import Trader  # noqa: E402

cfg = load_config('config.yaml')
tr = Trader(StubEx(), cfg, tf_override='15m')
# açılış testi için kontrollü, dar bantlı veri (swing ~99.5)
df_stable = pd.DataFrame(
    {'open': 100.0, 'high': 100.5, 'low': 99.5, 'close': 100.0, 'volume': 100.0},
    index=pd.date_range('2024-06-01', periods=60, freq='15min', tz='UTC'))
sig_t = Signal(side=1, score=5, reasons=['test'], atrv=1.0, price=100.0)
tr._open('TEST/USDT:USDT', sig_t, df_stable)
pos = tr.state.get('TEST/USDT:USDT')
check('pozisyon açıldı', pos is not None)
if pos:
    check('boyut = sermaye×%1 / mesafe',
          abs(pos['qty'] - 10000 * 0.01 / pos['risk0']) < 1e-6,
          f"qty={pos['qty']:.2f}")
    eq0 = tr.ex.paper
    # TP1 mumu: high tp1'i aşar, low stopun üstünde
    ts0 = pos['entry']
    bar_tp1 = pd.Series({'open': ts0, 'high': pos['tp1'] * 1.001,
                         'low': ts0 - pos['risk0'] * 0.3,
                         'close': pos['tp1'] * 0.99, 'volume': 100})
    tr._manage_position('TEST/USDT:USDT', pos, bar_tp1, atrv=1.0)
    check('TP1 kısmi kapatıldı', pos.get('tp1_done') is True)
    check('TP1 sonrası stop ≥ başabaş (trailing sıkılaştırabilir)',
          pos['sl'] >= pos['entry'] - 1e-9, f"sl={pos['sl']:.4f}")
    check('kalan miktar', abs(pos['qty'] - pos['qty0'] * 0.5) < 1e-6)
    check('TP1 kârı işlendi', tr.ex.paper > eq0)
    # TP2 mumu
    bar_tp2 = pd.Series({'open': pos['entry'], 'high': pos['tp2'] * 1.001,
                         'low': pos['entry'], 'close': pos['tp2'], 'volume': 100})
    tr._manage_position('TEST/USDT:USDT', pos, bar_tp2, atrv=1.0)
    check('TP2 ile tam kapandı', 'TEST/USDT:USDT' not in tr.state)
    check('işlem günlüğü yazıldı', os.path.exists(tr.journal_path))
    # SL akışı
    tr._open('TEST/USDT:USDT', sig_t, df_stable)
    pos2 = tr.state.get('TEST/USDT:USDT')
    eq1 = tr.ex.paper
    bar_sl = pd.Series({'open': pos2['entry'], 'high': pos2['entry'] + 0.1,
                        'low': pos2['sl'] * 0.999, 'close': pos2['sl'], 'volume': 100})
    tr._manage_position('TEST/USDT:USDT', pos2, bar_sl, atrv=1.0)
    check('SL ile kapandı', 'TEST/USDT:USDT' not in tr.state)
    check('SL zararı işlendi', tr.ex.paper < eq1)
    check('soğuma kaydedildi', 'TEST/USDT:USDT' in tr.last_loss)
    for f in (tr.state_path, tr.journal_path):
        if os.path.exists(f):
            os.remove(f)

print('-- backtest dumanı --')
from backtest import run_backtest  # noqa: E402

bt_cfg = {'paper_equity': 10000, 'leverage': 5, 'strategy': dict(DEFAULTS['strategy']),
          'risk': dict(DEFAULTS['risk'])}
m, _ = run_backtest(df, dh, bt_cfg, {'taker': 0.0004, 'slippage': 0.0002})
check('backtest çalıştı', 'islem' in m, str(m))

print()
if FAIL:
    print('BAŞARISIZ:', FAIL)
    sys.exit(1)
print('TÜM TESTLER GEÇTİ ✔')
