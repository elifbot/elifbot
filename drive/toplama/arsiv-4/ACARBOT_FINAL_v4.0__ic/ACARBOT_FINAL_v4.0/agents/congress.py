"""v4.0 — Kongre işlemleri ajanı (madde 20): DÜRÜST "uygulanmadı" durumu.

Kullanıcı şartnamesi kendisi "veri kaynağı gerekir" notunu taşır: ABD
kongre üyelerinin işlem verileri için güvenilir, ücretsiz ve programatik
bir kaynak YOKTUR (QuiverQuant vb. ücretlidir; Capitol trades scraping
tos ihlali + kararlılık sorunu taşır). Bot çalışma zamanına kararsız bir
veri hattı gömmek, "uygulanmadı" diye sahte veri göstermekten daha
kötüdür — bu yüzden ajan yalnızca ŞEFFAF bir durum raporlar.

Tasarım sözleşmesi: bilgi sinyalidir, işlem TETİKLEMEZ. Gelecekte bir
veri kaynağı bağlanacaksa `ingest(trades)` + `entry_block` arabirimi
hazırdır; o güne kadar status()["available"] = False döner.
"""

from __future__ import annotations


class CongressAgent:
    """Kongre işlem verisi ajanı — mevcut durum: veri kaynağı yok."""

    name = "congress"

    REASON = (
        "uygulanmadı: güvenilir ücretsiz veri kaynağı yok (ücretli API "
        "gerekir: QuiverQuant vb.). Bilgi sinyali olarak tasarlandı; "
        "işlem tetiklemez."
    )

    def __init__(self, mode: str = "off") -> None:
        self.mode = mode

    def tick(self, now_ms: int | None = None) -> None:
        return None  # veri kaynağı olmadığından tazeleme yok

    def entry_block(self, now_ms: int) -> str | None:
        return None  # ASLA engellemez (bilgi sinyali; işlem tetiklemez)

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "available": False,
            "reason": self.REASON,
        }
