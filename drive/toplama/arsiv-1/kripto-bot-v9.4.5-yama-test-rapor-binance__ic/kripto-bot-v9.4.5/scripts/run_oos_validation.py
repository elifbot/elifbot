"""v9.3 reproducible frozen-parameter holdout, ablation and execution stress.

Uses a saved, common-end-time snapshot, never silently refreshes an existing dataset.
The earlier in-memory calibration snapshot is unavailable: this is a NEW holdout,
not a claimed replication of the earlier [750:1500] dataset.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import pandas as pd
from backtests.engine import SimpleBacktestEngine
from backtests.engine_interface import BacktestConfig
from strategies.v93_flow_strategy import CausalMarketPanel, V93CanonicalFlowStrategy

BASE_DIR = Path(__file__).resolve().parent.parent
DATA = BASE_DIR / "reports" / "v93_market_snapshot.json"
REPORT = BASE_DIR / "reports" / "v9_3_oos_validation_report.json"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "AVAXUSDT"]
FAMILIES = ["TREND_IND", "VOLUME_FLOW", "LEADER_BREADTH_REGIME", "TEN_AGENT_AUDIT"]


def fetch_binance_perp_5m(raw_symbol: str, limit: int = 1500, end_ms: int | None = None) -> pd.DataFrame:
    end_ms = end_ms or (int(time.time() * 1000) // 300_000 * 300_000 - 1)
    url = f"https://www.binance.com/fapi/v1/klines?symbol={raw_symbol}&interval=5m&limit={limit}&endTime={end_ms}"
    req = urllib.request.Request(url, headers={"User-Agent": "kripto-bot-v9.3-validation"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.load(resp)
    if not isinstance(rows, list) or len(rows) != limit:
        raise ValueError(f"Incomplete market data: {raw_symbol}")
    return pd.DataFrame([dict(open_time=int(r[0]), open=float(r[1]), high=float(r[2]),
                              low=float(r[3]), close=float(r[4]), volume=float(r[7]),
                              taker_buy_quote=float(r[10]), trades_count=int(r[8])) for r in rows])


def load_snapshot() -> tuple[dict, dict[str, pd.DataFrame]]:
    if not DATA.exists():
        end_ms = int(time.time() * 1000) // 300_000 * 300_000 - 1
        with ThreadPoolExecutor(max_workers=8) as pool:
            frames = dict(zip(SYMBOLS, pool.map(lambda sym: fetch_binance_perp_5m(sym, end_ms=end_ms), SYMBOLS)))
        payload = {"end_ms": end_ms, "source": "Binance public USD-M 5m klines", "frames": {s: f.to_dict("records") for s, f in frames.items()}}
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps(payload, separators=(",", ":")))
    payload = json.loads(DATA.read_text())
    return payload, {s: pd.DataFrame(rows) for s, rows in payload["frames"].items()}


def evaluate_panel(frames: dict[str, pd.DataFrame], *, family=None, slippage=3.0, latency=0, start=750, end=1500, panel=None) -> dict:
    # Full stored panel is sliced causally on every lookup. Warm-up has no trading.
    panel = panel if panel is not None else CausalMarketPanel(frames)
    rows = []
    for symbol, frame in frames.items():
        strategy = V93CanonicalFlowStrategy(symbol=symbol, market_panel=panel, disabled_family=family)
        cfg = BacktestConfig(timeframe="5m", fee_rate=0.00035, leverage=10.0,
                             starting_balance=1000.0, slippage_bps=slippage,
                             latency_ms=latency, params_frozen=True)
        engine = SimpleBacktestEngine(strategy, cfg)
        for candle in frame.iloc[max(0, start-300):start].to_dict("records"):
            engine.feed(candle)
        for candle in frame.iloc[start:end].to_dict("records"):
            engine.feed(candle)
            engine.step()
        summary = engine.results()
        trades = [asdict(t) for t in engine.portfolio.closed_trades]
        rows.append({"symbol": symbol, "summary": summary, "trades": trades})
    all_trades = [t for row in rows for t in row["trades"]]
    net = sum(t["realized_pnl"] for t in all_trades)
    gross = sum(t["gross_pnl"] for t in all_trades)
    wins = sum(t["realized_pnl"] > 0 for t in all_trades)
    return {"disabled_family": family, "slippage_bps": slippage, "latency_ms": latency,
            "trade_count": len(all_trades), "gross_pnl": gross, "net_pnl": net,
            "fees": gross-net, "win_rate_pct": 100*wins/max(1,len(all_trades)),
            "net_expectancy_per_trade": net/max(1,len(all_trades)), "per_symbol": rows}


def main() -> dict:
    payload, frames = load_snapshot()
    freeze = {"params_frozen": True, "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "dataset_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
              "source_sha256": {str(p.relative_to(BASE_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for d in ("src", "strategies", "backtests") for p in (BASE_DIR/d).glob("*.py")},
              "test_range": [750,1500], "warmup_only_range": [450,750],
              "parameters": {"margin":50,"leverage":10,"entry_score":20,"min_flow":11,"min_rvol":0.85,"cooldown":3}}
    (BASE_DIR/"reports"/"v93_freeze_manifest.json").write_text(json.dumps(freeze, indent=2))
    started = time.monotonic()
    panel = CausalMarketPanel(frames)
    baseline = evaluate_panel(frames, panel=panel)
    print("BASELINE", baseline["trade_count"], baseline["net_pnl"], flush=True)
    ablations = []
    for family in FAMILIES:
        result = evaluate_panel(frames, family=family, panel=panel)
        result["net_delta_vs_baseline"] = result["net_pnl"] - baseline["net_pnl"]
        ablations.append(result)
        print("ABLATION",family,result["trade_count"],result["net_pnl"],flush=True)
    stress = []
    for slip, lag in [(8.0,0),(15.0,0),(8.0,1000)]:
        result = evaluate_panel(frames, slippage=slip, latency=lag, panel=panel)
        stress.append(result)
        print("STRESS",slip,lag,result["net_pnl"],flush=True)
    report = {"version":"9.3.0", "freeze":freeze,"source":payload["source"],
              "snapshot_end_ms":payload["end_ms"],"baseline":baseline,"ablations":ablations,"stress":stress,
              "elapsed_sec": time.monotonic()-started,
              "limitations":["New persisted snapshot; earlier in-memory calibration dataset was not retained.",
              "Recent overlapping market windows are not independent prospective OOS.",
              "Eight independent $1000 symbol sleeves, not a shared-margin portfolio simulation.",
              "Bar taker flow is not live tick flow; no claim of exact live/backtest equivalence.",
              "Latency is approximated by next available bar open; no sub-bar queue reconstruction.",
              "Single 750-bar temporal holdout, not rolling walk-forward or proof of profitability.",
              "Historical fees and funding are approximations; funding transfers are not modeled."]}
    REPORT.write_text(json.dumps(report, ensure_ascii=False,indent=2,default=str))
    print("SAVED",REPORT, "elapsed",report["elapsed_sec"],flush=True)
    return report

if __name__ == "__main__":
    main()
