import asyncio

from scanner.universe import split_okx_binance_overlap
from scanner.ws_scanner import OKX_INSTR, OKX_SPOT, okx_enstrumanlari


def test_okx_duplicates_removed_when_binance_has_same_base():
    okx = ["BTC-USDT-SWAP", "1000PEPE-USDT-SWAP", "ONLY-USDT-SWAP"]
    binance = {"BTCUSDT", "PEPEUSDT", "ETHUSDT"}
    kept, overlap = split_okx_binance_overlap(okx, binance)
    assert kept == ["ONLY-USDT-SWAP"]
    assert overlap == ["BTC-USDT-SWAP", "1000PEPE-USDT-SWAP"]


class _Response:
    def __init__(self, body):
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.body


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == OKX_INSTR:
            return _Response({"data": [
                {"instId": "BTC-USDT-SWAP", "settleCcy": "USDT", "state": "live", "instCategory": "1"},
                {"instId": "AAPL-USDT-SWAP", "settleCcy": "USDT", "state": "live", "instCategory": "3"},
                {"instId": "XAU-USDT-SWAP", "settleCcy": "USDT", "state": "live", "instCategory": "4"},
                {"instId": "OLD-USDT-SWAP", "settleCcy": "USDT", "state": "suspend", "instCategory": "1"},
                {"instId": "BTC-USD-SWAP", "settleCcy": "USD", "state": "live", "instCategory": "1"},
            ]})
        if url == OKX_SPOT:
            return _Response({"data": [{"instId": "BTC-USDT"}, {"instId": "ETH-USDT"}]})
        raise AssertionError(f"unexpected URL: {url}")


def test_okx_universe_excludes_us_equity_and_commodity_categories():
    session = _Session()
    symbols, spot_bases = asyncio.run(okx_enstrumanlari(session))
    assert symbols == ["BTC-USDT-SWAP"]
    assert spot_bases == {"BTC", "ETH"}
    assert len(session.calls) == 2
