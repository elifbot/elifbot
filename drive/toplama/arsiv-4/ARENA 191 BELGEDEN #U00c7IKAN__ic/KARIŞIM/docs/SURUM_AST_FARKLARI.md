# Python sürümleri — yapısal karşılaştırma

AST (satır konumu hariç) karşılaştırmasıdır. Aynı yapı aynı runtime davranışı garantisi değildir; değişiklikleri semantik olarak doğru/yanlış veya kronolojik üstünlük olarak yorumlamaz. Sınıfın ASTsi yöntemleri içerdiğinden sınıf ve yöntem değişiklikleri iç içe sayılır.

## file_31_executor.py ↔ file_79_executor.py
- Aynı AST: 9 · değişmiş: 12 · ikinci dosyada yeni: 20 · ikinci dosyada yok: 0

### Değişmiş
- `Executor` · file_31_executor.py:L14-L726 → file_79_executor.py:L27-L1698
- `Executor.__init__` · file_31_executor.py:L15-L69 → file_79_executor.py:L28-L140
- `Executor._add_layer` · file_31_executor.py:L519-L618 → file_79_executor.py:L1258-L1405
- `Executor._calc_qty` · file_31_executor.py:L377-L398 → file_79_executor.py:L938-L971
- `Executor._close` · file_31_executor.py:L620-L706 → file_79_executor.py:L1407-L1419
- `Executor._open` · file_31_executor.py:L400-L517 → file_79_executor.py:L973-L1256
- `Executor.close_all_positions` · file_31_executor.py:L708-L726 → file_79_executor.py:L1670-L1698
- `Executor.execute_pair_rescue` · file_31_executor.py:L255-L280 → file_79_executor.py:L722-L730
- `Executor.on_price_tick` · file_31_executor.py:L191-L253 → file_79_executor.py:L587-L720
- `Executor.on_signal` · file_31_executor.py:L283-L374 → file_79_executor.py:L760-L935
- `Executor.reconcile_with_exchange` · file_31_executor.py:L92-L131 → file_79_executor.py:L212-L260
- `Executor.restore_state` · file_31_executor.py:L71-L90 → file_79_executor.py:L142-L210

### İkinci dosyada yeni
- `Executor._apply_supertrend_trailing` · — → file_79_executor.py:L397-L406
- `Executor._close_lock_for` · — → file_79_executor.py:L354-L359
- `Executor._close_unlocked` · — → file_79_executor.py:L1421-L1668
- `Executor._execute_pair_rescue_unlocked` · — → file_79_executor.py:L732-L757
- `Executor._is_risk_free_position` · — → file_79_executor.py:L504-L512
- `Executor._make_position_plan` · — → file_79_executor.py:L283-L311
- `Executor._notify_position_observers` · — → file_79_executor.py:L366-L377
- `Executor._position_hold_sec` · — → file_79_executor.py:L498-L501
- `Executor._prepare_entry_plan` · — → file_79_executor.py:L313-L338
- `Executor._save_funding_clock` · — → file_79_executor.py:L453-L458
- `Executor._save_position_meta` · — → file_79_executor.py:L347-L352
- `Executor._save_trade_plans` · — → file_79_executor.py:L340-L345
- `Executor._try_opportunity_swap` · — → file_79_executor.py:L514-L542
- `Executor.add_position_observer` · — → file_79_executor.py:L361-L364
- `Executor.apply_funding` · — → file_79_executor.py:L460-L490
- `Executor.get_trade_plan` · — → file_79_executor.py:L379-L381
- `Executor.maybe_orderflow_exit` · — → file_79_executor.py:L544-L584
- `Executor.runner_exit_reason` · — → file_79_executor.py:L492-L496
- `Executor.set_market_structure` · — → file_79_executor.py:L274-L281
- `Executor.set_supertrend` · — → file_79_executor.py:L383-L395

### İkinci dosyada yok
- Yok.

### Aynı AST
- `Executor._all_positions_in_profit` · file_31_executor.py:L174-L181 → file_79_executor.py:L437-L444
- `Executor._say` · file_31_executor.py:L133-L140 → file_79_executor.py:L262-L269
- `Executor.get_dynamic_leverage` · file_31_executor.py:L156-L169 → file_79_executor.py:L419-L432
- `Executor.get_mtf_trend` · file_31_executor.py:L149-L150 → file_79_executor.py:L412-L413
- `Executor.in_cooldown` · file_31_executor.py:L171-L172 → file_79_executor.py:L434-L435
- `Executor.set_atr` · file_31_executor.py:L142-L143 → file_79_executor.py:L271-L272
- `Executor.set_market_mood` · file_31_executor.py:L152-L154 → file_79_executor.py:L415-L417
- `Executor.set_mtf_trend` · file_31_executor.py:L145-L147 → file_79_executor.py:L408-L410
- `Executor.total_unrealized_usdt` · file_31_executor.py:L183-L188 → file_79_executor.py:L446-L451

## file_79_executor.py ↔ file_13_executor.py
- Aynı AST: 22 · değişmiş: 19 · ikinci dosyada yeni: 5 · ikinci dosyada yok: 0

