"""Phase C (v18) — funding rate: GERCEK public feed (Binance premiumIndex / OKX funding-rate)."""
from __future__ import annotations
from data.extended._http import get_json, okx_data

class FundingFeed:
    name = "funding"
    def __init__(self, session=None): self._session = session
    def fetch_funding_rate(self, exchange: str, symbol: str) -> float:
        if exchange == "binance":
            d = get_json("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": symbol}, self._session)
            return float(d["lastFundingRate"])
        if exchange == "okx":
            d = okx_data(get_json("https://www.okx.com/api/v5/public/funding-rate", {"instId": symbol}, self._session))
            return float(d["fundingRate"])
        from data.extended import DataUnavailableError
        raise DataUnavailableError(f"bilinmeyen borsa: {exchange}")
