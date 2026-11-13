# Changelog

## V22.0.4 — Per-position USD hard-loss stop
- Enforced `PHOENIX_MAX_LOSS_USD` as the authoritative per-position stop distance.
- ATR no longer tightens the protective stop; ATR-derived early exits no longer override the user's dollar-loss rule.
- Exchange-rounded quantity is used to recalculate the hard-loss stop before submission.
- Reward multiple is preserved when sizing changes.
- Paper and live protective stop paths continue to use the same computed stop.
- Important limitation: stop-market gaps, excess slippage, fees/funding beyond estimates and exchange liquidation can cause realized loss to exceed $20. Cross/isolated liquidation rules remain exchange-specific; do not assume the stop guarantees a hard ceiling.


## V22.0.1 — review patch
- Fix: `PHOENIX_CORRELATION_MIN_SAMPLES` env default was 20 (dataclass/docs said 30); now 30.
- Added `PHOENIX_PAPER_STOP_FILL=stop|worse` (default stop); paper summary now reports `stop_gap_excess_total_usd` and `realized_total_gap_adjusted`.
- Docs/README test counts and wording aligned. Tests: 116.

## V22.0.0 — test-driven consolidation
- V20's sizing, telemetry, maker execution, Binance route, retry, and regression-test modules retained.
- Sandbox is applied before public routing; sandbox mode cannot be overwritten by the production WWW route.
- Default public-data mode is MAINNET market data with READ_ONLY/PAPER; startup and JSON report state the environment.
- OKX derivative volume is calculated from contract count × ctVal × ctMult and instrument value currency; missing metadata fails closed.
- Paper account is shared across all configured exchanges; same underlying cannot be opened twice across venues.
- Added theme concentration cap, 30-sample correlation minimum, ATR-tightened stop within the fixed $20 modeled risk cap.
- Paper positions are marked between long scan operations; stop exits use stop price and report gap-through risk separately.
- Added open-position mark timestamps and closed-trade details to paper report.
- Unlimited position count is represented by `PHOENIX_MAX_OPEN_POSITIONS=0`; equity/margin/fee/risk gates remain active.
- Exchange list is configurable with `PHOENIX_EXCHANGES`; multi-exchange LIVE remains intentionally locked until a shared live-account risk coordinator is implemented.

## 20.0.0 — ACARBOT V20 base release (retained)
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


## V22.0.2 — Unlimited signal-driven position count
- Removed global and theme-based position-count gates. Legacy `PHOENIX_MAX_POSITIONS_PER_THEME` settings are ignored.
- Each fresh eligible signal reaches shared collateral, equity, daily/weekly loss, drawdown and correlation checks.
- Kept duplicate-underlying-across-venues and duplicate-open-order safety gates.
- Paper stop fill now defaults to conservative `worse` (worse of stop and observed mark); `stop` remains an explicit optimistic diagnostic option.


## 22.0.3 - Fixed $50 notional sizing
- Entry size is now a fixed $50 NOTIONAL exposure per signal, not $50 margin.
- At 10x leverage, required initial margin is approximately $5 per position before fees.
- Unlimited position-count mode remains enabled (`PHOENIX_MAX_OPEN_POSITIONS=0`); available collateral, risk, correlation, exchange minimums and loss guards still apply.
- Added `PHOENIX_ENTRY_NOTIONAL_USD=50`; legacy `PHOENIX_ENTRY_MARGIN_USD` is accepted as a compatibility fallback and is interpreted as the notional amount.
- Updated strategy, backtest, sizing defaults, tests, operations documentation and telemetry version.


## V22.0.5 - NVIDIA review hardening
- Added a conservative leverage-relative stop-distance cap (default 70% of 1/leverage; 7% at 10x) while retaining the $20 per-position modeled loss ceiling. This is explicitly a heuristic, not an exchange liquidation guarantee.
- Maker entry now fails closed when the order book is unavailable/invalid; it no longer silently falls back to a potentially marketable signal price.
- Revalidates the final precision-formatted entry against the live spread before sending a post-only order.
- Serializes TradingService submit/reconcile/kill-switch state transitions with a re-entrant lock.
- Estimates reserved margin from notional/leverage when the exchange omits initialMargin, avoiding false free-collateral readings.
- Re-tested: 126 tests pass. Live indicator-based take-profit is not enabled in this build; it requires a separately verified score-driven close/reconciliation path and remains a follow-up item rather than being represented as implemented.
