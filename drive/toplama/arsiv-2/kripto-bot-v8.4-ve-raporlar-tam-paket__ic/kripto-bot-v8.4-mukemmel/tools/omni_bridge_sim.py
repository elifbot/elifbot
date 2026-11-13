"""AI OmniStudio <-> Kripto Bot v8.0 Canlı Simülasyon ve Tanı Köprüsü."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.ai_council import MultiAICouncil
from src.executor import Executor
from src.risk import RiskManager
from src.sizing import PositionSizer
from src.state_store import StateStore
from src.strategy import Strategy
from src.unified_v8_engine import UnifiedV8Engine
from tests._paper_fixtures import make_paper_broker


def _build_ohlcv(scenario: str) -> pd.DataFrame:
    n = 220
    ts = np.arange(n, dtype=float) * 300_000.0
    base = 100.0 + np.sin(np.linspace(0, 14, n)) * 1.2 + np.linspace(0.0, 4.0, n)
    base[-35:-12] -= np.linspace(0.2, 2.2, 23)
    base[-12:] += np.linspace(0.4, 4.2, 12)
    closes = base
    opens = np.r_[closes[0] - 0.05, closes[:-1]]
    highs = np.maximum(opens, closes) + 0.35
    lows = np.minimum(opens, closes) - 0.25
    vols = np.full(n, 200.0)
    vols[-12:] = 1400.0
    return pd.DataFrame(
        {"ts": ts, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}
    )


async def run_sim(symbol: str, scenario: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(Path(tmp) / "sim_v8.db")
        df5 = _build_ohlcv(scenario)
        last_px = float(df5["close"].iloc[-1])
        broker = make_paper_broker(5000.0, fee_pct=0.02)
        broker.prices[symbol] = last_px

        risk = RiskManager(
            stop_model="marj",
            margin_stop_fraction=0.80,
            leverage=10,
            unlimited_pyramiding=False,
        )
        strat = Strategy(
            w_ind=0.45,
            w_flow=0.40,
            w_news=0.0,
            w_ml=0.0,
            long_th=22.0,
            short_th=-22.0,
            runner_exit=True,
        )
        sizer = PositionSizer(mode="sabit_usdt", fixed_margin_usdt=100.0, leverage=10, kelly_on=False)
        ex = Executor(broker, risk, strat, sizer=sizer, state_store=store, protection_on=False)
        engine = UnifiedV8Engine(ex, mode="hybrid_fusion", council=MultiAICouncil(min_consensus_score=15.0))

        now_ms = int(time.time() * 1000)
        last_closed_mid = now_ms // 60_000 - 1
        for i, mid in enumerate(range(last_closed_mid - 59, last_closed_mid + 1)):
            c_px = last_px - 0.6 + (i / 60.0) * 0.5
            engine.ingest_closed_1m_candle(
                "binance", symbol, mid, c_px - 0.1, c_px + 0.3, c_px - 0.3, c_px, 18.0
            )

        spread_pct = 0.02
        if scenario == "high_spread_trap":
            spread_pct = 0.68
        elif scenario == "adverse_whale_dump":
            # Satıcı balina baskısı simüle et
            for i in range(40):
                t_ms = now_ms - (40 - i) * 1000
                qty = 1800.0 if i == 10 else 3.0
                await engine.on_trade("binance", symbol, last_px, qty, is_buyer_maker=True, ts_ms=t_ms)
        if scenario != "adverse_whale_dump":
            for i in range(40):
                t_ms = now_ms - (40 - i) * 1000
                qty = 1500.0 if i == 6 else 2.5
                await engine.on_trade("binance", symbol, last_px, qty, is_buyer_maker=False, ts_ms=t_ms)

        result = await engine.evaluate_and_route("binance", symbol, df5, spread_pct=spread_pct)
        ledger = store.verify_paper_ledger_integrity()
        return {
            "ok": True,
            "symbol": symbol,
            "scenario": scenario,
            "signal": result.get("signal"),
            "routed": result.get("routed"),
            "reason": result.get("reason"),
            "council": result.get("council"),
            "v4_60m": result.get("v4_60m"),
            "ledger_integrity": ledger,
            "open_positions": list(ex.positions.keys()),
            "paper_balance": round(broker.paper.balance, 4),
        }


def main():
    raw = sys.stdin.read().strip()
    payload = json.loads(raw) if raw else {}
    symbol = str(payload.get("symbol") or "BTC/USDT")
    scenario = str(payload.get("scenario") or "bullish_whale_breakout")
    out = asyncio.run(run_sim(symbol, scenario))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
