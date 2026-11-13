# ACARBOT V22.6-FINAL build report

## Why the previous builds made signals but no profit (the diagnosis this build fixes)

### 1. The reward:risk ratio was inverted by the exit engine (the #1 killer)
V22.0.5 cut winners at **+$0.10** net (`tp_min_net_usd=0.10`) the moment the score faded, while
losers ran to the stop (V22.0.4 style ~-$3.9 at the 7% cap, or up to -$20 on the 24h TIME exit).
Payoff ratio ≈ **1:40**. No win rate makes that profitable: at 90% winners you still lose.

Measured on identical synthetic signals/fees (40 paper positions, `scripts/simulate_v22_6.py`):

| Rules | Realized | Avg win | Avg loss | Payoff | Expectancy/trade |
|---|---|---|---|---|---|
| V22.5 rules | **-53.15 USD** | 8.26 | -20.18 | 0.41 | -1.90 |
| V22.6 rules | **+61.45 USD** | 11.02 | -12.69 | 0.87 | +1.54 |

Difference **+114.60 USD** comes ONLY from the exit engine.

### 2. The user rules were mathematically contradictory (V22.0.5 build report flagged it, now fixed)
"-$20 stop" on a **$50 notional** position at 10x is a ~40% adverse price move. Isolated 10x
liquidation happens near ~10%: the stop could never fire; the real risk was the liquidation.
The self-consistent reading of the user's rules is **$50 MARGIN x 10x = $500 notional**:
-$20 = ~3.9% move, comfortably inside liquidation. V22.6 defaults to this (`entry_mode=margin`)
and keeps the legacy notional mode as `entry_mode=notional` with a leverage-relative stop cap
(`liquidation_buffer_fraction/leverage` = 7% at 10x) so the stop always fires before liquidation.

### 3. Signal quality: noise-heavy score, no overextension filter
* The score mixed real trend (0.55 weight) with microstructure noise (book imbalance 0.15,
  5-min OI delta 0.15, sparse liquidations 0.10). V22.6 keeps the weights (architecture unchanged)
  but signs the OI flow WITH price direction (OI up + price up = new longs; OI up + price down =
  new shorts; OI down = unwinding, halved) and multiplies the score by 0.70 when 15m and 1h/4h
  disagree, so countertrend chases need a much stronger reading.
* New RSI(14) 15m gate blocks entries into overextended moves (no LONG at RSI >= 78, no SHORT at
  RSI <= 22). Exits are never RSI-gated. All three upgrades are env-tunable and shadow-visible.

### 4. LIVE could never run the indicator take profit
V22.0.5 refused `--live` with `tp_mode=indicator` (no exchange-side TP). Worse: the reconciler
required BOTH protective legs (`len % 2 == 0`), so a stop-only protection - exactly what indicator
mode places - was marked FILLED_PROTECTION_FAILED and emergency-closed. V22.6:
* single stop-only protection is valid (`TradingService._protective_ok`);
* the runner scores every FILLED, protected LIVE position each cycle (budgeted) and
  * moves the exchange stop when breakeven/trailing arms (cancel + re-arm, fail-safe:
    validate -> cancel old -> send new; unprotected => emergency close);
  * closes via reduce-only market order when INDICATOR_TP fires, then cancels the protective legs;
  * closes 24h-old positions (TIME parity with PAPER);
  * `--live` is no longer blocked (opt-out: `PHOENIX_LIVE_INDICATOR_TP=0`).

### 5. Paper honesty
Funding is now accrued every 8h held in PAPER (`funding_at_open x notional x periods`, both sides
pay - conservative). Paper summary gained `trade_stats`: avg_win/avg_loss/win_rate/payoff_ratio/
expectancy/profit_factor, and every closed trade records `final_stop`, `breakeven_armed`,
`trail_armed`, `peak_net`.

## The V22.6 exit engine (the core fix)
The stop only ever TIGHTENS; the fixed -$20 floor is never widened.
| Event | Action (defaults) |
|---|---|
| net >= 0.5R ($10) | indicator TP may fire on score fade; stop moves to entry+costs (BREAKEVEN) |
| peak net >= 1.0R ($20) | trailing stop arms, locks peak_net - 0.5R, follows the peak |
| net <= -1R (-$20) | fixed dollar stop (real: ~3.9% at $500 notional) |
| 96 bars (24h) | TIME exit |

## Entry semantics
| Mode | Env | Notional | Stop reachability |
|---|---|---|---|
| `margin` (DEFAULT) | `PHOENIX_ENTRY_MARGIN_USD=50` x `PHOENIX_LEVERAGE=10` | $500 | -$20 = ~3.9%: REAL |
| `notional` | `PHOENIX_ENTRY_NOTIONAL_USD=50` | $50 | stop capped to 7% (~-$3.9); -$20 stays a ceiling |

Conflicting env entries fail loud (never silently resize).

## Verification performed in this build
* `python -m compileall -q phoenix tests tools` - OK.
* `pytest -q`: **159 passed** (V22.5 had 152; new rules/engine/LIVE-TP tests added, legacy
  assertions updated to the corrected rules).
* Offline end-to-end simulation of 40 paper positions through the real PaperBroker: every exit
  branch exercised (INDICATOR_TP, trailing STOP, breakeven STOP, dollar STOP); numbers above.
* LIVE exit engine covered by tests with a fake exchange (stop amendment + reduce-only TP close +
  HOLD path + single-leg protection reconciliation).

## Still true / not claimed
* Passing tests = software correctness, not strategy edge. Run PAPER (real market data) for at
  least a few days before even thinking about LIVE; then walk-forward.
* Paper fills are mark-based per cycle; intra-cycle wicks are invisible. Stop fills are modeled
  conservatively (worse of stop/mark), so real fills are usually BETTER than paper.
* Funding in LIVE is real and not modeled per-position until reconcile reads it from the exchange.
* Liquidation distances are heuristics, not exchange guarantees.