### Değişmiş
- `Executor` · file_79_executor.py:L27-L1698 → file_13_executor.py:L30-L2217
- `Executor.__init__` · file_79_executor.py:L28-L140 → file_13_executor.py:L31-L164
- `Executor._add_layer` · file_79_executor.py:L1258-L1405 → file_13_executor.py:L1669-L1844
- `Executor._all_positions_in_profit` · file_79_executor.py:L437-L444 → file_13_executor.py:L604-L613
- `Executor._close` · file_79_executor.py:L1407-L1419 → file_13_executor.py:L1846-L1867
- `Executor._close_unlocked` · file_79_executor.py:L1421-L1668 → file_13_executor.py:L1869-L2171
- `Executor._open` · file_79_executor.py:L973-L1256 → file_13_executor.py:L1273-L1667
- `Executor._prepare_entry_plan` · file_79_executor.py:L313-L338 → file_13_executor.py:L464-L497
- `Executor._save_funding_clock` · file_79_executor.py:L453-L458 → file_13_executor.py:L637-L645
- `Executor._save_position_meta` · file_79_executor.py:L347-L352 → file_13_executor.py:L509-L517
- `Executor._save_trade_plans` · file_79_executor.py:L340-L345 → file_13_executor.py:L499-L507
- `Executor._try_opportunity_swap` · file_79_executor.py:L514-L542 → file_13_executor.py:L766-L796
- `Executor.apply_funding` · file_79_executor.py:L460-L490 → file_13_executor.py:L647-L742
- `Executor.close_all_positions` · file_79_executor.py:L1670-L1698 → file_13_executor.py:L2186-L2217
- `Executor.get_trade_plan` · file_79_executor.py:L379-L381 → file_13_executor.py:L544-L548
- `Executor.on_price_tick` · file_79_executor.py:L587-L720 → file_13_executor.py:L841-L1015
- `Executor.on_signal` · file_79_executor.py:L760-L935 → file_13_executor.py:L1055-L1235
- `Executor.restore_state` · file_79_executor.py:L142-L210 → file_13_executor.py:L213-L361
- `Executor.total_unrealized_usdt` · file_79_executor.py:L446-L451 → file_13_executor.py:L628-L635

### İkinci dosyada yeni
- `Executor._fresh_local_quote` · — → file_13_executor.py:L615-L626
- `Executor._is_isolated_external_broker_fixture` · — → file_13_executor.py:L166-L176
- `Executor.close_position` · — → file_13_executor.py:L2173-L2184
- `Executor.reconcile_and_unlock_paper_state` · — → file_13_executor.py:L178-L206
- `Executor.release_writer_ownership` · — → file_13_executor.py:L208-L211

### İkinci dosyada yok
- Yok.

### Aynı AST
- `Executor._apply_supertrend_trailing` · file_79_executor.py:L397-L406 → file_13_executor.py:L564-L573
- `Executor._calc_qty` · file_79_executor.py:L938-L971 → file_13_executor.py:L1238-L1271
- `Executor._close_lock_for` · file_79_executor.py:L354-L359 → file_13_executor.py:L519-L524
- `Executor._execute_pair_rescue_unlocked` · file_79_executor.py:L732-L757 → file_13_executor.py:L1027-L1052
- `Executor._is_risk_free_position` · file_79_executor.py:L504-L512 → file_13_executor.py:L756-L764
- `Executor._make_position_plan` · file_79_executor.py:L283-L311 → file_13_executor.py:L434-L462
- `Executor._notify_position_observers` · file_79_executor.py:L366-L377 → file_13_executor.py:L531-L542
- `Executor._position_hold_sec` · file_79_executor.py:L498-L501 → file_13_executor.py:L750-L753
- `Executor._say` · file_79_executor.py:L262-L269 → file_13_executor.py:L413-L420
- `Executor.add_position_observer` · file_79_executor.py:L361-L364 → file_13_executor.py:L526-L529
- `Executor.execute_pair_rescue` · file_79_executor.py:L722-L730 → file_13_executor.py:L1017-L1025
- `Executor.get_dynamic_leverage` · file_79_executor.py:L419-L432 → file_13_executor.py:L586-L599
- `Executor.get_mtf_trend` · file_79_executor.py:L412-L413 → file_13_executor.py:L579-L580
- `Executor.in_cooldown` · file_79_executor.py:L434-L435 → file_13_executor.py:L601-L602
- `Executor.maybe_orderflow_exit` · file_79_executor.py:L544-L584 → file_13_executor.py:L798-L838
- `Executor.reconcile_with_exchange` · file_79_executor.py:L212-L260 → file_13_executor.py:L363-L411
- `Executor.runner_exit_reason` · file_79_executor.py:L492-L496 → file_13_executor.py:L744-L748
- `Executor.set_atr` · file_79_executor.py:L271-L272 → file_13_executor.py:L422-L423
- `Executor.set_market_mood` · file_79_executor.py:L415-L417 → file_13_executor.py:L582-L584
- `Executor.set_market_structure` · file_79_executor.py:L274-L281 → file_13_executor.py:L425-L432
- `Executor.set_mtf_trend` · file_79_executor.py:L408-L410 → file_13_executor.py:L575-L577
- `Executor.set_supertrend` · file_79_executor.py:L383-L395 → file_13_executor.py:L550-L562

## file_40_risk.py ↔ file_94_risk.py
- Aynı AST: 2 · değişmiş: 22 · ikinci dosyada yeni: 10 · ikinci dosyada yok: 1

