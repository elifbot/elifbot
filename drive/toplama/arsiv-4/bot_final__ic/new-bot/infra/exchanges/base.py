"""Read-only public REST client base; intentionally has no order endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from infra.market_data.models import Candle


@dataclass(frozen=True)
class Market:
    symbol: str
    base_asset: str
    quote_volume_24h: float
    contract_type: str
    tick_size: float = 0.0
    percentage_24h: float = 0.0


@dataclass(frozen=True)
class Ticker:
    symbol: str
    quote_volume_24h: float
    last_price: float
    timestamp_ms: int


class PublicMarketDataError(RuntimeError):
    """Public market data could not be fetched or parsed."""


class PublicExchange:
    name = ""
    base_url = ""
    user_agent = "paper-trading-bot/1.0"

    def _get_json(self, path: str, params: dict[str, object]) -> object:
        url = f"{self.base_url}{path}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise PublicMarketDataError(
                        f"{self.name} public API returned HTTP {response.status}"
                    )
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise PublicMarketDataError(
                f"{self.name} public market-data request failed: {exc}"
            ) from exc

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        raise NotImplementedError

    def fetch_ticker(self, symbol: str) -> Ticker:
        raise NotImplementedError

    def fetch_top_usdt_futures(self, limit: int = 100) -> list[Market]:
        raise NotImplementedError

    async def stream_tickers(
        self, symbols: Sequence[str] | None = None
    ) -> AsyncIterator[Ticker]:
        raise NotImplementedError

    def fetch_price(self, symbol: str) -> float:
        return self.fetch_ticker(symbol).last_price


def validate_request(symbol: str, timeframe: str, limit: int) -> None:
    if not symbol or any(char.isspace() for char in symbol):
        raise ValueError("symbol must be a non-empty exchange symbol")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if timeframe not in {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}:
        raise ValueError("unsupported timeframe")
