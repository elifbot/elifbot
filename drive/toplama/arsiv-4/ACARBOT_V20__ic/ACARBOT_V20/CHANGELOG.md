# Changelog

## 20.0.0 — ACARBOT V20 (consolidation)
Base: PHOENIX V15_1 (4.5.1-hardened-v15) + min_score 0.30 package + live test report 2026-11-10.

### Binance / data layer
- swap and dated-future tickers are fetched in separate batches (ccxt "symbols must be of the same type").
- Missing Binance bid/ask is completed from `bookTicker` (one bulk call, liquid candidates only); if unavailable the spread is "unknown" and enforced later from the order book instead of 99999 bps.
- WWW public route lives inside the adapter (`phoenix/binance_route.py`); `PHOENIX_BINANCE_PUBLIC_WWW=auto|1|0` (auto = only after an HTTP 451). Spot catalogue is never loaded.
- Ban guard: HTTP 418 / `-1003 banned until` is detected, never retried, the exchange is paused until expiry and reported in `exchange_status`.
- Non-retryable errors (BadRequest, InvalidOrder, ...) are no longer retried; order creation is never auto-retried (client order id + lookup instead).
- 1h/4h candles and funding are cached (default 10 min / 5 min); default detail cap 150 symbols/exchange + 25 rotating tail slots.
- OKX 24h volume no longer double-scaled (`info.volCcy24h * last`); top volumes are echoed in the report for a manual sanity check.
- Cycle deadline: the detail loop stops at `--duration` and optionally at `--max-cycle-sec`; checkpoint reports every 25 snapshots and at every cycle end.

### Signal system
- `min_score` default 0.72 → 0.30 (score is a weighted average; 0.72 was unreachable).
- Signed OI direction + 5-minute lookback/scale parameters (from V15_1).
- Optional trend/HTF alignment gate (`PHOENIX_REQUIRE_ALIGNMENT`, off by default, always shadow-counted).
- Exact `score_pass_counts` per threshold, histogram, per-reason rank/snapshot/strategy rejection counters, optional `--score-log`.

### PAPER pipeline (new)
- `SIGNAL → SIZING → RISK → CORRELATION → PAPER ACCEPT/REJECT`, positions marked each cycle and closed by STOP/HARD_LOSS/TARGET/TIME, daily/weekly loss and drawdown kill switch, journal + state file.
- Funnel, rejection reasons (events and unique symbols), correlation gate stats and paper account in the report JSON; `tools/read_report.py` prints the chain.

### Risk / correlation
- Correlation gate: minimum sample size (default 20), direction-aware (`c >= limit`, no `abs()`); returns now come from the 15m closes already fetched, not from one price per cycle. `TradingService` finally receives the configured window.
- Kill switch: cancel entry orders → verify with the exchange → close reduce-only → clean protective legs; persisted halt blocks new entries; retried until flat; `--clear-halt`.

### Execution
- Maker re-pricing (LONG bid+tick, SHORT ask−tick, never crossing), stop/target shifted with it.
- Per-exchange params: Binance `postOnly+GTX` (+`positionSide` in hedge mode), OKX `tdMode`, `postOnly`, `posSide` in long/short mode.
- Pre-order sizing shared with paper: precision, min amount/notional, bump-or-skip with recomputed stop.
- Requote after `maker_timeout_sec` (price moved ≥ `requote_bps`, ≤ `max_requotes`, ≤ `max_chase_bps`), cancel verified with the exchange.
- Protective SL/TP: direction and "would trigger immediately" validation (fail-safe), OKX unified params with raw fallback, cancel failures flagged and retried, partial-fill-then-cancel now protected, protection failure → emergency close retried until it works.
- Duplicate-order and already-open-symbol guards; leverage/margin mode set once per symbol.

### Backtest
- Entry fills at the NEXT bar's open (was: signal bar close).

### Tests
- 28 → 99 tests (run offline with fakes; see build report for what that does and does not prove).

## 4.5.1-hardened-v15 and earlier
See `docs/history/`.
