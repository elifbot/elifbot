"""Paper broker — emir yaşam döngüsü tabanlı gerçekçi simülasyon.

Eski `infra/paper.py`'nin yerine geçer:
  - Girişler ARTIK anında dolmaz: POST_ONLY_LIMIT emri kuyruk modeliyle
    dolabilir, kısmen dolabilir veya TTL sonunda EXPIRED olabilir.
  - Post-only emre taker kayması uygulanmaz (Y2-5 tutarlılık düzeltmesi).
  - Çıkışlar: stop (kaymalı market), TP1 kısmi kâr (maker limit),
    ATR trailing, zaman stopu, momentum çıkışı, acil net-zarar stopu,
    likidasyon.
  - Zarar tavanı NET hesaplanır: ücretler + kayma + funding dâhil (Y1-B/Y2-4).
  - Funding ödemeleri ve likidasyon fiyatı izlenir (Y1-C).
"""

from __future__ import annotations

import logging
from dataclasses import replace as dc_replace
from math import ceil, floor, isfinite

from core.config import SuperConfig
from core.portfolio import (
    Position,
    Portfolio,
    compute_funding_payment,
    compute_liquidation_price,
)
from core.risk import TradePlan
from exec.orders import (
    Fill,
    MakerFillSimulator,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    market_fill_price,
)

logger = logging.getLogger(__name__)

_STOP_REASONS = {"stop_loss", "position_loss_stop", "trailing_stop", "liquidation"}


