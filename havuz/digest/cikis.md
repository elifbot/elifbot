# HAVUZ DEMETİ · CIKIS

**Soru:** Çıkış ve zarar kes: stop bütçesi (-10 $ net) korunurken kâr nasıl taşınır? BE/trailing eşikleri kayma ve komisyonla nasıl uyumlu olur?

Kanıt parçaları `dosya:satır` ile işaretlidir. Yalnızca bu kanıta dayan; kanıt yoksa 'veri yok' de, uydurma.

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/risk.py:312-318
```
            structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
            if structure_stop > 0 and structure_stop < stop:
                stop, source = structure_stop, "ATR+SWING"
        elif side == "SHORT" and swing_high is not None and float(swing_high) > entry:
            structure_stop = float(swing_high) + atr * float(structure_buffer_atr)
            if structure_stop > stop:
                stop, source = structure_stop, "ATR+SWING"
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/risk.py:702-708
```
                if pnl > 0 and trail_stop >= pos.entry:
                    candidate = max(trail_stop, floor)
                    if candidate > pos.stop:
                        pos.stop = candidate
            elif trail_stop > pos.stop and pnl > 0 and trail_stop >= pos.entry:
                pos.stop = trail_stop
            if price <= pos.stop:
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/risk.py:748-754
```
                if pnl > 0 and trail_stop <= pos.entry:
                    candidate = min(trail_stop, floor)
                    if candidate < pos.stop:
                        pos.stop = candidate
            elif trail_stop < pos.stop and pnl > 0 and trail_stop <= pos.entry:
                pos.stop = trail_stop
            if price >= pos.stop:
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/risk.py:308-314
```
            structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
            if structure_stop > 0 and structure_stop < stop:
                stop, source = structure_stop, "ATR+SWING"
        elif side == "SHORT" and swing_high is not None and float(swing_high) > entry:
            structure_stop = float(swing_high) + atr * float(structure_buffer_atr)
            if structure_stop > stop:
                stop, source = structure_stop, "ATR+SWING"
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/risk.py:658-664
```
                if pnl > 0 and trail_stop >= pos.entry:
                    candidate = max(trail_stop, floor)
                    if candidate > pos.stop:
                        pos.stop = candidate
            elif trail_stop > pos.stop and pnl > 0 and trail_stop >= pos.entry:
                pos.stop = trail_stop
            if price <= pos.stop:
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/risk.py:699-705
```
                if pnl > 0 and trail_stop <= pos.entry:
                    candidate = min(trail_stop, floor)
                    if candidate < pos.stop:
                        pos.stop = candidate
            elif trail_stop < pos.stop and pnl > 0 and trail_stop <= pos.entry:
                pos.stop = trail_stop
            if price >= pos.stop:
```

#### drive/toplama/arsiv-2/toplama 2/risk.py:312-318
```
            structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
            if structure_stop > 0 and structure_stop < stop:
                stop, source = structure_stop, "ATR+SWING"
        elif side == "SHORT" and swing_high is not None and float(swing_high) > entry:
            structure_stop = float(swing_high) + atr * float(structure_buffer_atr)
            if structure_stop > stop:
                stop, source = structure_stop, "ATR+SWING"
```

#### drive/toplama/arsiv-2/toplama 2/risk.py:704-710
```
                if pnl > 0 and trail_stop >= pos.entry:
                    candidate = max(trail_stop, floor)
                    if candidate > pos.stop:
                        pos.stop = candidate
            elif trail_stop > pos.stop and pnl > 0 and trail_stop >= pos.entry:
                pos.stop = trail_stop
            if price <= pos.stop:
