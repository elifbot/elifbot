# PHOENIX V15.1 — Build/Test Report

## Build
- Package: PHOENIX V4 SUPER FINAL 15 HARDENED
- Version: 4.5.1-hardened-v15
- Python target: >=3.11
- Default live mode: READ_ONLY
- Default signal threshold: 0.72
- Binance public WWW route: opt-in via `PHOENIX_BINANCE_PUBLIC_WWW=1`; the supplied Binance WWW runner enables it automatically.

## Changes in this build
1. Binance public USDⓈ-M WWW route integration for HTTP 451 restricted environments.
2. Binance linear-only market loading when the WWW route is enabled.
3. Signed OI direction preserved; `abs(oi)` trend-forcing logic removed.
4. Configurable OI lookback (`PHOENIX_OI_LOOKBACK_SEC`, default 300s) and normalization (`PHOENIX_OI_CHANGE_SCALE`, default 100).
5. Contract-size-aware stop-loss budget calculation.
6. Live diagnostics: snapshot drop reasons, strategy rejection reasons, score min/max/mean, score histogram, signal side/exchange counts.
7. Per-cycle checkpoint JSON reporting so interrupted tests retain diagnostics.
8. Read-only is the default report mode unless paper mode is explicitly enabled.
9. Added `RUN_SIGNAL_CALIBRATION.bat`: first 0.72, then 0.30, without changing the production default.
10. Version metadata aligned to 4.5.1-hardened-v15.

## Offline verification
- `compileall`: PASS
- pytest: **27 passed, 0 failed**
- Binance WWW route unit smoke test: PASS
- `python -m phoenix.live --help`: PASS

## Live verification
Not claimed in this build report. The package is prepared for the user's real 10-minute read-only test. The test must be run in an environment with working Binance/OKX network access and CCXT installed.

## Signal calibration procedure
### Pass 1
`PHOENIX_MIN_SCORE=0.72`

### Pass 2
If Pass 1 produces zero final signals, run the supplied calibration script or rerun with:
`PHOENIX_MIN_SCORE=0.30`

Compare:
- `score_max`
- `score_mean`
- `score_histogram`
- `strategy_rejections.below_min_score`
- `snapshot_dropped`
- `signals_seen`
- `unique_signals`
- LONG/SHORT distribution

A lower threshold is a signal-frequency experiment, not a profitability claim. Any threshold change must subsequently be validated with fees, slippage, and walk-forward/OOS testing before live execution.
