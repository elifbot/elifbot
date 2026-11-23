#!/usr/bin/env python3
"""Run Jesse core research on a real OKX candle capture.

This is intentionally a backtest/data-ingestion check, not Jesse live trading:
Jesse's licensed live/paper extension is not part of the received source and
OKX is not used as a Jesse live adapter here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


class PublicDataSmokeStrategy:  # replaced with a Jesse Strategy subclass in main
    pass


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return value


def run(input_path: Path, output_path: Path) -> dict:
    import jesse.helpers as jh
    import jesse.indicators as ta
    from jesse.research import backtest
    from jesse.strategies import Strategy

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    raw = payload.get("candles") or []
    if len(raw) < 600:
        raise RuntimeError("Jesse input contains fewer than 600 one-minute candles")
    candles = np.asarray(raw, dtype=np.float64)
    if candles.ndim != 2 or candles.shape[1] != 6:
        raise ValueError("expected Jesse candle columns [ts, open, close, high, low, volume]")
    if np.any(np.diff(candles[:, 0]) != 60_000):
        raise ValueError("Jesse input has a one-minute gap")

    class PublicDataSmoke(Strategy):
        """Small, fixed-risk observer strategy; not a production strategy."""

        def should_long(self) -> bool:
            if self.index < 60:
                return False
            fast = ta.ema(self.candles, 20)
            slow = ta.ema(self.candles, 50)
            momentum = ta.rsi(self.candles, 14)
            return bool(fast > slow and 45 <= momentum <= 70)

        def should_short(self) -> bool:
            return False

        def go_long(self):
            entry = self.price
            notional = min(50.0, self.available_margin * 0.10)
            # Keep the harness independent of exchange lot-size metadata: Jesse
            # research receives already-normalized candles, so a fixed notional
            # quantity is the least surprising paper-only sizing here.
            qty = notional / entry
            self.buy = qty, entry

        def on_open_position(self, _order):
            # Jesse installs spot exit orders after the position is open.
            self.stop_loss = self.position.qty, self.price * 0.99
            self.take_profit = self.position.qty, self.price * 1.01

        def go_short(self):
            pass

        def should_cancel_entry(self) -> bool:
            return False

    exchange = "OKX Public"
    symbol = payload["inst_id"].replace("-SWAP", "")
    key = jh.key(exchange, symbol)
    result = backtest(
        {
            "starting_balance": 1_000_000,
            "fee": 0.001,
            "type": "spot",
            "exchange": exchange,
            "warm_up_candles": 0,
        },
        [{"exchange": exchange, "symbol": symbol, "timeframe": "15m", "strategy": PublicDataSmoke}],
        [],
        {key: {"exchange": exchange, "symbol": symbol, "candles": candles}},
    )
    report = {
        "kind": "jesse_core_real_market_backtest",
        "status": "completed_historical_replay",
        "live_or_paper": False,
        "private_api_used": False,
        "source": {
            "exchange": "OKX public",
            "inst_id": payload["inst_id"],
            "timeframe_input": "1m",
            "strategy_timeframe": "15m",
            "closed_candles": len(candles),
            "first_open_utc": payload.get("first_open_utc"),
            "last_open_utc": payload.get("last_open_utc"),
            "volume_unit": payload.get("volume_unit"),
        },
        "strategy": "fixed 50 USDT long-only smoke strategy; EMA20/EMA50 and RSI14; 1% stop/target",
        "metrics": _json_safe(result.get("metrics", {})),
        "trades": len(result.get("trades", [])),
        "limitations": [
            "This validates Jesse core data ingestion and research execution, not Jesse licensed live/paper.",
            "The strategy is a harness, not a supplied profitable strategy.",
            "OKX contract volume, fees, slippage, funding and live order fills are not a profitability claim.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    encoded = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # GitHub keeps notices in the check-run API even when runner logs and
    # artifact blobs are unavailable to this sandbox.
    print("::notice title=Jesse core araştırma replay::" + encoded, flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