### Değişmiş
- `Position` · file_40_risk.py:L26-L79 → file_94_risk.py:L37-L93
- `Position.__post_init__` · file_40_risk.py:L40-L49 → file_94_risk.py:L63-L69
- `Position.add_layer` · file_40_risk.py:L51-L79 → file_94_risk.py:L71-L93
- `RiskManager` · file_40_risk.py:L82-L516 → file_94_risk.py:L96-L725
- `RiskManager.__init__` · file_40_risk.py:L83-L149 → file_94_risk.py:L97-L177
- `RiskManager._reset_day_if_needed` · file_40_risk.py:L151-L154 → file_94_risk.py:L210-L214
- `RiskManager._reset_week_if_needed` · file_40_risk.py:L431-L434 → file_94_risk.py:L216-L220
- `RiskManager.can_add_to_winner` · file_40_risk.py:L334-L353 → file_94_risk.py:L521-L541
- `RiskManager.can_open` · file_40_risk.py:L309-L332 → file_94_risk.py:L481-L519
- `RiskManager.compute_dynamic_leverage` · file_40_risk.py:L224-L267 → file_94_risk.py:L365-L386
- `RiskManager.effective_stop_pct` · file_40_risk.py:L161-L170 → file_94_risk.py:L250-L255
- `RiskManager.equity_pnl_pct` · file_40_risk.py:L180-L184 → file_94_risk.py:L433-L437
- `RiskManager.find_pair_rescue` · file_40_risk.py:L355-L429 → file_94_risk.py:L543-L587
- `RiskManager.initial_stop` · file_40_risk.py:L172-L177 → file_94_risk.py:L257-L265
- `RiskManager.leveraged_entry_size` · file_40_risk.py:L269-L291 → file_94_risk.py:L396-L415
- `RiskManager.margin_cap_ok` · file_40_risk.py:L186-L192 → file_94_risk.py:L439-L451
- `RiskManager.pnl_usdt` · file_40_risk.py:L303-L307 → file_94_risk.py:L427-L430
- `RiskManager.position_size` · file_40_risk.py:L194-L200 → file_94_risk.py:L388-L394
- `RiskManager.profit_pct` · file_40_risk.py:L293-L297 → file_94_risk.py:L417-L422
- `RiskManager.register_close` · file_40_risk.py:L441-L445 → file_94_risk.py:L589-L597
- `RiskManager.roe_pct` · file_40_risk.py:L299-L301 → file_94_risk.py:L424-L425
- `RiskManager.update` · file_40_risk.py:L447-L516 → file_94_risk.py:L616-L725

### İkinci dosyada yeni
- `RiskManager._restore_state` · — → file_94_risk.py:L179-L195
- `RiskManager._sync_state` · — → file_94_risk.py:L197-L208
- `RiskManager.atr_structure_plan` · — → file_94_risk.py:L283-L362
- `RiskManager.close_stop_reason` · — → file_94_risk.py:L273-L281
- `RiskManager.cross_pool_ok` · — → file_94_risk.py:L453-L479
- `RiskManager.liquidation_stop_pct` · — → file_94_risk.py:L232-L236
- `RiskManager.margin_stop_pct` · — → file_94_risk.py:L238-L248
- `RiskManager.net_breakeven_price` · — → file_94_risk.py:L599-L614
- `RiskManager.stop_reason` · — → file_94_risk.py:L267-L271
- `position_limits_for_mode` · — → file_94_risk.py:L18-L33

### İkinci dosyada yok
- `RiskManager.check_slippage` · file_40_risk.py:L203-L221 → —

### Aynı AST
- `RiskManager.daily_pnl_pct` · file_40_risk.py:L157-L159 → file_94_risk.py:L223-L225
- `RiskManager.weekly_pnl_pct` · file_40_risk.py:L437-L439 → file_94_risk.py:L228-L230

## file_94_risk.py ↔ file_145_risk.py
- Aynı AST: 30 · değişmiş: 4 · ikinci dosyada yeni: 0 · ikinci dosyada yok: 0

### Değişmiş
- `RiskManager` · file_94_risk.py:L96-L725 → file_145_risk.py:L96-L776
- `RiskManager.__init__` · file_94_risk.py:L97-L177 → file_145_risk.py:L97-L181
- `RiskManager.find_pair_rescue` · file_94_risk.py:L543-L587 → file_145_risk.py:L547-L609
- `RiskManager.update` · file_94_risk.py:L616-L725 → file_145_risk.py:L638-L776

### İkinci dosyada yeni
- Yok.

### İkinci dosyada yok
- Yok.

