"""Maker ters seçilim (adverse selection) ölçümü — v5.6.

SORU
----
Maker emirlerimiz "fiyat bize doğru gelirken değil, bize karşı
giderken" mi doluyor? Öyleyse beklenen kazancın bir kısmı dolum
anında kaybediliyor demektir.

MARKOUT NEDİR?
--------------
Dolumdan T dakika sonraki fiyatın dolum fiyatına göre, POZİSYON
YÖNÜNDE ne kadar ilerlediği:

    markout(T) = yön × (fiyat(t_dolum + T) − fiyat_dolum) / fiyat_dolum

  yön = +1 LONG, −1 SHORT

Pozitif markout → dolum sonrası fiyat lehimize gitmiş (iyi dolum).
Negatif markout → dolum sonrası fiyat aleyhimize gitmiş (ters seçilim).

NEDEN HAM FİYAT YETMEZ?
-----------------------
Piyasa genel olarak düşerken LONG markout'u negatif çıkar; bu
"ters seçilim" değil, piyasa sürüklenmesidir. Bu yüzden iki referans
birlikte raporlanır:

  * HAM markout        — olduğu gibi
  * PİYASADAN ARINDIRILMIŞ — aynı pencerede eşit-ağırlıklı evren
    getirisini çıkarır (beta=1 varsayımı; beta tahmini EDİLMEDİ)

KARŞILAŞTIRMA GRUBU
-------------------
Yalnız dolan emirlere bakmak yanlıdır. DolMAYAN emirler de aynı
alanlarla kaydedilir ve iki grup karşılaştırılır: ters seçilim
iddiası ancak "dolanlar, dolmayanlardan anlamlı kötü" ise desteklenir.

ÖRNEKLEM EŞİĞİ
--------------
Kullanıcı şartnamesi: en az 300 dolum. Bunun altında hüküm
YETERSIZ_ORNEKLEM'dir; "ters seçilim yok" DENMEZ.

DÜRÜSTLÜK
---------
Bu modül ölçüm ALTYAPISIDIR. Gerçek testnet dolumu olmadan
markout ÜRETMEZ ve sıfır göstermez — kayıt yoksa "veri yok" döner.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

# Dolum sonrası izleme pencereleri (dakika) — şartname
MARKOUT_HORIZONS_MIN: tuple[int, ...] = (1, 5, 15, 30)
MIN_FILLS_FOR_VERDICT = 300


@dataclass
class FillRecord:
    """Tek bir maker emrinin tam yaşam döngüsü.

    Dolmayan emirlerde `fill_*` alanları boş kalır; bu bir eksik
    değil, "dolmadı" bilgisidir ve karşılaştırma grubunu oluşturur.
    """

    order_id: str
    symbol: str
    side: str                       # LONG | SHORT
    # Sinyal anı
    signal_ts_ms: int
    signal_price: float
    # Gönderim anı
    submit_ts_ms: int = 0
    submit_price: float = 0.0       # gönderilen limit fiyatı
    submit_best_bid: float = 0.0
    submit_best_ask: float = 0.0
    submit_spread_bps: float = 0.0
    submit_book_imbalance: float = 0.0   # (bid_qty − ask_qty)/(toplam)
    # Dolum öncesi hareket (ters seçilimin erken işareti)
    pre_move_bps: dict[str, float] = field(default_factory=dict)
    # Dolum
    filled: bool = False
    fill_ts_ms: int = 0
    fill_price: float = 0.0
    fill_qty: float = 0.0
    fill_latency_ms: int = 0
    # Dolum sonrası fiyatlar (markout için ham veri)
    post_prices: dict[str, float] = field(default_factory=dict)
    # Evren (piyasa) getirisi — arındırma için
    market_post_returns: dict[str, float] = field(default_factory=dict)
    # Maliyetler
    fee_paid: float = 0.0
    slippage_bps: float = 0.0
    cancelled: bool = False
    cancel_reason: str = ""

    def direction(self) -> float:
        return 1.0 if self.side.upper() in ("LONG", "BUY") else -1.0

    def markout_bps(self, horizon_min: int) -> float | None:
        """Ham markout (baz puan). Veri yoksa None — SIFIR DEĞİL."""
        if not self.filled or self.fill_price <= 0:
            return None
        px = self.post_prices.get(str(horizon_min))
        if px is None or px <= 0:
            return None
        return self.direction() * (px - self.fill_price) / self.fill_price * 1e4

    def markout_excess_bps(self, horizon_min: int) -> float | None:
        """Piyasa getirisinden arındırılmış markout (beta=1)."""
        raw = self.markout_bps(horizon_min)
        if raw is None:
            return None
        mkt = self.market_post_returns.get(str(horizon_min))
        if mkt is None:
            return None
        return raw - self.direction() * mkt * 1e4

    def to_dict(self) -> dict:
        return asdict(self)


def _ci95(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 3:
        return None
    m = statistics.mean(values)
    se = statistics.stdev(values) / math.sqrt(len(values))
    return (m - 1.96 * se, m + 1.96 * se)


def analyze_fills(records: list[FillRecord]) -> dict:
    """Dolan/dolmayan karşılaştırmalı ters seçilim analizi.

    Kayıt yoksa veya örneklem yetersizse hüküm açıkça söylenir;
    ölçülmeyen metrik None döner (0 DEĞİL).
    """
    filled = [r for r in records if r.filled]
    unfilled = [r for r in records if not r.filled]
    out: dict = {
        "olcum_zamani": datetime.now(UTC).isoformat(),
        "kayit_sayisi": len(records),
        "dolan": len(filled),
        "dolmayan": len(unfilled),
        "dolum_orani": (len(filled) / len(records)) if records else None,
        "esik": MIN_FILLS_FOR_VERDICT,
        "pencereler_dk": list(MARKOUT_HORIZONS_MIN),
        "markout": {},
        "dolmayan_karsilastirma": {},
        "hukum": "VERI_YOK",
        "neden": "",
    }
    if not records:
        out["neden"] = "Hiç emir kaydı yok. Testnet/paper dolumu toplanmadan ölçüm yapılamaz."
        return out

    for h in MARKOUT_HORIZONS_MIN:
        raw = [v for r in filled if (v := r.markout_bps(h)) is not None]
        exc = [v for r in filled if (v := r.markout_excess_bps(h)) is not None]
        # Dolmayan emirler: gönderim fiyatına göre "dolmuş olsaydı"
        # karşılaştırması (karşı-olgusal, etiketlenir)
        cf = []
        for r in unfilled:
            px = r.post_prices.get(str(h))
            if px and r.submit_price > 0:
                cf.append(r.direction() * (px - r.submit_price) / r.submit_price * 1e4)
        out["markout"][str(h)] = {
            "n": len(raw),
            "ham_ortalama_bps": statistics.mean(raw) if raw else None,
            "ham_medyan_bps": statistics.median(raw) if raw else None,
            "ham_ga95": _ci95(raw),
            "arindirilmis_n": len(exc),
            "arindirilmis_ortalama_bps": statistics.mean(exc) if exc else None,
            "arindirilmis_ga95": _ci95(exc),
        }
        out["dolmayan_karsilastirma"][str(h)] = {
            "n": len(cf),
            "karsi_olgusal_ortalama_bps": statistics.mean(cf) if cf else None,
            "NOT": "Dolmayan emirler için gönderim fiyatına göre karşı-olgusal; gerçek dolum DEĞİL.",
        }

    # Hüküm: arındırılmış 5 dk markout üzerinden
    h5 = out["markout"]["5"]
    n5, mean5, ci5 = h5["arindirilmis_n"], h5["arindirilmis_ortalama_bps"], h5["arindirilmis_ga95"]
    if n5 < MIN_FILLS_FOR_VERDICT:
        out["hukum"] = "YETERSIZ_ORNEKLEM"
        out["neden"] = (
            f"5 dk arındırılmış markout için {n5} dolum var; "
            f"şartname eşiği {MIN_FILLS_FOR_VERDICT}. "
            "'Ters seçilim yok' sonucu ÇIKARILAMAZ."
        )
    elif ci5 is None:
        out["hukum"] = "HESAPLANAMADI"
        out["neden"] = "Güven aralığı hesaplanamadı."
    elif ci5[1] < 0:
        out["hukum"] = "TERS_SECILIM_VAR"
        out["neden"] = (
            f"5 dk arındırılmış markout {mean5:.2f} bps, GA95 {ci5} — "
            "üst sınır sıfırın altında. Dolum sonrası fiyat sistematik aleyhimize."
        )
    elif ci5[0] > 0:
        out["hukum"] = "TERS_SECILIM_YOK_POZITIF"
        out["neden"] = f"5 dk arındırılmış markout {mean5:.2f} bps, GA95 {ci5} — pozitif."
    else:
        out["hukum"] = "ANLAMSIZ"
        out["neden"] = f"5 dk markout GA95 {ci5} sıfırı kapsıyor; kanıt yok."

    # Dolum öncesi hareket ve maliyet özeti (varsa)
    pre = [v for r in filled for v in r.pre_move_bps.values()]
    out["dolum_oncesi_hareket_bps_ort"] = statistics.mean(pre) if pre else None
    fees = [r.fee_paid for r in filled if r.fee_paid]
    out["toplam_komisyon"] = sum(fees) if fees else None
    slips = [r.slippage_bps for r in filled if r.slippage_bps]
    out["ort_kayma_bps"] = statistics.mean(slips) if slips else None
    return out