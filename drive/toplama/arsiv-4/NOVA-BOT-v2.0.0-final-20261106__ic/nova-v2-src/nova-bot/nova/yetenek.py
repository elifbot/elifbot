"""NOVA-BOT v2 — yetenek katmanı.

Bu dosya, karşılaştırma sonucunda **eksik olduğu ölçülen** yetenekleri ekler.
Her yeteneğin kaynağı ve sınırı docstring'inde yazılıdır; hiçbiri kârlılık
iddiası taşımaz.

Kaynaklar (bkz. docs/KARSILASTIRMA-ve-YETENEKLER.md):
  • ACARBOT Python (maildeki zip)  → EDGE_BELOW_COST, mum sürekliliği/bütünlük
                                     denetimi, sembol başına cooldown, funding
                                     muhasebesi kapısı, kill-switch
  • acarbot-system v3.4 HTML       → Confluence 10 filtre oylaması, ADX/Stoch/
                                     OBV/VWAP/CCI/Supertrend göstergeleri,
                                     DCA güvenlik emirleri, risk-bazlı boyut,
                                     maks. tutma süresi, kill-switch davranışı
  • NOVA'da zaten vardı            → 3 borsa, WS akışı, funding oranı okuma,
                                     likidasyon mesafesi, ADX/choppiness,
                                     mikro-yapı kapıları, dürüstlük raporu
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .bot import Bar, Signal, ema, rsi

# ==========================================================================
# 1) GÖSTERGELER — ACARBOT v3.4 HTML'den Python'a birebir port
#    (HTML: ADX/Stoch/OBV/VWAP/CCI/Supertrend, finL uyumlu tanımlar)
# ==========================================================================
def _wilder_ema(values: Sequence[float | None], alpha: float) -> list[float | None]:
    """EWM(adjust=False): İlk geçerli değer tohum, sonrası alpha ile yumuşatma."""
    out: list[float | None] = [None] * len(values)
    prev: float | None = None
    for i, v in enumerate(values):
        if v is None or not math.isfinite(v):
            out[i] = prev
            continue
        prev = v if prev is None else v * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def adx_series(bars: Sequence[Bar], period: int = 14) -> list[float | None]:
    """ADX(14) — Wilder yumuşatma; HTML ile aynı: alpha = 1/period."""
    a = 1.0 / period
    n = len(bars)
    tr_raw: list[float | None] = [None] * n
    pdm: list[float | None] = [None] * n
    mdm: list[float | None] = [None] * n
    for i in range(1, n):
        yh = bars[i].high - bars[i - 1].high
        ll = bars[i - 1].low - bars[i].low
        pdm[i] = yh if (yh > ll and yh > 0) else 0.0
        mdm[i] = ll if (ll > yh and ll > 0) else 0.0
        tr_raw[i] = max(bars[i].high - bars[i].low,
                        abs(bars[i].high - bars[i - 1].close),
                        abs(bars[i].low - bars[i - 1].close))
    tr_e = _wilder_ema(tr_raw, a)
    p_e = _wilder_ema(pdm, a)
    m_e = _wilder_ema(mdm, a)
    dx: list[float | None] = []
    for i in range(n):
        if tr_e[i] in (None, 0) or p_e[i] is None or m_e[i] is None:
            dx.append(None)
            continue
        pdi = 100 * p_e[i] / max(tr_e[i], 1e-9)
        mdi = 100 * m_e[i] / max(tr_e[i], 1e-9)
        dx.append(100 * abs(pdi - mdi) / max(pdi + mdi, 1e-9))
    return _wilder_ema(dx, a)


def stochastic(bars: Sequence[Bar], period: int = 14, k_smooth: int = 3,
               d_smooth: int = 3) -> tuple[list[float | None], list[float | None]]:
    """Stochastic %K / %D — HTML: ham %K → SMA(k_smooth) → SMA(d_smooth)."""
    n = len(bars)
    raw: list[float | None] = [None] * n
    for i in range(period - 1, n):
        hh = max(b.high for b in bars[i - period + 1:i + 1])
        ll = min(b.low for b in bars[i - period + 1:i + 1])
        raw[i] = 100 * (bars[i].close - ll) / (hh - ll) if hh > ll else None

    def sma(seq: list[float | None], w: int) -> list[float | None]:
        out: list[float | None] = [None] * len(seq)
        for i in range(len(seq)):
            window = [x for x in seq[max(0, i - w + 1):i + 1] if x is not None]
            if len(window) == w:
                out[i] = sum(window) / w
        return out

    k = sma(raw, k_smooth)
    d = sma(k, d_smooth)
    return k, d


def obv_series(bars: Sequence[Bar], sma_len: int = 10) -> tuple[list[float],
                                                               list[float | None]]:
    """OBV + SMA(10) — hacim akışı yönü."""
    obv: list[float] = [0.0]
    for i in range(1, len(bars)):
        if bars[i].close > bars[i - 1].close:
            obv.append(obv[-1] + bars[i].volume)
        elif bars[i].close < bars[i - 1].close:
            obv.append(obv[-1] - bars[i].volume)
        else:
            obv.append(obv[-1])
    sma: list[float | None] = [None] * len(obv)
    for i in range(len(obv)):
        if i + 1 >= sma_len:
            sma[i] = sum(obv[i + 1 - sma_len:i + 1]) / sma_len
    return obv, sma


def vwap_series(bars: Sequence[Bar]) -> list[float | None]:
    """Günlük VWAP — UTC gün sınırında sıfırlanır (HTML/finL: ts//86400000)."""
    out: list[float | None] = [None] * len(bars)
    day = None
    pv = 0.0
    vol = 0.0
    for i, b in enumerate(bars):
        d = b.open_ms // 86_400_000
        if d != day:
            day, pv, vol = d, 0.0, 0.0
        typical = (b.high + b.low + b.close) / 3
        pv += typical * b.volume
        vol += b.volume
        out[i] = pv / vol if vol > 0 else None
    return out


def cci_series(bars: Sequence[Bar], period: int = 20) -> list[float | None]:
    """CCI(20) — tipik fiyat, ortalama sapma."""
    out: list[float | None] = [None] * len(bars)
    tp = [(b.high + b.low + b.close) / 3 for b in bars]
    for i in range(period - 1, len(bars)):
        window = tp[i - period + 1:i + 1]
        mean = sum(window) / period
        dev = sum(abs(x - mean) for x in window) / period
        out[i] = (tp[i] - mean) / (0.015 * dev) if dev > 0 else None
    return out


def supertrend_series(bars: Sequence[Bar], period: int = 10,
                      mult: float = 3.0) -> list[float | None]:
    """Supertrend(10, 3) — yön (+1 yukarı / -1 aşağı) dizisi."""
    n = len(bars)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    atr_vals: list[float | None] = [None] * n
    trs: list[float] = []
    for i in range(1, n):
        trs.append(max(bars[i].high - bars[i].low,
                       abs(bars[i].high - bars[i - 1].close),
                       abs(bars[i].low - bars[i - 1].close)))
        if len(trs) >= period:
            atr_vals[i] = sum(trs[-period:]) / period
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    trend: list[int] = [1] * n
    for i in range(period, n):
        a = atr_vals[i]
        if a is None:
            continue
        mid = (bars[i].high + bars[i].low) / 2
        bu, bl = mid + mult * a, mid - mult * a
        if i == period:
            upper[i], lower[i], trend[i] = bu, bl, 1
            continue
        prev_u, prev_l = upper[i - 1], lower[i - 1]
        upper[i] = bu if (prev_u is None or bu < prev_u or bars[i - 1].close > prev_u) else prev_u
        lower[i] = bl if (prev_l is None or bl > prev_l or bars[i - 1].close < prev_l) else prev_l
        if bars[i].close > upper[i]:
            trend[i] = 1
        elif bars[i].close < lower[i]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
        out[i] = float(trend[i])
    return out


# ==========================================================================
# 2) CONFLUENCE — 10 filtre oylaması (HTML v3.4 ile aynı ağırlıklar)
# ==========================================================================
@dataclass
class ConfluenceResult:
    side: str                     # long | short | ""
    score: int
    votes: dict[str, int]
    threshold: int
    detail: dict[str, float] = field(default_factory=dict)


def confluence_skoru(bars: Sequence[Bar], params: dict) -> ConfluenceResult | None:
    """HTML'deki 10 filtreli Confluence mantığının Python karşılığı.

    Oylar (HTML ile aynı): 1 EMA dizilişi, 2 MACD kesişimi, 3 RSI bölgesi,
    4 ADX+EMA hizası, 5 Stoch kesişimi, 6 OBV akışı, 7 CCI, 8 Supertrend,
    9 VWAP, 10 Bollinger kırılımı. Eşik varsayılan 4, sınır 2..8.
    """
    need = int(params.get("conf_min_bars", 220))
    if len(bars) < need:
        return None
    closes = [b.close for b in bars]
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    m_line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    m_sig = ema(m_line, 9)
    adx_s = adx_series(bars)
    k_s, d_s = stochastic(bars)
    obv_s, obv_sma = obv_series(bars)
    vwap_s = vwap_series(bars)
    cci_s = cci_series(bars)
    st_s = supertrend_series(bars)

    i = len(bars) - 1
    c = closes[i]
    r = rsi(closes)
    votes: dict[str, int] = {}

    up = e20[i] > e50[i] > e200[i]
    dn = e20[i] < e50[i] < e200[i]
    votes["ema"] = 1 if up else -1 if dn else 0

    def ok(*xs) -> bool:
        return all(x is not None and math.isfinite(x) for x in xs)

    votes["macd"] = (1 if ok(m_line[i - 1], m_sig[i - 1], m_line[i], m_sig[i])
                     and m_line[i - 1] <= m_sig[i - 1] and m_line[i] > m_sig[i]
                     else -1 if ok(m_line[i - 1], m_sig[i - 1], m_line[i], m_sig[i])
                     and m_line[i - 1] >= m_sig[i - 1] and m_line[i] < m_sig[i] else 0)
    votes["rsi"] = 1 if r is not None and r > 55 else -1 if r is not None and r < 45 else 0
    adx_v = adx_s[i]
    votes["adx"] = (1 if ok(adx_v) and adx_v > 25 and e20[i] > e50[i]
                    else -1 if ok(adx_v) and adx_v > 25 and e20[i] < e50[i] else 0)
    votes["stoch"] = (1 if ok(k_s[i - 1], d_s[i - 1], k_s[i], d_s[i])
                      and k_s[i - 1] <= d_s[i - 1] and k_s[i] > d_s[i] and k_s[i] < 80
                      else -1 if ok(k_s[i - 1], d_s[i - 1], k_s[i], d_s[i])
                      and k_s[i - 1] >= d_s[i - 1] and k_s[i] < d_s[i] and k_s[i] > 20 else 0)
    votes["obv"] = (1 if ok(obv_s[i], obv_sma[i], obv_s[i - 1])
                    and obv_s[i] > obv_sma[i] and obv_s[i] > obv_s[i - 1]
                    else -1 if ok(obv_s[i], obv_sma[i], obv_s[i - 1])
                    and obv_s[i] < obv_sma[i] and obv_s[i] < obv_s[i - 1] else 0)
    cci_v = cci_s[i]
    votes["cci"] = (1 if ok(cci_v) and 0 < cci_v < 100
                    else -1 if ok(cci_v) and -100 < cci_v < 0 else 0)
    votes["supertrend"] = 1 if ok(st_s[i]) and st_s[i] > 0 else -1 if ok(st_s[i]) and st_s[i] < 0 else 0
    vwap_v = vwap_s[i]
    votes["vwap"] = 1 if ok(vwap_v) and c > vwap_v else -1 if ok(vwap_v) and c < vwap_v else 0
    # Bollinger kırılımı
    window = closes[i - 19:i + 1]
    mean = sum(window) / len(window)
    sd = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))
    votes["boll"] = 1 if c > mean + 2 * sd else -1 if c < mean - 2 * sd else 0

    score = sum(votes.values())
    th = int(max(2, min(8, params.get("conf_th", 4))))
    side = "long" if score >= th else "short" if score <= -th else ""
    return ConfluenceResult(side=side, score=score, votes=votes, threshold=th,
                            detail={"adx": adx_v or 0.0, "rsi": r or 0.0,
                                    "cci": cci_s[i] or 0.0,
                                    "vwap": vwap_s[i] or 0.0})


