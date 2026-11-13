# Operations

## Rollout order (do not skip steps)
1. `pytest -q` and `compileall` green on the target machine (needs `ccxt` installed).
2. 10 min READ_ONLY on production data. Check `rank_rejections`, `exchange_scanned` (both exchanges > 0), `volume_samples` (compare with the exchange UI), `exchange_status` (no ban).
3. 10 min PAPER. Read the funnel (`tools/read_report.py`). Fix whatever the first non-score blocker is.
4. Several hours/days of PAPER with `--paper-resume`. Compare paper P&L with and without `PHOENIX_REQUIRE_ALIGNMENT=1`.
5. Offline: `phoenix.backtest` / `walkforward` with real fees and slippage on independent data.
6. Testnet/demo order-flow test (small size, see below).
7. Only then, tiny real capital.

## Testnet / demo order-flow test (item 6 of the review list)
```bash
export PHOENIX_BINANCE_SANDBOX=1 PHOENIX_OKX_SANDBOX=1   # use testnet/demo API keys
export PHOENIX_ENTRY_MARGIN_USD=10 PHOENIX_CONFIRM_LIVE=YES
python -m phoenix.live --live --duration 600 --poll 15 --detail-per-cycle 20 --max-cycle-sec 240 --report reports/testnet.json
```
Collect `live_rejections` and the log. Verify on the exchange UI: post-only entry rests on the passive side, requote after 45 s, SL/TP legs exist and are reduce-only, kill switch (lower `PHOENIX_DAILY_LOSS_LIMIT_USD` to force it).
Sandbox prices/liquidity are demo quality: do not tune the strategy on them.

## Kill switch
Persisted in `state.<exchange>.json` (`risk.halted_reason`). New entries are refused while it is set, even after a restart. Clear manually after you have looked at the account: `python -m phoenix.live --clear-halt`.

## Bans (Binance -1003 / HTTP 418)
The bot pauses that exchange until the ban expires and says so in `exchange_status`. Keep `--detail-per-cycle` bounded (default 150 + 25 rotating) and do not run several instances from one IP. `0` (= scan everything) is what triggered the WAF ban in the V15 test.

## Files
`paper_state.json`, `paper_trades.jsonl` (paper), `state.<exchange>.json` (live), `reports/*.json`.