### Aynı AST
- `Position` · file_94_risk.py:L37-L93 → file_145_risk.py:L37-L93
- `Position.__post_init__` · file_94_risk.py:L63-L69 → file_145_risk.py:L63-L69
- `Position.add_layer` · file_94_risk.py:L71-L93 → file_145_risk.py:L71-L93
- `RiskManager._reset_day_if_needed` · file_94_risk.py:L210-L214 → file_145_risk.py:L214-L218
- `RiskManager._reset_week_if_needed` · file_94_risk.py:L216-L220 → file_145_risk.py:L220-L224
- `RiskManager._restore_state` · file_94_risk.py:L179-L195 → file_145_risk.py:L183-L199
- `RiskManager._sync_state` · file_94_risk.py:L197-L208 → file_145_risk.py:L201-L212
- `RiskManager.atr_structure_plan` · file_94_risk.py:L283-L362 → file_145_risk.py:L287-L366
- `RiskManager.can_add_to_winner` · file_94_risk.py:L521-L541 → file_145_risk.py:L525-L545
- `RiskManager.can_open` · file_94_risk.py:L481-L519 → file_145_risk.py:L485-L523
- `RiskManager.close_stop_reason` · file_94_risk.py:L273-L281 → file_145_risk.py:L277-L285
- `RiskManager.compute_dynamic_leverage` · file_94_risk.py:L365-L386 → file_145_risk.py:L369-L390
- `RiskManager.cross_pool_ok` · file_94_risk.py:L453-L479 → file_145_risk.py:L457-L483
- `RiskManager.daily_pnl_pct` · file_94_risk.py:L223-L225 → file_145_risk.py:L227-L229
- `RiskManager.effective_stop_pct` · file_94_risk.py:L250-L255 → file_145_risk.py:L254-L259
- `RiskManager.equity_pnl_pct` · file_94_risk.py:L433-L437 → file_145_risk.py:L437-L441
- `RiskManager.initial_stop` · file_94_risk.py:L257-L265 → file_145_risk.py:L261-L269
- `RiskManager.leveraged_entry_size` · file_94_risk.py:L396-L415 → file_145_risk.py:L400-L419
- `RiskManager.liquidation_stop_pct` · file_94_risk.py:L232-L236 → file_145_risk.py:L236-L240
- `RiskManager.margin_cap_ok` · file_94_risk.py:L439-L451 → file_145_risk.py:L443-L455
- `RiskManager.margin_stop_pct` · file_94_risk.py:L238-L248 → file_145_risk.py:L242-L252
- `RiskManager.net_breakeven_price` · file_94_risk.py:L599-L614 → file_145_risk.py:L621-L636
- `RiskManager.pnl_usdt` · file_94_risk.py:L427-L430 → file_145_risk.py:L431-L434
- `RiskManager.position_size` · file_94_risk.py:L388-L394 → file_145_risk.py:L392-L398
- `RiskManager.profit_pct` · file_94_risk.py:L417-L422 → file_145_risk.py:L421-L426
- `RiskManager.register_close` · file_94_risk.py:L589-L597 → file_145_risk.py:L611-L619
- `RiskManager.roe_pct` · file_94_risk.py:L424-L425 → file_145_risk.py:L428-L429
- `RiskManager.stop_reason` · file_94_risk.py:L267-L271 → file_145_risk.py:L271-L275
- `RiskManager.weekly_pnl_pct` · file_94_risk.py:L228-L230 → file_145_risk.py:L232-L234
- `position_limits_for_mode` · file_94_risk.py:L18-L33 → file_145_risk.py:L18-L33

## file_44_state_store.py ↔ file_100_state_store.py
- Aynı AST: 0 · değişmiş: 20 · ikinci dosyada yeni: 2 · ikinci dosyada yok: 2

### Değişmiş
- `StateStore` · file_44_state_store.py:L29-L508 → file_100_state_store.py:L16-L554
- `StateStore.__init__` · file_44_state_store.py:L30-L47 → file_100_state_store.py:L19-L39
- `StateStore._conn` · file_44_state_store.py:L49-L58 → file_100_state_store.py:L42-L56
- `StateStore._init_db` · file_44_state_store.py:L60-L135 → file_100_state_store.py:L58-L178
- `StateStore.delete_position` · file_44_state_store.py:L288-L290 → file_100_state_store.py:L310-L312
- `StateStore.get_arb_history` · file_44_state_store.py:L446-L451 → file_100_state_store.py:L495-L500
- `StateStore.get_equity_curve` · file_44_state_store.py:L403-L409 → file_100_state_store.py:L465-L470
- `StateStore.get_meta` · file_44_state_store.py:L468-L478 → file_100_state_store.py:L517-L525
- `StateStore.get_trades` · file_44_state_store.py:L374-L379 → file_100_state_store.py:L425-L430
- `StateStore.get_wal_status` · file_44_state_store.py:L137-L149 → file_100_state_store.py:L180-L205
- `StateStore.load_positions` · file_44_state_store.py:L296-L318 → file_100_state_store.py:L314-L335
- `StateStore.maintenance_loop` · file_44_state_store.py:L232-L244 → file_100_state_store.py:L258-L264
- `StateStore.pop_commands` · file_44_state_store.py:L488-L508 → file_100_state_store.py:L534-L554
- `StateStore.push_command` · file_44_state_store.py:L481-L486 → file_100_state_store.py:L527-L532
- `StateStore.record_equity` · file_44_state_store.py:L381-L401 → file_100_state_store.py:L444-L463
- `StateStore.record_trade` · file_44_state_store.py:L334-L372 → file_100_state_store.py:L350-L423
- `StateStore.run_garbage_collector` · file_44_state_store.py:L152-L230 → file_100_state_store.py:L207-L256
- `StateStore.save_position` · file_44_state_store.py:L247-L286 → file_100_state_store.py:L267-L308
- `StateStore.set_meta` · file_44_state_store.py:L454-L466 → file_100_state_store.py:L503-L515
- `StateStore.startup_recovery_report` · file_44_state_store.py:L320-L331 → file_100_state_store.py:L337-L347

### İkinci dosyada yeni
- `StateStore.get_trades_since` · — → file_100_state_store.py:L432-L442
- `StateStore.record_arbitrage` · — → file_100_state_store.py:L472-L493

### İkinci dosyada yok
- `StateStore.clear_all_positions` · file_44_state_store.py:L292-L294 → —
- `StateStore.record_arb` · file_44_state_store.py:L412-L444 → —

### Aynı AST
- Yok.

## file_100_state_store.py ↔ file_146_state_store.py
- Aynı AST: 18 · değişmiş: 4 · ikinci dosyada yeni: 20 · ikinci dosyada yok: 0

### Değişmiş
- `StateStore` · file_100_state_store.py:L16-L554 → file_146_state_store.py:L28-L1287
- `StateStore.__init__` · file_100_state_store.py:L19-L39 → file_146_state_store.py:L31-L52
- `StateStore._conn` · file_100_state_store.py:L42-L56 → file_146_state_store.py:L55-L69
- `StateStore._init_db` · file_100_state_store.py:L58-L178 → file_146_state_store.py:L71-L223

