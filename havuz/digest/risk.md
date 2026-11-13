# HAVUZ DEMETİ · RISK

**Soru:** 50 $ teminat / 10x / CROSS dünyasında portföy düzeyi risk nedir? Eşzamanlı pozisyon, korelasyon ve tasfiye mesafesi nasıl yönetilir?

Kanıt parçaları `dosya:satır` ile işaretlidir. Yalnızca bu kanıta dayan; kanıt yoksa 'veri yok' de, uydurma.

#### drive/toplama/arsiv-2/toplama 2/executor.py:1244-1250
```
        leverage_override: int | None = None,
        force_risk_based: bool = False,
    ) -> tuple[float, dict]:
        lev = int(leverage_override or getattr(self.risk, "leverage", 20))
        fixed_margin_mode = self.sizer is None or getattr(self.sizer, "mode", None) == "kasa_10_20x"
        if force_risk_based and fixed_margin_mode:
            qty = self.risk.position_size(max(balance, 0), price, stop)
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:1323-1329
```
        if hasattr(self.risk, "policy"):
            policy = self.risk.policy
            candidate_risk = abs(price-stop)*qty
            open_risk = sum(max(0.0, (p.entry-p.stop) if p.side=="LONG" else (p.stop-p.entry))*p.qty for p in self.positions.values())
            side_risk = sum(max(0.0, (p.entry-p.stop) if p.side=="LONG" else (p.stop-p.entry))*p.qty for p in self.positions.values() if p.side==side)
            if open_risk+candidate_risk>pool_balance*policy.total_risk_fraction or side_risk+candidate_risk>pool_balance*policy.directional_risk_fraction:
                await self._say(f"⛔ {symbol}: V94 aggregate directional risk budget")
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:1783-1789
```
            await self._say(f"⛔ {symbol}: kademe emri dolmadı; mevcut pozisyon değiştirilmedi.")
            return
        lev = int(info.get("leverage") or pos.leverage)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        add_margin = float(
            fill.get("margin_usdt")
            or (estimated_margin * add_qty / requested_add_qty if estimated_margin and requested_add_qty else 0.0)
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/executor.py:1191-1197
```
        leverage_override: int | None = None,
        force_risk_based: bool = False,
    ) -> tuple[float, dict]:
        lev = int(leverage_override or getattr(self.risk, "leverage", 20))
        fixed_margin_mode = self.sizer is None or getattr(self.sizer, "mode", None) == "kasa_10_20x"
        if force_risk_based and fixed_margin_mode:
            qty = self.risk.position_size(max(balance, 0), price, stop)
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/executor.py:1424-1430
```
            await self._say(f"⛔ {symbol}: emir dolmadı; yerel pozisyon oluşturulmadı.")
            return
        lev = int(info.get("leverage") or dyn_lev)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        margin_usdt = float(
            fill.get("margin_usdt")
            or (estimated_margin * qty / requested_qty if estimated_margin and requested_qty else 0.0)
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/executor.py:1681-1687
```
            await self._say(f"⛔ {symbol}: kademe emri dolmadı; mevcut pozisyon değiştirilmedi.")
            return
        lev = int(info.get("leverage") or pos.leverage)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        add_margin = float(
            fill.get("margin_usdt")
            or (estimated_margin * add_qty / requested_add_qty if estimated_margin and requested_add_qty else 0.0)
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/executor.py:944-950
```
        leverage_override: int | None = None,
        force_risk_based: bool = False,
    ) -> tuple[float, dict]:
        lev = int(leverage_override or getattr(self.risk, "leverage", 20))
        fixed_margin_mode = self.sizer is None or getattr(self.sizer, "mode", None) == "kasa_10_20x"
        if force_risk_based and fixed_margin_mode:
            qty = self.risk.position_size(max(balance, 0), price, stop)
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/executor.py:1121-1127
```
            await self._say(f"⛔ {symbol}: emir dolmadı; yerel pozisyon oluşturulmadı.")
            return
        lev = int(info.get("leverage") or dyn_lev)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        margin_usdt = float(
            fill.get("margin_usdt")
            or (estimated_margin * qty / requested_qty if estimated_margin and requested_qty else 0.0)
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/executor.py:1348-1354
```
            await self._say(f"⛔ {symbol}: kademe emri dolmadı; mevcut pozisyon değiştirilmedi.")
            return
        lev = int(info.get("leverage") or pos.leverage)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        add_margin = float(
            fill.get("margin_usdt")
            or (estimated_margin * add_qty / requested_add_qty if estimated_margin and requested_add_qty else 0.0)
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/executor.py:944-950
```
        leverage_override: int | None = None,
        force_risk_based: bool = False,
    ) -> tuple[float, dict]:
        lev = int(leverage_override or getattr(self.risk, "leverage", 20))
        fixed_margin_mode = self.sizer is None or getattr(self.sizer, "mode", None) == "kasa_10_20x"
        if force_risk_based and fixed_margin_mode:
            qty = self.risk.position_size(max(balance, 0), price, stop)
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/executor.py:1106-1112
```
            await self._say(f"⛔ {symbol}: emir dolmadı; yerel pozisyon oluşturulmadı.")
            return
        lev = int(info.get("leverage") or dyn_lev)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        margin_usdt = float(
            fill.get("margin_usdt")
            or (estimated_margin * qty / requested_qty if estimated_margin and requested_qty else 0.0)
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/executor.py:1330-1336
```
            await self._say(f"⛔ {symbol}: kademe emri dolmadı; mevcut pozisyon değiştirilmedi.")
            return
        lev = int(info.get("leverage") or pos.leverage)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        add_margin = float(
            fill.get("margin_usdt")
            or (estimated_margin * add_qty / requested_add_qty if estimated_margin and requested_add_qty else 0.0)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:206-212
```
        assert cfg.min_risk_usdt == pytest.approx(2.5)
        assert cfg.max_risk_usdt == 0.0  # yukarı ölçekleme yok

    @pytest.mark.parametrize("kwargs", [
        {"min_risk_usdt": 0.0},
        {"max_risk_usdt": -1.0},
        {"max_risk_usdt": 1.0, "min_risk_usdt": 5.0},
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:394-400
```
        from core.risk import RiskManager

        risk = RiskManager()
        full = risk.plan(100.0, 0.02, "LONG")
        small = risk.plan(100.0, 0.02, "LONG", risk_budget=5.0)
        assert full.net_risk_at_stop == pytest.approx(25.0)
        assert small.net_risk_at_stop == pytest.approx(5.0)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:1424-1430
```
        trades = [{"type": "CLOSE", "net_risk": 5.0, "pnl": -5.0}]
        out = _risk_scaling_block(self._executor(sc), trades)
        assert out["opened_positions"] == 0

    def test_missing_net_risk_is_skipped(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:206-212
```
        assert cfg.min_risk_usdt == pytest.approx(2.5)
        assert cfg.max_risk_usdt == 0.0  # yukarı ölçekleme yok

    @pytest.mark.parametrize("kwargs", [
        {"min_risk_usdt": 0.0},
        {"max_risk_usdt": -1.0},
        {"max_risk_usdt": 1.0, "min_risk_usdt": 5.0},
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:394-400
```
        from core.risk import RiskManager

        risk = RiskManager()
        full = risk.plan(100.0, 0.02, "LONG")
        small = risk.plan(100.0, 0.02, "LONG", risk_budget=5.0)
        assert full.net_risk_at_stop == pytest.approx(25.0)
        assert small.net_risk_at_stop == pytest.approx(5.0)
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:1432-1438
```
        trades = [{"type": "CLOSE", "net_risk": 5.0, "pnl": -5.0}]
        out = _risk_scaling_block(self._executor(sc), trades)
        assert out["opened_positions"] == 0

    def test_missing_net_risk_is_skipped(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/risk.py:249-255
```
        lev = max(1, int(leverage or self.leverage or 1))
        requested = (100.0 / lev) * self.margin_stop_fraction
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(min(requested, liq_dist * self.margin_stop_liq_buffer), 4)

    def effective_stop_pct(self, leverage: int | None = None) -> float:
        """Seçilen marj veya fiyat-yüzde modelinin likidasyon bilinçli stopu."""
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/risk.py:256-262
```
        lev = max(1, int(leverage or self.leverage or 1))
        if self.stop_model in {"marj", "margin"}:
            return self.margin_stop_pct(lev)
        return round(min(self.stop_loss_pct, self.liquidation_stop_pct(lev)), 4)

    def initial_stop(self, side: str, entry: float, leverage: int | None = None) -> float:
        """Marj-risk veya eski fiyat-yüzde modeline göre başlangıç stopu."""
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/risk.py:407-413
```
        """Kasa yüzdesi × kaldıraç ile marj, büyüklük ve miktar hesabı."""
        cap = float(capital_pct if capital_pct is not None else self.capital_pct_per_entry)
        lev = max(1, int(leverage if leverage is not None else self.leverage))
        if balance_usdt <= 0 or entry <= 0 or cap <= 0:
            return 0.0, {"margin_usdt": 0.0, "notional_usdt": 0.0, "leverage": lev}
        margin_usdt = float(balance_usdt) * (cap / 100.0)
        notional_usdt = margin_usdt * lev
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/risk.py:245-251
```
        lev = max(1, int(leverage or self.leverage or 1))
        requested = (100.0 / lev) * self.margin_stop_fraction
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(min(requested, liq_dist * self.margin_stop_liq_buffer), 4)

    def effective_stop_pct(self, leverage: int | None = None) -> float:
        """Seçilen marj veya fiyat-yüzde modelinin likidasyon bilinçli stopu."""
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/risk.py:252-258
```
        lev = max(1, int(leverage or self.leverage or 1))
        if self.stop_model in {"marj", "margin"}:
            return self.margin_stop_pct(lev)
        return round(min(self.stop_loss_pct, self.liquidation_stop_pct(lev)), 4)

    def initial_stop(self, side: str, entry: float, leverage: int | None = None) -> float:
        """Marj-risk veya eski fiyat-yüzde modeline göre başlangıç stopu."""
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/risk.py:403-409
```
        """Kasa yüzdesi × kaldıraç ile marj, büyüklük ve miktar hesabı."""
        cap = float(capital_pct if capital_pct is not None else self.capital_pct_per_entry)
        lev = max(1, int(leverage if leverage is not None else self.leverage))
        if balance_usdt <= 0 or entry <= 0 or cap <= 0:
            return 0.0, {"margin_usdt": 0.0, "notional_usdt": 0.0, "leverage": lev}
        margin_usdt = float(balance_usdt) * (cap / 100.0)
        notional_usdt = margin_usdt * lev
```

#### drive/toplama/arsiv-2/toplama 2/risk.py:249-255
```
        lev = max(1, int(leverage or self.leverage or 1))
        requested = (100.0 / lev) * self.margin_stop_fraction
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(min(requested, liq_dist * self.margin_stop_liq_buffer), 4)

    def effective_stop_pct(self, leverage: int | None = None) -> float:
        """Seçilen marj veya fiyat-yüzde modelinin likidasyon bilinçli stopu."""
```

#### drive/toplama/arsiv-2/toplama 2/risk.py:256-262
```
        lev = max(1, int(leverage or self.leverage or 1))
        if self.stop_model in {"marj", "margin"}:
            return self.margin_stop_pct(lev)
        return round(min(self.stop_loss_pct, self.liquidation_stop_pct(lev)), 4)

    def initial_stop(self, side: str, entry: float, leverage: int | None = None) -> float:
        """Marj-risk veya eski fiyat-yüzde modeline göre başlangıç stopu."""
```

#### drive/toplama/arsiv-2/toplama 2/risk.py:407-413
```
        """Kasa yüzdesi × kaldıraç ile marj, büyüklük ve miktar hesabı."""
        cap = float(capital_pct if capital_pct is not None else self.capital_pct_per_entry)
        lev = max(1, int(leverage if leverage is not None else self.leverage))
        if balance_usdt <= 0 or entry <= 0 or cap <= 0:
            return 0.0, {"margin_usdt": 0.0, "notional_usdt": 0.0, "leverage": lev}
        margin_usdt = float(balance_usdt) * (cap / 100.0)
        notional_usdt = margin_usdt * lev
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/tests/test_v52_hardening.py:206-212
```
        assert cfg.min_risk_usdt == pytest.approx(2.5)
        assert cfg.max_risk_usdt == 0.0  # yukarı ölçekleme yok

    @pytest.mark.parametrize("kwargs", [
        {"min_risk_usdt": 0.0},
        {"max_risk_usdt": -1.0},
        {"max_risk_usdt": 1.0, "min_risk_usdt": 5.0},
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/tests/test_v52_hardening.py:368-374
```
        from core.risk import RiskManager

        risk = RiskManager()
        full = risk.plan(100.0, 0.02, "LONG")
        small = risk.plan(100.0, 0.02, "LONG", risk_budget=5.0)
        assert full.net_risk_at_stop == pytest.approx(25.0)
        assert small.net_risk_at_stop == pytest.approx(5.0)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/tests/test_v52_hardening.py:1395-1401
```
        trades = [{"type": "CLOSE", "net_risk": 5.0, "pnl": -5.0}]
        out = _risk_scaling_block(self._executor(sc), trades)
        assert out["opened_positions"] == 0

    def test_missing_net_risk_is_skipped(self):
        from app.main import _risk_scaling_block
        sc = RiskScaler(RiskScalingConfig())
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/risk.py:238-244
```
        lev = max(1, int(leverage or self.leverage or 1))
        requested = (100.0 / lev) * self.margin_stop_fraction
        liq_dist = max(0.1, 100.0 / lev - self.maintenance_margin_pct)
        return round(min(requested, liq_dist * self.margin_stop_liq_buffer), 4)

    def effective_stop_pct(self, leverage: int | None = None) -> float:
        """Seçilen marj veya fiyat-yüzde modelinin likidasyon bilinçli stopu."""
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/risk.py:245-251
```
        lev = max(1, int(leverage or self.leverage or 1))
        if self.stop_model in {"marj", "margin"}:
            return self.margin_stop_pct(lev)
        return round(min(self.stop_loss_pct, self.liquidation_stop_pct(lev)), 4)

    def initial_stop(self, side: str, entry: float, leverage: int | None = None) -> float:
        """Marj-risk veya eski fiyat-yüzde modeline göre başlangıç stopu."""
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/risk.py:396-402
```
        """Kasa yüzdesi × kaldıraç ile marj, büyüklük ve miktar hesabı."""
        cap = float(capital_pct if capital_pct is not None else self.capital_pct_per_entry)
        lev = max(1, int(leverage if leverage is not None else self.leverage))
        if balance_usdt <= 0 or entry <= 0 or cap <= 0:
            return 0.0, {"margin_usdt": 0.0, "notional_usdt": 0.0, "leverage": lev}
        margin_usdt = float(balance_usdt) * (cap / 100.0)
        notional_usdt = margin_usdt * lev
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/executor.py:842-848
```
        leverage_override: int | None = None,
        force_risk_based: bool = False,
    ) -> tuple[float, dict]:
        lev = int(leverage_override or getattr(self.risk, "leverage", 20))
        fixed_margin_mode = self.sizer is None or getattr(self.sizer, "mode", None) == "kasa_10_20x"
        if force_risk_based and fixed_margin_mode:
            qty = self.risk.position_size(max(balance, 0), price, stop)
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/executor.py:967-973
```
            await self._say(f"⛔ {symbol}: emir dolmadı; yerel pozisyon oluşturulmadı.")
            return
        lev = int(info.get("leverage") or dyn_lev)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        margin_usdt = float(
            fill.get("margin_usdt")
            or (estimated_margin * qty / requested_qty if estimated_margin and requested_qty else 0.0)
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/executor.py:1188-1194
```
            await self._say(f"⛔ {symbol}: kademe emri dolmadı; mevcut pozisyon değiştirilmedi.")
            return
        lev = int(info.get("leverage") or pos.leverage)
        estimated_margin = float(info.get("margin_usdt") or 0.0)
        add_margin = float(
            fill.get("margin_usdt")
            or (estimated_margin * add_qty / requested_add_qty if estimated_margin and requested_add_qty else 0.0)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:224-230
```
    def _margin_lock_blocks(self, order: Order, plan: TradePlan, price: float) -> bool:
        """v5.0: DOLUM ANI TEMİNAT KİLİDİ.

        Planlama anında teminat yeterliydi; ancak emir TTL boyunca beklerken
        başka emirler dolup teminatı tüketmiş olabilir. Eski kod dolum anında
        hiç kontrol etmiyordu. Artık her tick'te kalan miktarın gereken
        teminatı serbest teminatla karşılaştırılır; yetmiyorsa emir İPTAL
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:420-426
```
        dyn_margin = (
            filled_notional / plan.leverage
            if self.config.account.margin_per_position <= 0 else plan.margin
        )
        liq = compute_liquidation_price(
            avg_price, side, plan.leverage, self.config.funding
        )
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:531-537
```
            margin=margin, stop_loss=snapped, take_profit=take_profit,
            estimated_entry_fee=notional * self.cost_of(order.symbol, "maker_fee_rate"),
            estimated_exit_cost=notional * self.exit_cost_rate(order.symbol),
            estimated_funding_buffer=notional * funding_rate,
            net_risk_at_stop=notional * (fraction + cost_rate) + notional * funding_rate,
            liquidation_price=compute_liquidation_price(
                entry, plan.side, plan.leverage, self.config.funding
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/backtest.py:144-150
```
            stop_model=stop_model,
            margin_stop_fraction=margin_stop_fraction,
            margin_stop_liq_buffer=margin_stop_liq_buffer,
            capital_pct_per_entry=capital_pct,
            leverage=leverage,
            unlimited_pyramiding=(
                False if fixed_margin_usdt is not None else unlimited_pyramiding
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/backtest.py:441-447
```
                qty = self.risk.position_size(self.balance, sig.price, prepared["stop"])
                info = {"margin_usdt": qty * sig.price / max(1, leverage)}
            elif self.fixed_margin_usdt is not None:
                leverage = self.leverage
                if self.balance < self.fixed_margin_usdt:
                    return
                qty = self.fixed_margin_usdt * leverage / sig.price
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/backtest.py:476-482
```
                leverage = int(prepared["leverage"])
                qty = self.risk.position_size(self.balance, sig.price, prepared["stop"])
                info = {"margin_usdt": qty * sig.price / max(1, leverage)}
            else:
                leverage = self.leverage
                qty, info = self.risk.leveraged_entry_size(
                    self.balance, sig.price, self.capital_pct, leverage
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/exec/paper.py:224-230
```
    def _margin_lock_blocks(self, order: Order, plan: TradePlan, price: float) -> bool:
        """v5.0: DOLUM ANI TEMİNAT KİLİDİ.

        Planlama anında teminat yeterliydi; ancak emir TTL boyunca beklerken
        başka emirler dolup teminatı tüketmiş olabilir. Eski kod dolum anında
        hiç kontrol etmiyordu. Artık her tick'te kalan miktarın gereken
        teminatı serbest teminatla karşılaştırılır; yetmiyorsa emir İPTAL
```
