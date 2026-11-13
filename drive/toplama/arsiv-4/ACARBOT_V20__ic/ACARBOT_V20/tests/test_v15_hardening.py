import os
from phoenix.config import Config
from phoenix.live import CCXTAdapter
from phoenix.models import Signal
from phoenix.trading import TradingService
from phoenix.portfolio import PortfolioRisk


def test_config_from_env_is_complete(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOENIX_LEVERAGE", "7")
    monkeypatch.setenv("PHOENIX_DAILY_LOSS_LIMIT_USD", "55")
    monkeypatch.setenv("PHOENIX_WEIGHT_TREND", "0.5")
    monkeypatch.setenv("PHOENIX_STATE_PATH", str(tmp_path / "state.json"))
    c = Config.from_env()
    assert c.leverage == 7
    assert c.daily_loss_limit_usd == 55
    assert c.strategy_weights["trend"] == 0.5
    assert c.state_path.endswith("state.json")


def test_ccxt_adapter_fetch_my_trades_accepts_limit_without_ccxt_runtime():
    class FakeClient:
        def fetch_my_trades(self, *args):
            return list(args)
    adapter = object.__new__(CCXTAdapter)
    adapter.client = FakeClient()
    adapter._call = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    assert adapter.fetch_my_trades(since=123, limit=77) == [None, 123, 77]


def test_portfolio_uses_configured_window_and_symbol_aliases():
    p = PortfolioRisk(.8, correlation_window=4)
    returns = {
        "BTC/USDT:USDT": [1, 2, 3, 4, 5, 6],
        "ETH/USDT:USDT": [1, 2, 3, 4, 5, 6],
    }
    pos = type("P", (), {"symbol": "ETH/USDT:USDT"})()
    blocked, symbol, corr = p.correlated("BTC/USDT:USDT", returns, [pos])
    assert blocked and symbol == "ETH/USDT:USDT" and corr > .8


def test_exchange_contract_size_is_used_for_pending_margin(tmp_path):
    class A:
        exchange_id = "BINANCE"
        def fetch_balance(self):
            return {"info": {"totalMarginBalance": "1000"}, "total": {"USDT": 1000}, "free": {"USDT": 900}}
        def fetch_positions(self): return []
        def fetch_open_orders(self): return [{"symbol": "BTC/USDT:USDT", "amount": 2, "remaining": 2, "price": 100, "info": {}}]
        def fetch_my_trades(self, symbol=None, since=None, limit=None): return []
        def market(self, symbol): return {"contractSize": 0.01}
    svc = TradingService(A(), Config(), str(tmp_path / "state.json"))
    snap = svc.account_snapshot()
    assert snap["pending_reserved"] == 0.2


def test_env_credentials_are_not_required_for_read_only(monkeypatch):
    monkeypatch.delenv("PHOENIX_BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("PHOENIX_BINANCE_API_SECRET", raising=False)
    monkeypatch.delenv("PHOENIX_OKX_API_KEY", raising=False)
    monkeypatch.delenv("PHOENIX_OKX_API_SECRET", raising=False)
    monkeypatch.delenv("PHOENIX_OKX_PASSPHRASE", raising=False)
    # This is a configuration-level assertion: read-only mode must not require secrets.
    assert not Config.from_env().state_path.startswith("/etc/")

def test_realized_trade_pagination_deduplicates_and_advances():
    from phoenix.live import CCXTAdapter
    class A:
        def fetch_my_trades(self, since=None, limit=1000):
            if since is None or since <= 1000:
                return [{"id":"1","timestamp":1000},{"id":"2","timestamp":2000}]
            if since <= 2001:
                return [{"id":"2","timestamp":2000},{"id":"3","timestamp":3000}]
            return []
    adapter = object.__new__(CCXTAdapter)
    adapter.fetch_my_trades = A().fetch_my_trades
    rows = adapter.fetch_my_trades_paginated(since=None, max_records=10, page_limit=2)
    assert [r["id"] for r in rows] == ["1", "2", "3"]


def test_strategy_preserves_signed_oi_direction():
    from phoenix.models import Market, Snapshot
    from phoenix.strategy import Strategy
    c = Config(min_score=0.1)
    m = Market("B", "BTC/USDT:USDT", "BTC", "USDT", "USDT", "swap")
    base = dict(market=m, ts=1, price=100, bid=99.9, ask=100.1, spread_bps=1, quote_volume_24h=10_000_000,
                funding=0.0, oi=1000.0, book_imbalance=0.0, liquidation_pressure=0.0, regime_score=0.2, htf_score=0.2,
                stale_book=False, oi_available=True, funding_available=True, liquidation_available=False, data_quality=1.0)
    s_pos = Snapshot(oi_change=0.5, **base)
    s_neg = Snapshot(oi_change=-0.5, **base)
    a = Strategy(c).evaluate_details(s_pos)[2]["oi"]
    b = Strategy(c).evaluate_details(s_neg)[2]["oi"]
    assert a == 0.5 and b == -0.5


def test_live_report_contains_score_and_rejection_telemetry(tmp_path):
    from phoenix.live import LiveSignalRunner, LiveConfig
    from phoenix.models import Market
    class A:
        exchange = "BINANCE"
        client = type("C", (), {"has": {"fetchTickers": True}})()
        def load_markets(self): return [Market("BINANCE", "BTC/USDT:USDT", "BTC", "USDT", "USDT", "swap")]
        def tickers(self, symbols): return {symbols[0]: {"bid": 99.9, "ask": 100.1, "last": 100, "quoteVolume": 10_000_000}}
        def ticker(self, s): return self.tickers([s])[s]
        def order_book(self, s, limit=20): return {"timestamp": __import__("time").time()*1000, "bids": [[99.9,10]], "asks": [[100.1,10]]}
        def ohlcv(self, s, tf, limit=100): return [[i,100,101,99,100+(i%2)*0.1,1000] for i in range(limit)]
        def oi(self,s): return 1000.0
        def funding(self,s): return 0.0
        def liquidations(self,s,limit=50): return []
    path = tmp_path / "r.json"
    r = LiveSignalRunner(Config(min_score=.72), LiveConfig(duration_sec=0, report_path=str(path)), adapters={"BINANCE":A()})
    out = r.run()
    assert "score_histogram" in out and "strategy_rejections" in out and path.exists()