class PaperBroker:
    """Yerel borsa simülatörü. Gerçek borsaya ASLA emir göndermez."""

    def __init__(
        self,
        config: SuperConfig | None = None,
        initial_balance: float = 1_000.0,
    ) -> None:
        self.config = config or SuperConfig()
        acc = self.config.account
        self.portfolio = Portfolio(initial_balance)
        self.maker_fee_rate = acc.maker_fee_rate
        self.taker_fee_rate = acc.taker_fee_rate
        self.stop_slippage_rate = acc.stop_slippage_rate
        self.extra_slippage_rate = acc.extra_slippage_rate
        self.max_loss_per_position = acc.max_loss_per_position
        # v5.2: ÖLÇÜLMÜŞ sembol maliyetleri. Backtest ölçülmüş CostModel
        # kullanirken canli yol düz config varsayilani kullaniyordu; bu,
        # DOGE/ADA gibi genis kaymali sembollerde canlinin backtest'ten
        # IYIMSER olmasina yol aciyordu. set_symbol_costs() ile kapatildi.
        self.symbol_costs: dict[str, dict[str, float]] = {}
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
        self.trades: list[dict] = []
        self.mode = "paper"
        self._order_seq = 0
        # v5.0: dolum anı teminat kilidi + fiyat ızgarası hizalama
        self.margin_lock_cancels = 0
        # v5.2: dolum anı stop ihlali — ölçüm + opt-in iptal
        self.stale_fill_cancels = 0
        self.adverse_selection_fills = 0
        self._adverse_orders: set[str] = set()
        self.grid_realign_count = 0
        self.tick_sizes: dict[str, float] = {}
        self._plan_for_order: dict[str, TradePlan] = {}
        self._motor_for_order: dict[str, str] = {}
        self._meta_for_order: dict[str, dict] = {}   # v2.0: skor/rejim/oylar
        self.risk_manager_ref = None  # likidasyon/funding için RiskManager

    # ------------------------------------------------------------------
    # Giriş emirleri (yaşam döngüsü ile)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # v5.2: ölçülmüş sembol maliyetleri
    # ------------------------------------------------------------------

    def set_symbol_costs(
        self,
        symbol: str,
        *,
        maker_fee_rate: float | None = None,
        taker_fee_rate: float | None = None,
        stop_slippage_rate: float | None = None,
        extra_slippage_rate: float | None = None,
    ) -> None:
        """Sembol için ölçülmüş maliyet oranlarını kaydet (oran, bps değil).

        Verilmeyen alanlar config varsayılanında kalır. Bu sayede ölçülen
        sembol gerçek maliyetle, ölçülmeyen sembol etiketli varsayılanla
        işlem görür — ikisi de aynı simülatörden geçer.
        """
        bucket = self.symbol_costs.setdefault(symbol, {})
        for key, value in (
            ("maker_fee_rate", maker_fee_rate),
            ("taker_fee_rate", taker_fee_rate),
            ("stop_slippage_rate", stop_slippage_rate),
            ("extra_slippage_rate", extra_slippage_rate),
        ):
            if value is None:
                continue
            value = float(value)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{key} negatif veya sonlu olmayan değer: {value}")
            bucket[key] = value

    def cost_of(self, symbol: str, key: str) -> float:
        """Sembolün maliyet oranı; ölçüm yoksa config varsayılanı."""
        bucket = self.symbol_costs.get(symbol)
        if bucket is not None and key in bucket:
            return bucket[key]
        return float(getattr(self, key))

    def exit_cost_rate(self, symbol: str, extra: bool = True) -> float:
        """Çıkış maliyeti: taker ücreti + stop kayması (+ ek kayma)."""
        return (
            self.cost_of(symbol, "taker_fee_rate")
            + self.cost_of(symbol, "stop_slippage_rate")
            + (self.cost_of(symbol, "extra_slippage_rate") if extra else 0.0)
        )

    def cost_provenance(self) -> dict:
        """Hangi sembol ölçüldü, hangisi varsayılan? (rapor kanıtı)"""
        return {
            "measured_symbols": sorted(self.symbol_costs),
            "measured_count": len(self.symbol_costs),
            "defaults": {
                "maker_fee_rate": self.maker_fee_rate,
                "taker_fee_rate": self.taker_fee_rate,
                "stop_slippage_rate": self.stop_slippage_rate,
                "extra_slippage_rate": self.extra_slippage_rate,
            },
        }

    def place_entry(
        self,
        symbol: str,
        plan: TradePlan,
        now_ms: int,
        baseline_per_second: float = 0.0,
    ) -> Order:
        """Post-only limit giriş emri açar ve kuyruk modeline kaydeder."""
        if symbol in self.portfolio.positions:
            raise ValueError(f"{symbol} için pozisyon zaten açık")
        if self.pending(symbol):
            raise ValueError(f"{symbol} için bekleyen emir var")
        side = OrderSide.BUY if plan.side == "LONG" else OrderSide.SELL
        # Limit fiyatı: bid/ask tarafınatick iyileştirmesi (kayıt amaçlı; dolum
        # simülasyonu kuyruk modeliyle yapılır, VWAP kayması YOKTUR).
        tick_adjust = plan.entry * 0.0002
        limit_price = (
            plan.entry - tick_adjust if side == OrderSide.BUY
            else plan.entry + tick_adjust
        )
        self._order_seq += 1
        # v5.0 (v1.8 kuralı): hedef net risk NOMİNAL üzerinden sabittir.
        # Limit fiyatı referanstan farklıysa miktar, dolumda aynı notionalı
        # verecek şekilde ayarlanır.
        order_quantity = (
            plan.notional / limit_price if limit_price > 0 else plan.quantity
        )
        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=order_quantity,
            limit_price=limit_price,
            created_ms=now_ms,
            ttl_ms=int(self.config.exit.order_ttl_seconds * 1000),
            maker_fee_rate=self.maker_fee_rate,
            taker_fee_rate=self.taker_fee_rate,
        )
        self.fill_sim.register(order, baseline_per_second)
        self.pending_orders.setdefault(symbol, []).append(order)
        self.trades.append({
            "type": "ORDER_NEW", "order_id": order.id, "symbol": symbol,
            "side": plan.side, "order_type": order.order_type.value,
            "limit_price": limit_price, "quantity": order_quantity,
            "notional": plan.notional, "margin": plan.margin,
            "net_risk": plan.net_risk_at_stop,
            "ttl_ms": order.ttl_ms, "timestamp": now_ms, "mode": "paper",
        })
        return order

    def pending(self, symbol: str) -> list[Order]:
        return [o for o in self.pending_orders.get(symbol, []) if o.is_active]

    def reserved_margin(self, exclude_order_id: str | None = None) -> float:
        """v5.0: bekleyen giriş emirlerinin bağlanmış teminatı.

        Yeni giriş planlanırken açık pozisyonlara EK olarak bu rezerv düşülür;
        aynı anda bekleyen birden fazla emir bakiyeyi aşamaz.
        """
        total = 0.0
        for orders in self.pending_orders.values():
            for order in orders:
                if not order.is_active:
                    continue
                if exclude_order_id is not None and order.id == exclude_order_id:
                    continue
                plan = self._plan_for_order.get(order.id)
                if plan is not None:
                    total += plan.margin * (1.0 + self.maker_fee_rate)
        return total

    def free_margin(self, exclude_order_id: str | None = None) -> float:
        """v5.0: şu anda SERBEST olan teminat (emir kendi rezervini saymaz)."""
        return self.portfolio.free_balance() - max(
            0.0, self.reserved_margin(exclude_order_id=exclude_order_id)
        )

    def _margin_lock_blocks(self, order: Order, plan: TradePlan, price: float) -> bool:
        """v5.0: DOLUM ANI TEMİNAT KİLİDİ.

        Planlama anında teminat yeterliydi; ancak emir TTL boyunca beklerken
        başka emirler dolup teminatı tüketmiş olabilir. Eski kod dolum anında
        hiç kontrol etmiyordu. Artık her tick'te kalan miktarın gereken
        teminatı serbest teminatla karşılaştırılır; yetmiyorsa emir İPTAL
        edilir ve pozisyon açılmaz.
        """
        remaining = order.quantity - order.filled_quantity
        if remaining <= 0:
            return False
        ref_price = order.limit_price if order.limit_price else price
        if not isfinite(ref_price) or ref_price <= 0 or plan.leverage <= 0:
            return False
        required = remaining * ref_price / plan.leverage
        required *= 1.0 + self.maker_fee_rate
        free = self.free_margin(exclude_order_id=order.id)
        if required <= free + 1e-9:
            return False
        order.cancel(OrderStatus.CANCELED)
        self.fill_sim.release(order.id)
        self._plan_for_order.pop(order.id, None)
        self._motor_for_order.pop(order.id, None)
        self._meta_for_order.pop(order.id, None)
        self.margin_lock_cancels += 1
        self.trades.append({
            "type": "ORDER_CANCELLED", "order_id": order.id, "symbol": order.symbol,
            "reason": "TEMINAT_KILIDI", "required_margin": required,
            "free_margin": free, "filled_quantity": order.filled_quantity,
            "quantity": order.quantity, "timestamp": order.created_ms,
            "mode": "paper",
        })
        logger.info(
            "TEMİNAT KİLİDİ: [%s] dolum anında teminat yetmedi — "
            "gereken %.2f USDT > serbest %.2f USDT, emir iptal",
            order.symbol, required, free,
        )
        return True

    def _stale_fill_blocks(self, order: Order, plan: TradePlan, price: float) -> bool:
        """v5.2: DOLUM ANI STOP İHLALİ KONTROLÜ.

        Bulunan hata (15 dk canlı test, 2026-11-08 05:21:38 → 05:22:04):
        GNO SHORT için 111.92238 limit emri kondu, stop 112.26 idi. Emir
        26 sn bekledi; bu sırada fiyat 112.45'e çıktı — yani STOPUN
        ÖTESİNE. Maker simülatörü emri limit fiyatından doldurdu ve
        pozisyon AYNİ tick'te stop oldu (`hold_ms=0`, −31,37 USDT,
        hedefin 1,255x'i).

        Kök neden: v3.1'in bayat sinyal koruması yalnız EMİR KOYULURKEN
        çalışıyordu. Emir TTL boyunca beklerken fiyat stopu geçerse
        kimse kontrol etmiyordu. Sonuç: doğuşta ölü pozisyon.

        v5.2 KARARI: bu durum varsayılan olarak ENGELLENMEZ, ÖLÇÜLÜR.
        Ters seçilim gerçektir; iptal etmek simülatörü iyimser yapar ve
        v5.0'da bilinçli olarak kapatılan bir kayıp-gizleme davranışını
        geri getirir. `adverse_selection_fills` sayacı bunu görünür kılar.
        İptal yalnız `exit.cancel_on_stop_breach_at_fill=True` ile olur ve
        rapor İYİMSER diye etiketlenir.
        """
        if order.filled_quantity > 0:
            # Kısmen dolmuş emirde pozisyon zaten var; stop yönetimi
            # pozisyon tarafında yapılır, burada iptal edilmez.
            return False
        stop = float(plan.stop_loss or 0.0)
        if stop <= 0 or not isfinite(price) or price <= 0:
            return False
        is_long = order.side == OrderSide.BUY
        breached = (price <= stop) if is_long else (price >= stop)
        if not breached:
            return False
        # ÖLÇÜM her politikada yapılır: "doğuşta ölü" dolum sayısı.
        # Bu, ters seçilimin büyüklüğünü görünür kılar; gizlemez.
        self.adverse_selection_fills += 1
        self._adverse_orders.add(order.id)
        if not getattr(self.config.exit, "cancel_on_stop_breach_at_fill", False):
            # VARSAYILAN: gerçekçi davranış — dolum olur, aynı tick'te stop.
            logger.info(
                "TERS SEÇİLİM: [%s] canlı fiyat %.6g stop %.6g ötesinde — "
                "limit doluyor ve doğuşta stop olacak (gerçekçi model)",
                order.symbol, price, stop,
            )
            return False
        order.status = OrderStatus.CANCELED
        self.stale_fill_cancels += 1
        self.fill_sim.release(order.id)
        self.trades.append({
            "type": "ORDER_CANCELED", "order_id": order.id, "symbol": order.symbol,
            "reason": "DOLUM_ANI_STOP_IHLALI", "live_price": price,
            "stop_loss": stop, "limit_price": order.limit_price,
            "filled_quantity": order.filled_quantity,
            "quantity": order.quantity, "timestamp": order.created_ms,
            "mode": "paper",
        })
        logger.info(
            "BAYAT DOLUM ENGELI: [%s] canlı fiyat %.6g stop %.6g ötesinde — "
            "emir iptal (doğuşta ölü pozisyon engellendi)",
            order.symbol, price, stop,
        )
        return True

    def process_entry_tick(
        self,
        symbol: str,
        price: float,
        tick_base_volume: float,
        now_ms: int,
    ) -> Fill | None:
        """Bekleyen giriş emirlerini tick ile besler; dolarsa pozisyon açar."""
        fill = None
        for order in self.pending(symbol):
            # v5.0: dolumdan ÖNCE teminat kilidi
            lock_plan = self._plan_for_order.get(order.id)
            if lock_plan is not None and self._margin_lock_blocks(order, lock_plan, price):
                continue
            # v5.2: dolum anı stop ihlali — fiyat stopu geçtiyse DOLDURMA
            if lock_plan is not None and self._stale_fill_blocks(order, lock_plan, price):
                continue
            result = self.fill_sim.process_tick(order, price, tick_base_volume, now_ms)
            if result is not None:
                fill = result
                self.portfolio.balance -= result.fee
                self.trades.append({
                    "type": "ORDER_FILL", "order_id": order.id, "symbol": symbol,
                    "price": result.price, "quantity": result.quantity,
                    "fee": result.fee, "maker": result.is_maker,
                    "partial": order.status == OrderStatus.PARTIALLY_FILLED,
                    "timestamp": now_ms, "mode": "paper",
                })
            if order.status == OrderStatus.FILLED:
                self._open_position_from_order(symbol, order, now_ms)
        # Süresi dolanları temizle
        expired = [
            o for o in self.pending_orders.get(symbol, [])
            if o.status == OrderStatus.EXPIRED
        ]
        for order in expired:
            self.trades.append({
                "type": "ORDER_EXPIRED", "order_id": order.id, "symbol": symbol,
                "filled_quantity": order.filled_quantity,
                "quantity": order.quantity, "timestamp": now_ms, "mode": "paper",
            })
            self.fill_sim.release(order.id)
            # v3.0: kısmen dolmuş emrin DOLAN kısmı pozisyona dönüşür.
            # Eski davranış: dolan kısım sadece ücret düşer, pozisyon
            # açılmazdı → borsa tarafıyla (kısmi dolum pozisyon yaratır)
            # tutarsızdı ve muhasebe sızıntısıydı.
            if order.filled_quantity > 0:
                self._open_position_from_order(symbol, order, now_ms)
        if expired:
            self.pending_orders[symbol] = [
                o for o in self.pending_orders[symbol] if o.is_active
            ]
        # v5.0: teminat kilidiyle iptal edilenleri de listeden temizle
        if any(
            o.status == OrderStatus.CANCELED
            for o in self.pending_orders.get(symbol, [])
        ):
            self.pending_orders[symbol] = [
                o for o in self.pending_orders[symbol]
                if o.status != OrderStatus.CANCELED
            ]
        return fill

    def _open_position_from_order(
        self, symbol: str, order: Order, now_ms: int
    ) -> None:
        avg_price = order.average_fill_price
        if avg_price is None or order.filled_quantity <= 0:
            return
        entry_fee = order.total_fee
        side = "LONG" if order.side == OrderSide.BUY else "SHORT"
        # Plan bağlamı: stop/TP hesabı emrin kaydedildiği plandan gelir.
        plan = self._plan_for_order.pop(order.id, None)
        motor = self._motor_for_order.pop(order.id, "fade")
        meta = self._meta_for_order.pop(order.id, {})
        if plan is None:
            raise ValueError("dolum için plan kaydı eksik")
        # Gerçek dolum fiyatına göre stop/TP/likidasyonu yeniden ölçekle.
        stop_loss = avg_price * (plan.stop_loss / plan.entry)
        take_profit = (
            avg_price * (plan.take_profit / plan.entry)
            if plan.take_profit is not None else None
        )
        stop_fraction = abs(plan.entry - plan.stop_loss) / plan.entry
        filled_notional = order.filled_quantity * avg_price
        # v5.0: funding tamponu notional ile ölçeklenir; teminat dinamiktir.
        _plan_notional = getattr(plan, "notional", 0.0) or 0.0
        funding_rate = (
            plan.estimated_funding_buffer / _plan_notional
            if _plan_notional > 0 else 0.0
        )
        net_risk = filled_notional * (
            stop_fraction + self._cost_rate() + funding_rate
        )
        dyn_margin = (
            filled_notional / plan.leverage
            if self.config.account.margin_per_position <= 0 else plan.margin
        )
        liq = compute_liquidation_price(
            avg_price, side, plan.leverage, self.config.funding
        )
        position = Position(
            symbol=symbol, side=side, entry=avg_price,
            quantity=order.filled_quantity,
            initial_quantity=order.filled_quantity,
            margin=dyn_margin,
            stop_loss=stop_loss,
            opened_at_ms=now_ms,
            entry_fee=entry_fee,
            leverage=plan.leverage,
            liquidation_price=liq,
            take_profit=take_profit,
            initial_net_risk=net_risk,
            motor=motor,
            score=float(meta.get("score", 0.0)),
            regime=str(meta.get("regime", "")),
            signal_key=str(meta.get("signal_key", order.id)),
        )
        self.portfolio.positions[symbol] = position
        self.trades.append({
            "type": "OPEN", "symbol": symbol, "side": side,
            "price": avg_price, "quantity": order.filled_quantity,
            "fee": entry_fee, "margin": dyn_margin,
            "notional": filled_notional,
            "stop_loss": stop_loss, "take_profit": take_profit,
            "liquidation_price": liq, "net_risk": net_risk,
            "motor": position.motor, "order_id": order.id,
            "signal_key": position.signal_key,
            "fills": len(order.fills), "timestamp": now_ms, "mode": "paper",
            "order_type": "post_only", "reduce_only": False,
            "score": position.score, "regime": position.regime,
            "experts": meta.get("experts", ""),
            "partial": order.filled_quantity < order.quantity - 1e-12,
        })

    def _align_plan_to_grid(
        self, order: Order, plan: TradePlan, risk_budget: float | None = None,
    ) -> TradePlan:
        """v5.0: planı GERÇEK dolum fiyatına ve fiyat ızgarasına oturtur.

        Maker emir her zaman limit fiyatından dolar. Eski kod stopu referans
        girişten hesaplıyor, dolumda `avg_price / plan.entry` oranıyla
        ölçekliyordu; bu oran stopu yeniden ızgara DIŞINA taşıyordu.
        Izgarası kaba coinlerde (BTTC: tick fiyatın %2,78'i) bu, 25 USDT
        hedefini 28 USDT'ye çıkarıyordu.

        Çözüm: referans limit fiyatı, stop ızgaraya DIŞA yuvarlanır, pozisyon
        bu gerçek mesafeden yeniden boyutlanır. plan.entry == dolum fiyatı
        olur, ölçekleme oranı 1'dir ve stop ızgarada kalır.
        """
        tick = self.tick_sizes.get(order.symbol, 0.0)
        entry = order.limit_price
        if (
            tick <= 0 or not isfinite(tick) or entry is None
            or entry <= 0 or order.filled_quantity > 0 or plan.entry <= 0
        ):
            return plan
        direction = 1.0 if plan.side == "LONG" else -1.0
        raw_fraction = (
            plan.raw_stop_distance_fraction
            if plan.raw_stop_distance_fraction > 0
            else abs(plan.entry - plan.stop_loss) / plan.entry
        )
        if raw_fraction <= 0:
            return plan
        steps = entry * (1.0 - direction * raw_fraction) / tick
        snapped = (floor(steps) if plan.side == "LONG" else ceil(steps)) * tick
        if snapped <= 0:
            return plan
        fraction = abs(entry - snapped) / entry
        widen = self.config.exit.stop_tick_max_widen_ratio
        if widen > 0 and fraction > raw_fraction * widen:
            return plan  # risk.plan bu enstrümanı zaten reddediyor
        cost_rate = self._cost_rate()
        _plan_notional = getattr(plan, "notional", 0.0) or 0.0
        funding_rate = (
            plan.estimated_funding_buffer / _plan_notional
            if _plan_notional > 0 else 0.0
        )
        per_unit = fraction + cost_rate + funding_rate
        if per_unit <= 0:
            return plan
        # v5.2: dinamik butce verildiyse sabit tavan ONU EZMEZ.
        # (v5.2 oncesi bu satir backtest'in verdigi butceyi sifirliyordu.)
        _budget = (
            risk_budget if risk_budget is not None and risk_budget > 0
            else self.max_loss_per_position
        )
        notional = _budget / per_unit
        acc = self.config.account
        if acc.max_notional_per_position > 0:
            notional = min(notional, acc.max_notional_per_position)
        quantity = notional / entry
        order.quantity = quantity
        tp_r = self.config.exit.tp1_r_multiple
        take_profit = (
            entry * (1.0 + direction * tp_r * fraction) if tp_r > 0 else None
        )
        margin = (
            notional / plan.leverage if acc.margin_per_position <= 0
            else acc.margin_per_position
        )
        aligned = dc_replace(
            plan, entry=entry, quantity=quantity, notional=notional,
            margin=margin, stop_loss=snapped, take_profit=take_profit,
            estimated_entry_fee=notional * self.cost_of(order.symbol, "maker_fee_rate"),
            estimated_exit_cost=notional * self.exit_cost_rate(order.symbol),
            estimated_funding_buffer=notional * funding_rate,
            net_risk_at_stop=notional * (fraction + cost_rate) + notional * funding_rate,
            liquidation_price=compute_liquidation_price(
                entry, plan.side, plan.leverage, self.config.funding
            ),
            raw_stop_distance_fraction=raw_fraction,
        )
        self.grid_realign_count += 1
        for rec in reversed(self.trades):
            if rec.get("type") == "ORDER_NEW" and rec.get("order_id") == order.id:
                rec.update({
                    "quantity": quantity, "notional": notional,
                    "margin": margin, "net_risk": aligned.net_risk_at_stop,
                    "stop_loss": snapped, "grid_aligned": True,
                })
                break
        return aligned

    def bind_plan(self, order: Order, plan: TradePlan, motor: str,
                  meta: dict | None = None,
                  risk_budget: float | None = None) -> None:
        """Emir ile plan, motor ve meta bağlar (v5.0: ızgara hizalı).

        v5.2: risk_budget verilirse ızgara hizalaması da o bütçeyi kullanır.
        """
        self._plan_for_order[order.id] = self._align_plan_to_grid(
            order, plan, risk_budget=risk_budget,
        )
        self._motor_for_order[order.id] = motor
        if meta:
            self._meta_for_order[order.id] = meta

    def cancel_pending_entries(self, now_ms: int, reason: str = "safe_mode") -> int:
        """Güvenli mod / kill switch: tüm bekleyen girişleri iptal eder."""
        count = 0
        for symbol, orders in self.pending_orders.items():
            for order in orders:
                if order.is_active:
                    order.cancel(OrderStatus.CANCELED)
                    self.trades.append({
                        "type": "ORDER_CANCELED", "order_id": order.id,
                        "symbol": symbol, "reason": reason,
                        "timestamp": now_ms, "mode": "paper",
                    })
                    self.fill_sim.release(order.id)
                    count += 1
        return count

    # ------------------------------------------------------------------
    # Çıkışlar
    # ------------------------------------------------------------------

    def close_position_market(
        self,
        symbol: str,
        price: float,
        reason: str,
        now_ms: int,
        extra_slippage: bool = False,
    ) -> dict | None:
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return None
        slippage_rate = self.cost_of(symbol, "stop_slippage_rate") + (
            self.cost_of(symbol, "extra_slippage_rate") if extra_slippage else 0.0
        )
        fill_price = market_fill_price(
            price,
            OrderSide.SELL if position.side == "LONG" else OrderSide.BUY,
            slippage_rate if reason in _STOP_REASONS else 0.0,
        )
        return self._settle_close(symbol, position, fill_price, price, reason, now_ms, full=True)

    def close_partial(
        self,
        symbol: str,
        fraction: float,
        price: float,
        reason: str,
        now_ms: int,
    ) -> dict | None:
        """TP1 kısmi kâr alma: maker limit dolumu (kayma yok)."""
        position = self.portfolio.positions.get(symbol)
        if position is None or not 0 < fraction < 1:
            return None
        close_qty = min(position.quantity, position.initial_quantity * fraction)
        if close_qty <= 0:
            return None
        fee = price * close_qty * self.cost_of(symbol, "maker_fee_rate")
        gross = position.direction * (price - position.entry) * close_qty
        entry_fee_share = position.entry_fee * (close_qty / position.initial_quantity)
        margin_share = position.margin * (close_qty / position.initial_quantity)
        position.quantity -= close_qty
        position.margin -= margin_share
        position.entry_fee -= entry_fee_share
        position.tp1_realized_pnl += gross - fee - entry_fee_share
        position.tp1_done = True
        self.portfolio.balance += gross - fee
        trade = {
            "type": "PARTIAL_CLOSE", "symbol": symbol, "side": position.side,
            "price": price, "quantity": close_qty, "gross_pnl": gross,
            "fee": fee, "net_pnl": gross - fee - entry_fee_share,
            "reason": reason, "timestamp": now_ms, "mode": "paper",
            "motor": position.motor, "maker": True,
        }
        self.trades.append(trade)
        return trade

    def _settle_close(
        self,
        symbol: str,
        position: Position,
        fill_price: float,
        trigger_price: float,
        reason: str,
        now_ms: int,
        full: bool = True,
        liquidation: bool = False,
    ) -> dict:
        qty = position.quantity
        exit_fee = fill_price * qty * (
            self.config.funding.liquidation_fee_rate
            if liquidation else self.cost_of(symbol, "taker_fee_rate")
        )
        gross = position.direction * (fill_price - position.entry) * qty
        net = (
            gross + position.tp1_realized_pnl
            - position.entry_fee - exit_fee - position.funding_paid
        )
        del self.portfolio.positions[symbol]
        self.portfolio.balance += gross - exit_fee
        r_multiple = (
            net / position.initial_net_risk
            if position.initial_net_risk > 0 else 0.0
        )
        trade = {
            "type": "CLOSE", "symbol": symbol, "side": position.side,
            "entry": position.entry, "trigger_price": trigger_price,
            "price": fill_price, "quantity": qty,
            "gross_pnl": gross, "entry_fee": position.entry_fee,
            "fee": exit_fee, "funding_paid": position.funding_paid,
            "slippage": abs(fill_price - trigger_price) * qty,
            "pnl": net, "r_multiple": r_multiple,
            # v5.1: oturum sonu denetim — gerçekleşen/hedef kayıp oranı ve
            # stop aşımı (overshoot) için gerekli iki alan.
            "target_net_risk": position.initial_net_risk,
            "stop_loss": position.stop_loss,
            "reason": reason, "motor": position.motor,
            "order_id": position.signal_key,
            "hold_ms": now_ms - position.opened_at_ms,
            "timestamp": now_ms, "mode": "paper",
            "execution_type": "liquidation" if liquidation else (
                "stop_market" if reason in _STOP_REASONS else "market"
            ),
            "reduce_only": True, "tp1_done": position.tp1_done,
            "score": position.score, "regime": position.regime,
        }
        self.trades.append(trade)
        return trade

    def close_all(
        self,
        prices: dict[str, float],
        now_ms: int,
        reason: str = "kill_switch",
    ) -> list[dict]:
        trades = []
        for symbol in list(self.portfolio.positions):
            price = prices.get(symbol)
            if price is None:
                continue
            trade = self.close_position_market(symbol, price, reason, now_ms)
            if trade is not None:
                trades.append(trade)
        return trades

    # ------------------------------------------------------------------
    # Pozisyon yönetimi — tick yolu (canlı)
    # ------------------------------------------------------------------

    def manage_position_tick(
        self,
        symbol: str,
        price: float,
        now_ms: int,
        atr: float | None = None,
        funding_rate: float | None = None,
    ) -> list[dict]:
        """Her tick'te: likidasyon → acil net stop → stop → trailing.

        Funding ödemesi `apply_funding` ile ayrı çağrılır.
        """
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return []
        events: list[dict] = []
        if self.risk_manager_ref is not None and self.risk_manager_ref.check_liquidation(position, price):
            events.append(self._settle_close(
                symbol, position, price, price, "liquidation", now_ms, liquidation=True,
            ))
            return events
        # Acil net-zarar stopu: maliyet dâhil net PnL tavanı (Y1-B/Y2-4).
        if position.net_pnl(price, self.cost_of(symbol, "taker_fee_rate"),
                            self.cost_of(symbol, "stop_slippage_rate")
                            + self.cost_of(symbol, "extra_slippage_rate")) \
                <= -self.max_loss_per_position:
            events.append(self.close_position_market(
                symbol, price, "position_loss_stop", now_ms, extra_slippage=True,
            ))
            return events
        # Klasik stop
        if position.side == "LONG" and price <= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(symbol, price, reason, now_ms))
            return events
        if position.side == "SHORT" and price >= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(symbol, price, reason, now_ms))
            return events
        self._update_trailing(position, price, atr)
        return events

    # ------------------------------------------------------------------
    # Pozisyon yönetimi — mum yolu (backtest ve 5m kapanışı)
    # ------------------------------------------------------------------

    def manage_position_candle(
        self,
        symbol: str,
        candle,
        now_ms: int,
        atr: float | None = None,
        impulse_pct: float | None = None,
        rvol: float | None = None,
        funding_rate: float | None = None,
        intrabar: bool = False,
    ) -> list[dict]:
        """Mum bazlı çıkış yönetimi; MUHAFAZAKÂR sıralama: stop önce.

        v5.1 `intrabar=True`: bu bir ALT mumdur (1m). Bar sayacı ve son mum
        zamanı güncellenmez; kaba bar (5m) başına tek artış çağıranın
        sorumluluğundadır. Aksi hâlde zaman bazlı çıkış 5 kat erken tetiklenir.


        Aynı mumda hem stop hem TP seviyesi varsa önce STOP varsayılır
        (intrabar sıra belirsizliğinde zararlı senaryo seçilir).
        """
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return []
        events: list[dict] = []
        if not intrabar and candle.timestamp > position.last_candle_timestamp:
            position.bars_held += 1
            position.last_candle_timestamp = candle.timestamp

        # Likidasyon
        if self.risk_manager_ref is not None:
            worst = candle.low if position.side == "LONG" else candle.high
            if self.risk_manager_ref.check_liquidation(position, worst):
                events.append(self._settle_close(
                    symbol, position, worst, worst, "liquidation", now_ms,
                    liquidation=True,
                ))
                return events

        # Acil net stop: en kötü fiyat üzerinden NET hesap (maliyet dâhil).
        worst_price = candle.low if position.side == "LONG" else candle.high
        if position.net_pnl(worst_price, self.cost_of(symbol, "taker_fee_rate"),
                            self.cost_of(symbol, "stop_slippage_rate")
                            + self.cost_of(symbol, "extra_slippage_rate")) \
                <= -self.max_loss_per_position:
            events.append(self.close_position_market(
                symbol, worst_price, "position_loss_stop", now_ms,
                extra_slippage=True,
            ))
            return events

        # Stop (kaymalı)
        if position.side == "LONG" and candle.low <= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(
                symbol, position.stop_loss, reason, now_ms,
            ))
            return events
        if position.side == "SHORT" and candle.high >= position.stop_loss:
            reason = "trailing_stop" if position.trailing_active else "stop_loss"
            events.append(self.close_position_market(
                symbol, position.stop_loss, reason, now_ms,
            ))
            return events

        # Funding (mum zaman damgası üzerinden)
        if self.risk_manager_ref is not None:
            payment = self.risk_manager_ref.apply_funding_if_due(
                position, candle.close, now_ms, funding_rate,
            )
            if payment is not None:
                self.portfolio.balance -= payment
                events.append({
                    "type": "FUNDING", "symbol": symbol, "payment": payment,
                    "cumulative": position.funding_paid, "timestamp": now_ms,
                })

        # TP1 kısmi kâr alma (maker limit)
        exit_cfg = self.config.exit
        if (
            not position.tp1_done and position.take_profit is not None
            and position.initial_net_risk > 0
        ):
            tp_hit = (
                candle.high >= position.take_profit
                if position.side == "LONG"
                else candle.low <= position.take_profit
            )
            if tp_hit:
                events.append(self.close_partial(
                    symbol, exit_cfg.tp1_close_fraction,
                    position.take_profit, "tp1", now_ms,
                ))
                position.trailing_active = True
                position.best_price = (
                    max(position.best_price or position.entry, candle.high)
                    if position.side == "LONG"
                    else min(position.best_price or position.entry, candle.low)
                )

        # Momentum çıkışı: kâr bandında (trail aktivasyonu ≥ 0.75R) momentum
        # ölürse kâr realize edilir; TP1 sonrası kalan miktar için de geçerli.
        if (
            position.initial_net_risk > 0
            and impulse_pct is not None and rvol is not None
        ):
            mark = candle.close
            net_now = position.net_pnl(mark, self.cost_of(symbol, "taker_fee_rate"), 0.0)
            r_now = net_now / position.initial_net_risk
            if r_now >= exit_cfg.trail_activation_r:
                momentum_continues = (
                    impulse_pct > 0 if position.side == "LONG" else impulse_pct < 0
                ) and rvol >= self.config.signal.min_rvol_for_exit
                if not momentum_continues:
                    events.append(self.close_position_market(
                        symbol, mark, "momentum_end", now_ms,
                    ))
                    return events

        # Zaman stopu (FADE ve TREND farklı sınır)
        max_hold = (
            exit_cfg.fade_max_hold_minutes if position.motor in {"fade", "fade+trend"}
            else exit_cfg.trend_max_hold_minutes
        )
        if now_ms - position.opened_at_ms >= max_hold * 60_000:
            events.append(self.close_position_market(
                symbol, candle.close, "time_stop", now_ms,
            ))
            return events

        # v2.0: funding maliyeti kârı yiyor mu? (oran biliniyorsa)
        funding_trade = self._maybe_funding_exit(
            symbol, position, candle.close, now_ms, funding_rate,
        )
        if funding_trade is not None:
            events.append(funding_trade)
            return events

        self._update_trailing(position, candle.close, atr)
        return events

    def _maybe_funding_exit(
        self,
        symbol: str,
        position: Position,
        mark: float,
        now_ms: int,
        funding_rate: float | None,
    ) -> dict | None:
        """v2.0: funding maliyetine göre pozisyon yönetimi (şartname 4).

        Yalnızca KÂR BÖLGESİNDE (r >= trail_activation_r) ve BİLİNEN funding
        oranıyla çalışır: bir sonraki ödeme beklenen kârın %25'inden fazlasını
        yiyecekse pozisyon erken kapatılır. Varsayılan oranla (%0.01/8s)
        pratikte tetiklenmez; canlıda yüksek funding dönemlerini yakalar.
        Oran bilinmiyorsa "uygulanmadı" — dokunulmaz.
        """
        f = self.config.funding
        if not f.enabled or funding_rate is None or position.initial_net_risk <= 0:
            return None
        net_now = position.net_pnl(mark, self.taker_fee_rate, 0.0)
        r_now = net_now / position.initial_net_risk
        if r_now < self.config.exit.trail_activation_r or net_now <= 0:
            return None
        notional = position.quantity * mark
        next_payment = abs(
            compute_funding_payment(notional, funding_rate, position.side)
        )
        if next_payment > 0 and next_payment > net_now * 0.25:
            return self.close_position_market(
                symbol, mark, "funding_cost_exit", now_ms,
            )
        return None

    def _update_trailing(self, position: Position, price: float,
                         atr_value: float | None) -> None:
        """ATR tabanlı trailing (Y2-3): TP1 sonrası veya erken aktivasyonda.

        v2.0: +1R'ye ulaşan pozisyonda stop, maliyetleri karşılayan BAŞA BAŞ
        (break-even) seviyesinin altına inemez (gidiş-dönüş maliyet oranı
        config'ten hesaplanır). ATR takip mesafesi bundan genişse trailing
        geçerli kalır.
        """
        exit_cfg = self.config.exit
        if position.initial_net_risk <= 0:
            return
        direction = position.direction
        unrealized = direction * (price - position.entry) * position.quantity
        r_now = unrealized / position.initial_net_risk
        if not position.trailing_active:
            if r_now >= exit_cfg.trail_activation_r:
                position.trailing_active = True
                position.best_price = price
            else:
                return
        position.best_price = (
            max(position.best_price or price, price) if direction > 0
            else min(position.best_price or price, price)
        )
        if atr_value is not None and isfinite(atr_value) and atr_value > 0:
            distance = exit_cfg.trail_atr_multiple * atr_value
        else:
            distance = price * 0.005  # ATR yoksa %0,5 güvenli varsayım
        if direction > 0:
            candidate = (position.best_price or price) - distance
            candidate = max(candidate, self._breakeven_price(position, price, direction))
            position.stop_loss = max(position.stop_loss, candidate)
        else:
            candidate = (position.best_price or price) + distance
            candidate = min(candidate, self._breakeven_price(position, price, direction))
            position.stop_loss = min(position.stop_loss, candidate)

    def _breakeven_price(self, position: Position, price: float,
                         direction: float) -> float:
        """Maliyetleri karşılayan başa baş fiyatı (v2.0, config oranlı).

        R hedefine (breakeven_activation_r) ulaşmayan pozisyonda dokunulmaz;
        ulaşılan pozisyonda stop en az bu seviyeye çekilir.
        """
        exit_cfg = self.config.exit
        if not exit_cfg.breakeven_enabled or position.initial_net_risk <= 0:
            return position.entry
        unrealized = position.direction * (price - position.entry) * position.quantity
        r_now = unrealized / position.initial_net_risk
        if r_now < exit_cfg.breakeven_activation_r:
            return position.entry
        # Gidiş-dönüş maliyet oranı: maker giriş + taker çıkış + kayma
        cost_rate = self._cost_rate()
        buffer = position.entry * cost_rate
        if direction > 0:
            return position.entry + buffer
        return position.entry - buffer

    def _cost_rate(self) -> float:
        return (
            self.maker_fee_rate + self.taker_fee_rate
            + self.stop_slippage_rate + self.extra_slippage_rate
        )

    def apply_funding(self, symbol: str, payment: float, now_ms: int) -> None:
        """Funding nakit akışı: pozitif = pozisyon öder."""
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return
        position.funding_paid += payment
        self.portfolio.balance -= payment
        self.trades.append({
            "type": "FUNDING", "symbol": symbol, "payment": payment,
            "cumulative": position.funding_paid, "timestamp": now_ms,
            "mode": "paper",
        })

    def apply_dca(
        self, symbol: str, quantity: float, price: float, now_ms: int,
    ) -> dict | None:
        """v4.0: DCA güvenlik emri (market dolum; YALNIZ LONG — çağıran sorumlu).

        Muhasebe: taker ücreti bakiyeden düşülür; ek marj pozisyona yazılır
        (bakiye marj ayırmaz — Portfolio modeli); ortalama giriş ve miktar
        güncellenir; STOP VE initial_net_risk DEĞİŞMEZ (risk zemini korunur;
        büyüyen net risk executor tarafında tavana karşı kontrol edilir).
        """
        position = self.portfolio.positions.get(symbol)
        if position is None or position.side != "LONG":
            return None
        if quantity <= 0 or price <= 0 or not isfinite(quantity * price):
            return None
        fee = quantity * price * self.taker_fee_rate
        margin_add = quantity * price / max(position.leverage, 1.0)
        new_qty = position.quantity + quantity
        position.entry = (
            position.entry * position.quantity + price * quantity
        ) / new_qty
        position.quantity = new_qty
        position.margin += margin_add
        position.dca_count += 1
        self.portfolio.balance -= fee
        trade = {
            "type": "DCA", "symbol": symbol, "side": "LONG",
            "price": price, "quantity": quantity, "fee": fee,
            "margin_add": margin_add, "avg_entry": position.entry,
            "safety_orders": position.dca_count,
            "stop_loss": position.stop_loss,
            "order_id": f"dca-{position.signal_key}-{position.dca_count}",
            "signal_key": position.signal_key,
            "timestamp": now_ms, "mode": "paper",
            "execution_type": "market", "reduce_only": False,
        }
        self.trades.append(trade)
        return trade

    def mark_to_market(self, prices: dict[str, float]) -> float:
        return self.portfolio.equity(prices)
