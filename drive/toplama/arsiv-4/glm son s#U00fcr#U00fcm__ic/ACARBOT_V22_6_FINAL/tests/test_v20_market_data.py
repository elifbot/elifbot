import time
import pytest
from phoenix.config import Config
from phoenix.live import LiveSignalRunner, LiveConfig
from phoenix.models import Market
from phoenix.utils_retry import with_retry, RetryPolicy, is_ban, parse_ban_until, ExchangeBanned


class BinanceLike:
    """24hr ticker has NO bid/ask; mixed swap+future batch raises (ccxt binance rule)."""
    exchange = "BINANCE"
    client = type("C", (), {"has": {"fetchTickers": True, "fetchBidsAsks": True}})()

    def __init__(self):
        self.ticker_calls, self.ba_calls = [], []

    def load_markets(self):
        return [Market("BINANCE", "BTC/USDT:USDT", "BTC", "USDT", "USDT", "swap"),
                Market("BINANCE", "ETH/USDT:USDT", "ETH", "USDT", "USDT", "swap"),
                Market("BINANCE", "BTC/USDT:USDT-261225", "BTC", "USDT", "USDT", "future")]

    def tickers(self, symbols):
        kinds = {("future" if "-" in s else "swap") for s in symbols}
        self.ticker_calls.append(list(symbols))
        if len(kinds) > 1:
            raise ValueError("binance symbols must be of the same type, either swap or future.")
        return {s: {"bid": None, "ask": None, "last": 100.0, "quoteVolume": 9e6} for s in symbols}

    def bids_asks(self, symbols):
        self.ba_calls.append(list(symbols))
        return {s: {"bid": 99.99, "ask": 100.01} for s in symbols}


def _runner(adapter, **kw):
    cfg = Config(max_spread_bps=12, **kw)
    r = LiveSignalRunner(cfg, LiveConfig(duration_sec=0), adapters={adapter.exchange: adapter})
    r.refresh_universe()
    return r


def test_swap_and_future_are_never_mixed_in_one_batch():
    a = BinanceLike(); r = _runner(a)
    ranked = r._rank_tickers()
    assert len(a.ticker_calls) == 2
    assert all(len({("future" if "-" in s else "swap") for s in call}) == 1 for call in a.ticker_calls)
    assert len(ranked["BINANCE"]) == 3


def test_missing_bid_ask_is_completed_from_bookticker():
    a = BinanceLike(); r = _runner(a)
    ranked = r._rank_tickers()
    # one call per market type (swap / dated future), never one per symbol and never mixed
    assert len(a.ba_calls) == 2
    assert all(len({("future" if "-" in s else "swap") for s in call}) == 1 for call in a.ba_calls)
    assert all(t["bid"] and t["ask"] for _, _, t in ranked["BINANCE"])
    assert r.tm.rank_rejections["BINANCE"].get("wide_spread", 0) == 0


def test_unknown_spread_is_not_treated_as_99999_bps():
    a = BinanceLike()
    a.client = type("C", (), {"has": {"fetchTickers": True, "fetchBidsAsks": False}})()
    a.bids_asks = lambda s: {}
    r = _runner(a)
    ranked = r._rank_tickers()
    assert len(ranked["BINANCE"]) == 3              # admitted; true spread is enforced from the order book later
    assert r.tm.rank_rejections["BINANCE"]["spread_unknown_admitted"] == 3


def test_rank_rejection_reasons_are_counted_separately():
    class A(BinanceLike):
        def tickers(self, symbols):
            out = {}
            for s in symbols:
                if "ETH" in s:
                    out[s] = {"bid": 99.0, "ask": 101.0, "last": 100.0, "quoteVolume": 9e6}     # 200 bps
                elif "-" in s:
                    out[s] = {"bid": 99.99, "ask": 100.01, "last": 100.0, "quoteVolume": 10.0}  # tiny volume
            return out
    r = _runner(A())
    rr = r._rank_tickers() and r.tm.rank_rejections["BINANCE"]
    assert rr["wide_spread"] == 1 and rr["low_volume"] == 1 and rr["no_ticker"] == 1


def test_okx_quote_volume_uses_contract_value_not_raw_contract_count():
    from phoenix.models import Market
    t = {"last": 74.0,
         "info": {"instType": "SWAP", "vol24h": "100000000", "volCcy24h": "100000000"}}
    m = Market("OKX", "XAG/USDT:USDT", "XAG", "USDT", "USDT", "swap", contract_size=0.01,
               info={"instType": "SWAP", "ctVal": "0.01", "ctMult": "1", "ctValCcy": "XAG"})
    qv, src = LiveSignalRunner._quote_volume_info(t, m)
    assert qv == 74_000_000 and src == "okx.vol24h*ctVal*ctMult_base*last"


