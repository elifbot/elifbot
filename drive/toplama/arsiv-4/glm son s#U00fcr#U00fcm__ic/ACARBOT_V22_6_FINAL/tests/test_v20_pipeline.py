import json
import time
import pytest
from phoenix.config import Config
from phoenix.live import LiveSignalRunner, LiveConfig
from phoenix.models import Market


class TrendAdapter:
    """Strong, consistent uptrend + bid-heavy book + rising OI -> high LONG score."""
    exchange = "BINANCE"
    client = type("C", (), {"has": {"fetchTickers": True}})()

    def __init__(self, names=("AAA", "BBB", "CCC"), exchange="BINANCE", delay=0.0, ban_after=None):
        self.names, self.exchange, self.delay, self.ban_after = names, exchange, delay, ban_after
        self.n_oi = 0
        self.calls = 0

    def load_markets(self):
        return [Market(self.exchange, f"{n}/USDT:USDT", n, "USDT", "USDT", "swap") for n in self.names]

    def tickers(self, symbols):
        return {s: {"bid": 109.99, "ask": 110.01, "last": 110.0, "quoteVolume": 5e7 - i * 1e6} for i, s in enumerate(symbols)}

    def ticker(self, s): return self.tickers([s])[s]

    def order_book(self, s, limit=20):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.ban_after is not None and self.calls > self.ban_after:
            raise RuntimeError('binance {"code":-1003,"msg":"Way too many requests; IP(1.1.1.1) banned until 1794385677806."}')
        return {"timestamp": time.time() * 1000, "bids": [[109.99, 500]], "asks": [[110.01, 50]]}

    def ohlcv(self, s, tf, limit=100):
        seed = sum(map(ord, s)) % 7 * 0.0003            # distinct per symbol so returns are not perfectly collinear
        out, p = [], 100.0
        for i in range(limit):
            p *= 1 + 0.002 + (seed if i % 3 == 0 else -seed / 2)
            if i % 4 == 3:
                p *= 0.994                              # regular pullback keeps RSI(14) below the overextension gate
            out.append([i * 900000, p, p * 1.001, p * 0.999, p, 1000])
        return out

    def funding(self, s): return 0.0

    def oi(self, s):
        self.n_oi += 1
        return 1000.0 * (1 + 0.01 * self.n_oi)

    def liquidations(self, s, limit=50): return []

    def market_meta(self, s):
        return {"min_amount": 0.001, "min_cost": 5.0, "amount_step": 0.001, "price_tick": 0.01, "contract_size": 1.0}


def make(tmp_path, adapter=None, paper=True, cfg=None, **lc):
    cfg = cfg or Config(min_score=0.30, paper_state_path=str(tmp_path / "ps.json"), paper_journal_path=str(tmp_path / "pj.jsonl"),
                        correlation_min_samples=20, correlation_limit=0.999)
    lcfg = LiveConfig(duration_sec=lc.pop("duration_sec", 3), poll_sec=0, max_cycles=lc.pop("max_cycles", 2), paper_trading=paper,
                      report_path=str(tmp_path / "r.json"), **lc)
    return LiveSignalRunner(cfg, lcfg, adapters={"BINANCE": adapter or TrendAdapter()})


def test_paper_run_reports_full_funnel_and_writes_checkpoint(tmp_path):
    r = make(tmp_path, score_log_path=str(tmp_path / "scores.jsonl"))
    rep = r.run()
    f = rep["funnel"]
    assert rep["final"] and rep["mode"] == "PAPER" and rep["version"].startswith("22.")
    assert f["candidates"] >= 3 and f["snapshots"] >= 3 and f["scored"] >= 3 and f["passed_min_score"] >= 3
    assert f["paper_accepted"] >= 1 and rep["paper"]["open_positions"] >= 1
    assert rep["exchange_scanned"]["BINANCE"] >= 3 and rep["universe_discovered"] == 3 and rep["exchange_ranked"]["BINANCE"] == 3
    assert rep["score_max"] > 0.30 and sum(rep["score_histogram"].values()) == rep["funnel"]["scored"]
    pc = rep["score_pass_counts"]
    assert pc["0.30"] >= 3 and pc["0.30"] >= pc["0.35"] >= pc["0.50"] >= pc["0.72"]      # exact, monotonic
    assert rep["volume_samples"]["BINANCE"][0]["source"] == "quoteVolume"
    assert json.loads((tmp_path / "r.json").read_text())["final"] is True
    rows = [json.loads(x) for x in (tmp_path / "scores.jsonl").read_text().splitlines()]
    assert rows and {"ts", "ex", "sym", "score", "pass_min", "aligned"} <= set(rows[0])


def test_paper_rejections_are_explained_with_stage_and_unique_counts(tmp_path):
    cfg = Config(min_score=0.30, max_open_positions=1, paper_state_path=str(tmp_path / "ps.json"),
                 paper_journal_path=str(tmp_path / "pj.jsonl"))
    rep = make(tmp_path, cfg=cfg).run()
    assert rep["funnel"]["paper_accepted"] == 1
    assert rep["paper_rejections"]["RISK:max_open_positions"] >= 2
    assert rep["paper_rejections_unique"]["RISK:max_open_positions"] >= 2
    assert rep["funnel"]["rejected_risk"] >= 2 and rep["funnel"]["paper_rejected"] >= 2


def test_correlation_gate_shows_up_in_the_funnel(tmp_path):
    cfg = Config(min_score=0.30, correlation_limit=0.5, correlation_min_samples=20,
                 paper_state_path=str(tmp_path / "ps.json"), paper_journal_path=str(tmp_path / "pj.jsonl"))
    rep = make(tmp_path, adapter=TrendAdapter(("AAA", "AAB", "AAC")), cfg=cfg).run()
    assert rep["funnel"]["paper_accepted"] >= 1
    assert rep["paper_rejections"].get("CORRELATION:correlation_limit", 0) >= 1
    assert rep["correlation_gate"]["blocked"] >= 1


