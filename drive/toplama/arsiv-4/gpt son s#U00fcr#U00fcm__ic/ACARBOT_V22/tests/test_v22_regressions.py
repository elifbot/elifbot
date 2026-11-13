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
    broker = PaperBroker(cfg, equity=1000)
    for i in range(19):
        s = signal(symbol=f"A{i}/USDT:USDT")
        assert broker.submit(s)["status"] == "ACCEPTED"
    assert len(broker.open_positions()) == 19
    accepted = broker.submit(signal(symbol="A19/USDT:USDT"))
    assert accepted["status"] == "ACCEPTED"
    assert len(broker.open_positions()) == 20


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


def test_atr_does_not_tighten_user_dollar_loss_stop():
    cfg = Config(atr_stop_multiplier=1.5)
    risk = RiskManager(cfg)
    qty = 5
    wide = risk.stop_price(100, "LONG", qty, 1, 0, 0)
    with_atr = risk.stop_price(100, "LONG", qty, 1, 0, .002)
    assert with_atr == wide


def test_sizing_overrides_upstream_tight_atr_stop_with_per_position_usd_cap():
    from phoenix.sizing import MarketMeta, fit_order
    cfg = Config()
    risk = RiskManager(cfg)
    s = signal(entry=100.0)
    # Simulate an old/foreign strategy stop that would close far earlier than $20.
    from dataclasses import replace
    early = replace(s, stop=99.5, target=101.1)
    fitted, reason, _ = fit_order(
        early, MarketMeta(amount_step=0.000001, contract_size=1.0), risk, cfg
    )
    assert fitted is not None
    assert fitted.stop < 99.5
    modeled_loss = abs(fitted.entry - fitted.stop) * fitted.qty
    assert modeled_loss <= 3.51
    assert modeled_loss <= cfg.max_loss_usd
    assert fitted.target > fitted.entry


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


def test_fixed_50_usd_notional_and_10x_margin():
    cfg = Config(entry_notional_usd=50, leverage=10)
    risk = RiskManager(cfg)
    assert risk.target_notional() == 50
    assert risk.required_margin(risk.target_notional()) == 5


def test_margin_named_legacy_env_cannot_change_notional_sizing():
    cfg = Config.from_env({"PHOENIX_ENTRY_MARGIN_USD": "500", "PHOENIX_LEVERAGE": "10"})
    assert cfg.entry_notional_usd == 50
    assert RiskManager(cfg).required_margin(RiskManager(cfg).target_notional()) == 5


def test_cross_margin_is_mandatory_and_isolated_config_is_rejected():
    import pytest
    with pytest.raises(ValueError, match="cross margin is mandatory"):
        Config(okx_td_mode="isolated")
    cfg = Config.from_env({"PHOENIX_OKX_TD_MODE": "isolated"})
    assert cfg.okx_td_mode == "cross"


def test_one_hundred_positions_fit_under_1000_usd_collateral_at_50_notional():
    broker = PaperBroker(Config(max_open_positions=0), equity=1000)
    for i in range(100):
        result = broker.submit(signal(symbol=f"SIZE{i}/USDT:USDT"))
        assert result["status"] == "ACCEPTED", (i, result)
    assert len(broker.open_positions()) == 100
