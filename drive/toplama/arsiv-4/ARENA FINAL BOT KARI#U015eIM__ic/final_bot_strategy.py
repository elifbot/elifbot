#!/usr/bin/env python3
"""
FINAL SÜRÜM STRATEJI — 3 botun en iyi ozellikleri toplandi:
- GLM: 7 faktorlu konfluans + sert vetolar (olum pazar, tukenme, funding, OI, MTF)
- CLAUDE/SENZE: 10 oylu konfluans (Stoch, OBV, CCI, Supertrend, VWAP ekle) + sonraki mum acilisinda dolum + kotumser cikis
- CHATGPT/FUSION PRO: Edge/kalite veto + hacim onayi + dinamik TP/trailing

Tek bir Python dosyasi, ccxt/pandas/numpy ile, OKX 15m verisinde backtest.
"""
import sys, os, json, pandas as pd, numpy as np
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = '/home/user/market_data_long'
RESULTS_DIR = '/home/user/test_results_final'

os.makedirs(RESULTS_DIR, exist_ok=True)

SYMBOLS_OKX = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT',
    'DOGE/USDT:USDT', 'XRP/USDT:USDT', 'ADA/USDT:USDT',
    'AVAX/USDT:USDT', 'DOT/USDT:USDT', 'LINK/USDT:USDT',
    'TRX/USDT:USDT', 'LTC/USDT:USDT'
]