def test_read_only_mode_never_touches_paper_or_trading(tmp_path):
    r = make(tmp_path, paper=False)
    rep = r.run()
    assert rep["mode"] == "READ_ONLY" and r.paper is None and not r.trading
    assert rep["funnel"].get("paper_accepted", 0) == 0 and rep["signals_seen"] >= 3


def test_duration_is_respected_and_cycle_is_truncated_with_a_final_report(tmp_path):
    names = tuple(f"S{i:02d}" for i in range(40))
    r = make(tmp_path, adapter=TrendAdapter(names, delay=0.05), duration_sec=1, max_cycles=0)
    t0 = time.time()
    rep = r.run()
    assert time.time() - t0 < 2.5 and rep["final"] and rep["truncated_cycles"] >= 1
    assert rep["funnel"]["snapshots"] < 40


def test_max_cycle_sec_truncates_but_keeps_looping(tmp_path):
    names = tuple(f"S{i:02d}" for i in range(30))
    r = make(tmp_path, adapter=TrendAdapter(names, delay=0.05), duration_sec=3, max_cycles=2, max_cycle_sec=1)
    rep = r.run()
    assert rep["cycles"] == 2 and rep["truncated_cycles"] >= 1


def test_ban_mid_cycle_stops_hammering_that_exchange_and_is_reported(tmp_path):
    a = TrendAdapter(tuple(f"S{i:02d}" for i in range(10)), ban_after=2)
    r = make(tmp_path, adapter=a, max_cycles=1)
    rep = r.run()
    assert rep["snapshot_dropped"]["exchange_banned"] >= 1
    assert a.calls == 3                                  # first call after the ban -> everything else skipped
    assert rep["exchange_status"]["BINANCE"]["banned"] is True


def test_paper_positions_are_marked_and_closed_on_later_cycles(tmp_path):
    a = TrendAdapter(("AAA",))
    r = make(tmp_path, adapter=a, max_cycles=3, duration_sec=3)
    clock = {"t": time.time()}
    r.run()
    pos = r.paper.open_positions()[0]
    # indicator mode: there is no fixed target, a huge rally does not close the position by itself
    assert pos.target == 0.0
    assert not r.paper.update({(pos.exchange, pos.symbol): pos.entry * 1.5}, now=pos.opened_at + 120)
    # the fixed -$20 stop still closes it
    closed = r.paper.update({(pos.exchange, pos.symbol): pos.stop - 1}, now=pos.opened_at + 180)
    assert closed and closed[0]["reason"] == "STOP"


def test_live_requires_explicit_confirmation_and_credentials(monkeypatch):
    for k in ("PHOENIX_CONFIRM_LIVE", "PHOENIX_BINANCE_API_KEY", "PHOENIX_BINANCE_API_SECRET", "PHOENIX_OKX_API_KEY",
              "PHOENIX_OKX_API_SECRET", "PHOENIX_OKX_PASSPHRASE"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="PHOENIX_CONFIRM_LIVE"):
        LiveSignalRunner(Config(), LiveConfig(live_trading=True), adapters={"BINANCE": TrendAdapter()})
    monkeypatch.setenv("PHOENIX_CONFIRM_LIVE", "YES")
    with pytest.raises(RuntimeError, match="credentials"):
        LiveSignalRunner(Config(), LiveConfig(live_trading=True), adapters={"BINANCE": TrendAdapter()})


def test_live_and_paper_together_are_refused():
    with pytest.raises(RuntimeError, match="mutually exclusive"):
        LiveSignalRunner(Config(), LiveConfig(live_trading=True, paper_trading=True), adapters={"BINANCE": TrendAdapter()})


def test_cli_defaults_to_read_only_even_if_env_enables_paper_flag_off(monkeypatch, tmp_path):
    from phoenix import live
    monkeypatch.setenv("PHOENIX_LIVE_TRADING", "0")
    monkeypatch.setenv("PHOENIX_PAPER_TRADING", "0")
    seen = {}
    class R:
        def __init__(self, cfg=None, live_cfg=None): seen["mode"] = live_cfg.mode
        def run(self): pass
    monkeypatch.setattr(live, "LiveSignalRunner", R)
    live.main(["--duration", "1"])
    assert seen["mode"] == "READ_ONLY"
    live.main(["--duration", "1", "--paper"])
    assert seen["mode"] == "PAPER"


def test_score_pass_counts_are_exact_not_bin_estimates():
    from phoenix.telemetry import Telemetry
    t = Telemetry(extra_thresholds=(0.33,))
    for s in (0.299, 0.30, 0.331, -0.35, 0.72, -0.9):
        t.record_score(s)
    pc = t.pass_counts()
    assert pc["0.30"] == 5 and pc["0.33"] == 4 and pc["0.35"] == 3 and pc["0.72"] == 2 and pc["0.50"] == 2


def test_cli_clear_halt_edits_state_without_exchange_access(monkeypatch, tmp_path):
    from phoenix import live
    from phoenix.state import StateStore
    monkeypatch.setenv("PHOENIX_STATE_PATH", str(tmp_path / "state.json"))
    p = tmp_path / "state.binance.json"
    StateStore(str(p)).save({"risk": {"halted_reason": "daily_loss_kill_switch", "halted_at": 1, "kill_complete": True, "peak_equity": 900}})
    live.main(["--clear-halt"])
    risk = StateStore(str(p)).load()["risk"]
    assert "halted_reason" not in risk and risk["peak_equity"] == 900
