import time
from phoenix.config import Config
from phoenix.live import LiveSignalRunner, CCXTAdapter
from phoenix.models import Market, Signal
from phoenix.paper import PaperBroker
from phoenix.risk import RiskManager
from phoenix.portfolio import PortfolioRisk


def signal(exchange="BINANCE", symbol="AAA/USDT:USDT", side="LONG", entry=100.0):
    cfg = Config()
    risk = RiskManager(cfg)
    notional = cfg.entry_notional_usd
    qty = notional / entry
    fee = risk.estimated_entry_fee(notional)
    stop = risk.stop_price(entry, side, qty, 1.0, fee)
    dist = abs(entry-stop)
    target = entry + dist * cfg.tp_r if side == "LONG" else entry - dist * cfg.tp_r
    return Signal(exchange, symbol, side, .6, entry, stop, target, notional, notional / cfg.leverage, time.time(), qty, [], 1.0)


def test_zero_position_cap_means_unlimited_count_but_margin_still_binds():
    cfg = Config(max_open_positions=0, max_reserved_margin_pct=1.0)
    broker = PaperBroker(cfg, equity=10000)     # bigger bankroll: the point is COUNT, not collateral
    for i in range(150):          # far beyond the old 19-20 position ceiling
        s = signal(symbol=f"A{i}/USDT:USDT")
        assert broker.submit(s)["status"] == "ACCEPTED"
    assert len(broker.open_positions()) == 150
    for i in range(150, 215):
        broker.submit(signal(symbol=f"A{i}/USDT:USDT"))
    assert 190 <= len(broker.open_positions()) <= 200      # ~$50 margin + fee each; only collateral binds
    rejected = broker.submit(signal(symbol="A999/USDT:USDT"))
    assert rejected["reason"] == "reserved_margin_cap"


def test_same_underlying_is_not_opened_on_two_exchanges():
    broker = PaperBroker(Config(max_open_positions=0), equity=1000)
    assert broker.submit(signal("BINANCE", "SOXL/USDT:USDT"))["status"] == "ACCEPTED"
    rejected = broker.submit(signal("OKX", "SOXL/USDT:USDT"))
    assert rejected["reason"] == "underlying_already_open"


def test_default_theme_position_count_is_unlimited_until_margin_binds():
    cfg = Config(max_open_positions=0, max_reserved_margin_pct=1.0)
    broker = PaperBroker(cfg, equity=1000)
    for symbol in ("AMD/USDT:USDT", "MU/USDT:USDT", "INTC/USDT:USDT", "NVDA/USDT:USDT", "TSM/USDT:USDT"):
        assert broker.submit(signal(symbol=symbol))["status"] == "ACCEPTED"
    assert len(broker.open_positions()) == 5


def test_legacy_theme_cap_env_setting_is_ignored():
    cfg = Config.from_env({"PHOENIX_MAX_POSITIONS_PER_THEME": "1"})
    broker = PaperBroker(cfg, equity=1000)
    for symbol in ("AMD/USDT:USDT", "MU/USDT:USDT", "INTC/USDT:USDT"):
        assert broker.submit(signal(symbol=symbol))["status"] == "ACCEPTED"
    assert len(broker.open_positions()) == 3


def test_paper_stop_defaults_to_conservative_worse_fill():
    assert Config().paper_stop_fill == "worse"

def test_paper_stop_fill_respects_twenty_dollar_modeled_loss():
    cfg = Config()
    broker = PaperBroker(cfg, equity=1000)
    s = signal()
    assert broker.submit(s)["status"] == "ACCEPTED"
    closed = broker.update({("BINANCE", s.symbol): s.stop}, now=time.time()+60)
    assert len(closed) == 1
    assert abs(closed[0]["net_pnl"]) <= 20.01
    assert closed[0]["exit"] == s.stop


def test_atr_only_tightens_stop_never_widens_risk_cap():
    cfg = Config(atr_stop_multiplier=1.5)
    risk = RiskManager(cfg)
    qty = 5
    wide = risk.stop_price(100, "LONG", qty, 1, 0, 0)
    tight = risk.stop_price(100, "LONG", qty, 1, 0, .002)
    assert tight > wide


def test_okx_contract_volume_uses_ctval_and_multiplier():
    t = {"last": 74, "info": {"instType": "SWAP", "vol24h": "100000000"}}
    m = Market("OKX", "XAG/USDT:USDT", "XAG", "USDT", "USDT", "swap", .01, info={"ctVal":"0.01", "ctMult":"1", "ctValCcy":"XAG"})
    qv, source = LiveSignalRunner._quote_volume_info(t, m)
    assert qv == 74_000_000 and "ctVal" in source


def test_okx_contract_volume_missing_metadata_is_not_admitted():
    t = {"last": 74, "quoteVolume": 7.42e9, "info": {"instType": "SWAP", "vol24h": "100000000"}}
    qv, source = LiveSignalRunner._quote_volume_info(t)
    assert qv == 0 and source == "okx_contract_metadata_missing"


def test_live_env_flag_cannot_enable_real_orders_without_cli_flag(monkeypatch):
    from phoenix import live
    monkeypatch.setenv("PHOENIX_LIVE_TRADING", "1")
    monkeypatch.setenv("PHOENIX_PAPER_TRADING", "0")
    seen = {}
    class Runner:
        def __init__(self, cfg=None, live_cfg=None): seen["mode"] = live_cfg.mode
        def run(self): pass
    old = live.LiveSignalRunner
    live.LiveSignalRunner = Runner
    try:
        live.main(["--duration", "1"])
    finally:
        live.LiveSignalRunner = old
    assert seen["mode"] == "READ_ONLY"


