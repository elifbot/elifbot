# $20 Stop-Loss Math

## The key point

The bot uses **$50 margin × 10x = $500 nominal notional** for each new tranche.
For a linear USDT-margined contract, the quantity is:

`qty = $500 / entry_price`

Therefore a $20 gross price PnL corresponds to:

`$20 / $500 = 4%`

adverse price movement, regardless of whether the symbol is BTC, DOGE, ETH, etc.

### Example

- BTC entry = $100,000 → quantity ≈ 0.005 BTC → $4,000 adverse move ≈ -$20 gross.
- DOGE entry = $0.20 → quantity = 2,500 DOGE → $0.008 adverse move = -$20 gross.

So the stop is **not** the same number of dollars or the same raw price distance. It is the same PnL budget because notional is fixed.

## Fees and slippage

The implementation reserves estimated round-trip fees and exit slippage before calculating the stop distance. This keeps the expected all-in loss close to the requested $20 rather than blindly setting a $20 gross stop.

Actual loss can still exceed the budget in a fast gap, liquidation event, partial fill, or exchange execution anomaly. A stop is a risk control, not a mathematical guarantee.

## Cross margin

Cross margin is used. There is **no artificial 20-position or 100-position limit** in the strategy. The real constraints are available account equity/margin, exchange limits, instrument minimums, daily/weekly kill switches, and execution safety.

The bot can therefore keep accepting independent $50 tranches while free margin and risk controls permit them.
