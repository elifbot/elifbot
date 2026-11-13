# V22 test plan — 30-minute real-market PAPER

1. Install dependencies: `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` if no `.env` exists. Inspect both sandbox flags and ensure they are `0` for public mainnet data. Keep `PHOENIX_LIVE_TRADING=0`.
3. Configure `PHOENIX_EXCHANGES=binance,okx` or the CCXT venues intended for the test.
4. Run `RUN_V22_30MIN_PAPER_TEST.bat` on Windows or `./run_v22_30min_paper_test.sh` on Linux/macOS.
5. Inspect `reports/v22_paper_30min.json` and `reports/v22_paper_30min_scores.jsonl`.

Paper mode does not submit orders. It uses public market data and one shared virtual $1,000 portfolio. A 15-second poll is a desired cadence, not a guaranteed cadence: the 180-second per-cycle budget truncates a scan when rate limits or latency make a full scan too slow.

Acceptance checklist:
- `market_data_env` is MAINNET_PUBLIC_DATA on all venues.
- OKX derivative turnover uses ctVal/ctMult; missing contract metadata means the market is excluded.
- Underlying duplication is blocked across venues.
- Theme concentration and correlation gates report their own rejections/skips.
- Open position marks refresh during long scan cycles.
- Stop fill, gap-through estimate, realized/unrealized PnL and fees are separately visible.
- No live order submission appears in logs.
