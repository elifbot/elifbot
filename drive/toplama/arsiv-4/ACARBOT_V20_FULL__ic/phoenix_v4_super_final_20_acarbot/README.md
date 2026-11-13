# AcarBot V20

A consolidated Binance Futures + OKX Futures/Swap signal and execution hardening release.

## Modes
- `--read-only`: market data and signal diagnostics only.
- `--paper`: runs signal -> risk -> correlation -> paper-fill without exchange orders.
- `--live`: authenticated exchange execution; use only after paper/sandbox validation.

Default is read-only.

## V20 diagnostic chain
`MARKET -> FILTERS -> SCORE -> SIGNAL -> RISK -> CORRELATION -> PAPER/LIVE EXECUTION`

Paper reports expose accepted/rejected counts and exact rejection reasons so a signal that passes `min_score=0.30` cannot disappear silently.

## Binance
Only USDT-settled futures markets are loaded. Swap and dated-future ticker batches are separated. Missing bid/ask values fall back to order-book data. Optional public WWW routing is retained for restricted public FAPI environments.

## Threshold
Production default is `PHOENIX_MIN_SCORE=0.30`. The 0.72 value remains available for calibration comparison; it is not asserted to be profitable.

## Safety
Real exchange orders are opt-in. Keep `--read-only` or `--paper` for validation. Do not put API credentials in source files.
# PHOENIX V4 SUPER FINAL 15 — HARDENED

Binance Futures + OKX Futures signal, risk, backtest and optional CCXT execution core.

## What is complete
- All active USDT-settled swap/future markets exposed by Binance/OKX are discovered.
- Eligible markets are filtered by 24h quote volume and spread.
- Scan order is **24h volume descending**; `--detail-per-cycle 0` means all eligible markets.
- Strategy architecture and default weights are preserved.
- Exchange-authoritative equity, positions, open orders and realized PnL are used for authenticated risk checks.
- Realized trade history is paginated with bounded deduplication instead of a single 1000-row request.
- Exchange contract size is carried through positions, pending-margin calculations, signals and PnL.
- Persistent position/risk state survives restart.
- Daily/weekly/max-drawdown kill switches can submit reduce-only emergency closes.
- Maker expiry can cancel the remote order.
- Filled entries receive reduce-only protective stop/TP orders; partial fills top up protection.
- If protection cannot be established, the service cancels successful protective legs and attempts an emergency reduce-only close.
- Binance/OKX trigger routing remains exchange-aware.
- Retry/backoff and symbol normalization are shared by live exchange calls.
- Backtest includes contract size, entry/exit fees, slippage and conservative same-bar stop-first handling.
- Live test report is written to JSON so cycles, snapshots, signals and runtime errors are visible.

## Install

```bash
python -m pip install -r requirements.txt
```

## Configure

Copy `.env.example` to `.env` and fill the exchange credentials only when authenticated testing is required. All other runtime parameters are already populated.

The bot does **not** read secrets from source code.

## Read-only 5-minute test

```bash
python -m phoenix.live --duration 300 --poll 15 --detail-per-cycle 0 --report live_test_report.json
```

This does not submit orders. It discovers the full eligible universe, ranks by 24h volume, builds live snapshots and reports signal/error counts.

## Paper test

```bash
python -m phoenix.live --duration 300 --poll 15 --detail-per-cycle 0 --paper --report paper_test_report.json
```

## Authenticated sandbox/testnet test

Set the Binance/OKX sandbox credentials and keep `PHOENIX_LIVE_TRADING=0` for a first pass. After read-only/paper validation, use the exchange sandbox/testnet and explicitly enable `--live` only for that environment.

```bash
python -m phoenix.live --duration 300 --poll 15 --detail-per-cycle 0 --live --report sandbox_test_report.json
```

## Real-money mode

`--live` is opt-in. Do not use real capital until exchange permissions, symbol/contract sizing, fill reconciliation, protective orders, restart recovery, kill switches, and out-of-sample/walk-forward results have been independently verified.

## Test suite

```bash
PYTHONPATH=. pytest -q
python -m compileall -q phoenix tests
```

The package intentionally does not claim profitability. A successful software test proves execution correctness for the tested path, not trading profitability.
