# V22 Operations

## Safe rollout
1. On the target machine run `python -m pip install -r requirements.txt`.
2. Run `python -m compileall -q phoenix tests tools` and `pytest -q` (current bundled suite: 134 tests).
3. Check `.env`: `PHOENIX_BINANCE_SANDBOX=0`, `PHOENIX_OKX_SANDBOX=0`, `PHOENIX_LIVE_TRADING=0`. The 30-minute launcher also passes `--require-mainnet-data` and refuses to start if sandbox/demo is enabled.
4. Run `RUN_V22_30MIN_PAPER_TEST.bat` or `./run_v22_30min_paper_test.sh`. This sends no orders and needs no API keys.
5. Inspect `reports/v22_paper_30min.json`, including `config.market_data_env`, `paper.open_position_details`, `paper.closed_trade_details`, `correlation_gate`, and `cycle_durations_sec`.
6. Only after multiple successful short tests, run at least 24 hours of PAPER and accumulate 100+ closed trades before evaluating any live readiness.

## Account rules
- Initial virtual equity: $1,000.
- Fixed position size: $50 NOTIONAL per entry at 10x (~$5 margin); stop is a fixed -$20; take profit is indicator-driven (paper).
- Leverage: 10x; initial margin is approximately $5 per position before fees and exchange-specific requirements. Minimum-order auto-bump is capped at 1.0x.
- Modeled per-position stop budget: $20 including configured entry/exit fees and slippage reserve. ATR can tighten, never widen, the dollar-risk cap.
- `PHOENIX_MAX_OPEN_POSITIONS=0` removes the arbitrary count cap. Actual available equity/margin and the 100% reserved-margin ceiling still constrain entries. Correlation and duplicate-underlying guards remain active. Daily/weekly loss and drawdown halts are OFF by default (0 / 1.0); enable via env if wanted.

## Exchange universe
Set `PHOENIX_EXCHANGES=binance,okx,bybit` (or any supported CCXT exchange IDs that list USDT-settled futures). Read-only/paper uses public market data. Each exchange's sandbox flag is `PHOENIX_<EXCHANGE>_SANDBOX`. Startup and JSON report state whether data came from MAINNET public endpoints or sandbox/demo.

PAPER positions from all configured exchanges share one $1,000 virtual account. The same underlying cannot be opened twice on different venues; there is no theme-based position-count cap. Shared collateral, loss, drawdown and correlation gates govern additional entries.

**Multi-exchange LIVE is intentionally blocked.** The live service still needs a cross-venue account/equity/margin coordinator before multiple exchanges can safely share a single $1,000 live risk budget. Do not bypass this guard. Single-exchange LIVE still requires explicit `--live`, `PHOENIX_CONFIRM_LIVE=YES`, and the selected venue's credentials. An environment variable alone cannot activate LIVE.

## Sandbox order-flow test
Sandbox/demo data is not suitable for strategy calibration. The mainnet paper launcher rejects sandbox flags; to do a deliberate sandbox order-flow test, use a separate `.env` and follow the exchange-specific demo account process. Real order submission remains disabled unless the `--live` CLI flag is explicitly supplied.

## Kill switch
Persisted live state files are `state.<exchange>.json`. `python -m phoenix.live --clear-halt` clears persisted halt fields for the exchanges listed in `PHOENIX_EXCHANGES`. Review the exchange account before clearing a halt.

## Rate limits
Default detailed scan: top 100 volume-ranked markets plus 25 rotating tail markets per exchange per cycle. The 180-second cycle budget truncates an overlong cycle. This is not a guarantee of 15-second full-universe scans; actual endpoint latency, exchange rate limits, and rotating coverage are included in the report.
