# Changelog

## 22.6.0-FINAL - the "signals but no profit" fix set (exit engine + real -$20 stop + signal quality + LIVE TP)
Base: 22.0.5 tree (architecture, modes, gates, CLI unchanged). Full analysis: docs/V22_6_FINAL_BUILD_REPORT.md.
- EXIT ENGINE (the #1 profit blocker fixed): V22.5 cut winners at +$0.10 while losers ran to the stop (payoff ~1:40). Now: `PHOENIX_TP_MIN_R=0.5` (indicator TP needs net >= $10), `PHOENIX_BREAKEVEN_R=0.5` (stop -> entry+costs at +$10), `PHOENIX_TRAIL_ARM_R=1.0` + `PHOENIX_TRAIL_GIVEBACK_R=0.5` (trail locks peak-10 at +$20). The stop only tightens; the fixed -$20 floor never widens.
- ENTRY SEMANTICS (the -$20 stop made REAL): new `PHOENIX_ENTRY_MODE=margin` (default): $50 margin x 10x = $500 notional -> the -$20 stop is a ~3.9% move, inside isolated liquidation. `entry_mode=notional` keeps the legacy $50-notional behaviour with the stop capped to `PHOENIX_LIQUIDATION_BUFFER_FRACTION/leverage` (7% at 10x). Conflicting env entries fail loud.
- SIGNAL QUALITY: OI x price agreement (OI up + price up = new longs, OI up + price down = new shorts, OI down = unwinding -> halved), 15m/1h-4h conflict penalty (score x `PHOENIX_CONFLICT_PENALTY`=0.70), RSI(14) 15m overextension gate (no LONG >= 78, no SHORT <= 22; exits never gated).
- LIVE indicator TP un-blocked: bot-managed exits for FILLED positions - exchange stop amendment (breakeven/trail), reduce-only market close on INDICATOR_TP, 24h TIME exit; reconciler now accepts stop-only protection (V22.5 marked it FILLED_PROTECTION_FAILED and emergency-closed every indicator-mode position). `PHOENIX_LIVE_INDICATOR_TP=0` restores the old refusal.
- PAPER honesty: funding accrued every 8h held; `trade_stats` (avg win/loss, win rate, payoff, expectancy, profit factor) in the paper summary; exit-engine context (final_stop, be/trail armed, peak_net) on every closed trade.
- Report/config echo extended (entry_mode, stop cap, tp_min_r, be/trail, rsi/oi/conflict settings); banner shows the effective entry math.
- Tests: 152 -> 159; offline 40-position simulation compares V22.5 vs V22.6 rules on identical signals: -53.15 USD vs +61.45 USD (docs/V22_6_FINAL_BUILD_REPORT.md).


## 22.0.5 - user rules enforced: $50 NOTIONAL, 10x, -$20 stop, unlimited positions
Base: the 22.0.4 tree. Evidence for the 500 USD positions: 22.0.4 `config.py` had `entry_margin_usd=50` and derived `entry_notional_usd = margin x leverage = 500`.
- `entry_notional_usd=50` is now the real setting; margin is derived (50/10 = ~5). `PHOENIX_ENTRY_MARGIN_USD` raises an error so a stale `.env` cannot recreate 500 USD positions.
- Stop stays a fixed -$20 modeled loss (fees + slippage included, ATR off). At $50 notional this is ~40% from entry, beyond isolated 10x liquidation (~10%): no longer a hard config error; exposed as `Config.stop_beyond_liquidation` and in the report/banner. `PHOENIX_STRICT_LIQUIDATION_GUARD=1` restores the refusal.
- Daily/weekly loss and drawdown halts are OFF by default (`0`, `0`, `1.0`); `0` disables, positive values re-enable. Applied in `risk.can_enter` and `trading.enforce_kill_switch`.
- `tp_min_net_usd` default 1.0 -> 0.10 (same 0.2% of notional as before). At $50 notional a $1 minimum needed a ~2% move, so the indicator take profit would almost never fire.
- Capacity is now collateral-bound at ~196 concurrent paper positions (was 19-20).
- Tests: 134 -> 152; new `tests/test_v22_5_user_rules.py` locks every rule. Old tests that asserted $500 were updated.

## 22.0.4 - strategy rules restored + fixes (on top of 22.0.3)
**Strategy (restored, as specified):** $1,000 account; $50 margin x 10x = $500 notional per entry; stop = fixed -$20 (fees and slippage included, ATR no longer touches it); take profit decided by indicators; no position-count cap.
- Reverted the 22.0.3 "$50 notional" sizing. `PHOENIX_ENTRY_MARGIN_USD=50`; notional is derived (margin x leverage). `PHOENIX_ENTRY_NOTIONAL_USD` now raises an error.
- Stop: `PHOENIX_ATR_STOP_MULTIPLIER` default 0 (off). If enabled, ATR can only tighten the stop. Config refuses a stop at/beyond the liquidation distance (e.g. `max_loss_usd=45`).
- Take profit: `PHOENIX_TP_MODE=indicator` (default). No fixed target (`target=0`). A net-profitable position (>= `PHOENIX_TP_MIN_NET_USD`) is closed (`INDICATOR_TP`) when the signed score in its direction falls below `PHOENIX_TP_EXIT_SCORE`. Losers are never cut by indicators. Open positions are scored every cycle (budget `PHOENIX_EXIT_EVAL_BUDGET_SEC`) and whenever they appear in the detail scan. `PHOENIX_TP_MODE=fixed_rr` restores the old R-multiple target.
- LIVE guard: `--live` refuses to start with `tp_mode=indicator` (no exchange-side TP exists); protective orders now skip the TP leg when `target=0`.
- Fix: Binance `bookTicker` bulk call is split by market type (swap / dated future), removing `symbols must be of the same type` and the unchecked-spread ranking.
- Fix: version is single-sourced (`phoenix/__init__.py`); the banner and report no longer say 22.0.0. Test enforces it.
- Report: score log has `px`, `atr_pct` and all components; rejections by side (`paper_rejections_by_side`); `exit_eval` counters; paper summary has `gross_notional_usd`, `net_notional_usd`, `open_risk_usd`, `closed_by_reason`; config echo has margin/leverage/stop/tp settings.
- Tooling: `tools/package_release.py` builds a clean zip (no `__pycache__`/`.pytest_cache`).
- Tests: 134.


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