```

#### drive/toplama/arsiv-2/toplama 2/risk.py:750-756
```
                if pnl > 0 and trail_stop <= pos.entry:
                    candidate = min(trail_stop, floor)
                    if candidate < pos.stop:
                        pos.stop = candidate
            elif trail_stop < pos.stop and pnl > 0 and trail_stop <= pos.entry:
                pos.stop = trail_stop
            if price >= pos.stop:
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/risk.py:301-307
```
            structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
            if structure_stop > 0 and structure_stop < stop:
                stop, source = structure_stop, "ATR+SWING"
        elif side == "SHORT" and swing_high is not None and float(swing_high) > entry:
            structure_stop = float(swing_high) + atr * float(structure_buffer_atr)
            if structure_stop > stop:
                stop, source = structure_stop, "ATR+SWING"
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/risk.py:635-641
```
                if pnl > 0 and trail_stop >= pos.entry:
                    candidate = max(trail_stop, floor)
                    if candidate > pos.stop:
                        pos.stop = candidate
            elif trail_stop > pos.stop and pnl > 0 and trail_stop >= pos.entry:
                pos.stop = trail_stop
            if price <= pos.stop:
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/risk.py:666-672
```
                if pnl > 0 and trail_stop <= pos.entry:
                    candidate = min(trail_stop, floor)
                    if candidate < pos.stop:
                        pos.stop = candidate
            elif trail_stop < pos.stop and pnl > 0 and trail_stop <= pos.entry:
                pos.stop = trail_stop
            if price >= pos.stop:
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:299-305
```
        self._adverse_orders.add(order.id)
        if not getattr(self.config.exit, "cancel_on_stop_breach_at_fill", False):
            # VARSAYILAN: gerçekçi davranış — dolum olur, aynı tick'te stop.
            logger.info(
                "TERS SEÇİLİM: [%s] canlı fiyat %.6g stop %.6g ötesinde — "
                "limit doluyor ve doğuşta stop olacak (gerçekçi model)",
                order.symbol, price, stop,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:677-683
```
            # v5.1: oturum sonu denetim — gerçekleşen/hedef kayıp oranı ve
            # stop aşımı (overshoot) için gerekli iki alan.
            "target_net_risk": position.initial_net_risk,
            "stop_loss": position.stop_loss,
            # v5.5: açılış stopu — trailing sonrası stop_loss değişir,
            # çıkış katkısı ölçümü İLK stopu gerektirir.
            "initial_stop_loss": position.initial_stop_loss or position.stop_loss,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:748-754
```
        # Klasik stop
        if position.side == "LONG" and price <= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(symbol, price, reason, now_ms))
            return events
        if position.side == "SHORT" and price >= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/risk.py:290-296