# ==========================================================================
# 3) SİNYAL ÜRETİCİ — mevcut 5 oylu skor + Confluence birleşimi
# ==========================================================================
def sinyal(bars: Sequence[Bar], params: dict) -> tuple[Signal | None, dict]:
    """Aktif stratejiye göre sinyal üretir; her zaman denetim bilgisi döndürür."""
    from .bot import strategi_skoru          # döngüsel import olmaması için yerel
    mod = params.get("strateji", "skor")
    info: dict = {"mod": mod}
    if mod == "confluence":
        conf = confluence_skoru(bars, params)
        if conf is None:
            info["reason"] = "INSUFFICIENT_BARS"
            return None, info
        info.update({"score": conf.score, "votes": conf.votes,
                     "threshold": conf.threshold, **conf.detail})
        if not conf.side:
            info["reason"] = "THRESHOLD"
            return None, info
        if params.get("conf_chop_gate", True):
            from .bot import choppiness
            chop = choppiness(bars)
            info["chop"] = chop
            if chop is not None and chop >= float(params.get("max_chop", 62.0)):
                info["reason"] = "CHOP"
                return None, info
        from .bot import atr as _atr
        a = _atr(bars)
        if not a or a <= 0:
            info["reason"] = "ATR_MISSING"
            return None, info
        sig = Signal(conf.side, float(conf.score), conf.votes, a, bars[-1].close,
                     bars[-1].open_ms, "confluence≥eşik")
        info["reason"] = "SIGNAL"
        return sig, info
    sig = strategi_skoru(bars, params)
    info["reason"] = "SIGNAL" if sig else "SCORE"
    return sig, info