### İkinci dosyada yeni
- `StateStore._is_pid_alive` · — → file_146_state_store.py:L339-L352
- `StateStore.acquire_writer_lease` · — → file_146_state_store.py:L354-L392
- `StateStore.cancel_unfilled_paper_open` · — → file_146_state_store.py:L751-L775
- `StateStore.commit_external_close` · — → file_146_state_store.py:L546-L637
- `StateStore.commit_paper_close` · — → file_146_state_store.py:L801-L857
- `StateStore.commit_paper_funding` · — → file_146_state_store.py:L882-L911
- `StateStore.commit_paper_layer` · — → file_146_state_store.py:L934-L969
- `StateStore.commit_paper_open` · — → file_146_state_store.py:L718-L749
- `StateStore.has_journal_intents` · — → file_146_state_store.py:L312-L320
- `StateStore.is_uninitialized_position_only_fixture` · — → file_146_state_store.py:L322-L336
- `StateStore.paper_ledger_health_snapshot` · — → file_146_state_store.py:L409-L412
- `StateStore.paper_requires_recovery` · — → file_146_state_store.py:L639-L654
- `StateStore.prepare_paper_close` · — → file_146_state_store.py:L777-L799
- `StateStore.prepare_paper_funding` · — → file_146_state_store.py:L859-L880
- `StateStore.prepare_paper_layer` · — → file_146_state_store.py:L913-L932
- `StateStore.prepare_paper_open` · — → file_146_state_store.py:L656-L716
- `StateStore.release_writer_lease` · — → file_146_state_store.py:L394-L407
- `StateStore.update_paper_risk_if_unchanged` · — → file_146_state_store.py:L971-L998
- `StateStore.verify_paper_ledger_integrity` · — → file_146_state_store.py:L414-L544
- `paper_position_snapshot` · — → file_146_state_store.py:L18-L25

### İkinci dosyada yok
- Yok.

### Aynı AST
- `StateStore.delete_position` · file_100_state_store.py:L310-L312 → file_146_state_store.py:L1043-L1045
- `StateStore.get_arb_history` · file_100_state_store.py:L495-L500 → file_146_state_store.py:L1228-L1233
- `StateStore.get_equity_curve` · file_100_state_store.py:L465-L470 → file_146_state_store.py:L1198-L1203
- `StateStore.get_meta` · file_100_state_store.py:L517-L525 → file_146_state_store.py:L1250-L1258
- `StateStore.get_trades` · file_100_state_store.py:L425-L430 → file_146_state_store.py:L1158-L1163
- `StateStore.get_trades_since` · file_100_state_store.py:L432-L442 → file_146_state_store.py:L1165-L1175
- `StateStore.get_wal_status` · file_100_state_store.py:L180-L205 → file_146_state_store.py:L225-L250
- `StateStore.load_positions` · file_100_state_store.py:L314-L335 → file_146_state_store.py:L1047-L1068
- `StateStore.maintenance_loop` · file_100_state_store.py:L258-L264 → file_146_state_store.py:L303-L309
- `StateStore.pop_commands` · file_100_state_store.py:L534-L554 → file_146_state_store.py:L1267-L1287
- `StateStore.push_command` · file_100_state_store.py:L527-L532 → file_146_state_store.py:L1260-L1265
- `StateStore.record_arbitrage` · file_100_state_store.py:L472-L493 → file_146_state_store.py:L1205-L1226
- `StateStore.record_equity` · file_100_state_store.py:L444-L463 → file_146_state_store.py:L1177-L1196
- `StateStore.record_trade` · file_100_state_store.py:L350-L423 → file_146_state_store.py:L1083-L1156
- `StateStore.run_garbage_collector` · file_100_state_store.py:L207-L256 → file_146_state_store.py:L252-L301
- `StateStore.save_position` · file_100_state_store.py:L267-L308 → file_146_state_store.py:L1000-L1041
- `StateStore.set_meta` · file_100_state_store.py:L503-L515 → file_146_state_store.py:L1236-L1248
- `StateStore.startup_recovery_report` · file_100_state_store.py:L337-L347 → file_146_state_store.py:L1070-L1080

## file_33_indicators.py ↔ file_83_indicators.py
- Aynı AST: 15 · değişmiş: 4 · ikinci dosyada yeni: 5 · ikinci dosyada yok: 0

### Değişmiş
- `Indicators` · file_33_indicators.py:L16-L125 → file_83_indicators.py:L17-L288
- `Indicators.mfi` · file_33_indicators.py:L100-L109 → file_83_indicators.py:L105-L119
- `Indicators.rsi` · file_33_indicators.py:L28-L35 → file_83_indicators.py:L29-L40
- `indicator_score` · file_33_indicators.py:L138-L271 → file_83_indicators.py:L301-L649

### İkinci dosyada yeni
- `Indicators.anchored_vwap` · — → file_83_indicators.py:L233-L240
- `Indicators.keltner` · — → file_83_indicators.py:L187-L197
- `Indicators.session_vwap` · — → file_83_indicators.py:L200-L230
- `Indicators.supertrend` · — → file_83_indicators.py:L138-L184
- `Indicators.volume_profile` · — → file_83_indicators.py:L243-L288

### İkinci dosyada yok
- Yok.