```
            structure_stop = float(swing_low) - atr * float(structure_buffer_atr)
            if structure_stop > 0 and structure_stop < stop:
                stop, source = structure_stop, "ATR+SWING"
        elif side == "SHORT" and swing_high is not None and float(swing_high) > entry:
            structure_stop = float(swing_high) + atr * float(structure_buffer_atr)
            if structure_stop > stop:
                stop, source = structure_stop, "ATR+SWING"
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/risk.py:589-595
```
                if pnl > 0 and trail_stop >= pos.entry:
                    candidate = max(trail_stop, floor)
                    if candidate > pos.stop:
                        pos.stop = candidate
            elif trail_stop > pos.stop and pnl > 0 and trail_stop >= pos.entry:
                pos.stop = trail_stop
            if price <= pos.stop:
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/risk.py:613-619
```
                if pnl > 0 and trail_stop <= pos.entry:
                    candidate = min(trail_stop, floor)
                    if candidate < pos.stop:
                        pos.stop = candidate
            elif trail_stop < pos.stop and pnl > 0 and trail_stop <= pos.entry:
                pos.stop = trail_stop
            if price >= pos.stop:
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:756-762
```
    def _is_risk_free_position(pos: Position) -> bool:
        """Stop seviyesi kâr kilidine veya girişin kâr tarafına geçmiş pozisyon ortak kasada risk taşımaz."""
        if getattr(pos, "locked_profit", False):
            return True
        if pos.side == "LONG" and pos.stop > pos.entry:
            return True
        if pos.side == "SHORT" and 0 < pos.stop < pos.entry:
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:1325-1331
```
            candidate_risk = abs(price-stop)*qty
            open_risk = sum(max(0.0, (p.entry-p.stop) if p.side=="LONG" else (p.stop-p.entry))*p.qty for p in self.positions.values())
            side_risk = sum(max(0.0, (p.entry-p.stop) if p.side=="LONG" else (p.stop-p.entry))*p.qty for p in self.positions.values() if p.side==side)
            if open_risk+candidate_risk>pool_balance*policy.total_risk_fraction or side_risk+candidate_risk>pool_balance*policy.directional_risk_fraction:
                await self._say(f"⛔ {symbol}: V94 aggregate directional risk budget")
                return
        if is_cross and hasattr(self.risk, "cross_pool_ok"):
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:1546-1552
```
        if hasattr(self.risk, "policy"):
            try:final_stop = self.risk.policy.initial_stop(side, fill_px, raw_atr)
            except ValueError:
                # A fill already exists: protect it immediately rather than discarding its accounting.
                distance = fill_px*self.risk.policy.max_stop_pct/100
                final_stop = fill_px-distance if side=="LONG" else fill_px+distance
        pos_atr_pct = (raw_atr / fill_px * 100.0) if (raw_atr > 0 and fill_px > 0) else 0.0
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/exec/paper.py:265-271
```
        """v5.2: DOLUM ANI STOP İHLALİ KONTROLÜ.

        Bulunan hata (15 dk canlı test, 2026-11-08 05:21:38 → 05:22:04):
        GNO SHORT için 111.92238 limit emri kondu, stop 112.26 idi. Emir
        26 sn bekledi; bu sırada fiyat 112.45'e çıktı — yani STOPUN
        ÖTESİNE. Maker simülatörü emri limit fiyatından doldurdu ve
        pozisyon AYNİ tick'te stop oldu (`hold_ms=0`, −31,37 USDT,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/exec/paper.py:299-305
```
        self._adverse_orders.add(order.id)
        if not getattr(self.config.exit, "cancel_on_stop_breach_at_fill", False):
            # VARSAYILAN: gerçekçi davranış — dolum olur, aynı tick'te stop.
            logger.info(
                "TERS SEÇİLİM: [%s] canlı fiyat %.6g stop %.6g ötesinde — "
                "limit doluyor ve doğuşta stop olacak (gerçekçi model)",
                order.symbol, price, stop,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/exec/paper.py:743-749
```
        # Klasik stop
        if position.side == "LONG" and price <= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(symbol, price, reason, now_ms))
            return events
        if position.side == "SHORT" and price >= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/executor.py:436-442
```
        stop: float,
        source: str = "RECOVERED",
        atr: float = 0.0,
        tp1_hit: bool = False,
    ) -> dict | None:
        risk_distance = abs(float(entry) - float(stop))
        if entry <= 0 or stop <= 0 or risk_distance <= 0:
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/executor.py:719-725
```
    def _is_risk_free_position(pos: Position) -> bool:
        """Stop seviyesi kâr kilidine veya girişin kâr tarafına geçmiş pozisyon ortak kasada risk taşımaz."""
        if getattr(pos, "locked_profit", False):
            return True
        if pos.side == "LONG" and pos.stop > pos.entry:
            return True
        if pos.side == "SHORT" and 0 < pos.stop < pos.entry:
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/executor.py:1559-1565
```
        await self._say(
            f"🟢 {side} AÇILDI | {symbol} @ {fill_px:,.4f} | {lev}x Kaldıraç ({lev_why}) | "
            f"Marj: ${margin_usdt:,.2f} (%{info.get('risk_pct')}) | "
            f"Emir: {fill.get('emir_tipi', '?')} | Stop: {pos.stop:,.4f} "
            f"(%{actual_stop_pct:.2f} / ~${estimated_stop_loss:,.2f} fiyat K/Z)"
            f"{plan_note} | Koruma: {prot_note} | Neden: {reason}"
        )
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/executor.py:287-293
```
        stop: float,
        source: str = "RECOVERED",
        atr: float = 0.0,
        tp1_hit: bool = False,
    ) -> dict | None:
        risk_distance = abs(float(entry) - float(stop))
        if entry <= 0 or stop <= 0 or risk_distance <= 0:
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/executor.py:504-510
```
    def _is_risk_free_position(pos: Position) -> bool:
        """Stop seviyesi kâr kilidine veya girişin kâr tarafına geçmiş pozisyon ortak kasada risk taşımaz."""
        if getattr(pos, "locked_profit", False):
            return True
        if pos.side == "LONG" and pos.stop > pos.entry:
            return True
        if pos.side == "SHORT" and 0 < pos.stop < pos.entry:
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/executor.py:1250-1256
```
        await self._say(
            f"🟢 {side} AÇILDI | {symbol} @ {fill_px:,.4f} | {lev}x Kaldıraç ({lev_why}) | "
            f"Marj: ${margin_usdt:,.2f} (%{info.get('risk_pct')}) | "
            f"Emir: {fill.get('emir_tipi', '?')} | Stop: {pos.stop:,.4f} "
            f"(%{actual_stop_pct:.2f} / ~${estimated_stop_loss:,.2f} fiyat K/Z)"
            f"{plan_note} | Koruma: {prot_note} | Neden: {reason}"
        )
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/executor.py:287-293
```
        stop: float,
        source: str = "RECOVERED",
        atr: float = 0.0,
        tp1_hit: bool = False,
    ) -> dict | None:
        risk_distance = abs(float(entry) - float(stop))
        if entry <= 0 or stop <= 0 or risk_distance <= 0:
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/executor.py:504-510
```
    def _is_risk_free_position(pos: Position) -> bool:
        """Stop seviyesi kâr kilidine veya girişin kâr tarafına geçmiş pozisyon ortak kasada risk taşımaz."""
        if getattr(pos, "locked_profit", False):
            return True
        if pos.side == "LONG" and pos.stop > pos.entry:
            return True
        if pos.side == "SHORT" and 0 < pos.stop < pos.entry:
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/executor.py:1232-1238
```
        await self._say(
            f"🟢 {side} AÇILDI | {symbol} @ {fill_px:,.4f} | {lev}x Kaldıraç ({lev_why}) | "
            f"Marj: ${margin_usdt:,.2f} (%{info.get('risk_pct')}) | "
            f"Emir: {fill.get('emir_tipi', '?')} | Stop: {pos.stop:,.4f} "
            f"(%{actual_stop_pct:.2f} / ~${estimated_stop_loss:,.2f} fiyat K/Z)"
            f"{plan_note} | Koruma: {prot_note} | Neden: {reason}"
        )
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/executor.py:164-170
```
                plan = saved_plans.get(sym) if isinstance(saved_plans, dict) else None
                required = {"initial_risk", "initial_stop", "tp1", "tp2", "tp1_hit"}
                if not isinstance(plan, dict) and not self.trade_plan_enabled:
                    continue
                if not isinstance(plan, dict) or not required.issubset(plan):
                    already_tp1 = (
                        pos.side == "LONG" and pos.stop >= pos.entry
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/executor.py:268-274
```
        stop: float,
        source: str = "RECOVERED",
        atr: float = 0.0,
        tp1_hit: bool = False,
    ) -> dict | None:
        risk_distance = abs(float(entry) - float(stop))
        if entry <= 0 or stop <= 0 or risk_distance <= 0:
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/executor.py:1090-1096
```
        await self._say(
            f"🟢 {side} AÇILDI | {symbol} @ {fill_px:,.4f} | {lev}x Kaldıraç ({lev_why}) | "
            f"Marj: ${margin_usdt:,.2f} (%{info.get('risk_pct')}) | "
            f"Emir: {fill.get('emir_tipi', '?')} | Stop: {pos.stop:,.4f} "
            f"(%{actual_stop_pct:.2f} / ~${estimated_stop_loss:,.2f} fiyat K/Z)"
            f"{plan_note} | Koruma: {prot_note} | Neden: {reason}"
        )
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:377-383
```
        plan = risk.plan(1000, 100, 0.05, "SHORT")
        broker.open_position("BTCUSDT", plan, 100)
        self.assertEqual(broker.portfolio.positions["BTCUSDT"].side, "SHORT")
        stop = broker.check_exit("BTCUSDT", 106, 99, 102, 200)
        self.assertEqual(stop["reason"], "stop_loss")
        self.assertEqual(stop["side"], "SHORT")
        self.assertLessEqual(-stop["pnl"], 25.0)
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:616-622
```
                "BTCUSDT", expected_trailing_stop + 1,
                expected_trailing_stop, expected_trailing_stop, 400,
            )
        self.assertEqual(closed["reason"], "trailing_stop")
        self.assertTrue(closed["reduce_only"])
        self.assertIn(
            "YÜZDESEL TRAILING STOP TETİKLENDİ: [BTCUSDT] %2 düşüş ile kapatıldı",
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.0_PAPER__ic/new-bot/tests/test_trading_system.py:1242-1248
```
        self.assertEqual(closed["reason"], "position_loss_stop")
        self.assertTrue(closed["reduce_only"])
        self.assertEqual(closed["execution_type"], "stop_market")
        self.assertNotIn("BTCUSDT", broker.portfolio.positions)
        self.assertIn("ETHUSDT", broker.portfolio.positions)
        self.assertIn(
            "STOP LOSS TETİKLENDİ: [BTCUSDT] 25 USDT zarar ile kapatıldı",
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/exec/paper.py:595-601
```
        # Klasik stop
        if position.side == "LONG" and price <= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(symbol, price, reason, now_ms))
            return events
        if position.side == "SHORT" and price >= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/exec/paper.py:650-656
```
        # Acil net stop: en kötü fiyat üzerinden NET hesap (maliyet dâhil).
        worst_price = candle.low if position.side == "LONG" else candle.high
        if position.net_pnl(worst_price, self.taker_fee_rate,
                            self.stop_slippage_rate + self.extra_slippage_rate) \
                <= -self.max_loss_per_position:
            events.append(self.close_position_market(
                symbol, worst_price, "position_loss_stop", now_ms,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/exec/paper.py:663-669
```
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(
                symbol, position.stop_loss, reason, now_ms,
            ))
            return events
        if position.side == "SHORT" and candle.high >= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
```

#### drive/toplama/arsiv-4/ACAR_FUTURES_APEX_v1.1_PAPER_UNLIMITED_POSITIONS__ic/new-bot/tests/test_trading_system.py:374-380
```
        plan = risk.plan(1000, 100, 0.05, "SHORT")
        broker.open_position("BTCUSDT", plan, 100)
        self.assertEqual(broker.portfolio.positions["BTCUSDT"].side, "SHORT")
        stop = broker.check_exit("BTCUSDT", 106, 99, 102, 200)
        self.assertEqual(stop["reason"], "stop_loss")
        self.assertEqual(stop["side"], "SHORT")
        self.assertLessEqual(-stop["pnl"], 25.0)
```