# ==========================================================================
# 4) BARIŞIKLIK (mum sürekliliği + bütünlük) — ACARBOT Python'dan uyarlama
# ==========================================================================
def mum_denetimi(bars: Sequence[Bar], max_gap_ms: int = 60_000) -> tuple[bool, str]:
    """Kapanmış mum serisinde boşluk/bozukluk var mı? (ACARBOT: CANDLE_GAP/BAD_CANDLE)

    NOVA 3 borsada çalıştığı ve WS kopmaları olabildiği için boşluk denetimi
    tek bir mum atlamasını hoş görür: **iki ardışık** eksik mum = GAP.
    """
    if len(bars) < 3:
        return False, "INSUFFICIENT"
    # açıkça artan sıra (kaynak sırası bozuksa boşluk sayılmaz, sıralı bakılır)
    bars = sorted(bars, key=lambda b: b.open_ms)
    for i in range(1, len(bars)):
        d = bars[i].open_ms - bars[i - 1].open_ms
        if d <= max_gap_ms:
            continue
        # kaç mum eksik? tek eksik mum hoş görülür, iki ve fazlası boşluktur
        missing = round(d / max_gap_ms) - 1
        if missing >= 2:
            return False, "CANDLE_GAP"
    for b in bars[-5:]:
        if not all(math.isfinite(x) for x in (b.open, b.high, b.low, b.close)):
            return False, "BAD_CANDLE"
        if b.low > min(b.open, b.close) or b.high < max(b.open, b.close) or b.low > b.high:
            return False, "BAD_CANDLE"
    return True, ""


