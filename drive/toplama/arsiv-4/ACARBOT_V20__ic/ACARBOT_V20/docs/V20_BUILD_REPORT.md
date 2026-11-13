# ACARBOT V20 — build report

## 1. Inputs merged
| Input | Used for |
|---|---|
| `PHOENIX_V4_SUPER_FINAL_15_HARDENED_V15_1.zip` (4.5.1) | code base (signed OI, telemetry, contract-aware stop, www route) |
| `PHOENIX_V15_min_score_030.zip` | `min_score=0.30`, score-log idea, 1087-row reference log (`reference_data/`) |
| `PHOENIX_Canli_Test_Raporu.docx` | OKX volume inflation, mid-cycle report loss, WAF ban `-1003`, sandbox caveats |
| `PHOENIX_V15_1_TEST_RAPORU_2026-11-10.md` | Binance layers 2 + 3, 705/705 `below_min_score`, capacity warning |
| Your review list (6 items) and the other-chat V20 notes | execution/risk/telemetry items (mapping below) |

Reference check: `tools/calibrate_from_scores.py` reproduces the report's numbers from the raw log (65 candidates ≥0.30, 38 unique symbols, 5 ≥0.50, 0 ≥0.72).

## 2. Your list → implementation
| # | Request | Status | Where |
|---|---|---|---|
| 1 | per-exchange order params | done | `exchange_execution.entry_params/position_params` — Binance `postOnly+GTX` (+`positionSide` hedge), OKX `tdMode`,`postOnly`,`posSide` (long_short) |
| 2 | maker price + requote | done | `ExchangeExecutor.maker_price`, `TradingService._handle_resting_entry` (timeout → keep / requote / give up; chase limit; cancel verified) |
| 3 | pre-order qty check | done | `sizing.fit_order` (same code in PAPER and LIVE) |
| 4 | correlation n≥20, same direction only | done | `portfolio.PortfolioRisk` (direction-aware, no `abs`) |
| 5 | rejection reasons in report | done | `telemetry` (`funnel`, `paper_rejections[_unique]`, `live_rejections`, `rank_rejections`, `snapshot_dropped`, `strategy_rejections`) |
| 6 | demo/testnet test on your machine | **not possible here** | procedure in `docs/OPERATIONS.md` |

Other-chat V20 notes: Binance batches/bookTicker/www route ✔ · signed OI + lookback ✔ · rejection counters ✔ · paper through the real gates ✔ · kill switch order ✔ · protective validation/cancel failures ✔ · backtest next-bar open ✔ · checkpoint telemetry ✔ · READ_ONLY default / `--paper` / `--live` ✔. I could not see that package, so this is a re-implementation from the descriptions, not a diff against it.

## 3. Bugs found while reading the code (fixed)
1. `LONG` entry was the **ask** → a post-only order there is rejected (taker price). Now the passive side of a fresh book.
2. Partial fill then cancel/expire left the filled part **unprotected** (status just became CANCELED).
3. `protective_ok` required exactly 2 legs, so any partial-fill top-up flipped it to False.
4. Kill switch: set the halt only after closes were attempted, never retried failed closes, never cancelled pending entries (an entry could fill after the close).
5. `TradingService` built `PortfolioRisk` without the configured window.
6. Correlation used one price per ~3-minute cycle (needs ~hours for 20 samples); now 15m closes already fetched (99 returns immediately).
7. `create_order` went through the 5-attempt retry → a timeout could double-submit. Now single attempt + client order id + lookup.
8. Retry loop retried `BadRequest`/`InvalidOrder` and **bans** (retrying during a ban extends it).
9. OKX volume fallback double-scaled (ranking distortion).
10. `reconcile_all` re-fetched every historic order every cycle (terminal orders now skipped).
11. Mode label/paper: V15 `--paper` was only a label — no gate ran.
12. `.env.example` shipped `SANDBOX=1` (READ_ONLY would silently use demo data) and `MIN_SCORE=0.72`.

## 4. Verification actually performed
- 99 tests pass, `compileall` clean, `python -m phoenix.live --help` OK, calibration tool reproduces the report.
- **Caveats you must know:**
  - The sandbox has no network, no `pytest` and no `ccxt`. Tests were run with a minimal local pytest stand-in (`raises`, `approx`, `monkeypatch`, `tmp_path`); please run real `pytest -q` once on your machine.
  - Everything touching ccxt (precision modes, `fetch_bids_asks`, OKX trigger params, `set_leverage`) is tested against fakes written from the documented behaviour — **not** against the real library or the real exchanges. First real contact is tomorrow's run.
  - `ensure_leverage`, OKX `stopLossPrice`/raw `conditional` fallback and hedge-mode params are the most likely places for a first-contact surprise; they are only exercised in `--live`.
  - OKX volume fix relies on the documented meaning of `info.volCcy24h` (base-coin units). `volume_samples` in the report lets you verify it in 10 seconds.

## 5. Known limitations / not done
- No websocket feeds (REST polling; mitigated by caching, caps, ban guard).
- Liquidation component still unavailable on both exchanges (weights are averaged over present components only).
- PAPER fills at the signal price with fee+slippage reserve, no queue/maker-fill modelling; marks once per cycle (wicks invisible).
- Live path does not journal to `trades.jsonl` (state files + exchange are authoritative).
- Strategy edge is unproven. 0.30 is a *measurable* threshold, not a validated one.

Note: `phoenix/execution.py` (`MakerExecutor`, local lifecycle helper from V15) is kept for compatibility but is not on the live path; the live requote logic is in `TradingService` because it must act on exchange state, not local timers.
