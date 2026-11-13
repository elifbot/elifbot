# AcarBot V20 Test Plan

## 1. Offline software validation

```bash
PYTHONPATH=. pytest -q
python -m compileall -q phoenix tests
```

This validates configuration, risk, strategy, contract sizing, state serialization, live snapshot parsing, pagination, exchange-state reconciliation and protective-order behavior without contacting an exchange.

## 2. Read-only live market-data validation

```bash
python -m phoenix.live --duration 300 --poll 15 --detail-per-cycle 0 --report live_test_report.json
```

Expected report fields:
- cycles
- universe
- detailed_snapshots
- signals_seen
- unique_signals
- errors
- exchanges
- detail_per_cycle

No authenticated credentials are required for read-only market-data mode.

## 3. Paper validation

```bash
python -m phoenix.live --duration 300 --poll 15 --detail-per-cycle 0 --paper --report paper_test_report.json
```

## 4. Sandbox authenticated validation

Only after read-only validation, configure sandbox/testnet credentials in `.env` and use:

```bash
python -m phoenix.live --duration 300 --poll 15 --detail-per-cycle 0 --live --report sandbox_test_report.json
```

The exchange sandbox flags in `.env.example` default to `1`.

## 5. Real capital

Do not enable real-money execution until:
- exchange position and order reconciliation is confirmed;
- partial fills create correct protection;
- failed protection triggers emergency reduce-only handling;
- kill-switch close behavior is confirmed;
- restart recovery is confirmed;
- contract size / min amount / min notional are verified on both venues;
- OOS/walk-forward performance is acceptable.
