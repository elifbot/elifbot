# V20 test plan — 10 min READ_ONLY → 10 min PAPER

Goal: find the SECOND blocker (after `min_score`) with numbers, not guesses.

```bash
./run_v20_plan.sh      # or RUN_V20_PLAN.bat
```
Outputs: `reports/readonly_10min.json`, `reports/paper_10min.json`, score logs, `paper_state.json`, `paper_trades.jsonl`.

## Step 0 — sanity (first 2 minutes of the READ_ONLY log)
| Check | Where | Expected |
|---|---|---|
| Both exchanges scanned | `exchange_scanned` | BINANCE > 0 **and** OKX > 0 |
| No ban | `exchange_status` | empty (no `banned`) |
| Volume numbers plausible | `volume_samples` | BTC ≈ the exchange UI's 24h USDT volume (order of 1e9–1e11), `source` filled |
| Ranking filters sane | `rank_rejections` | `low_volume`/`wide_spread` dominate; `no_ticker`≈0; `exchange_banned` absent |
| Cycle fits its budget | `cycle_durations_sec`, `truncated_cycles` | < 240 s each, 0 truncated (else lower `--detail-per-cycle`) |

## The chain (PAPER report, `funnel`)
```
candidates → detailed snapshots → scored → passed_min_score
   → SIZING → RISK → CORRELATION → PAPER ACCEPTED
```
Counts are EVENTS (the same symbol is re-evaluated every cycle). `paper_rejections_unique` counts symbols.

| Where it drains | Meaning | Action |
|---|---|---|
| `snapshots` ≪ `candidates` | see `snapshot_dropped` (`oi_unavailable`, `book_timestamp_missing`, `market_data_stale`, `exception:*`, `exchange_banned`) | fix the dominant reason; stale data → raise `PHOENIX_MAX_MARKET_AGE_SEC` only with evidence |
| `passed_min_score` = 0 | threshold/score issue | `score_pass_counts` shows how many clear 0.30/0.35/0.40…; pick by target frequency |
| `SIZING:below_min_notional / zero_qty_after_rounding / below_min_amount` | exchange minimum/precision vs 500 USD notional (50 margin × 10x) | raise `PHOENIX_ENTRY_MARGIN_USD` or accept the skip; high-price coins (BTC) hit this first |
| `RISK:max_open_positions / reserved_margin_cap` | capacity, not signal quality | normal when many signals arrive at once |
| `RISK:daily_loss_kill_switch / max_drawdown_kill_switch` | the paper account already lost the limit | expected only after losses |
| `RISK:already_open_symbol` | same coin signalled again | informational |
| `CORRELATION:correlation_limit` | stacked same-direction exposure (`correlation_gate.blocked`) | check `PHOENIX_CORRELATION_LIMIT`; `skipped_insufficient_samples` high ⇒ gate is not actually active yet |
| `PAPER ACCEPTED` > 0 | pipeline works end to end | let it run longer (`--paper-resume`) and read the closes in `paper_trades.jsonl` |

## Alignment experiment (optional)
`passed_min_score_and_aligned / passed_min_score` is the share of signals where 15m trend and HTF agree. Compare PAPER runs with `PHOENIX_REQUIRE_ALIGNMENT=0/1` over the same period before changing the default.

## What 10 minutes can NOT tell you
Win rate, expectancy, drawdown. Targets/stops need hours–days of paper plus a proper out-of-sample backtest.
Intra-cycle wicks are invisible to paper (marks are taken once per cycle).
