# ACARBOT V22.0.5 build report

## Rules implemented (user's immutable rules)
| Rule | Where | Test |
|---|---|---|
| 1000 USD bankroll | `Config.reference_equity`, PaperBroker equity | `test_defaults_are_1000_equity_...` |
| 50 USD NOTIONAL per position | `Config.entry_notional_usd=50` | `test_signal_notional_is_50_and_margin_is_5`, `test_paper_broker_never_opens_a_position_larger_than_50_notional` |
| 10x leverage, ~5 USD margin | `Config.leverage`, `entry_margin_usd` (derived) | same |
| -20 USD modeled stop per position | `RiskManager.stop_price` | `test_modeled_net_loss_at_stop_is_20_usd_including_costs`, `test_contract_size_does_not_change_the_dollar_budget` |
| No position-count cap | `max_open_positions=0`; only margin cap binds | `test_no_position_cap_well_past_the_old_20_limit`, `test_only_collateral_stops_new_positions` |
| ATR never narrows stop | `atr_stop_multiplier=0` | `test_atr_default_off_and_does_not_move_stop` |
| LONG/SHORT symmetric | strategy + stop | `test_long_and_short_get_mirrored_stops` |
| Indicator take profit | `PositionManager.indicator_exit` | `test_indicator_take_profit_fires_at_50_notional_scale` |
| No LIVE by accident | `LiveConfig` default READ_ONLY; `--live` + `PHOENIX_CONFIRM_LIVE=YES` | `test_live_is_off_by_default_...` |

## Which copy was used
`claude_bot.zip` (22.0.4) is the base. `gpt_bot.zip` (22.0.3) is older: ATR default 2.0 and `atr_stop_multiplier > 0` required, no indicator TP, no `package_release.py`. Its only advantage was `entry_notional_usd=50` as a plain field, which is now in the base.

## KNOWN CONTRADICTION IN THE RULES (needs the owner's decision)
$20 stop on $50 notional = ~40% price move. With 10x isolated margin, liquidation is near a ~10% adverse move, so the position would be liquidated (loss ~ margin, ~$5) long before the -$20 stop. The stop is modeled correctly, but it is not reachable in isolated mode. Alternatives:
- keep as is (max realistic loss ~ $5/position in isolated mode; cross margin behaves differently and is not modeled);
- `PHOENIX_ENTRY_NOTIONAL_USD=500` (4% stop, inside liquidation);
- reduce `PHOENIX_MAX_LOSS_USD` to <= ~$4 for $50 notional.

## Verified (offline, this environment)
- `compileall` OK.
- 152 tests pass, run with a small pytest stand-in (`raises`, `approx`, `tmp_path`, `monkeypatch`, `parametrize`) because pytest and ccxt could not be installed offline. Run `pytest -q` yourself to confirm with real pytest.

## NOT verified
- Any real exchange behavior: maker (post-only) fills, spread-of-one-tick behavior, OKX contract sizes, minimum notionals for $50 orders (many contracts may reject $50 as below minimum -> `below_min_amount`; auto-bump is capped at 1.0x so no silent upsizing).
- LIVE: the indicator take profit does not exist on the exchange side, so `--live` refuses to start with `tp_mode=indicator`. LIVE stays blocked until that is built and tested.
- Funding costs on open positions.
- Paper results are modeled, mark-based per cycle (wicks between cycles are invisible).
- Questions 5, 6, 11 of the analysis (why 45 GPT positions stayed open; the large Claude realized loss; LONG vs SHORT results) need the original test report/journal files, which were not in the zips.
