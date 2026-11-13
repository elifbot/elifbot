"""7 faktörlü konflüans sinyal motoru + veto zinciri.

Mimaride AcarBot'un katmanlı onay yaklaşımı korunmuştur:
  skorlama (konflüans) -> sert vetolar (MTF, tükenme, ölü pazar)
Buna karşılık haber/ML/order-flow akışları (harici bağımlılık) çıkarılmıştır;
onların yerine türev piyasa verisi (funding, OI) veto katmanı Trader'da vardır.
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from core.indicators import ema, rsi, atr, adx, macd, bollinger


@dataclass
class Signal:
    side: int = 0                    # 1 = LONG, -1 = SHORT, 0 = yok
    score: int = 0                   # 0-7 konflüans puanı
    reasons: list = field(default_factory=list)
    atrv: float = 0.0
    price: float = 0.0


class ConfluenceStrategy:
    """Faktörler: trend, MTF trend, MACD, RSI bandı, ADX, hacim, BB kırılımı.
    Giriş için: puan >= eşik VE diğer yöne karşı en az +2 fark.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def evaluate(self, df: pd.DataFrame, mtf_trend=None) -> Signal:
        c = self.cfg
        s = Signal()
        need = max(c['ema_trend'], c['bb_len'], 30) + 5
        if len(df) < need:
            return s
        o, h, l, cl, v = df['open'], df['high'], df['low'], df['close'], df['volume']

        ef = ema(cl, c['ema_fast'])
        es = ema(cl, c['ema_slow'])
        et = ema(cl, c['ema_trend'])
        r = rsi(cl, c['rsi_len'])
        a = atr(h, l, cl, c['atr_len'])
        x, pdi, mdi = adx(h, l, cl, c['adx_len'])
        _, _, mh = macd(cl)
        bbu, bbm, bbl = bollinger(cl, c['bb_len'], c['bb_dev'])
        volma = v.rolling(20).mean()

        price = float(cl.iloc[-1])
        atrv = float(a.iloc[-1])
        if any(pd.isna(z) for z in (et.iloc[-1], x.iloc[-1], volma.iloc[-1], atrv)):
            return s
        s.price, s.atrv = price, atrv

        # --- sert veto 1: ölü pazar (hareket maliyeti karşılamıyor) ---
        atr_pct = atrv / price * 100
        if atr_pct < c['min_atr_pct']:
            s.reasons.append(f"ölü pazar (ATR% {atr_pct:.2f} < {c['min_atr_pct']})")
            return s

        lp = sp = 0

        # 1) Yerel trend: hızlı EMA > yavaş EMA ve fiyat 200 EMA üstünde
        if ef.iloc[-1] > es.iloc[-1] and price > et.iloc[-1]:
            lp += 1; s.reasons.append('trend↑')
        if ef.iloc[-1] < es.iloc[-1] and price < et.iloc[-1]:
            sp += 1; s.reasons.append('trend↓')

        # 2) Üst zaman dilimi trendi (yumuşak faktör, backtest'te lookahead'siz)
        if mtf_trend == 1:
            lp += 1; s.reasons.append('mtf↑')
        elif mtf_trend == -1:
            sp += 1; s.reasons.append('mtf↓')

        # 3) Momentum: MACD histogramı işaret + güçleniyor
        if mh.iloc[-1] > 0 and mh.iloc[-1] > mh.iloc[-2]:
            lp += 1; s.reasons.append('macd↑')
        if mh.iloc[-1] < 0 and mh.iloc[-1] < mh.iloc[-2]:
            sp += 1; s.reasons.append('macd↓')

        # 4) RSI bandı: yönle uyumlu ama aşırı bölgede değil (kovalamayı önler)
        if 45 <= r.iloc[-1] <= 68:
            lp += 1; s.reasons.append('rsi-bull')
        if 32 <= r.iloc[-1] <= 55:
            sp += 1; s.reasons.append('rsi-bear')

        # 5) ADX rejimi: trend gücü var ve DI yönü net
        if x.iloc[-1] >= c['adx_min']:
            if pdi.iloc[-1] > mdi.iloc[-1]:
                lp += 1; s.reasons.append('adx-bull')
            elif mdi.iloc[-1] > pdi.iloc[-1]:
                sp += 1; s.reasons.append('adx-bear')

        # 6) Hacim onayı: ortalamanın üstünde hacim, mum yönüyle uyumlu
        if v.iloc[-1] > volma.iloc[-1] * c['volume_factor']:
            if cl.iloc[-1] > o.iloc[-1]:
                lp += 1; s.reasons.append('vol-bull')
            elif cl.iloc[-1] < o.iloc[-1]:
                sp += 1; s.reasons.append('vol-bear')

        # 7) Bollinger kırılımı (trend teyidiyle birlikte)
        breakout_up = price > bbu.iloc[-1]
        breakout_dn = price < bbl.iloc[-1]
        if breakout_up:
            lp += 1; s.reasons.append('bb↑')
        elif breakout_dn:
            sp += 1; s.reasons.append('bb↓')

        # --- sert veto 2: tükenme (AcarBot exhaustion_guard'tan uyarlandı) ---
        # aşırı bölgede VE kırılım yoksa geç giriş reddedilir
        ex = c['exhaustion_rsi']
        if r.iloc[-1] >= ex and not breakout_up:
            s.reasons.append(f"tükenme vetosu (RSI {r.iloc[-1]:.0f} ≥ {ex}, kırılım yok)")
            return s
        if r.iloc[-1] <= (100 - ex) and not breakout_dn:
            s.reasons.append(f"tükenme vetosu (RSI {r.iloc[-1]:.0f} ≤ {100-ex}, kırılım yok)")
            return s

        thr = int(c['score_threshold'])
        if lp >= thr and lp - sp >= 2:
            s.side, s.score = 1, lp
        elif sp >= thr and sp - lp >= 2:
            s.side, s.score = -1, sp
        return s


def mtf_trend_series(dh: pd.DataFrame, index, fast=50, slow=200) -> pd.Series:
    """Üst zaman dilimi trendi (-1/0/1), giriş mumlarına ileri doldurulur.
    shift(1): yalnızca TAMAMLANMIŞ üst-muma bakılır → lookahead yok."""
    if len(dh) < slow + 2:
        return pd.Series(np.nan, index=index)
    cl = dh['close']
    ef, es = ema(cl, fast), ema(cl, slow)
    t = pd.Series(
        np.where((ef > es) & (cl > es), 1.0,
                 np.where((ef < es) & (cl < es), -1.0, 0.0)),
        index=dh.index)
    t = t.shift(1)
    return t.reindex(index).ffill()