def test_okx_volume_fails_closed_without_contract_metadata():
    t = {"last": 74.0, "quoteVolume": 7.42e9, "info": {"instType": "SWAP", "vol24h": "100000000"}}
    qv, src = LiveSignalRunner._quote_volume_info(t)
    assert qv == 0 and src == "okx_contract_metadata_missing"


def test_quote_volume_falls_back_in_order():
    assert LiveSignalRunner._quote_volume({"last": 10, "quoteVolume": 123.0}) == 123.0
    assert LiveSignalRunner._quote_volume({"last": 10, "quoteVolume": None, "baseVolume": 5}) == 50
    assert LiveSignalRunner._quote_volume({"last": 0, "baseVolume": 5}) == 0.0


def test_ban_is_detected_and_never_retried():
    msg = 'binance {"code":-1003,"msg":"Way too many requests; IP(1.2.3.4) banned until 1794385677806."}'
    exc = RuntimeError(msg)
    assert is_ban(exc) and abs(parse_ban_until(exc) - 1794385677.806) < 1e-3
    calls = []
    def fn():
        calls.append(1); raise exc
    with pytest.raises(RuntimeError):
        with_retry(fn, RetryPolicy(attempts=5, base_delay=0, jitter=0))
    assert len(calls) == 1


def test_validity_errors_are_not_retried_but_network_errors_are():
    class BadRequest(Exception): pass
    class RequestTimeout(Exception): pass
    n = {"bad": 0, "net": 0}
    def bad():
        n["bad"] += 1; raise BadRequest("x")
    def net():
        n["net"] += 1
        if n["net"] < 3: raise RequestTimeout("t")
        return "ok"
    with pytest.raises(BadRequest):
        with_retry(bad, RetryPolicy(attempts=4, base_delay=0, jitter=0))
    assert n["bad"] == 1
    assert with_retry(net, RetryPolicy(attempts=4, base_delay=0, jitter=0)) == "ok" and n["net"] == 3


def test_banned_exchange_is_skipped_and_reported():
    a = BinanceLike()
    a.banned = lambda: True
    a.banned_until = time.time() + 600
    a.ban_message = "banned until x"
    r = _runner(a)
    ranked = r._rank_tickers()
    assert ranked["BINANCE"] == [] and a.ticker_calls == []
    assert r.tm.exchange_status["BINANCE"]["banned"] is True
    assert r.tm.rank_rejections["BINANCE"]["exchange_banned"] == 3


def test_detail_cap_rotates_through_the_tail():
    a = BinanceLike()
    r = LiveSignalRunner(Config(), LiveConfig(duration_sec=0, detail_symbols_per_exchange=2, rotation_slots=1), adapters={"BINANCE": a})
    items = [(100 - i, Market("BINANCE", f"S{i}/USDT:USDT", f"S{i}", "USDT", "USDT", "swap"), {}) for i in range(6)]
    first = [x[1].symbol for x in r._detail_batch({"BINANCE": items})]
    second = [x[1].symbol for x in r._detail_batch({"BINANCE": items})]
    assert first[:2] == second[:2] == ["S0/USDT:USDT", "S1/USDT:USDT"]
    assert first[2] != second[2]


def test_binance_route_is_wired_into_adapter_auto_mode(monkeypatch):
    from phoenix import live
    class FakeBinance:
        def __init__(self, cfg): self.urls = {"api": {"fapiPublic": "https://fapi.binance.com/fapi/v1"}}; self.options = {}; self.has = {}
        def load_markets(self, reload=False):
            if "fapi.binance.com" in self.urls["api"]["fapiPublic"]:
                raise RuntimeError("binance GET ... 451 Service unavailable from a restricted location")
            return {}
    class FakeCcxt: binance = FakeBinance
    monkeypatch.setattr(live, "ccxt", FakeCcxt)
    monkeypatch.delenv("PHOENIX_BINANCE_PUBLIC_WWW", raising=False)
    ad = live.CCXTAdapter("binance")
    assert ad.client.options["fetchMarkets"] == {"types": ["linear"]}      # spot never loaded
    assert ad.load_markets() == []                                        # 451 -> www route -> retry succeeded
    assert ad.client.urls["api"]["fapiPublic"].startswith("https://www.binance.com/")