### Aynı AST
- `Indicators.adx` · file_33_indicators.py:L75-L90 → file_83_indicators.py:L80-L95
- `Indicators.atr` · file_33_indicators.py:L44-L50 → file_83_indicators.py:L49-L55
- `Indicators.bollinger` · file_33_indicators.py:L53-L56 → file_83_indicators.py:L58-L61
- `Indicators.cci` · file_33_indicators.py:L93-L97 → file_83_indicators.py:L98-L102
- `Indicators.donchian` · file_33_indicators.py:L123-L125 → file_83_indicators.py:L133-L135
- `Indicators.ema` · file_33_indicators.py:L20-L21 → file_83_indicators.py:L21-L22
- `Indicators.macd` · file_33_indicators.py:L38-L41 → file_83_indicators.py:L43-L46
- `Indicators.obv` · file_33_indicators.py:L112-L114 → file_83_indicators.py:L122-L124
- `Indicators.sma` · file_33_indicators.py:L24-L25 → file_83_indicators.py:L25-L26
- `Indicators.stochastic_rsi` · file_33_indicators.py:L59-L66 → file_83_indicators.py:L64-L71
- `Indicators.vwap` · file_33_indicators.py:L117-L120 → file_83_indicators.py:L127-L130
- `Indicators.williams_r` · file_33_indicators.py:L69-L72 → file_83_indicators.py:L74-L77
- `_last` · file_33_indicators.py:L128-L135 → file_83_indicators.py:L291-L298
- `compute_htf_trend` · file_33_indicators.py:L274-L371 → file_83_indicators.py:L651-L748
- `multi_timeframe_filter` · file_33_indicators.py:L374-L428 → file_83_indicators.py:L751-L805

## file_35_market_data.py ↔ file_85_market_data.py
- Aynı AST: 3 · değişmiş: 10 · ikinci dosyada yeni: 14 · ikinci dosyada yok: 2

### Değişmiş
- `MarketData` · file_35_market_data.py:L32-L415 → file_85_market_data.py:L88-L532
- `MarketData.__init__` · file_35_market_data.py:L33-L76 → file_85_market_data.py:L89-L153
- `MarketData._binance_loop` · file_35_market_data.py:L166-L258 → file_85_market_data.py:L264-L381
- `MarketData._mark_lat` · file_35_market_data.py:L81-L96 → file_85_market_data.py:L189-L203
- `MarketData._okx_loop` · file_35_market_data.py:L300-L392 → file_85_market_data.py:L384-L500
- `MarketData._ws_keepalive_task` · file_35_market_data.py:L143-L163 → file_85_market_data.py:L233-L249
- `MarketData.get_price` · file_35_market_data.py:L410-L415 → file_85_market_data.py:L520-L529
- `MarketData.record_pong` · file_35_market_data.py:L98-L103 → file_85_market_data.py:L205-L212
- `MarketData.run_forever` · file_35_market_data.py:L394-L405 → file_85_market_data.py:L502-L515
- `to_okx_inst` · file_35_market_data.py:L28-L29 → file_85_market_data.py:L23-L25

### İkinci dosyada yeni
- `IncrementalOrderBook` · — → file_85_market_data.py:L40-L85
- `IncrementalOrderBook.__init__` · — → file_85_market_data.py:L48-L51
- `IncrementalOrderBook._apply_levels` · — → file_85_market_data.py:L54-L60
- `IncrementalOrderBook.apply` · — → file_85_market_data.py:L62-L80
- `IncrementalOrderBook.top` · — → file_85_market_data.py:L82-L85
- `MarketData._handle_reconnect_state_sync` · — → file_85_market_data.py:L214-L231
- `MarketData._mark_exchange_data` · — → file_85_market_data.py:L155-L168
- `MarketData.data_stats_snapshot` · — → file_85_market_data.py:L170-L171
- `MarketData.get` · — → file_85_market_data.py:L531-L532
- `MarketData.normalize_quantity` · — → file_85_market_data.py:L173-L184
- `MarketData.stream_batches` · — → file_85_market_data.py:L256-L261
- `MarketData.symbols_for_exchange` · — → file_85_market_data.py:L251-L254
- `OrderBookSyncError` · — → file_85_market_data.py:L36-L37
- `binance_ws_base` · — → file_85_market_data.py:L28-L33

### İkinci dosyada yok
- `MarketData._binance_liq_loop` · file_35_market_data.py:L261-L297 → —
- `MarketData.handle_reconnect` · file_35_market_data.py:L105-L141 → —

### Aynı AST
- `MarketData.avg_latency_ms` · file_35_market_data.py:L78-L79 → file_85_market_data.py:L186-L187
- `MarketData.stop` · file_35_market_data.py:L407-L408 → file_85_market_data.py:L517-L518
- `to_binance_stream` · file_35_market_data.py:L24-L25 → file_85_market_data.py:L19-L20

## file_45_strategy.py ↔ file_101_strategy.py
- Aynı AST: 0 · değişmiş: 5 · ikinci dosyada yeni: 0 · ikinci dosyada yok: 0

### Değişmiş
- `Strategy` · file_45_strategy.py:L19-L225 → file_101_strategy.py:L5-L322
- `Strategy.__init__` · file_45_strategy.py:L20-L51 → file_101_strategy.py:L6-L43
- `Strategy.combine` · file_45_strategy.py:L53-L112 → file_101_strategy.py:L45-L188
- `Strategy.entry_decision` · file_45_strategy.py:L114-L195 → file_101_strategy.py:L190-L292
- `Strategy.exit_decision` · file_45_strategy.py:L197-L225 → file_101_strategy.py:L294-L322

### İkinci dosyada yeni
- Yok.

### İkinci dosyada yok
- Yok.

### Aynı AST
- Yok.

## file_26_backtest.py ↔ file_72_backtest.py
- Aynı AST: 4 · değişmiş: 12 · ikinci dosyada yeni: 2 · ikinci dosyada yok: 0

