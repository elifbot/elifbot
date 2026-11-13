"""BOYUT TUTARLILIĞI — marj, kaldıraç ve stop birlikte sağlanabiliyor mu?

Kullanıcı şartnamesi
--------------------
    kasa            1.000 USDT
    pozisyon marjı     50 USDT
    kaldıraç           10x
    zarar kes          25 USDT

Bu üçlü **tek başına** stop mesafesini belirler:

    notional = marj x kaldıraç = 500 USDT
    gereken stop = (zarar / notional) - maliyet_oranı
                 = (25 / 500) - 0,002139 = %4,786

Yani şartname **%4,79 stop** ister. Ölçülen 5m stopları ise
**%0,33** — 14,5 kat daha dar.

v5.5'te bulunan kusur
---------------------
`apex` profilinde `margin_per_position = 0` ve
`max_notional_per_position = 0` (İKİSİ DE SINIRSIZ). Bot 25 USDT
riski hedefleyip notionalı serbestçe büyütüyordu:

    %0,33 stop → notional 5.102 USDT → marj 510 USDT

Bu, kullanıcının 50 USDT marj şartının **10,2 katı** ve 1.000 USDT
kasada tek pozisyonda bakiyenin %51'i. Üstelik `max_positions=0`
(sınırsız) olduğu için teorik olarak kasa katlanarak aşılabilirdi.

Ölçülen sonuç: ilk iki işlem 25'er USDT risk taşıdı ve toplam
zararın %58'ini yaptı.

Bu modül ne yapar
-----------------
Üç kısıtın hangisinin bağlayıcı olduğunu AÇIKÇA raporlar ve
şartname sessizce ihlal ediliyorsa uyarır. Sessizce birini seçip
diğerini çiğnemez.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COST_RATE = 0.002139  # ölçülen OKX gidiş-dönüş (v5.2)


@dataclass(frozen=True)
class SizingSpec:
    """Kullanıcının verdiği işlem şartnamesi."""

    balance: float = 1_000.0
    margin_per_position: float = 50.0
    leverage: float = 10.0
    max_loss_usdt: float = 25.0
    cost_rate: float = DEFAULT_COST_RATE

    @property
    def notional(self) -> float:
        return self.margin_per_position * self.leverage

    @property
    def required_stop_fraction(self) -> float:
        """25 USDT riski bu notionalda veren stop mesafesi."""
        return self.max_loss_usdt / self.notional - self.cost_rate

    @property
    def margin_fraction_of_balance(self) -> float:
        return self.margin_per_position / self.balance


def audit(
    stop_fraction: float, spec: SizingSpec | None = None,
) -> dict:
    """Verilen stop mesafesiyle şartname sağlanabiliyor mu?

    Üç senaryo:
      * stop == gereken stop  → üçü birden sağlanır (tutarlı)
      * stop <  gereken stop  → 25 USDT risk için marj ŞİŞMELİ
                                (şartname ihlali) veya risk küçülmeli
      * stop >  gereken stop  → marj sabitken risk 25'in ALTINDA kalır
                                (güvenli, şartname uyumlu)
    """
    s = spec or SizingSpec()
    if not 0 < stop_fraction < 1:
        raise ValueError("stop_fraction (0,1) aralığında olmalı")
    req = s.required_stop_fraction
    # 25 USDT riski bu stopla veren notional ve marj
    denom = stop_fraction + s.cost_rate
    notional_for_risk = s.max_loss_usdt / denom if denom > 0 else float("inf")
    margin_for_risk = notional_for_risk / s.leverage
    # marj sabitken gerçekleşen risk
    risk_at_spec_margin = s.notional * denom
    ratio = margin_for_risk / s.margin_per_position

    if ratio > 1.05:
        hukum = "SARTNAME_IHLALI"
        neden = (
            f"%{100 * stop_fraction:.3f} stop ile {s.max_loss_usdt:.0f} USDT risk "
            f"için marj {margin_for_risk:.2f} USDT gerekir — şartnamenin "
            f"{ratio:.1f} katı. Ya marj şişirilir (YASAK) ya da risk "
            f"{risk_at_spec_margin:.2f} USDT'ye düşer."
        )
    elif ratio < 0.95:
        # Geniş stop: 50 USDT marjda risk 25'i AŞARDI. Kayıp tavanı
        # bağlayıcı olur → notional (ve marj) KÜÇÜLTÜLÜR. Bu güvenlidir.
        hukum = "KAYIP_TAVANI_BAGLAYICI"
        neden = (
            f"%{100 * stop_fraction:.3f} stop ile {s.margin_per_position:.0f} USDT "
            f"marj {risk_at_spec_margin:.2f} USDT risk verirdi — tavanı aşar. "
            f"Bu yüzden marj {margin_for_risk:.2f} USDT'ye düşürülür; "
            f"{s.max_loss_usdt:.0f} USDT kayıp tavanı korunur. GÜVENLİ."
        )
    else:
        hukum = "TUTARLI"
        neden = (
            f"%{100 * stop_fraction:.3f} stop, {s.margin_per_position:.0f} USDT "
            f"marj ve {s.max_loss_usdt:.0f} USDT risk birlikte sağlanıyor."
        )

    return {
        "hukum": hukum,
        "neden": neden,
        "sartname": {
            "kasa": s.balance,
            "marj": s.margin_per_position,
            "kaldirac": s.leverage,
            "notional": s.notional,
            "zarar_kes": s.max_loss_usdt,
            "gereken_stop_yuzde": round(100 * req, 4),
            "maliyet_orani": s.cost_rate,
        },
        "verilen_stop_yuzde": round(100 * stop_fraction, 4),
        "risk_icin_gereken_marj": round(margin_for_risk, 4),
        "marj_sisme_katsayisi": round(ratio, 4),
        "sabit_marjda_risk_HIPOTETIK": round(risk_at_spec_margin, 4),
        "uygulanacak_marj": round(min(margin_for_risk, s.margin_per_position), 4),
        "uygulanacak_risk": round(
            min(risk_at_spec_margin, s.max_loss_usdt), 4),
        "maliyet_usdt": round(s.notional * s.cost_rate, 4),
        "maliyet_risk_payi": round(
            s.cost_rate / denom, 4,
        ),
        "kasa_payi_marj": round(s.margin_fraction_of_balance, 4),
    }


def required_timeframe_scale(
    observed_stop_fraction: float, spec: SizingSpec | None = None,
) -> dict:
    """Şartnamenin istediği stopa ulaşmak için zaman dilimi kaç kat büyümeli?

    ATR ~ sqrt(zaman) varsayımıyla: olcek = (hedef_stop / mevcut_stop)^2
    Bu bir YAKLAŞIKLIK; gerçek ATR ölçümüyle doğrulanmalıdır.
    """
    s = spec or SizingSpec()
    req = s.required_stop_fraction
    if observed_stop_fraction <= 0:
        raise ValueError("observed_stop_fraction pozitif olmalı")
    scale = (req / observed_stop_fraction) ** 2
    return {
        "mevcut_stop_yuzde": round(100 * observed_stop_fraction, 4),
        "gereken_stop_yuzde": round(100 * req, 4),
        "zaman_katsayisi": round(scale, 2),
        "5m_dakika": 5,
        "onerilen_dakika": round(5 * scale, 1),
        "onerilen_saat": round(5 * scale / 60, 2),
        "varsayim": "ATR ~ sqrt(zaman); gerçek ATR ile doğrulanmalı",
    }
