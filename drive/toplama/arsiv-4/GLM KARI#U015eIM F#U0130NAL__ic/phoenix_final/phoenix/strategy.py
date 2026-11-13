"""Strateji: 8 faktörlü confluence + rejim algısı + veto katmanı.

Faktörler (kaynak): 1. EMA dizilişi (hepsi) · 2. MACD histogram + ivme (Phoenix) ·
3. RSI bandı (Phoenix) · 4. ADX + DI yönü (Phoenix) · 5. Hacim onayı (FUSION) ·
6. VWAP konumu (FUSION/sentez) · 7. Supertrend (sentez) · 8. Bollinger konumu (Phoenix)

Rejim (FUSION_PRO): TREND / RANGE / HIGH_VOL / LOW_VOL → dinamik eşik.
Vetolar: CHOP, SIKIŞMA, HACIM_YOK, EDGE_BELOW_COST, HTF_CELISKI, MUM_BOŞLUĞU, SPREAD.
"""
from __future__ import annotations

import pandas as pd

from .indicators import ema, enrich, vwap
from .models import Signal
from .risk import edge_ratio


def htf_bias_at(x: pd.DataFrame, i: int) -> str:
    """x: e20/e50/vw sütunlu üst-çerçeve; i. mum kapanışındaki eğilim."""
    r = x.iloc[i]
    if pd.isna(r.e20) or pd.isna(r.e50) or pd.isna(r.vw):
        return "NEUTRAL"
    if r.e20 > r.e50 and r.close > r.vw:
        return "LONG"
    if r.e20 < r.e50 and r.close < r.vw:
        return "SHORT"
    return "NEUTRAL"


def htf_bias(df: pd.DataFrame) -> str:
    """Üst zaman çerçevesi eğilimi (FUSION_PRO MTF fikri): EMA20/50 + kapanış/VWAP."""
    x = df.copy()
    x["e20"] = ema(x.close, 20)
    x["e50"] = ema(x.close, 50)
    x["vw"] = vwap(x, 30)
    return htf_bias_at(x, len(x) - 1)


def htf_consensus(biases: list[str]) -> str:
    """Birden çok HTF eğilimini birleştirir: aynı yön → yön; çelişki → MIXED."""
    n_long, n_short = biases.count("LONG"), biases.count("SHORT")
    if n_long and n_short:
        return "MIXED"
    if n_long:
        return "LONG"
    if n_short:
        return "SHORT"
    return "NEUTRAL"


