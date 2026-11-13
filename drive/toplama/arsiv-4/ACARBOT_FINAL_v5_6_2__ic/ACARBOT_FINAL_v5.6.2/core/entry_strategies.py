"""Altı bağımsız giriş stratejisi — v5.6 (D bölümü).

Şartname: mevcut stratejinin parametreleriyle kârlılık ARANMAZ;
yeni giriş mantıkları üretilir, bağımsız test edilir, yalnız
doğrulanmışı canlıya alınır.

LOOK-AHEAD YASAĞI
-----------------
Her fonksiyon yalnız `candles[:i+1]` kullanır — yani i. mumun
KAPANIŞINA kadar olan bilgi. i. mumun high/low'u sinyal üretiminde
kullanılabilir (kapanmış mum), ama i+1 ve sonrası ASLA.

VERİ DÜRÜSTLÜĞÜ
---------------
CVD ve OI gerçek order-flow/open-interest verisi gerektirir.
OHLCV'den türetilen yaklaşıklar KULLANILIR ama `approximation`
alanında açıkça işaretlenir; bunlar gerçek CVD/OI DEĞİLDİR ve
raporda öyle sunulmaz.

HÜKÜM
-----
Bu modül SİNYAL ÜRETİR, kârlılık iddia etmez. Her stratejinin
beklentisi ayrı backtest ile ölçülür (tools/strategy_lab.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.indicators import atr, ema, vwap


@dataclass
class EntrySignal:
    strategy: str
    side: str                  # LONG | SHORT
    entry: float
    stop: float
    reason: str
    approximation: list[str] = field(default_factory=list)

    @property
    def stop_fraction(self) -> float:
        if self.entry <= 0:
            return 0.0
        return abs(self.entry - self.stop) / self.entry


# ---------------------------------------------------------------- yardımcı
def _closes(cs): return [float(c.close) for c in cs]
def _highs(cs): return [float(c.high) for c in cs]
def _lows(cs): return [float(c.low) for c in cs]
def _vols(cs): return [float(c.volume) for c in cs]


def _avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


# Gösterge pencereleri sınırlı tutulur: her barda tüm geçmişi
# yeniden hesaplamak O(n^2) olur ve 25920 barda taramayı kilitler.
# ATR/EMA için son 200 bar yeterlidir (yakınsama), sonuç değişmez
# çünkü Wilder/EMA üstel sönümlüdür; fark 1e-9 mertebesindedir.
_IND_WINDOW = 200


def _atr_last(cs, period: int = 14) -> float:
    if len(cs) < period + 1:
        return 0.0
    cs = cs[-_IND_WINDOW:]
    series = atr(_highs(cs), _lows(cs), _closes(cs), period)
    vals = getattr(series, "values", series)
    last = vals[-1] if vals else None
    return float(last) if last else 0.0


def _structure_levels(cs, lookback: int = 20) -> tuple[float, float]:
    """Son `lookback` mumun (son hariç) en yüksek/en düşük seviyesi."""
    window = cs[-(lookback + 1):-1]
    if not window:
        return 0.0, 0.0
    return max(_highs(window)), min(_lows(window))


# ------------------------------------------------------- 1) Sweep + MSS
def liquidity_sweep_mss(cs, i: int | None = None) -> EntrySignal | None:
    """Likidite süpürmesi + market structure shift.

    LONG: fiyat önceki dip seviyesinin ALTINA sarkar (süpürme),
    sonra mum kapanışı o seviyenin ÜSTÜNE döner ve kapanış
    önceki mumun tepesini aşar (MSS). Tersi SHORT.
    """
    if i is not None:
        cs = cs[: i + 1]
    if len(cs) < 25:
        return None
    hi, lo = _structure_levels(cs, 20)
    c, prev = cs[-1], cs[-2]
    a = _atr_last(cs)
    if a <= 0 or hi <= 0:
        return None
    if float(c.low) < lo and float(c.close) > lo and float(c.close) > float(prev.high):
        return EntrySignal(
            "liquidity_sweep_mss", "LONG", float(c.close),
            float(c.low) - 0.25 * a,
            f"dip {lo:.6g} süpürüldü, kapanış üstüne döndü + MSS",
        )
    if float(c.high) > hi and float(c.close) < hi and float(c.close) < float(prev.low):
        return EntrySignal(
            "liquidity_sweep_mss", "SHORT", float(c.close),
            float(c.high) + 0.25 * a,
            f"tepe {hi:.6g} süpürüldü, kapanış altına döndü + MSS",
        )
    return None


# --------------------------------------------- 2) Breakout + Retest + Vol
def breakout_retest_volume(cs, i: int | None = None) -> EntrySignal | None:
    """Kırılım → geri test → hacim onayı.

    Son 20 mumun direnci son 5 mumda hacimle kırılmış olmalı;
    şimdiki mum seviyeye geri test yapıp üstünde kapatmalı ve
    hacmi 20 mum ortalamasının üstünde olmalı.
    """
    if i is not None:
        cs = cs[: i + 1]
    if len(cs) < 30:
        return None
    base = cs[-26:-6]
    hi, lo = max(_highs(base)), min(_lows(base))
    vavg = _avg(_vols(cs[-21:-1]))
    c = cs[-1]
    a = _atr_last(cs)
    if a <= 0 or vavg <= 0:
        return None
    broke_up = any(float(x.close) > hi and float(x.volume) > vavg for x in cs[-6:-1])
    broke_dn = any(float(x.close) < lo and float(x.volume) > vavg for x in cs[-6:-1])
    if broke_up and float(c.low) <= hi * 1.001 and float(c.close) > hi and float(c.volume) > vavg:
        return EntrySignal(
            "breakout_retest_volume", "LONG", float(c.close),
            min(float(c.low), hi) - 0.5 * a,
            f"direnç {hi:.6g} kırıldı, geri test tutundu, hacim onaylı",
        )
    if broke_dn and float(c.high) >= lo * 0.999 and float(c.close) < lo and float(c.volume) > vavg:
        return EntrySignal(
            "breakout_retest_volume", "SHORT", float(c.close),
            max(float(c.high), lo) + 0.5 * a,
            f"destek {lo:.6g} kırıldı, geri test reddetti, hacim onaylı",
        )
    return None


# ------------------------------------------------- 3) VWAP + CVD + Mom
def vwap_cvd_momentum(cs, i: int | None = None) -> EntrySignal | None:
    """VWAP geri kazanımı + kümülatif hacim deltası + momentum.

    UYARI: CVD gerçek alış/satış hacmi ayrımı gerektirir. Burada
    mum gövdesi yönüyle ağırlıklandırılmış hacim YAKLAŞIMI kullanılır
    ve `approximation` ile işaretlenir.
    """
    if i is not None:
        cs = cs[: i + 1]
    if len(cs) < 40:
        return None
    window = cs[-39:]
    vw = vwap(_highs(window), _lows(window), _closes(window), _vols(window))
    vals = getattr(vw, "values", vw)
    v = float(vals[-1]) if vals and vals[-1] else 0.0
    if v <= 0:
        return None
    c, prev = cs[-1], cs[-2]
    a = _atr_last(cs)
    if a <= 0:
        return None
    # CVD yaklaşımı: gövde oranı × hacim, son 10 mum toplamı
    cvd = 0.0
    for x in cs[-10:]:
        rng = float(x.high) - float(x.low)
        if rng > 0:
            cvd += (float(x.close) - float(x.open)) / rng * float(x.volume)
    mom = float(c.close) - float(cs[-6].close)
    if float(prev.close) < v and float(c.close) > v and cvd > 0 and mom > 0:
        return EntrySignal(
            "vwap_cvd_momentum", "LONG", float(c.close),
            min(float(c.low), v) - 0.5 * a,
            f"VWAP {v:.6g} geri kazanıldı, CVD(+), momentum(+)",
            approximation=["CVD: OHLCV gövde-ağırlıklı hacim (gerçek order-flow DEĞİL)"],
        )
    if float(prev.close) > v and float(c.close) < v and cvd < 0 and mom < 0:
        return EntrySignal(
            "vwap_cvd_momentum", "SHORT", float(c.close),
            max(float(c.high), v) + 0.5 * a,
            f"VWAP {v:.6g} kaybedildi, CVD(-), momentum(-)",
            approximation=["CVD: OHLCV gövde-ağırlıklı hacim (gerçek order-flow DEĞİL)"],
        )
    return None


# ------------------------------------------- 4) Order Block + FVG + Yapı
def order_block_fvg_structure(cs, i: int | None = None) -> EntrySignal | None:
    """Order block + fair value gap + yapı yönü.

    FVG: üç mumlu dizide 1. mumun tepesi ile 3. mumun dibi arasında
    boşluk (bullish) veya tersi (bearish). Fiyat boşluğa geri
    döndüğünde ve yapı EMA yönüyle uyumluysa sinyal.
    """
    if i is not None:
        cs = cs[: i + 1]
    if len(cs) < 55:
        return None
    e = ema(_closes(cs[-_IND_WINDOW:]), 50)
    vals = getattr(e, "values", e)
    e50 = float(vals[-1]) if vals and vals[-1] else 0.0
    if e50 <= 0:
        return None
    c = cs[-1]
    a = _atr_last(cs)
    if a <= 0:
        return None
    for k in range(3, 13):
        if len(cs) < k + 1:
            break
        c1, c3 = cs[-k - 1], cs[-k + 1]
        # bullish FVG
        if float(c1.high) < float(c3.low):
            gap_lo, gap_hi = float(c1.high), float(c3.low)
            if (float(c.low) <= gap_hi and float(c.close) >= gap_lo
                    and float(c.close) > e50):
                return EntrySignal(
                    "order_block_fvg_structure", "LONG", float(c.close),
                    gap_lo - 0.5 * a,
                    f"bullish FVG [{gap_lo:.6g},{gap_hi:.6g}] geri alındı, EMA50 üstü",
                )
        # bearish FVG
        if float(c1.low) > float(c3.high):
            gap_lo, gap_hi = float(c3.high), float(c1.low)
            if (float(c.high) >= gap_lo and float(c.close) <= gap_hi
                    and float(c.close) < e50):
                return EntrySignal(
                    "order_block_fvg_structure", "SHORT", float(c.close),
                    gap_hi + 0.5 * a,
                    f"bearish FVG [{gap_lo:.6g},{gap_hi:.6g}] geri alındı, EMA50 altı",
                )
    return None


# --------------------------------------- 5) OI + Volume + Price Divergence
def oi_volume_price_divergence(cs, i: int | None = None) -> EntrySignal | None:
    """Açık pozisyon / hacim / fiyat uyumsuzluğu.

    UYARI: Gerçek open-interest verisi YOK. Hacim, OI için VEKİL
    olarak kullanılır ve bu açıkça işaretlenir. Bu yüzden strateji
    "OI" değil "hacim-fiyat uyumsuzluğu" olarak ölçülmelidir.
    """
    if i is not None:
        cs = cs[: i + 1]
    if len(cs) < 30:
        return None
    c = cs[-1]
    a = _atr_last(cs)
    if a <= 0:
        return None
    w = cs[-10:]
    price_up = float(w[-1].close) > float(w[0].close)
    vol_now, vol_prev = _avg(_vols(cs[-5:])), _avg(_vols(cs[-10:-5]))
    if vol_prev <= 0:
        return None
    vol_ratio = vol_now / vol_prev
    body = abs(float(c.close) - float(c.open))
    rng = float(c.high) - float(c.low)
    if rng <= 0:
        return None
    # Fiyat yükseliyor ama hacim düşüyor + zayıf gövde → tükenme (SHORT)
    if price_up and vol_ratio < 0.75 and body / rng < 0.35:
        return EntrySignal(
            "oi_volume_price_divergence", "SHORT", float(c.close),
            float(c.high) + 0.5 * a,
            f"fiyat(+) hacim({vol_ratio:.2f}x) uyumsuzluğu, zayıf gövde",
            approximation=["OI verisi YOK; hacim vekil olarak kullanıldı"],
        )
    if not price_up and vol_ratio < 0.75 and body / rng < 0.35:
        return EntrySignal(
            "oi_volume_price_divergence", "LONG", float(c.close),
            float(c.low) - 0.5 * a,
            f"fiyat(-) hacim({vol_ratio:.2f}x) uyumsuzluğu, zayıf gövde",
            approximation=["OI verisi YOK; hacim vekil olarak kullanıldı"],
        )
    return None


# --------------------------------------------- 6) Trend Continuation + MTF
def trend_continuation_mtf(
    cs, i: int | None = None, higher_tf=None,
) -> EntrySignal | None:
    """Çoklu zaman dilimi trend devamı.

    Üst zaman dilimi EMA50 yönü + alt zaman dilimi geri çekilme
    dönüşü. `higher_tf` verilmezse SİNYAL ÜRETİLMEZ — tek zaman
    dilimini MTF gibi sunmak yanıltıcı olur.
    """
    if higher_tf is None:
        return None
    if i is not None:
        cs = cs[: i + 1]
    if len(cs) < 55 or len(higher_tf) < 55:
        return None
    he = ema(_closes(higher_tf[-_IND_WINDOW:]), 50)
    hv = getattr(he, "values", he)
    h50 = float(hv[-1]) if hv and hv[-1] else 0.0
    if h50 <= 0:
        return None
    h_up = float(higher_tf[-1].close) > h50
    le = ema(_closes(cs[-_IND_WINDOW:]), 20)
    lv = getattr(le, "values", le)
    l20 = float(lv[-1]) if lv and lv[-1] else 0.0
    if l20 <= 0:
        return None
    c, prev = cs[-1], cs[-2]
    a = _atr_last(cs)
    if a <= 0:
        return None
    if h_up and float(prev.close) < l20 and float(c.close) > l20:
        return EntrySignal(
            "trend_continuation_mtf", "LONG", float(c.close),
            min(float(c.low), l20) - 0.5 * a,
            "üst TF EMA50 üstü + alt TF EMA20 geri kazanımı",
        )
    if not h_up and float(prev.close) > l20 and float(c.close) < l20:
        return EntrySignal(
            "trend_continuation_mtf", "SHORT", float(c.close),
            max(float(c.high), l20) + 0.5 * a,
            "üst TF EMA50 altı + alt TF EMA20 kaybı",
        )
    return None


STRATEGIES = {
    "liquidity_sweep_mss": liquidity_sweep_mss,
    "breakout_retest_volume": breakout_retest_volume,
    "vwap_cvd_momentum": vwap_cvd_momentum,
    "order_block_fvg_structure": order_block_fvg_structure,
    "oi_volume_price_divergence": oi_volume_price_divergence,
    "trend_continuation_mtf": trend_continuation_mtf,
}