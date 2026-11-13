"""
Phase C — mark / index price.

UNVERIFIED: Mark-price uç noktası DOĞRULANMADI. Basis hesabı yapılmaz.
"""
from __future__ import annotations

from data.extended import DataUnavailableError


class MarkPriceFeed:
    """Mark price sağlamaz; açıkça hata fırlatır."""

    name = "mark_price"

    def fetch_mark_price(self, exchange: str, symbol: str) -> float:
        raise DataUnavailableError("mark price: unverified or unavailable")