# ==========================================================================
# 5) MALİYET / BEKLENEN HAREKET KAPISI — ACARBOT'un EDGE_BELOW_COST'u
# ==========================================================================
def edge_dengesi(price: float, spread_bps: float, atr_v: float, cfg,
                 move_fraction: float = 0.35) -> dict:
    """Gidiş-dönüş maliyet vs beklenen hareket (ACARBOT ile aynı formül).

    cost_bps  = ücret(2 yön) + kayma(2 yön) + makas
    move_bps  = ATR × move_fraction → fiyata çevrilmiş beklenen hareket
    `min_edge_ratio` altındaysa giriş reddedilir (HTML ACARBOT: 1.15).
    DİKKAT: bu kapı işlem sayısını **ciddi biçimde** azaltır; ACARBOT'un
    15 dakikalık koşusunda 11 sinyalin 10'u burada reddedildi.
    """
    cost_bps = cfg.taker_bps * 2 + cfg.slip_bps * 2 + max(0.0, spread_bps)
    move_bps = (atr_v / price) * 10000 * move_fraction if price > 0 else 0.0
    ratio = (move_bps / cost_bps) if cost_bps > 0 else 0.0
    return {"cost_bps": round(cost_bps, 2), "move_bps": round(move_bps, 2),
            "ratio": round(ratio, 3), "ok": ratio >= float(cfg.min_edge_ratio)}


