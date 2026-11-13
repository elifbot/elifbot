import pathlib
from phoenix.config import Config
from phoenix.live import LiveConfig

EX = pathlib.Path(__file__).resolve().parent.parent / ".env.example"


def _env():
    out = {}
    for line in EX.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_env_example_parses_and_matches_code_defaults():
    env = _env()
    c = Config.from_env(env)
    d = Config()
    assert c.min_score == d.min_score == 0.30
    assert c.max_open_positions == d.max_open_positions == 0
    assert c.max_reserved_margin_pct == d.max_reserved_margin_pct == 1.0
    assert c.auto_bump_max_factor == d.auto_bump_max_factor == 1.0
    assert c.correlation_min_samples == d.correlation_min_samples
    assert c.max_requotes == d.max_requotes and c.max_chase_bps == d.max_chase_bps
    assert c.okx_pos_mode == "net" and c.binance_pos_mode == "oneway" and c.require_alignment is False
    # V22.6 entry semantics: margin mode, $50 margin x 10x = $500 notional, real -$20 stop
    assert c.entry_mode == d.entry_mode == "margin"
    assert c.entry_margin_usd == d.entry_margin_usd == 50.0
    assert c.entry_notional_usd == d.entry_notional_usd == 500.0
    assert c.max_loss_usd == d.max_loss_usd == 20.0
    assert c.stop_beyond_liquidation is False
    assert c.tp_min_r == d.tp_min_r == 0.5 and c.breakeven_r == d.breakeven_r == 0.5
    assert c.trail_arm_r == d.trail_arm_r == 1.0
    assert env["PHOENIX_BINANCE_SANDBOX"] == "0" and env["PHOENIX_OKX_SANDBOX"] == "0"
    assert env["PHOENIX_LIVE_TRADING"] == "0" and env["PHOENIX_PAPER_TRADING"] == "0"
    assert env["PHOENIX_CONFIRM_LIVE"] == ""


def test_env_example_live_loop_values_load(monkeypatch):
    for k, v in _env().items():
        if k.startswith("PHOENIX_") and v != "":
            monkeypatch.setenv(k, v)
    lc = LiveConfig.from_env()
    assert lc.mode == "READ_ONLY" and lc.detail_symbols_per_exchange == 100 and lc.rotation_slots == 25 and lc.max_cycle_sec == 180
    assert lc.htf_cache_sec == 600 and lc.include_dated_futures is True
