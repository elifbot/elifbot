# ACARBOT V22.0.6 — Build & Validation Report

## Base
`ACARBOT_V22_0_5_NVIDIA_HARDENED.zip` from the user's Library. This is an earlier V22.0.5 hardened package, not the unprovided V22.6 ZIP.

## Applied rules
- Target entry notional: **50 USD** per position. This is exposure, not margin.
- Leverage: **10x** default. Approximate initial margin: 5 USD per 50 USD notional, excluding fees and venue-specific requirements.
- Margin mode: **CROSS mandatory**. Isolated configuration is rejected; OKX `tdMode` is fixed to cross.
- Position count: `PHOENIX_MAX_OPEN_POSITIONS=0` (no fixed count cap). Equity/available collateral, daily/weekly loss, drawdown, correlation, exchange minimums and other safety checks still govern entries.
- Maker-first execution retained.

## Safety changes
- Removed the legacy `PHOENIX_ENTRY_MARGIN_USD` fallback. A margin-named environment variable can no longer be misread as a notional setting.
- Before an entry, the exchange must accept/confirm cross margin and requested leverage. If setup fails, the order is rejected before submission. Binance's documented “No need to change margin type” response is treated as already configured; other failures block entry.
- The existing 20 USD modeled per-position loss budget remains, but the stop-distance heuristic also caps adverse distance at 70% of 1/leverage (7% at 10x). On 50 USD notional this usually implies a modeled stop loss around 3.5 USD before costs, not 20 USD. This is not an exchange liquidation guarantee, especially in cross mode.

## Validation
- Baseline package before changes: **126 tests passed**.
- Updated package after changes: **128 tests passed**.
- `compileall` is also run for source syntax validation.

## Not established
- No exchange testnet order was sent in this build process.
- No cross-margin liquidation price was independently calculated from a live venue account.
- No profitability or live-trading safety claim is made.
- The user's four existing PAPER test processes must remain untouched; this package is for a separate next test run.

## Recommended next test
Run READ_ONLY, then PAPER in a separate working directory and verify report entries show 50 USD notional, 10x leverage, no numeric position-count rejection, and rejections only for actual collateral/risk/exchange constraints. Before any LIVE use, validate account mode and liquidation behavior on the selected exchange's demo/test environment.