# ==========================================================================
# 6) DCA GÜVENLİK EMRİ — HTML v3.4 DCAEngine'in ortalama-maliyet mantığı
# ==========================================================================
@dataclass
class DcaPlan:
    max_adds: int
    step_pct: float           # ortalamaya göre kaç % düşüşte ekleme
    mult: float               # her eklemede marj çarpanı
    tp_pct: float             # ortalamadan hedef (%)
    stop_pct: float           # ortalamadan stop (%)
    adds_done: int = 0
    realized_adds: list[float] = field(default_factory=list)


def dca_ekle(p, price: float, plan: DcaPlan, cfg) -> tuple[bool, str]:
    """Pozisyona ekleme yapar: adet/marj ortalaması güncellenir.

    HTML'deki `dcaEkle` ile aynı muhasebe: yeni ortalama = ağırlıklı ortalama,
    ekleme büyüklüğü = ilk marj × mult^(ekleme sırası). Stop ve hedef yeni
    ortalamadan yeniden hesaplanır. Yalnız LONG (HTML de yalnız LONG yapıyor).
    """
    from decimal import Decimal as D
    if p.side != "long" or plan.adds_done >= plan.max_adds or price <= 0:
        return False, "DCA_NOT_ALLOWED"
    base = p.notional / max(1, 1)                     # ilk notional referansı
    add_usd = float(p.dca_base_notional or base) * (plan.mult ** (plan.adds_done + 1))
    if add_usd < 5:
        return False, "DCA_TOO_SMALL"
    add_qty_nominal = D(str(add_usd))
    unit = D(str(price)) * p.face
    qty_add = (add_qty_nominal / unit).to_integral_value(rounding=__import__(
        "decimal").ROUND_DOWN)
    if qty_add <= 0:
        return False, "DCA_QTY_ZERO"
    new_qty = p.qty + qty_add
    p.entry = (p.entry * p.qty + D(str(price)) * qty_add) / new_qty
    p.qty = new_qty
    p.notional = p.qty * p.face * p.entry
    p.open_fee += add_qty_nominal * D(str(cfg.taker_bps)) / 10000
    p.risk = (p.entry - p.stop) * p.qty * p.face if p.stop < p.entry else p.risk
    plan.adds_done += 1
    plan.realized_adds.append(price)
    # yeni ortalamadan stop/hedef
    p.stop = p.entry * D(str(1 - plan.stop_pct / 100))
    p.tp = p.entry * D(str(1 + plan.tp_pct / 100))
    return True, f"DCA_ADD_{plan.adds_done}"


# ==========================================================================
# 7) GENİŞLİK (breadth) — ACARBOT'un piyasa genişliği fikrinin ucuz sürümü
# ==========================================================================
def genislik(history: dict[str, list[Bar]]) -> float:
    """Evrendeki sembollerin ne kadarı EMA20 üstünde? -1..+1 arası nötr skala.

    ACARBOT Python bunu 'breadth' olarak taşıyor ama bu koşuda ölçmedi
    (mtf_aligned=False, breadth yok). NOVA bunu ısınmış 1m serilerden
    bedavaya hesaplayabilir; filtrenin kendisi **opsiyonel**.
    """
    up = tot = 0
    for bars in history.values():
        if len(bars) < 25:
            continue
        closes = [b.close for b in bars]
        e = ema(closes, 20)[-1]
        tot += 1
        up += 1 if closes[-1] > e else 0
    if not tot:
        return 0.0
    return round((up / tot) * 2 - 1, 3)
