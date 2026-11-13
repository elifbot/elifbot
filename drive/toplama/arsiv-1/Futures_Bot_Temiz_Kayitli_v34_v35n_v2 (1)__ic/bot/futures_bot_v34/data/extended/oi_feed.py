"""Phase C (v18) — open interest: GERCEK public feed."""
from __future__ import annotations
from data.extended._http import get_json, okx_data

class OpenInterestFeed:
    name = "open_interest"
    def __init__(self, session=None): self._session = session
    def fetch_open_interest(self, exchange: str, symbol: str) -> float:
        if exchange == "binance":
            d = get_json("https://fapi.binance.com/fapi/v1/openInterest", {"symbol": symbol}, self._session)
            return float(d["openInterest"])
        if exchange == "okx":
            d = okx_data(get_json("https://www.okx.com/api/v5/public/open-interest", {"instType": "SWAP", "instId": symbol}, self._session))
            return float(d["oi"])
        from data.extended import DataUnavailableError
        raise DataUnavailableError(f"bilinmeyen borsa: {exchange}")
