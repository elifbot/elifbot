"""
Phase C — funding rate.

UNVERIFIED: Bu proje kapsamında funding uç noktası DOĞRULANMADI.
Fonlama maliyeti hiçbir PnL hesabına dahil edilmez; tüm çıktılar
"funding hariç / bilinmiyor" olarak etiketlenir.
"""
from __future__ import annotations

from data.extended import DataUnavailableError


class FundingFeed:
    """Funding verisi sağlamaz; açıkça hata fırlatır."""

    name = "funding"

    def fetch_funding_rate(self, exchange: str, symbol: str) -> float:
        raise DataUnavailableError("funding: unverified or unavailable")
