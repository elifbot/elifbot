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
from math import isfinite

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
        self.fill_sim = MakerFillSimulator()
        self.pending_orders: dict[str, list[Order]] = {}
        self.trades: list[dict] = []
        self.mode = "paper"
        self._order_seq = 0
        self._plan_for_order: dict[str, TradePlan] = {}
        self._motor_for_order: dict[str, str] = {}
        self._meta_for_order: dict[str, dict] = {}   # v2.0: skor/rejim/oylar
        self.risk_manager_ref = None  # likidasyon/funding için RiskManager

    # ------------------------------------------------------------------
    # Giriş emirleri (yaşam döngüsü ile)
    # ------------------------------------------------------------------

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
        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=plan.quantity,
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
            "limit_price": limit_price, "quantity": plan.quantity,
            "ttl_ms": order.ttl_ms, "timestamp": now_ms, "mode": "paper",
        })
        return order

    def pending(self, symbol: str) -> list[Order]:
        return [o for o in self.pending_orders.get(symbol, []) if o.is_active]

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
        return fill

    def _open_position_from_order(
        self, symbol: str, order: Order, now_ms: int
    ) -> None:
        avg_price = order.average_fill_price
        if avg_price is None or order.filled_quantity <= 0:
            return
        plan_qty = order.quantity
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
        net_risk = (
            order.filled_quantity * avg_price * (stop_fraction + self._cost_rate())
            + plan.estimated_funding_buffer
        )
        liq = compute_liquidation_price(
            avg_price, side, plan.leverage, self.config.funding
        )
        position = Position(
            symbol=symbol, side=side, entry=avg_price,
            quantity=order.filled_quantity,
            initial_quantity=order.filled_quantity,
            margin=plan.margin,
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
            "fee": entry_fee, "margin": plan.margin,
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

    def bind_plan(self, order: Order, plan: TradePlan, motor: str,
                  meta: dict | None = None) -> None:
        """Emir ile plan, motor etiketi ve v2.0 meta (skor/rejim) bağlar."""
        self._plan_for_order[order.id] = plan
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
        slippage_rate = self.stop_slippage_rate + (
            self.extra_slippage_rate if extra_slippage else 0.0
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
        fee = price * close_qty * self.maker_fee_rate
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
            if liquidation else self.taker_fee_rate
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
        if position.net_pnl(price, self.taker_fee_rate,
                            self.stop_slippage_rate + self.extra_slippage_rate) \
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
    ) -> list[dict]:
        """Mum bazlı çıkış yönetimi; MUHAFAZAKÂR sıralama: stop önce.

        Aynı mumda hem stop hem TP seviyesi varsa önce STOP varsayılır
        (intrabar sıra belirsizliğinde zararlı senaryo seçilir).
        """
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return []
        events: list[dict] = []
        if candle.timestamp > position.last_candle_timestamp:
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
        if position.net_pnl(worst_price, self.taker_fee_rate,
                            self.stop_slippage_rate + self.extra_slippage_rate) \
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
            net_now = position.net_pnl(mark, self.taker_fee_rate, 0.0)
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
