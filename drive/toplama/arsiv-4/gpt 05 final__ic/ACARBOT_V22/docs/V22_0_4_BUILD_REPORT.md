# ACARBOT V22.0.4 Build Report

## Implemented
- `PHOENIX_MAX_LOSS_USD` is now the per-position hard-loss stop budget.
- ATR no longer tightens the protective stop.
- The stop is recalculated after final exchange quantity precision/rounding.
- Maker-price changes recalculate the stop from the final entry and quantity.
- ATR-based take-profit distance is kept independent from the per-position dollar stop.
- The same calculated stop is used by the paper close manager and the live exchange protective stop order path.
- Fixed open-position count remains uncapped at `0`; 50 USD notional and 10x leverage defaults remain.

## Verification
- Full pytest suite: **122 passed**.
- No live exchange order was sent during tests.

## Important risk limitation
The configured 20 USD amount is a modeled per-position loss budget, not a guaranteed maximum realized loss. Price gaps, stop-market slippage beyond the reserve, funding, fees, exchange outages, and liquidation mechanics can cause a larger loss. Exchange-specific liquidation price/margin calculations are not universally modeled by this patch. Do not assume a 20 USD stop can prevent liquidation in every margin mode or market condition.
\n\nSuperseded by V22.0.5; see NVIDIA_REVIEW_STATUS.md for applied hardening and intentionally pending LIVE indicator TP.\n