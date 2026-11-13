# NVIDIA review implementation status - V22.0.5

## Applied in this build

1. **Position sizing semantics:** canonical setting remains `PHOENIX_ENTRY_NOTIONAL_USD=50`; at 10x the target initial margin is approximately $5. The legacy `PHOENIX_ENTRY_MARGIN_USD` alias is retained only for compatibility and is interpreted as notional, never as $50 margin.
2. **Stop/liquidation risk:** the $20 per-position modeled loss remains a ceiling. A leverage-relative stop-distance cap is added: `max adverse move = liquidation_buffer_fraction / leverage`; default 0.70/10 = 7%. This is a heuristic and does not replace the exchange's actual liquidation price, maintenance tiers, or cross-margin risk calculation.
3. **Maker safety:** missing/invalid order books cause a pre-trade rejection. Final precision-rounded prices are checked again so they cannot cross the spread. Exchange post-only/GTX flags remain enabled.
4. **Margin accounting:** positions with missing exchange `initialMargin` are assigned a conservative notional/leverage estimate.
5. **Concurrency:** submit, reconcile-all, and kill-switch transitions are serialized per TradingService instance.
6. **Unlimited position count:** `max_open_positions=0` remains uncapped by count; equity, reserved margin, daily/weekly loss, drawdown, duplicate-underlying and correlation gates remain active.

## Not claimed as completed

- **LIVE indicator-based take-profit:** the V22.0.4 code does not have a verified per-open-position score feed and market-close reconciliation state machine for this mode. This build deliberately keeps the existing fixed protective TP rather than introducing an unverified live exit path. A separate implementation must score every open symbol, require positive net PnL plus a defined signed-score fade, submit reduce-only close, verify fill, and only then cancel the remaining stop.
- **Exchange-specific liquidation price validation:** CCXT adapter data and maintenance-tier data vary by venue and contract. The new stop-distance cap is only a conservative fallback; it must not be described as a liquidation guarantee.
- **Profitability:** passing tests validates software behavior, not strategy edge. Continue PAPER/walk-forward validation with fees, funding, spread and slippage before LIVE.

## Test result

`pytest -q`: **126 passed** (after adding regression tests for maker fail-closed behavior, post-precision spread validation, leverage-relative stops, and missing-margin fallback).
