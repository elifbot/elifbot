"""
Phase C — open interest.

UNVERIFIED: OI uç noktası DOĞRULANMADI; hiçbir sinyalde kullanılmaz.
"""
from __future__ import annotations

from data.extended import DataUnavailableError


class OpenInterestFeed:
    """OI verisi sağlamaz; açıkça hata fırlatır."""

    name = "open_interest"

    def fetch_open_interest(self, exchange: str, symbol: str) -> float:
        raise DataUnavailableError("open interest: unverified or unavailable")
