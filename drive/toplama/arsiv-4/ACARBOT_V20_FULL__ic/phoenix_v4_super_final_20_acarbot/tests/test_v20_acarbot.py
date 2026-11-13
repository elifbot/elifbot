from phoenix.config import Config
from phoenix.live import PaperExecution, LiveSignalRunner
from phoenix.models import Market, Signal


def test_v20_default_min_score():
    assert Config().min_score == 0.30


def test_paper_execution_accepts_through_risk_pipeline():
    cfg = Config(reference_equity=1000, entry_margin_usd=50, leverage=10)
    paper = PaperExecution(cfg, 1000)
    sig = Signal("OKX", "BTC/USDT:USDT", "LONG", .42, 100, 95, 111,
                 500, 50, 1.0, qty=5, contract_size=1)
    rec = paper.submit(sig, returns={})
    assert rec["status"] == "PAPER_FILLED"
    assert paper.accepted == 1


def test_paper_execution_rejects_max_positions():
    cfg = Config(max_open_positions=1)
    paper = PaperExecution(cfg, 1000)
    s1 = Signal("OKX", "BTC/USDT:USDT", "LONG", .42, 100, 95, 111, 500, 50, 1, qty=5)
    s2 = Signal("OKX", "ETH/USDT:USDT", "LONG", .42, 100, 95, 111, 500, 50, 2, qty=5)
    assert paper.submit(s1)["status"] == "PAPER_FILLED"
    r = paper.submit(s2)
    assert r["status"] == "REJECTED"
    assert r["reason"] == "max_open_positions"


def test_paper_execution_rejects_correlation():
    cfg = Config(correlation_limit=.85, correlation_window=3)
    paper = PaperExecution(cfg, 1000)
    s1 = Signal("OKX", "BTC/USDT:USDT", "LONG", .42, 100, 95, 111, 500, 50, 1, qty=5)
    s2 = Signal("OKX", "ETH/USDT:USDT", "LONG", .42, 100, 95, 111, 500, 50, 2, qty=5)
    assert paper.submit(s1)["status"] == "PAPER_FILLED"
    returns = {"BTC/USDT:USDT": [0.01, 0.02, 0.03], "ETH/USDT:USDT": [0.01, 0.02, 0.03]}
    r = paper.submit(s2, returns=returns)
    assert r["status"] == "REJECTED"
    assert r["reason"].startswith("correlation_limit:")


def test_timestamp_unit_normalization():
    now = 1_700_000_000.0
    assert abs(LiveSignalRunner._book_timestamp_age(now * 1000, now)) < 1e-6
    assert abs(LiveSignalRunner._book_timestamp_age(now * 1_000_000, now)) < 1e-6
    assert abs(LiveSignalRunner._book_timestamp_age(now * 1_000_000_000, now)) < 1e-6


def test_binance_ticker_batches_are_split_by_contract_type():
    calls = []
    class A:
        exchange_id = "BINANCE"
        def load_markets(self):
            return [
                Market("BINANCE", "BTC/USDT:USDT", "BTC", "USDT", "USDT", "swap"),
                Market("BINANCE", "BTC/USDT:USDT-2601", "BTC", "USDT", "USDT", "future"),
            ]
        def tickers(self, symbols):
            calls.append(tuple(symbols))
            return {s: {"bid": 99, "ask": 101, "last": 100, "quoteVolume": 2_000_000} for s in symbols}
        def book_tickers(self, symbols): return {}
    r = LiveSignalRunner(Config(max_spread_bps=30), adapters={"BINANCE": A()})
    r.refresh_universe()
    r._rank_tickers()
    assert len(calls) == 2
    assert all(len(c) == 1 for c in calls)