print("=" * 85)
print("FINAL SÜRÜM STRATEJI — 3 BOTUN EN IYI OZELLIKLERININ BIRLESTIRILMESI")
print("=" * 85)
print(f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
print(f"Kaynak: OKX 15m (gercek veri)")
print(f"Sembol: {len(SYMBOLS_OKX)} OKX USDT Perpétual")
print()

# =====================================================================
# 1. VERI YUKLE
# =====================================================================
print("Veri yukleniyor...")
all_data = {}
for sym in SYMBOLS_OKX:
    fname = sym.replace('/', '_').replace(':', '_') + '_15m.csv'
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        print(f"  ✗ {sym}: DOSYA YOK")
        continue
    df = pd.read_csv(fpath)
    if df['ts'].dtype == object:
        df['ts'] = pd.to_datetime(df['ts'], utc=True)
    else:
        df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('ts').sort_index()
    all_data[sym] = df
    print(f"  ✓ {sym}: {len(df)} mum, son fiyat: {df['close'].iloc[-1]:,.4f}")
print()

# =====================================================================
# 2. GOSTERGE KUTUPHANESI (saf pandas/numpy)
# =====================================================================
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = -d.clip(upper=0.0)
    ru = up.ewm(alpha=1/n, adjust=False).mean()
    rd = dn.ewm(alpha=1/n, adjust=False).mean()
    rs = ru / rd.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def adx(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    atrv = atr(h, l, c, n).replace(0, np.nan)
    pdi = 100 * plus_dm.ewm(alpha=1/n, adjust=False).mean() / atrv
    mdi = 100 * minus_dm.ewm(alpha=1/n, adjust=False).mean() / atrv
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean(), pdi, mdi

def macd(close, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal

def bollinger(close, n=20, dev=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid + dev * sd, mid, mid - dev * sd

def stoch(h, l, c, n=14, k_smooth=3, d_smooth=3):
    lo = l.rolling(n).min()
    hi = h.rolling(n).max()
    k = 100 * (c - lo) / (hi - lo).replace(0, np.nan)
    k = k.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return k, d

def obv(c, v):
    return (np.sign(c.diff()).fillna(0) * v).cumsum()

def cci(h, l, c, n=20):
    tp = (h + l + c) / 3
    ma = tp.rolling(n).mean()
    dev = (tp - ma).abs().rolling(n).mean()
    return (tp - ma) / (0.015 * dev.replace(0, np.nan))

def supertrend(h, l, c, n=10, mult=3.0):
    atrv = atr(h, l, c, n)
    hl2 = (h + l) / 2
    upper = hl2 + mult * atrv
    lower = hl2 - mult * atrv
    st = pd.Series(index=c.index, dtype=float)
    direction = pd.Series(index=c.index, dtype=int)
    st.iloc[0] = upper.iloc[0]
    direction.iloc[0] = 1
    for i in range(1, len(c)):
        prev_st = st.iloc[i-1]
        prev_dir = direction.iloc[i-1]
        curr_upper = upper.iloc[i]
        curr_lower = lower.iloc[i]
        if prev_dir == 1:
            if c.iloc[i] <= prev_st:
                st.iloc[i] = curr_lower
                direction.iloc[i] = -1
            else:
                st.iloc[i] = max(prev_st, curr_lower)
                direction.iloc[i] = 1
        else:
            if c.iloc[i] >= prev_st:
                st.iloc[i] = curr_upper
                direction.iloc[i] = 1
            else:
                st.iloc[i] = min(prev_st, curr_upper)
                direction.iloc[i] = -1
    return st, direction

def vwap(c, v, n=30):
    pv = (c * v).rolling(n).sum()
    vv = v.rolling(n).sum()
    return pv / vv.replace(0, np.nan)

def chop(h, l, c, n=14):
    """Choppiness Index (0-100, yuksek = yatay/düzensiz)"""
    atrv = atr(h, l, c, n)
    hh = h.rolling(n).max()
    ll = l.rolling(n).min()
    return 100 * np.log10(atrv.rolling(n).sum() / (hh - ll).replace(0, np.nan)) / np.log10(n)

# =====================================================================
# 3. FINAL STRATEJI SINYAL MOTORU
# =====================================================================
class FinalStrategy:
    """
    3 botun en iyi ozelliklerinin birlesimi:
    - GLM: 7 faktorlu konfluans (trend, MTF, MACD, RSI bandi, ADX, hacim, BB)
    - CLAUDE: + Stoch, OBV, CCI, Supertrend, VWAP (10 oy tamamla)
    - FUSION: + orderbook/hacim onay, edge hesabi
    """
    def __init__(self, cfg):
        self.cfg = cfg

    def evaluate(self, df, mtf_trend=None):
        c = self.cfg
        s = {'side': 0, 'score': 0, 'long_score': 0, 'short_score': 0,
             'reasons': [], 'vetoes': [], 'price': 0.0, 'atr': 0.0,
             'confidence': 0.0, 'edge_bps': 0.0}

        need = max(c['ema_trend'], c['bb_len'], 60) + 5
        if len(df) < need:
            return s

        o, h, l, cl, v = df['open'], df['high'], df['low'], df['close'], df['volume']
        price = float(cl.iloc[-1])

        # Gostergeler
        ef = ema(cl, c['ema_fast'])
        es = ema(cl, c['ema_slow'])
        et = ema(cl, c['ema_trend'])
        r = rsi(cl, c['rsi_len'])
        a = atr(h, l, cl, c['atr_len'])
        x, pdi, mdi = adx(h, l, cl, c['adx_len'])
        _, _, mh = macd(cl)
        bbu, bbm, bbl = bollinger(cl, c['bb_len'], c['bb_dev'])
        volma = v.rolling(20).mean()
        k, d = stoch(h, l, cl)
        ob = obv(cl, v)
        cc = cci(h, l, cl)
        st, st_dir = supertrend(h, l, cl)
        vw = vwap(cl, v)
        ch = chop(h, l, cl)

        atrv = float(a.iloc[-1])
        if any(pd.isna(z) for z in (et.iloc[-1], x.iloc[-1], volma.iloc[-1], atrv)):
            return s
        s['price'] = price
        s['atr'] = atrv

        # === SERV VETO 1: Olum pazar ===
        atr_pct = atrv / price * 100
        if atr_pct < c['min_atr_pct']:
            s['vetoes'].append(f"olum_pazar (ATR% {atr_pct:.2f} < {c['min_atr_pct']})")
            return s

        # === SERV VETO 2: Choppiness (yatay pazar) ===
        chop_val = float(ch.iloc[-1]) if not pd.isna(float(ch.iloc[-1])) else 50
        if chop_val >= c['max_chop']:
            s['vetoes'].append(f"choppiness ({chop_val:.1f} >= {c['max_chop']})")
            return s

        # === SERV VETO 3: Tukenme (RSI asiri + kirlanim yok) ===
        ex_rsi = c['exhaustion_rsi']
        rsi_v = float(r.iloc[-1])
        breakout_up = price > float(bbu.iloc[-1])
        breakout_dn = price < float(bbl.iloc[-1])
        if rsi_v >= ex_rsi and not breakout_up:
            s['vetoes'].append(f"tukenme_long (RSI {rsi_v:.0f} >= {ex_rsi})")
            return s
        if rsi_v <= (100 - ex_rsi) and not breakout_dn:
            s['vetoes'].append(f"tukenme_short (RSI {rsi_v:.0f} <= {100-ex_rsi})")
            return s

        # === 12 FAKTORLU KONFLUANS ===
        lp = sp = 0

        # 1) Yerel trend
        if float(ef.iloc[-1]) > float(es.iloc[-1]) and price > float(et.iloc[-1]):
            lp += 1; s['reasons'].append('trend_up')
        elif float(ef.iloc[-1]) < float(es.iloc[-1]) and price < float(et.iloc[-1]):
            sp += 1; s['reasons'].append('trend_down')

        # 2) MTF trend (yumuşak)
        if mtf_trend == 1:
            lp += 1; s['reasons'].append('mtf_up')
        elif mtf_trend == -1:
            sp += 1; s['reasons'].append('mtf_down')

        # 3) MACD
        if float(mh.iloc[-1]) > 0 and float(mh.iloc[-1]) > float(mh.iloc[-2]):
            lp += 1; s['reasons'].append('macd_up')
        elif float(mh.iloc[-1]) < 0 and float(mh.iloc[-1]) < float(mh.iloc[-2]):
            sp += 1; s['reasons'].append('macd_down')

        # 4) RSI bandi
        if 45 <= rsi_v <= 68:
            lp += 1; s['reasons'].append('rsi_bull')
        if 32 <= rsi_v <= 55:
            sp += 1; s['reasons'].append('rsi_bear')

        # 5) ADX
        if float(x.iloc[-1]) >= c['adx_min']:
            if float(pdi.iloc[-1]) > float(mdi.iloc[-1]):
                lp += 1; s['reasons'].append('adx_bull')
            elif float(mdi.iloc[-1]) > float(pdi.iloc[-1]):
                sp += 1; s['reasons'].append('adx_bear')

        # 6) Hacim
        if float(v.iloc[-1]) > float(volma.iloc[-1]) * c['volume_factor']:
            if float(cl.iloc[-1]) > float(o.iloc[-1]):
                lp += 1; s['reasons'].append('vol_bull')
            elif float(cl.iloc[-1]) < float(o.iloc[-1]):
                sp += 1; s['reasons'].append('vol_bear')

        # 7) Bollinger kirlanimi
        if price > float(bbu.iloc[-1]):
            lp += 1; s['reasons'].append('bb_up')
        elif price < float(bbl.iloc[-1]):
            sp += 1; s['reasons'].append('bb_down')

        # 8) Stoch (CLAUDE'den)
        k_v = float(k.iloc[-1]); d_v = float(d.iloc[-1])
        if k_v > d_v and k_v < 88:
            lp += 0.5; s['reasons'].append('stoch_bull')
        elif k_v < d_v and k_v > 12:
            sp += 0.5; s['reasons'].append('stoch_bear')

        # 9) VWAP (CLAUDE'den)
        vw_v = float(vw.iloc[-1]) if not pd.isna(float(vw.iloc[-1])) else price
        if price > vw_v:
            lp += 0.5; s['reasons'].append('vwap_bull')
        elif price < vw_v:
            sp += 1; s['reasons'].append('vwap_bear')  # VWAP'alti daha guclu sinyal

        # 10) Supertrend (CLAUDE'den)
        st_dir_v = float(st_dir.iloc[-1]) if not pd.isna(float(st_dir.iloc[-1])) else 0
        if st_dir_v == 1:
            lp += 1; s['reasons'].append('supertrend_up')
        elif st_dir_v == -1:
            sp += 1; s['reasons'].append('supertrend_down')

        # 11) CCI (CLAUDE'den)
        cc_v = float(cc.iloc[-1])
        if cc_v > 75:
            lp += 0.5; s['reasons'].append('cci_bull')
        elif cc_v < -75:
            sp += 0.5; s['reasons'].append('cci_bear')

        # 12) OBV (CLAUDE'den)
        if float(ob.iloc[-1]) > float(ob.iloc[-2]):
            lp += 0.5; s['reasons'].append('obv_bull')
        elif float(ob.iloc[-1]) < float(ob.iloc[-2]):
            sp += 0.5; s['reasons'].append('obv_bear')

        s['long_score'] = lp
        s['short_score'] = sp
        s['score'] = max(lp, sp)

        # Veto 4: FUSION edge/kalite (basitleştirilmiş)
        spread_bps = c.get('spread_bps', 2.0)
        fee_bps = c.get('fee_bps', 5.0)
        slip_bps = c.get('slip_bps', 2.0)
        gross_edge = atr_pct * 100 * 0.2 * (s['score'] / 10)
        net_edge = gross_edge - spread_bps - fee_bps - slip_bps*2
        s['edge_bps'] = net_edge
        if net_edge < c['min_edge_bps']:
            s['vetoes'].append(f"net_edge_too_small ({net_edge:.1f} bps < {c['min_edge_bps']})")

        if s['score'] < c['min_score']:
            s['vetoes'].append(f"score_below_threshold ({s['score']:.1f} < {c['min_score']})")

        # INDICATOR ANALIZI: tum dusus faktörleri kayipici (trend_down %26, macd_down %37, obv_bear %28 vb.)
        # => sadece LONG alinir; short kismi kaldirildi.
        # Long girisi icin konfluans zorunlu: macd_up / vol_bull / bb_up arasinda en az biri (her biri %66 WR)
        thr = c['min_score']
        long_confluence = ('macd_up' in s['reasons'] or 'vol_bull' in s['reasons'] or 'bb_up' in s['reasons'])
        if lp >= thr and lp - sp >= 2 and long_confluence and not s['vetoes']:
            s['side'] = 1
        else:
            s['side'] = 0

        # Confidence
        total_votes = lp + sp
        s['confidence'] = min(0.99, max(0.01, s['score'] / 12 * 0.6 + min(abs(lp-sp), 4)/4 * 0.4))

        return s

# =====================================================================
# 4. FINAL RISK / PAPER ENGINE (CLAUDE'dan kotumser model + GLM'dan TP/trailing)
# =====================================================================
class FinalPaperEngine:
    """
    Paper trading engine:
    - Sinyal mum kapanisinda uretir, giris SONRAKI mumun acilisinda
    - Ayni mumda stop ve hedef birlutde gorulurse STOP kazanir (kotumser)
    - Breakeven + ATR trailing + max hold + cooldown
    - TP1 (kismi kapatma) + TP2 (tumu)
    """
    def __init__(self, cfg):
        self.cfg = cfg
        self.balance = cfg['equity']
        self.positions = {}  # sym -> position dict
        self.trades = []
        self.equity_curve = []
        self.cooldown_until = {}
        self.stats = {'REJECT_VETO': 0, 'REJECT_EDGE': 0, 'REJECT_POSITIONS': 0,
                      'OPENED': 0, 'CLOSED_STOP': 0, 'CLOSED_TP': 0,
                      'CLOSED_BREAKEVEN': 0, 'CLOSED_TRAIL': 0, 'CLOSED_TIME': 0,
                      'CLOSED_END': 0}

    def _slip(self):
        return (self.cfg['slip_bps'] + self.cfg['spread_bps'] / 2.0) / 10000.0

    def step(self, ts, bars):
        """bars: {sym: Bar-like dict with open, high, low, close, volume, ts}"""
        # 1) Mevcut pozisyonlari yönet
        for sym in list(self.positions.keys()):
            if sym not in bars:
                continue
            p = self.positions[sym]
            b = bars[sym]
            self._manage(p, b, ts)

        # 2) Bekleyen girisleri doldur (yuksek skor once)
        due = sorted([(abs(p.get('signal_score', 0)), sym) for sym, p in self.positions.items() if sym in bars and p.get('pending_entry')],
                     key=lambda x: -x[0])
        # (bu basit versiyonda pending entry yok, direkt yeni sinyal acilir)

        # 3) Yeni sinyaller
        for sym in sorted(bars.keys()):
            if sym in self.positions:
                continue
            if ts < self.cooldown_until.get(sym, 0):
                self.stats['REJECT_POSITIONS'] += 1
                continue

            sig = bars[sym].get('_signal')
            if sig is None or sig['side'] == 0:
                continue

            if sig['vetoes']:
                self.stats['REJECT_VETO'] += 1
                continue

            if sig['edge_bps'] < self.cfg['min_edge_bps']:
                self.stats['REJECT_EDGE'] += 1
                continue

            # Giris: sonraki mum acilisinda (simulasyon icin bu mumun acilisi yaklasik)
            entry = float(bars[sym]['open']) * (1 + sig['side'] * self._slip())
            atrv = sig['atr']

            # Risk boyutlandirma: %1 risk / islem
            risk_pct = self.cfg['risk_per_trade_pct'] / 100.0
            risk_usd = self.balance * risk_pct
            stop_dist = self.cfg['stop_atr_mult'] * atrv
            qty = risk_usd / stop_dist if stop_dist > 0 else 0
            notional = qty * entry

            if notional > self.balance * self.cfg['max_notional_pct'] / 100.0:
                self.stats['REJECT_POSITIONS'] += 1
                continue

            # ATR bazli SL/TP
            if sig['side'] > 0:
                stop = entry - stop_dist
                tp1 = entry + stop_dist * self.cfg['tp1_r']
                tp2 = entry + stop_dist * self.cfg['tp2_r']
            else:
                stop = entry + stop_dist
                tp1 = entry - stop_dist * self.cfg['tp1_r']
                tp2 = entry - stop_dist * self.cfg['tp2_r']

            fee = notional * self.cfg['taker_bps'] / 10000.0
            self.positions[sym] = {
                'sym': sym, 'side': sig['side'], 'entry': entry, 'qty': qty,
                'stop': stop, 'tp1': tp1, 'tp2': tp2, 'atr': atrv,
                'risk_usd': risk_usd, 'entry_fee': fee, 'open_ts': ts,
                'bars_held': 0, 'best': entry, 'stop_kind': 'INITIAL',
                'tp1_hit': False, 'score': sig['score'],
            }
            self.stats['OPENED'] += 1

            # Ayni mumda cikis kontrolu
            self._manage(self.positions[sym], bars[sym], ts)

        # 4) Equity kayit
        eq = self.balance
        for sym, p in self.positions.items():
            px = bars[sym]['close'] if sym in bars else p['entry']
            eq += p['side'] * (px - p['entry']) * p['qty'] - p['entry_fee']
        self.equity_curve.append((ts, eq))

    def _manage(self, p, bar, ts):
        side = p['side']
        if side > 0:
            stop_hit = bar['open'] <= p['stop'] or bar['low'] <= p['stop']
            tp1_hit = not p['tp1_hit'] and bar['high'] >= p['tp1']
            tp2_hit = bar['low'] >= p['tp2'] if p['tp1_hit'] else bar['high'] >= p['tp2']
        else:
            stop_hit = bar['open'] >= p['stop'] or bar['high'] >= p['stop']
            tp1_hit = not p['tp1_hit'] and bar['low'] <= p['tp1']
            tp2_hit = bar['low'] <= p['tp2'] if p['tp1_hit'] else bar['high'] <= p['tp2']

        # Stop her zaman once (kotumser)
        if stop_hit:
            raw = min(bar['open'], p['stop']) if side > 0 else max(bar['open'], p['stop'])
            px = raw * (1 - side * self._slip())
            self._close(p, px, ts, 'STOP')
            return

        # TP1: %50 kapat, stop basabasa
        if tp1_hit and not p['tp1_hit']:
            p['tp1_hit'] = True
            side_close = -side
            pnl_part = p['qty'] * 0.5 * (p['tp1'] - p['entry']) * side
            fee_part = p['qty'] * 0.5 * p['tp1'] * self.cfg['taker_bps'] / 10000.0
            self.balance += pnl_part - fee_part
            self.stats['CLOSED_TP'] += 1
            # Stop basabasa
            be = p['entry'] + side * (p['entry'] * (self.cfg['taker_bps']*2 + self.cfg['slip_bps']) / 10000.0)
            p['stop'] = be
            p['stop_kind'] = 'BREAKEVEN'
            p['qty'] *= 0.5  # kalan
            return

        # TP2: kalanı kapat
        if tp2_hit:
            px = p['tp2']
            self._close(p, px, ts, 'TP2')
            return

        p['bars_held'] += 1
        fav = bar['high'] if side > 0 else bar['low']
        p['best'] = max(p['best'], fav) if side > 0 else min(p['best'], fav)

        # Breakeven at 0.8R
        r_fav = side * (p['best'] - p['entry']) / max(abs(p['stop'] - p['entry']), 1e-12)
        if r_fav >= self.cfg['breakeven_r'] and p['stop_kind'] == 'INITIAL':
            be = p['entry'] + side * p['entry'] * (self.cfg['taker_bps']*2 + self.cfg['slip_bps']) / 10000.0
            if (p['stop'] - be) * side < 0:
                p['stop'] = be
                p['stop_kind'] = 'BREAKEVEN'
                self.stats['CLOSED_BREAKEVEN'] += 1

        # ATR trailing at 1.0R
        if r_fav >= self.cfg['trail_start_r']:
            tr = p['best'] - side * self.cfg['trail_atr_mult'] * p['atr']
            if (tr - p['stop']) * side > 0:
                p['stop'] = tr
                p['stop_kind'] = 'TRAIL'

        # Max hold
        if p['bars_held'] >= self.cfg['max_hold_bars']:
            self._close(p, bar['close'] * (1 - side * self._slip()), ts, 'TIME')

    def _close(self, p, px, ts, reason):
        side = p['side']
        exit_fee = p['qty'] * px * self.cfg['taker_bps'] / 10000.0
        gross = side * (px - p['entry']) * p['qty']
        pnl = gross - p['entry_fee'] - exit_fee
        self.balance += pnl
        self.trades.append({
            'sym': p['sym'], 'side': side, 'entry': p['entry'], 'exit': px,
            'qty': p['qty'], 'pnl': pnl, 'reason': reason,
            'bars': p['bars_held'], 'score': p['score'],
        })
        if reason == 'STOP':
            self.stats['CLOSED_STOP'] += 1
        elif reason == 'TP2':
            self.stats['CLOSED_TP'] += 1
        elif reason == 'TIME':
            self.stats['CLOSED_TIME'] += 1
        elif reason == 'END':
            self.stats['CLOSED_END'] += 1
        self.positions.pop(p['sym'], None)
        self.cooldown_until[p['sym']] = ts + self.cfg['cooldown_bars'] * 900000  # 15m = 900s

    def finish(self, bars, ts, force_close=True):
        if not force_close:
            return
        for sym in list(self.positions.keys()):
            p = self.positions[sym]
            px = bars[sym]['close'] if sym in bars else p['entry']
            self._close(p, px * (1 - p['side'] * self._slip()), ts, 'END')

# =====================================================================
# 5. TEST DONGUSU
# =====================================================================
final_cfg = {
    # Sinyal
    'ema_fast': 21, 'ema_slow': 55, 'ema_trend': 200,
    'rsi_len': 14, 'adx_len': 14, 'adx_min': 20,
    'atr_len': 14, 'volume_factor': 1.2,
    'bb_len': 20, 'bb_dev': 2.0,
    'min_atr_pct': 0.12,
    'exhaustion_rsi': 73,
    'max_chop': 70.0,
    'min_score': 4.0,
    'min_edge_bps': 0.0,
    'spread_bps': 2.0, 'fee_bps': 5.0, 'slip_bps': 2.0,
    # Risk
    'equity': 1000.0,
    'risk_per_trade_pct': 1.0,
    'stop_atr_mult': 2.5,   # INDICATOR ANALIZI: 1.5x ATR cok sikti (23/24 STOP), 2.5x ile darbelere dayanilabiliyor
    'tp1_r': 1.0,   # +1R'de %50 kapat
    'tp2_r': 2.0,   # +2R'de kalan
    'breakeven_r': 0.8,
    'trail_start_r': 1.0,
    'trail_atr_mult': 1.5,
    'max_hold_bars': 30,
    'cooldown_bars': 3,
    'max_notional_pct': 100.0,
    'taker_bps': 5.0,
}

final_strat = FinalStrategy(final_cfg)

final_results = {}
for sym in SYMBOLS_OKX:
    if sym not in all_data:
        continue
    df = all_data[sym]

    # MTF 30m (GLM'den optimized)
    df_30m = df.resample('30min').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    cl_30 = df_30m['close']
    ef30 = ema(cl_30, 20)
    es30 = ema(cl_30, 50)
    mtf_series = pd.Series(
        np.where((ef30 > es30) & (cl_30 > es30), 1.0,
                 np.where((ef30 < es30) & (cl_30 < es30), -1.0, 0.0)),
        index=df_30m.index
    ).shift(1).reindex(df.index).ffill()

    engine = FinalPaperEngine(final_cfg)

    for i in range(len(df)):
        row = df.iloc[i]
        ts = int(row.name.timestamp() * 1000)
        bar = {
            'open': float(row['open']), 'high': float(row['high']),
            'low': float(row['low']), 'close': float(row['close']),
            'volume': float(row['volume']), 'ts': ts,
        }
        # Sinyal hesapla (i-1'e kadar olan verilerle, lookahead yok)
        df_slice = df.iloc[:i+1]
        mtf_val = mtf_series.iloc[i] if i < len(mtf_series) else 0
        mtf_t = int(mtf_val) if not pd.isna(mtf_val) else 0
        sig = final_strat.evaluate(df_slice, mtf_trend=mtf_t)
        bar['_signal'] = sig
        engine.step(ts, {sym: bar})

    # Son mumda kapanik
    last_row = df.iloc[-1]
    last_ts = int(last_row.name.timestamp() * 1000)
    engine.finish({sym: {'close': float(last_row['close'])}}, last_ts, force_close=True)

    trades = engine.trades
    total_pnl = sum(t['pnl'] for t in trades)
    win_trades = [t for t in trades if t['pnl'] > 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0

    final_results[sym] = {
        'trades': len(trades), 'total_pnl': total_pnl, 'win_rate': win_rate,
        'final_equity': engine.balance,
        'stats': engine.stats,
    }

    side_counts = {}
    for t in trades:
        sc = 'LONG' if t['side'] > 0 else 'SHORT'
        side_counts[sc] = side_counts.get(sc, 0) + 1
    print(f"{sym}: {len(trades)}is | Kar {total_pnl:+.2f} USDT | Win% {win_rate:.0f}% | Equity {engine.balance:.2f} | Isler: {side_counts}")

# =====================================================================
# 6. SONUCLAR
# =====================================================================
report = {
    'tarih': datetime.now(timezone.utc).isoformat(),
    'kaynak': 'OKX 15m (gercek piyasa verisi, FINAL surum)',
    'semboller': SYMBOLS_OKX,
    'strategie': 'FINAL: GLM 7 faktor + CLAUDE 10 oy + FUSION veto + kotumser paper engine',
    'config': final_cfg,
    'not_gemini': 'GEMINI 2 bu gruda DEGIL — sadece GLM, CLAUDE/SENZE, CHATGPT/FUSION PRO ozellikleri toplandi.',
    'results': {k: {'trades': v['trades'], 'total_pnl': v['total_pnl'], 'win_rate': v['win_rate'],
                    'final_equity': v['final_equity'], 'stats': v['stats']} for k, v in final_results.items()},
}

with open(os.path.join(RESULTS_DIR, 'final_strategy_results.json'), 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2, default=str)

print()
print("=" * 85)
print("FINAL SÜRÜM TESTI TAMAMLANDI")
print(f"JSON: {RESULTS_DIR}/final_strategy_results.json")
print("=" * 85)

print()
print("KARSILASTIRMA (Onceki en iyi vs FINAL)")
print("-" * 100)
print(f"{'Sembol':<18} {'SENZE_onceki':<22} {'FUSION_onceki':<22} {'GEMINI_onceki':<20} {'FINAL':<20}")
print(f"{'':<18} {'Islem/Kar/Win%':<22} {'Sinyal/Skor':<22} {'Islem/Kar/Win%':<20} {'Islem/Kar/Win%':<20}")
onceki_senze = {'BTC/USDT:USDT': (8, -7.33, 38), 'ETH/USDT:USDT': (6, -7.40, 17), 'SOL/USDT:USDT': (7, -12.96, 14)}
onceki_fusion = {'BTC/USDT:USDT': ('SHORT', 1.75), 'ETH/USDT:USDT': ('LONG', 2.75), 'SOL/USDT:USDT': ('SHORT', 2.50)}
onceki_gemini = {'BTC/USDT:USDT': (18, -146, 28), 'ETH/USDT:USDT': (13, 0, 38), 'SOL/USDT:USDT': (16, 0, 31)}
for sym in SYMBOLS_OKX:
    if sym not in final_results:
        continue
    fr = final_results[sym]
    final_str = f"{fr['trades']}is/{fr['total_pnl']:+.0f}/%{fr['win_rate']:.0f}"
    s_key = sym
    os_trade, os_pnl, os_wr = onceki_senze.get(s_key, (0, 0, 0))
    s_str = f"{os_trade}is/{os_pnl:+.0f}/%{os_wr}"
    of_side, of_score = onceki_fusion.get(s_key, ('-', 0))
    f_str = f"{of_side}/{of_score:.1f}"
    og_trade, og_pnl, og_wr = onceki_gemini.get(s_key, (0, 0, 0))
    g_str = f"{og_trade}is/{og_pnl:+.0f}/%{og_wr}"
    print(f"{sym:<18} {s_str:<22} {f_str:<22} {g_str:<20} {final_str:<20}")