def resample_htf(df_indexed: pd.DataFrame, rule: str = "1h") -> pd.DataFrame:
    """15m frame'i HTF'e çevirir; TAM OLMAYAN son kova atılır (nedensellik)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    o = df_indexed.resample(rule, label="left", closed="left").agg(agg).dropna()
    if len(o):
        rule_ms = pd.Timedelta(rule)
        if o.index[-1] + rule_ms > df_indexed.index[-1] + pd.Timedelta(seconds=1):
            o = o.iloc[:-1]  # henüz kapanmamış HTF mumu
    return o


def evaluate(x: pd.DataFrame, cfg, i: int = -1, htf: str = "NEUTRAL",
             spread_bps: float = 2.0) -> Signal:
    """x: `enrich` ile zenginleştirilmiş frame; i: karar verilen (KAPALI) mumun indeksi.

    Yalnızca ≤ i verisi okunur — nedensellik `indicators.enrich` garantisindedir.
    """
    s = cfg.strategy
    if len(x) == 0 or i < 0 or i >= len(x):
        i = len(x) - 1
    if i < max(s.ema_slow + 10, cfg.market.warmup):
        return Signal(0, 0.0, reasons=["WARMUP"], ts=x.index[i] if len(x) else None)

    # mum boşluğu koruması (sentez): son 3 mum aralığı > ~2 bar süre = veri boşluğu
    step = x.index[i] - x.index[i - 2]
    nominal = x.index[i] - x.index[i - 1]
    if pd.Timedelta(step) > pd.Timedelta(nominal) * 2.2:
        return Signal(0, 0.0, vetoes=["MUM_BOSLUK"], ts=x.index[i])

    r = x.iloc[i]
    votes: dict[str, float] = {}

    # 1) EMA dizilişi
    if r.ema_f > r.ema_m > r.ema_s:
        votes["ema"] = s.w_ema
    elif r.ema_f < r.ema_m < r.ema_s:
        votes["ema"] = -s.w_ema
    else:
        votes["ema"] = 0.0

    # 2) MACD: histogram işareti + ivme
    h0, h1 = x.macd_hist.iloc[i - 1], x.macd_hist.iloc[i]
    if r.macd_hist > 0 and h1 >= h0:
        votes["macd"] = s.w_macd
    elif r.macd_hist < 0 and h1 <= h0:
        votes["macd"] = -s.w_macd
    else:
        votes["macd"] = 0.0

    # 3) RSI bandı (simetrik: 50 etrafında; mirror-test uyumlu)
    if 50 <= r.rsi <= 70:
        votes["rsi"] = s.w_rsi
    elif 30 <= r.rsi < 50:
        votes["rsi"] = -s.w_rsi
    else:
        votes["rsi"] = 0.0

    # 4) ADX + DI yönü
    if pd.notna(r.adx) and r.adx >= s.adx_trend:
        votes["adx"] = s.w_adx if r.pdi > r.mdi else -s.w_adx
    else:
        votes["adx"] = 0.0

    # 5) Hacim: > 1.2×MA20 ve mum yönü aynı
    vol_ma = x.volume.rolling(20, min_periods=20).mean().iloc[i]
    candle_up = r.close > r.open
    if pd.notna(vol_ma) and vol_ma > 0 and r.volume > 1.2 * vol_ma:
        votes["volume"] = s.w_volume if candle_up else -s.w_volume
    else:
        votes["volume"] = 0.0

    # 6) VWAP konumu
    votes["vwap"] = s.w_vwap if (pd.notna(r.vwap) and r.close > r.vwap) else (
        -s.w_vwap if pd.notna(r.vwap) else 0.0)

    # 7) Supertrend
    votes["supertrend"] = s.w_supertrend if r.st > 0 else -s.w_supertrend

    # 8) Bollinger konumu
    votes["boll"] = s.w_boll if (pd.notna(r.bb_mid) and r.close > r.bb_mid) else (
        -s.w_boll if pd.notna(r.bb_mid) else 0.0)

    score = sum(votes.values())
    side = 1 if score >= s.score_threshold else (-1 if score <= -s.score_threshold else 0)

    # karşı yön baskınlık filtresi (Phoenix)
    if side != 0:
        own = sum(v for v in votes.values() if v * side > 0)
        opp = sum(-v for v in votes.values() if v * side < 0)
        if own - opp < s.side_gap:
            side = 0

    # --- rejim (FUSION_PRO) ---
    regime = "TREND" if (pd.notna(r.adx) and r.adx >= s.adx_trend) else "RANGE"
    atrp = float(r.atrp) if pd.notna(r.atrp) else 0.0
    if atrp > s.atrp_high:
        regime = "HIGH_VOL"
    elif atrp < s.atrp_low:
        regime = "LOW_VOL"

    # --- vetolar ---
    vetoes: list[str] = []
    if side != 0:
        if pd.notna(r.chop) and r.chop >= s.max_chop:
            vetoes.append("CHOP")
        if (regime in ("TREND", "HIGH_VOL") and votes["volume"] * side <= 0
                and pd.notna(r.vol_z) and r.vol_z < s.volume_z_min):
            vetoes.append("HACIM_YOK")
        if pd.notna(r.bb_width_pct) and r.bb_width_pct < s.min_bb_width_pct:
            vetoes.append("SIKISMA")
        if s.min_edge_ratio > 0 and edge_ratio(float(r.close), float(r.atr), cfg) < s.min_edge_ratio:
            vetoes.append("EDGE_BELOW_COST")
        if regime in ("RANGE", "LOW_VOL") and abs(score) < s.score_threshold + s.th_range:
            vetoes.append("REJIM_ZAYIF")
        if htf == "LONG" and side < 0:
            vetoes.append("HTF_CELISKI")
        if htf == "SHORT" and side > 0:
            vetoes.append("HTF_CELISKI")
        if spread_bps > cfg.market.max_spread_bps:
            vetoes.append("SPREAD")

    stop_dist = float(r.atr) * cfg.exit.stop_atr if pd.notna(r.atr) else 0.0
    reasons = [f"rejim={regime}"] if side != 0 else []
    return Signal(side, round(score, 2), votes, reasons, vetoes, regime,
                  float(r.atr) if pd.notna(r.atr) else 0.0, float(r.close),
                  x.index[i], stop_dist)


def evaluate_last(df_raw: pd.DataFrame, cfg, htf: str = "NEUTRAL",
                  spread_bps: float = 2.0) -> Signal:
    """Canlı kullanım: ham OHLCV (kapanmış mumlar) → zenginleştir → son mumda karar."""
    x = enrich(df_raw, cfg)
    return evaluate(x, cfg, i=len(x) - 1, htf=htf, spread_bps=spread_bps)


def funding_guard(now_ts, cfg) -> bool:
    """Funding settlement penceresi (FUSION_PRO): 00/08/16 UTC ± guard saniye."""
    ts = pd.Timestamp(now_ts).tz_localize(None)
    sec_of_day = ts.hour * 3600 + ts.minute * 60 + ts.second
    for h in (0, 8, 16):
        d = min(abs(sec_of_day - h * 3600), 86400 - abs(sec_of_day - h * 3600))
        if d <= cfg.market.funding_guard_sec:
            return True
    return False
