# ACARBOT V22 — build and validation report

## Source baseline
V22 is based on the fuller `ACARBOT_V20.zip` tree, not the reduced V21 tree. It retains V20's `sizing.py`, `telemetry.py`, `paper.py`, `binance_route.py`, retry/backoff code, maker execution, calibration/report tools, historical docs, and the V20 regression suites. The V21-specific global paper account behavior and changes were reviewed and integrated where safe.

## Applied fixes from the V21 30-minute paper report

1. **Sandbox/production routing:** `.env.example` defaults both Binance and OKX sandbox flags to `0`. `set_sandbox_mode(True)` is applied before route configuration; production WWW fallback is disabled in sandbox. Startup and report configuration echo the environment per exchange.
2. **$20 modeled stop:** risk stop math includes entry fee, exit fee, and slippage reserve. ATR may tighten the stop but cannot widen the $20 per-position modeled risk. Paper STOP fills default to the worse of stop and observed mark (`PHOENIX_PAPER_STOP_FILL=worse`); gap-through price and gap-adjusted PnL are separately reported. `stop` remains an optimistic diagnostic option. Real stop-market orders can still gap in live markets; $20 is not an absolute guarantee under gaps, outages, or execution failure.
3. **Slow scan / stale stops:** open paper positions are marked with batched ticker requests between candidate scans, rather than only once per full cycle. Default detailed scan is volume-ranked 100 symbols plus 25 rotating tail symbols per exchange per cycle; cycle budget defaults to 180 seconds. This is a bounded scan strategy, not a promise that every market is scanned every 15 seconds. API rate limits and endpoint latency still govern actual cycle time.
4. **Cross-exchange duplication:** one paper portfolio is shared across configured exchanges; one underlying cannot be opened twice while already open. There is no global or theme-based position-count cap. Every fresh eligible signal reaches the collateral, loss, drawdown and correlation gates.
5. **OKX volume:** OKX derivative contract counts are converted using instrument `ctVal`, `ctMult`, value currency, and last price. If required contract metadata is missing, the market is excluded rather than accepted on inflated raw volume. This formula is unit-tested with a 0.01 contract-value fixture; it still needs validation against live OKX instrument metadata for each instrument family.
6. **Correlation:** default minimum sample size is 30; insufficient data is skipped and counted, not treated as a valid correlation. Existing direction-aware correlation behavior is retained.
7. **Reporting:** open positions include venue, symbol, side, entry, mark, mark timestamp, stop, target, margin, and unrealized PnL. Closed trades include stop-gap diagnostics.
8. **Versioning:** package, telemetry, docs, launchers, and report version identify V22.
9. **Exchange list:** `PHOENIX_EXCHANGES` accepts a comma-separated list of CCXT exchange IDs. Multi-exchange READ_ONLY/PAPER shares one virtual $1,000 account. Multi-exchange LIVE is deliberately blocked until global live balance/margin coordination is implemented; this avoids multiplying a separate risk budget at every venue.

## User's immutable trading settings

- Starting paper equity: $1,000
- Fixed nominal position size: $50 per entry (not $50 margin)
- Leverage: 10x
- Approximate initial margin: $5 per entry before fees and venue requirements; minimum-order auto-bump is capped at 1.0x.
- Modeled maximum loss per position: $20 before unforeseen market gaps / venue failures
- `PHOENIX_MAX_OPEN_POSITIONS=0`: no arbitrary global position-count cap
- No theme position-count cap is implemented; legacy `PHOENIX_MAX_POSITIONS_PER_THEME` settings are ignored
- `PHOENIX_MAX_RESERVED_MARGIN_PCT=1.0`: available equity and margin remain the natural capacity limit; fees are included in reserved usage

## V22.0.3 sizing change

- With 10x leverage, the theoretical initial margin is $5 per position; actual collateral use also includes fees and exchange maintenance requirements.

## Local validation performed

- `python -m compileall -q .`
- `pytest -q`: 121 tests passed for V22.0.3.

## Not yet validated

- No new external 30-minute exchange paper run has been performed by this build process.
- No live order has been sent and no API key is required for READ_ONLY/PAPER.
- Actual OKX contract metadata for all instrument families, real rate-limit behavior, and cycle duration must be verified in the next Arena.ai paper run.
- Multi-exchange LIVE is locked; do not enable it by bypassing the guard.
- The scan uses a volume-ranked head plus rotating tail to respect rate limits; coverage and cycle duration must be evaluated from the next report.

## Acceptance test

Run `RUN_V22_30MIN_PAPER_TEST.bat` (Windows) or `./run_v22_30min_paper_test.sh` (Linux/macOS). Verify:

- `market_data_env` says `MAINNET_PUBLIC_DATA` for every intended exchange.
- OKX XAG/LLY volume provenance references `ctVal` conversion, not raw contract count.
- No same-underlying duplicate opens across exchanges.
- No arbitrary `max_open_positions` rejection; rejections should be margin/risk/correlation reasons; there must be no theme-count rejection.
- Every STOP close includes stop fill and gap diagnostics; a gap can produce a realized modeled loss worse than -$20, and this must be visible in the report.
- Position mark timestamps advance during long scan cycles.
- Full report includes open positions, closed trades, cycle durations, and gate skip counts.

A 30-minute run is a regression screen only. Before any real-money use, run at least 24 hours of paper testing and accumulate at least 100 closed trades across representative market conditions.


## V22.0.4 - strategy rules restored (supersedes the 22.0.3 sizing note)

- $1,000 account, $50 margin per entry at 10x = $500 notional, fixed -$20 modeled stop, indicator take profit, no position-count cap.
- `PHOENIX_ENTRY_NOTIONAL_USD` was removed; setting it now raises an error so a stale `.env` cannot silently resize entries.
- Capacity with these rules is collateral-bound (about 19-20 simultaneous positions); this is arithmetic, not a count limit.
