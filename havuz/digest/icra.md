# HAVUZ DEMETİ · ICRA

**Soru:** Emir icrası: post-only, kısmi dolum, amend, idempotency ve kayma. Hangi hata sınıfı gerçek parada pahalıya patlar?

Kanıt parçaları `dosya:satır` ile işaretlidir. Yalnızca bu kanıta dayan; kanıt yoksa 'veri yok' de, uydurma.

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:28-34
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:185-191
```
        self.fill_sim.register(order, baseline_per_second)
        self.pending_orders.setdefault(symbol, []).append(order)
        self.trades.append({
            "type": "ORDER_NEW", "order_id": order.id, "symbol": symbol,
            "side": plan.side, "order_type": order.order_type.value,
            "limit_price": limit_price, "quantity": order_quantity,
            "notional": plan.notional, "margin": plan.margin,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5_6_2__ic/ACARBOT_FINAL_v5.6.2/exec/paper.py:310-316
```
        self.fill_sim.release(order.id)
        self.trades.append({
            "type": "ORDER_CANCELED", "order_id": order.id, "symbol": order.symbol,
            "reason": "DOLUM_ANI_STOP_IHLALI", "live_price": price,
            "stop_loss": stop, "limit_price": order.limit_price,
            "filled_quantity": order.filled_quantity,
            "quantity": order.quantity, "timestamp": order.created_ms,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/exec/paper.py:28-34
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/exec/paper.py:185-191
```
        self.fill_sim.register(order, baseline_per_second)
        self.pending_orders.setdefault(symbol, []).append(order)
        self.trades.append({
            "type": "ORDER_NEW", "order_id": order.id, "symbol": symbol,
            "side": plan.side, "order_type": order.order_type.value,
            "limit_price": limit_price, "quantity": order_quantity,
            "notional": plan.notional, "margin": plan.margin,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.3__ic/ACARBOT_FINAL_v5.3/exec/paper.py:310-316
```
        self.fill_sim.release(order.id)
        self.trades.append({
            "type": "ORDER_CANCELED", "order_id": order.id, "symbol": order.symbol,
            "reason": "DOLUM_ANI_STOP_IHLALI", "live_price": price,
            "stop_loss": stop, "limit_price": order.limit_price,
            "filled_quantity": order.filled_quantity,
            "quantity": order.quantity, "timestamp": order.created_ms,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/exec/paper.py:28-34
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/exec/paper.py:54-60
```
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.1 (1)__ic/ACARBOT_FINAL_v5.1/exec/paper.py:115-121
```
        self.fill_sim.register(order, baseline_per_second)
        self.pending_orders.setdefault(symbol, []).append(order)
        self.trades.append({
            "type": "ORDER_NEW", "order_id": order.id, "symbol": symbol,
            "side": plan.side, "order_type": order.order_type.value,
            "limit_price": limit_price, "quantity": order_quantity,
            "notional": plan.notional, "margin": plan.margin,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/exec/paper.py:28-34
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/exec/paper.py:54-60
```
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.0__ic/ACARBOT_FINAL_v5.0/exec/paper.py:260-266
```
        plan_qty = order.quantity
        entry_fee = order.total_fee
        side = "LONG" if order.side == OrderSide.BUY else "SHORT"
        # Plan bağlamı: stop/TP hesabı emrin kaydedildiği plandan gelir.
        plan = self._plan_for_order.pop(order.id, None)
        motor = self._motor_for_order.pop(order.id, "fade")
        meta = self._meta_for_order.pop(order.id, {})
```

#### drive/toplama/arsiv-1/kripto-bot-v9.4.5-yama-test-rapor-binance__ic/kripto-bot-v9.4.5/src/exchanges.py:1086-1092
```
        if order.get("id") and (filled is None or (average is None and cost is None)):
            try:
                # Emri TEKRAR GÖNDERMEZ; yalnızca mevcut emrin nihai dolgusunu okur.
                fetched = await ex.fetch_order(order["id"], self._ccxt_symbol(symbol))
                order = {**order, **(fetched or {})}
                filled = order.get("filled")
                average = order.get("average")
```

#### drive/toplama/arsiv-1/kripto-bot-v9.4.5-yama-test-rapor-binance__ic/kripto-bot-v9.4.5/src/exchanges.py:1114-1120
```
            "fee": float((order.get("fee") or {}).get("cost") or 0.0),
            "id": order.get("id"),
            "client_order_id": order_id,
            "status": order.get("status"),
            "mode": self.mode,
            "exchange": target_ex,
            "emir_tipi": "market",
```

#### drive/toplama/arsiv-1/kripto-bot-v9.4.5-yama-test-rapor-binance__ic/kripto-bot-v9.4.5/src/exchanges.py:1451-1457
```
                f"Maker emir kurulamadı veya sonucu belirsiz (clientOrderId={client_id}): {e}"
            ) from e

        oid = order.get("id")
        filled = float(order.get("filled") or 0.0)
        avg_px = float(order.get("average") or limit_px)
        status = order
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/exec/paper.py:27-33
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/exec/paper.py:53-59
```
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v4.0__ic/ACARBOT_FINAL_v4.0/exec/paper.py:170-176
```
        plan_qty = order.quantity
        entry_fee = order.total_fee
        side = "LONG" if order.side == OrderSide.BUY else "SHORT"
        # Plan bağlamı: stop/TP hesabı emrin kaydedildiği plandan gelir.
        plan = self._plan_for_order.pop(order.id, None)
        motor = self._motor_for_order.pop(order.id, "fade")
        meta = self._meta_for_order.pop(order.id, {})
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.8__ic/ACARBOT_FINAL_v1.8/exec/paper.py:22-28
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.8__ic/ACARBOT_FINAL_v1.8/exec/paper.py:48-54
```
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.8__ic/ACARBOT_FINAL_v1.8/exec/paper.py:102-108
```
        self.fill_sim.register(order, baseline_per_second)
        self.pending_orders.setdefault(symbol, []).append(order)
        self.trades.append({
            "type": "ORDER_NEW", "order_id": order.id, "symbol": symbol,
            "side": plan.side, "order_type": order.order_type.value,
            "limit_price": limit_price, "quantity": order_quantity,
            "notional": plan.notional, "margin": plan.margin,
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/exchanges.py:947-953
```
        if order.get("id") and (filled is None or (average is None and cost is None)):
            try:
                # Emri TEKRAR GÖNDERMEZ; yalnızca mevcut emrin nihai dolgusunu okur.
                fetched = await ex.fetch_order(order["id"], self._ccxt_symbol(symbol))
                order = {**order, **(fetched or {})}
                filled = order.get("filled")
                average = order.get("average")
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/exchanges.py:975-981
```
            "fee": float((order.get("fee") or {}).get("cost") or 0.0),
            "id": order.get("id"),
            "client_order_id": order_id,
            "status": order.get("status"),
            "mode": self.mode,
            "exchange": target_ex,
            "emir_tipi": "market",
```

#### drive/toplama/arsiv-2/kripto-bot-v8.4-ve-raporlar-tam-paket__ic/kripto-bot-v8.4-mukemmel/src/exchanges.py:1169-1175
```
                f"Maker emir kurulamadı veya sonucu belirsiz (clientOrderId={client_id}): {e}"
            ) from e

        oid = order.get("id")
        filled = float(order.get("filled") or 0.0)
        avg_px = float(order.get("average") or limit_px)
        status = order
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/exec/paper.py:27-33
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/exec/paper.py:53-59
```
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v3.0__ic/ACARBOT_FINAL_v3.0/exec/paper.py:170-176
```
        plan_qty = order.quantity
        entry_fee = order.total_fee
        side = "LONG" if order.side == OrderSide.BUY else "SHORT"
        # Plan bağlamı: stop/TP hesabı emrin kaydedildiği plandan gelir.
        plan = self._plan_for_order.pop(order.id, None)
        motor = self._motor_for_order.pop(order.id, "fade")
        meta = self._meta_for_order.pop(order.id, {})
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/exec/paper.py:27-33
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/exec/paper.py:53-59
```
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v2.0.1__ic/ACARBOT_FINAL_v2.0.1/exec/paper.py:164-170
```
        plan_qty = order.quantity
        entry_fee = order.total_fee
        side = "LONG" if order.side == OrderSide.BUY else "SHORT"
        # Plan bağlamı: stop/TP hesabı emrin kaydedildiği plandan gelir.
        plan = self._plan_for_order.pop(order.id, None)
        motor = self._motor_for_order.pop(order.id, "fade")
        meta = self._meta_for_order.pop(order.id, {})
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/exchanges.py:910-916
```
        if order.get("id") and (filled is None or (average is None and cost is None)):
            try:
                # Emri TEKRAR GÖNDERMEZ; yalnızca mevcut emrin nihai dolgusunu okur.
                fetched = await ex.fetch_order(order["id"], self._ccxt_symbol(symbol))
                order = {**order, **(fetched or {})}
                filled = order.get("filled")
                average = order.get("average")
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/exchanges.py:938-944
```
            "fee": float((order.get("fee") or {}).get("cost") or 0.0),
            "id": order.get("id"),
            "client_order_id": order_id,
            "status": order.get("status"),
            "mode": self.mode,
            "exchange": target_ex,
            "emir_tipi": "market",
```

#### drive/toplama/arsiv-2/newkripto-arena-f582cf73-newkripto__ic/newkripto-arena-f582cf73-newkripto/src/exchanges.py:1110-1116
```
                f"Maker emir kurulamadı veya sonucu belirsiz (clientOrderId={client_id}): {e}"
            ) from e

        oid = order.get("id")
        filled = float(order.get("filled") or 0.0)
        avg_px = float(order.get("average") or limit_px)
        status = order
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/exchanges.py:941-947
```
        if order.get("id") and (filled is None or (average is None and cost is None)):
            try:
                # Emri TEKRAR GÖNDERMEZ; yalnızca mevcut emrin nihai dolgusunu okur.
                fetched = await ex.fetch_order(order["id"], self._ccxt_symbol(symbol))
                order = {**order, **(fetched or {})}
                filled = order.get("filled")
                average = order.get("average")
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/exchanges.py:969-975
```
            "fee": float((order.get("fee") or {}).get("cost") or 0.0),
            "id": order.get("id"),
            "client_order_id": order_id,
            "status": order.get("status"),
            "mode": self.mode,
            "exchange": target_ex,
            "emir_tipi": "market",
```

#### drive/toplama/arsiv-2/toplama 2/KRIPTO_BOT_WINDOWS_TEK_TIK_1_SAAT/src/exchanges.py:1141-1147
```
                f"Maker emir kurulamadı veya sonucu belirsiz (clientOrderId={client_id}): {e}"
            ) from e

        oid = order.get("id")
        filled = float(order.get("filled") or 0.0)
        avg_px = float(order.get("average") or limit_px)
        status = order
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.1__ic/ACARBOT_FINAL_v1.1/exec/paper.py:22-28
```
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.1__ic/ACARBOT_FINAL_v1.1/exec/paper.py:48-54
```
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v1.1__ic/ACARBOT_FINAL_v1.1/exec/paper.py:98-104
```
        self.fill_sim.register(order, baseline_per_second)
        self.pending_orders.setdefault(symbol, []).append(order)
        self.trades.append({
            "type": "ORDER_NEW", "order_id": order.id, "symbol": symbol,
            "side": plan.side, "order_type": order.order_type.value,
            "limit_price": limit_price, "quantity": plan.quantity,
            "ttl_ms": order.ttl_ms, "timestamp": now_ms, "mode": "paper",
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/exchanges.py:892-898
```
        if order.get("id") and (filled is None or (average is None and cost is None)):
            try:
                # Emri TEKRAR GÖNDERMEZ; yalnızca mevcut emrin nihai dolgusunu okur.
                fetched = await ex.fetch_order(order["id"], self._ccxt_symbol(symbol))
                order = {**order, **(fetched or {})}
                filled = order.get("filled")
                average = order.get("average")
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/exchanges.py:920-926
```
            "fee": float((order.get("fee") or {}).get("cost") or 0.0),
            "id": order.get("id"),
            "client_order_id": order_id,
            "status": order.get("status"),
            "mode": self.mode,
            "exchange": target_ex,
            "emir_tipi": "market",
```

#### drive/toplama/arsiv-2/newkripto-main__ic/newkripto-main/src/exchanges.py:1092-1098
```
                f"Maker emir kurulamadı veya sonucu belirsiz (clientOrderId={client_id}): {e}"
            ) from e

        oid = order.get("id")
        filled = float(order.get("filled") or 0.0)
        avg_px = float(order.get("average") or limit_px)
        status = order
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:1480-1486
```
            if fill.get("emir_tipi") in ("chase_limit", "maker+chase-limit"):
                self.stats["chase_orders"] += 1
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_order_success()
        except Exception as e:
            err_safe = safe_exception_msg(e)
            await self._say(f"⛔ {symbol} emir hatası: {err_safe}")
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:1762-1768
```
                    timeout=self.maker_timeout,
                    exchange=ex_name,
                )
            if fill.get("emir_tipi") in ("chase_limit", "maker+chase-limit"):
                self.stats["chase_orders"] += 1
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_order_success()
```

#### drive/toplama/arsiv-2/toplama 2/executor.py:1947-1953
```
                    fill = await self.broker.market_order(
                        symbol, order_side, requested_qty, price_hint=price,
                        exchange=pos.exchange or None, reduce_only=True
                    )
                except TypeError:
                    fill = await self.broker.market_order(
                        symbol, order_side, requested_qty, price_hint=price,
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:412-418
```
        order = Order(
            symbol="okx:X-USDT-SWAP", side=OrderSide.BUY,
            order_type=OrderType.POST_ONLY_LIMIT, quantity=plan.quantity,
            limit_price=100.0, created_ms=BASE_MS, ttl_ms=60_000,
        )
        broker.bind_plan(order, plan, "trend", risk_budget=5.0)
        aligned = broker._plan_for_order[order.id]
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:1778-1784
```
        order, plan = self._place(b)
        assert b._stale_fill_blocks(order, plan, float("nan")) is False
        assert b._stale_fill_blocks(order, plan, 0.0) is False

    def test_counter_not_double_counted_per_tick(self):
        """Aynı emir ikinci tick'te yeniden sayılmamalı (pozisyon açıldı)."""
        b = self._broker(cancel=False)
```

#### drive/toplama/arsiv-4/ACARBOT_FINAL_v5.4__ic/ACARBOT_FINAL_v5.4/tests/test_v52_hardening.py:1933-1939
```
        plan = RiskManager(cfg).plan(100.0, 0.015, "LONG", motor="trend")
        order = b.place_entry("X:T", plan, now_ms=0, baseline_per_second=1e12)
        b.bind_plan(order, plan, "trend")
        aligned = b._plan_for_order[order.id]
        b.process_entry_tick("X:T", aligned.entry * 0.999, 1e12, 1_000)
        pos = b.portfolio.positions["X:T"]
        assert pos.entry == order.limit_price
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:412-418
```
        order = Order(
            symbol="okx:X-USDT-SWAP", side=OrderSide.BUY,
            order_type=OrderType.POST_ONLY_LIMIT, quantity=plan.quantity,
            limit_price=100.0, created_ms=BASE_MS, ttl_ms=60_000,
        )
        broker.bind_plan(order, plan, "trend", risk_budget=5.0)
        aligned = broker._plan_for_order[order.id]
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:1786-1792
```
        order, plan = self._place(b)
        assert b._stale_fill_blocks(order, plan, float("nan")) is False
        assert b._stale_fill_blocks(order, plan, 0.0) is False

    def test_counter_not_double_counted_per_tick(self):
        """Aynı emir ikinci tick'te yeniden sayılmamalı (pozisyon açıldı)."""
        b = self._broker(cancel=False)
```

#### drive/toplama/arsiv-4/ACARBOT_V6.2_NORMAL__ic/ACARBOT_V6.2_NORMAL/tests/test_v52_hardening.py:1941-1947
```
        plan = RiskManager(cfg).plan(100.0, 0.015, "LONG", motor="trend")
        order = b.place_entry("X:T", plan, now_ms=0, baseline_per_second=1e12)
        b.bind_plan(order, plan, "trend")
        aligned = b._plan_for_order[order.id]
        b.process_entry_tick("X:T", aligned.entry * 0.999, 1e12, 1_000)
        pos = b.portfolio.positions["X:T"]
        assert pos.entry == order.limit_price
```
