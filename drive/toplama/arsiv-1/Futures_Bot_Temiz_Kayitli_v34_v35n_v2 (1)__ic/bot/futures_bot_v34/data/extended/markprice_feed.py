"""Phase C (v18) — mark price: GERCEK public feed."""
from __future__ import annotations
from data.extended._http import get_json, okx_data

class MarkPriceFeed:
    name = "mark_price"
    def __init__(self, session=None): self._session = session
    def fetch_mark_price(self, exchange: str, symbol: str) -> float:
        if exchange == "binance":
            d = get_json("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": symbol}, self._session)
            return float(d["markPrice"])
        if exchange == "okx":
            d = okx_data(get_json("https://www.okx.com/api/v5/public/mark-price", {"instType": "SWAP", "instId": symbol}, self._session))
            return float(d["markPx"])
        from data.extended import DataUnavailableError
        raise DataUnavailableError(f"bilinmeyen borsa: {exchange}")
