# AcarBot V20 Build/Test Report

## Basis
V20 consolidates the PHOENIX V15.1 source line, the min_score 0.30 live-test findings, and the confirmed hardening items from the supplied test/council material.

## Implemented
- Default `min_score=0.30`.
- Signed OI direction and configurable OI lookback retained.
- Binance Futures-only USDT universe; swap/future ticker batches separated.
- Missing Binance bid/ask fallback to order book.
- Binance WWW public routing retained.
- Robust order-book timestamp unit normalization.
- Paper execution now runs risk and correlation gates without exchange orders.
- Paper rejection reasons are persisted in the live report.
- Partial-fill protective validation accepts multiple protection batches while requiring both SL/TP coverage.
- Protective cancellation is followed by exchange-state verification.
- Kill-switch attempts cancellation of pending non-reduce-only orders before position closes.
- Correlation uses configured window.
- Backtest enters at next-bar open after signal-bar close.
- Per-cycle checkpoint reports and discovered-vs-scanned telemetry.
- Explicit mutually-exclusive read-only/paper/live CLI modes.
- Stale report is removed before a new CLI run.

## Verification
- `pytest -q`: **34 passed, 0 failed**
- `python -m compileall -q phoenix tests`: PASS
- `python -m phoenix.live --help`: PASS
- ZIP integrity: PASS
- No `__pycache__`, `.pytest_cache`, or `.pyc` files included in release ZIP.

## Live-data status
No new real-market live run is claimed by this build. The supplied V15 live report remains the evidence for the 0.72 -> 0.30 signal calibration. V20 must be run in the user's network environment for fresh Binance/OKX runtime verification.

## Recommended validation order
1. 10-minute `--read-only`.
2. 10-minute `--paper`.
3. Compare `strategy_rejections`, `paper_execution`, `paper_rejections`, score distribution and exchange/side counts.
4. Only after paper validation, consider sandbox/live execution.