def test_sandbox_mode_is_not_overwritten_by_production_www_route(monkeypatch):
    from phoenix import live
    calls = []
    class FakeBinance:
        def __init__(self, cfg):
            self.options = {}
            self.urls = {"api": {"fapiPublic": "https://fapi.binance.com/fapi/v1"}}
            self.has = {}
        def set_sandbox_mode(self, enabled):
            calls.append(("sandbox", enabled))
            self.urls["api"]["fapiPublic"] = "https://testnet.binancefuture.com/fapi/v1"
    class FakeCcxt: binance = FakeBinance
    monkeypatch.setattr(live, "ccxt", FakeCcxt)
    monkeypatch.setenv("PHOENIX_BINANCE_PUBLIC_WWW", "1")
    adapter = live.CCXTAdapter("binance", sandbox=True)
    assert calls == [("sandbox", True)]
    assert adapter.client.urls["api"]["fapiPublic"].startswith("https://testnet.binancefuture.com")


def test_mainnet_data_guard_refuses_any_configured_sandbox(monkeypatch):
    from phoenix import live
    monkeypatch.setenv("PHOENIX_EXCHANGES", "binance,okx")
    monkeypatch.setenv("PHOENIX_BINANCE_SANDBOX", "0")
    monkeypatch.setenv("PHOENIX_OKX_SANDBOX", "1")
    try:
        live.main(["--paper", "--require-mainnet-data", "--duration", "1"])
    except SystemExit as exc:
        assert "OKX" in str(exc)
    else:
        raise AssertionError("sandbox/demo run should have been refused")


def test_exchange_list_is_dynamic_for_readonly_and_paper(monkeypatch):
    from phoenix import live
    monkeypatch.setenv("PHOENIX_EXCHANGES", "binance,okx,bybit")
    class Client:
        def __init__(self, cfg):
            self.options = {}
            self.urls = {"api": {}}
            self.has = {}
    class FakeCcxt:
        binance = Client
        okx = Client
        bybit = Client
    monkeypatch.setattr(live, "ccxt", FakeCcxt)
    runner = live.LiveSignalRunner(live_cfg=live.LiveConfig(), adapters=None)
    assert list(runner.adapters) == ["BINANCE", "OKX", "BYBIT"]


def test_stop_gap_is_reported_separately_from_modeled_stop_fill():
    broker = PaperBroker(Config(), equity=1000)
    s = signal()
    assert broker.submit(s)["status"] == "ACCEPTED"
    mark = s.stop - 1.0
    closed = broker.update({("BINANCE", s.symbol): mark}, now=time.time()+60)
    rec = closed[0]
    assert rec["exit"] == mark
    assert rec["stop_gap_excess_usd_estimate"] > 0
    assert abs(rec["gap_adjusted_net_pnl_estimate"] - rec["net_pnl"]) < 1e-6
    summary = broker.summary()
    assert summary["closed_trade_details"][-1]["stop_trigger_mark"] == mark


def test_default_sizing_never_bumps_notional_above_fifty_dollars():
    from phoenix.sizing import MarketMeta, fit_order
    cfg = Config()
    s = signal(symbol="MIN/USDT:USDT", entry=100000.0)
    # A venue minimum requiring $600 notional must be skipped, not auto-bumped above $50.
    fitted, reason, info = fit_order(s, MarketMeta(min_amount=0.006, amount_step=0.001, contract_size=1.0), RiskManager(cfg), cfg)
    assert fitted is None
    assert reason in {"below_min_amount", "zero_qty_after_rounding"}


def test_fixed_50_usd_margin_10x_is_500_notional():
    cfg = Config()
    risk = RiskManager(cfg)
    assert cfg.entry_mode == "margin" and cfg.entry_margin_usd == 50
    assert cfg.entry_notional_usd == 500 and cfg.leverage == 10
    assert risk.target_notional() == 500
    assert risk.required_margin(risk.target_notional()) == 50


def test_entry_env_semantics_v22_6():
    import pytest
    # default: margin mode -> $50 margin x 10x = $500 notional
    assert Config.from_env({}).entry_notional_usd == 500
    assert Config.from_env({"PHOENIX_ENTRY_MARGIN_USD": "50"}).entry_notional_usd == 500
    # explicit notional mode opt-in
    cfg = Config.from_env({"PHOENIX_ENTRY_MODE": "notional", "PHOENIX_ENTRY_NOTIONAL_USD": "50", "PHOENIX_LEVERAGE": "10"})
    assert cfg.entry_notional_usd == 50 and cfg.entry_margin_usd == 5
    # conflicting entries fail loud, never silently
    with pytest.raises(ValueError):
        Config.from_env({"PHOENIX_ENTRY_MODE": "margin", "PHOENIX_ENTRY_NOTIONAL_USD": "50"})
    with pytest.raises(ValueError):
        Config.from_env({"PHOENIX_ENTRY_MODE": "notional", "PHOENIX_ENTRY_MARGIN_USD": "50"})


def test_no_position_count_cap_capacity_is_set_by_collateral():
    broker = PaperBroker(Config(max_open_positions=0), equity=1000)
    results = [broker.submit(signal(symbol=f"SIZE{i}/USDT:USDT")) for i in range(260)]
    accepted = [r for r in results if r["status"] == "ACCEPTED"]
    assert 18 <= len(accepted) <= 21                       # ~$50 margin + fee each -> ~19 positions on $1000
    assert {r["reason"] for r in results if r["status"] != "ACCEPTED"} == {"reserved_margin_cap"}
