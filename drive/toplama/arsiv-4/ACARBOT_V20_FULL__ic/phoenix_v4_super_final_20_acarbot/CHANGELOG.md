# Changelog

## 5.0.0 — AcarBot V20
- Consolidated V15.1, the 0.30 threshold test, live-test findings and council hardening into one release.
- Production strategy default min_score is now 0.30; 0.72 remains available for calibration diagnostics.
- Binance Futures ticker batches are split by swap/future contract type; spot remains excluded.
- Missing Binance bid/ask values fall back to the live order book.
- Added paper execution through risk and correlation gates without submitting exchange orders.
- Added explicit paper accept/reject telemetry and per-reason rejection counts.
- Added robust order-book timestamp unit normalization.
- Fixed partial-fill protective-order validation so multiple protection batches do not falsely fail.
- Added protective-cancel exchange-state verification.
- Kill-switch now attempts cancellation of pending non-reduce-only entry orders before closing positions.
- Correlation uses the configured correlation window.
- Backtest entries occur at the next bar open after a signal bar closes.
- Added per-cycle checkpoint reports and discovered-vs-scanned universe telemetry.
- Added explicit mutually exclusive --read-only / --paper / --live execution modes.

## 4.5.0 — PHOENIX V15 Hardened Consolidation
- Consolidated the verified V10–V12 hardening line and the latest council findings into one coherent release.
- Fixed the CCXT `fetch_my_trades` adapter signature mismatch used by authenticated risk synchronization.
- Added bounded pagination/deduplication for realized trade history.
- Replaced exchange-position `SimpleNamespace` objects with typed `Position` objects carrying actual contract size.
- Added contract-size-aware pending-order margin reservation and excluded reduce-only orders from entry-margin reservation.
- Persisted open-order and exchange-position details in synchronized state.
- Made portfolio correlation use the configured correlation window and tolerant symbol normalization.
- Added complete environment-driven runtime configuration for risk, strategy, live loop, state and reporting.
- Added structured JSON live-test reporting for cycles, universe size, snapshots, signals and errors.
- Added protection cleanup before emergency close when a protective leg fails.
- Fixed package/root/version naming so V15 is internally consistent.
- Removed cache artifacts from the distributable package.

## 4.4.0 — hardened safety integration
- Global daily/weekly/max-drawdown kill-switch enforcement.
- Persisted position serialization and exchange-authoritative restart reconciliation.
- Partial-fill protective-order top-up and emergency close on protection failure.
- Maker expiry -> exchange cancel callback.
- Shared bounded retry policy and symbol normalization.
- Binance/OKX funding and open-interest REST fallbacks.
- Configurable strategy weights.
- Process-local state locking and additional boundary tests.
- CI workflow for pytest and compile checks.

## 4.3.0 — V11 Hardened Live
- Exchange-authoritative equity, positions and open-order reconciliation.
- Daily/weekly realized PnL refresh from exchange trade history.
- Restart-safe exchange state snapshot.
- Fill reconciliation with exchange-aware protective SL/TP.
- Binance/OKX trigger routing.
- Entry amount/notional minimum checks.

## Earlier V4 hardening
- Explicit daily/weekly loss limits and startup validation.
- Bounded retry/backoff.
- Contract-size-aware backtest PnL and fees/slippage.
- Volume-ranked full liquid universe.

## 4.5.1-hardened-v15
- Integrated optional Binance public WWW FAPI routing for HTTP 451 restricted environments.
- Added cycle checkpoint reports, snapshot-drop reasons, strategy rejection counts, score min/max/mean and histogram.
- Fixed signed OI direction handling; added configurable OI lookback and normalization.
- Made stop-loss budget explicitly contract-size aware.
- Added controlled 0.72 vs 0.30 signal calibration runner without changing the production default.