### Değişmiş
- `EventDrivenBacktester` · file_26_backtest.py:L104-L471 → file_72_backtest.py:L100-L700
- `EventDrivenBacktester.__init__` · file_26_backtest.py:L105-L158 → file_72_backtest.py:L101-L179
- `EventDrivenBacktester._handle_fill_event` · file_26_backtest.py:L357-L399 → file_72_backtest.py:L527-L615
- `EventDrivenBacktester._handle_market_event` · file_26_backtest.py:L170-L278 → file_72_backtest.py:L226-L418
- `EventDrivenBacktester._handle_order_event` · file_26_backtest.py:L332-L355 → file_72_backtest.py:L503-L525
- `EventDrivenBacktester._handle_signal_event` · file_26_backtest.py:L280-L330 → file_72_backtest.py:L420-L501
- `EventDrivenBacktester.run_df` · file_26_backtest.py:L401-L471 → file_72_backtest.py:L617-L700
- `FillEvent` · file_26_backtest.py:L70-L81 → file_72_backtest.py:L72-L84
- `OrderEvent` · file_26_backtest.py:L57-L66 → file_72_backtest.py:L58-L68
- `run` · file_26_backtest.py:L557-L576 → file_72_backtest.py:L788-L835
- `run_out_of_sample_test` · file_26_backtest.py:L475-L554 → file_72_backtest.py:L703-L785
- `verify_no_lookahead_bias` · file_26_backtest.py:L84-L101 → file_72_backtest.py:L87-L97

### İkinci dosyada yeni
- `EventDrivenBacktester._make_r_plan` · — → file_72_backtest.py:L201-L219
- `EventDrivenBacktester._prepare_atr_plan` · — → file_72_backtest.py:L186-L199

### İkinci dosyada yok
- Yok.

### Aynı AST
- `EventDrivenBacktester._apply_slippage` · file_26_backtest.py:L160-L163 → file_72_backtest.py:L181-L184
- `EventDrivenBacktester._intrabar_ticks` · file_26_backtest.py:L165-L168 → file_72_backtest.py:L221-L224
- `MarketEvent` · file_26_backtest.py:L36-L43 → file_72_backtest.py:L37-L44
- `SignalEvent` · file_26_backtest.py:L47-L53 → file_72_backtest.py:L48-L54

## file_36_ml_predictor.py ↔ file_87_ml_predictor.py
- Aynı AST: 0 · değişmiş: 3 · ikinci dosyada yeni: 8 · ikinci dosyada yok: 8

### Değişmiş
- `MLPredictor` · file_36_ml_predictor.py:L199-L357 → file_87_ml_predictor.py:L130-L258
- `MLPredictor.__init__` · file_36_ml_predictor.py:L202-L216 → file_87_ml_predictor.py:L133-L146
- `MLPredictor.predict` · file_36_ml_predictor.py:L307-L357 → file_87_ml_predictor.py:L198-L258

### İkinci dosyada yeni
- `MLPredictor.build_features` · — → file_87_ml_predictor.py:L149-L196
- `_NumpyGBDTClassifier` · — → file_87_ml_predictor.py:L23-L82
- `_NumpyGBDTClassifier.__init__` · — → file_87_ml_predictor.py:L26-L30
- `_NumpyGBDTClassifier._sigmoid` · — → file_87_ml_predictor.py:L33-L34
- `_NumpyGBDTClassifier.fit` · — → file_87_ml_predictor.py:L36-L73
- `_NumpyGBDTClassifier.predict_proba` · — → file_87_ml_predictor.py:L75-L82
- `_Stump` · — → file_87_ml_predictor.py:L16-L20
- `_select_backend` · — → file_87_ml_predictor.py:L85-L127

### İkinci dosyada yok
- `MLPredictor._create_model` · file_36_ml_predictor.py:L218-L262 → —
- `MLPredictor.fit` · file_36_ml_predictor.py:L264-L305 → —
- `NumpyGBDTClassifier` · file_36_ml_predictor.py:L105-L196 → —
- `NumpyGBDTClassifier.__init__` · file_36_ml_predictor.py:L112-L120 → —
- `NumpyGBDTClassifier._sigmoid` · file_36_ml_predictor.py:L123-L124 → —
- `NumpyGBDTClassifier.fit` · file_36_ml_predictor.py:L126-L184 → —
- `NumpyGBDTClassifier.predict_proba` · file_36_ml_predictor.py:L186-L196 → —
- `extract_features` · file_36_ml_predictor.py:L39-L102 → —

### Aynı AST
- Yok.

## file_38_news.py ↔ file_89_news.py
- Aynı AST: 0 · değişmiş: 9 · ikinci dosyada yeni: 3 · ikinci dosyada yok: 4

### Değişmiş
- `NewsEngine` · file_38_news.py:L107-L332 → file_89_news.py:L66-L293
- `NewsEngine.__init__` · file_38_news.py:L108-L131 → file_89_news.py:L69-L96
- `NewsEngine._register` · file_38_news.py:L200-L232 → file_89_news.py:L98-L134
- `NewsEngine.mood` · file_38_news.py:L146-L198 → file_89_news.py:L224-L277
- `NewsEngine.push_item` · file_38_news.py:L234-L237 → file_89_news.py:L136-L138
- `NewsEngine.run_forever` · file_38_news.py:L315-L329 → file_89_news.py:L286-L290
- `NewsEngine.stop` · file_38_news.py:L331-L332 → file_89_news.py:L292-L293
- `NewsItem` · file_38_news.py:L62-L72 → file_89_news.py:L54-L63
- `score_text` · file_38_news.py:L75-L104 → file_89_news.py:L32-L50

### İkinci dosyada yeni
- `NewsEngine._poll_cryptopanic` · — → file_89_news.py:L177-L222
- `NewsEngine._poll_rss` · — → file_89_news.py:L140-L175
- `NewsEngine.poll_once` · — → file_89_news.py:L279-L284

### İkinci dosyada yok
- `NewsEngine._enrich_loop` · file_38_news.py:L298-L313 → —
- `NewsEngine._fetch_cryptopanic` · file_38_news.py:L269-L296 → —
- `NewsEngine._fetch_rss` · file_38_news.py:L239-L267 → —
- `NewsEngine._weighted_fg` · file_38_news.py:L133-L144 → —

### Aynı AST
- Yok.

## file_41_security.py ↔ file_95_security.py
- Aynı AST: 0 · değişmiş: 7 · ikinci dosyada yeni: 3 · ikinci dosyada yok: 5

### Değişmiş
- `install_log_masking` · file_41_security.py:L155-L159 → file_95_security.py:L160-L167
- `is_auth_or_permission_error` · file_41_security.py:L195-L200 → file_95_security.py:L106-L112
- `mask_secrets` · file_41_security.py:L108-L127 → file_95_security.py:L79-L92
- `register_secret` · file_41_security.py:L90-L95 → file_95_security.py:L61-L67
- `safe_exception_msg` · file_41_security.py:L130-L133 → file_95_security.py:L95-L103
- `sanitize_external_text` · file_41_security.py:L162-L182 → file_95_security.py:L115-L126
- `sanitize_url` · file_41_security.py:L185-L192 → file_95_security.py:L129-L143

### İkinci dosyada yeni
- `_SecretMaskingFilter` · — → file_95_security.py:L146-L157
- `_SecretMaskingFilter.filter` · — → file_95_security.py:L147-L157
- `_active_secrets` · — → file_95_security.py:L70-L76

### İkinci dosyada yok
- `SecretMaskingFilter` · file_41_security.py:L143-L152 → —
- `SecretMaskingFilter.filter` · file_41_security.py:L146-L152 → —
- `_collect_active_secrets` · file_41_security.py:L98-L105 → —
- `safe_log` · file_41_security.py:L136-L140 → —
- `verify_no_hardcoded_secrets` · file_41_security.py:L203-L214 → —

### Aynı AST
- Yok.

## file_46_telegram.py ↔ file_102_telegram.py
- Aynı AST: 2 · değişmiş: 7 · ikinci dosyada yeni: 17 · ikinci dosyada yok: 0

### Değişmiş
- `InteractiveTelegramBot` · file_46_telegram.py:L56-L223 → file_102_telegram.py:L145-L869
- `InteractiveTelegramBot.__init__` · file_46_telegram.py:L59-L75 → file_102_telegram.py:L148-L187
- `InteractiveTelegramBot._format_status_report` · file_46_telegram.py:L142-L184 → file_102_telegram.py:L478-L489
- `InteractiveTelegramBot.handle_command` · file_46_telegram.py:L83-L140 → file_102_telegram.py:L195-L277
- `InteractiveTelegramBot.poll_forever` · file_46_telegram.py:L186-L220 → file_102_telegram.py:L811-L866
- `make_alerter` · file_46_telegram.py:L39-L53 → file_102_telegram.py:L88-L113
- `send_telegram` · file_46_telegram.py:L21-L36 → file_102_telegram.py:L44-L85

### İkinci dosyada yeni
- `InteractiveTelegramBot._fetch_balance` · — → file_102_telegram.py:L279-L289
- `InteractiveTelegramBot._financial_snapshot` · — → file_102_telegram.py:L400-L409
- `InteractiveTelegramBot._format_daily_report` · — → file_102_telegram.py:L491-L595
- `InteractiveTelegramBot._format_market_report` · — → file_102_telegram.py:L411-L476
- `InteractiveTelegramBot._format_periodic_report` · — → file_102_telegram.py:L645-L778
- `InteractiveTelegramBot._format_pnl_report` · — → file_102_telegram.py:L634-L643
- `InteractiveTelegramBot._format_positions_report` · — → file_102_telegram.py:L623-L632
- `InteractiveTelegramBot._pnl_lines` · — → file_102_telegram.py:L360-L398
- `InteractiveTelegramBot._position_lines` · — → file_102_telegram.py:L329-L358
- `InteractiveTelegramBot._refresh_position_prices` · — → file_102_telegram.py:L291-L323
- `InteractiveTelegramBot._send_whatsapp_if_enabled` · — → file_102_telegram.py:L597-L611
- `InteractiveTelegramBot._timestamp` · — → file_102_telegram.py:L326-L327
- `InteractiveTelegramBot.periodic_report_forever` · — → file_102_telegram.py:L780-L809
- `InteractiveTelegramBot.send_daily_report` · — → file_102_telegram.py:L613-L621
- `_normalize_telegram_credentials` · — → file_102_telegram.py:L26-L41
- `send_telegram_long` · — → file_102_telegram.py:L133-L142
- `telegram_message_chunks` · — → file_102_telegram.py:L116-L130

### İkinci dosyada yok
- Yok.

### Aynı AST
- `InteractiveTelegramBot.is_authorized` · file_46_telegram.py:L77-L81 → file_102_telegram.py:L189-L193
- `InteractiveTelegramBot.stop` · file_46_telegram.py:L222-L223 → file_102_telegram.py:L868-L869
