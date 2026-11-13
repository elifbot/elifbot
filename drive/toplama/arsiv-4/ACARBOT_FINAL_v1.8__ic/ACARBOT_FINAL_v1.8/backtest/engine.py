"""Çoklu sembol backtest motoru — CANLI sistemi test eder (Y1-D, Y2-6).

Yorum 2, madde 6'nın ana eleştirisi: backtest canlı akıştaki filtreleri
kullanmıyordu. Bu motor canlıyla AYNI katmanları kullanır:

  - Aynı strateji motorları (FADE LONG/SHORT, TREND LONG/SHORT)
  - Aynı sinyal çözümleyici (rejim, BTC filtresi, sahte kırılım)
  - Aynı risk yöneticisi (portföy limitleri, kill switch)
  - Aynı paper broker (maliyet-dâhil zarar tavanı, funding, likidasyon)
  - Maker giriş dolumu: sinyal mumu KAPANDIKTAN SONRA limit emri konur
    ve yalnızca SONRAKİ mum limit seviyesine değerse dolar. Değmezse
    emir düşer (dolmayan maker = gerçekçi).
  - Dolduktan sonra AYNI mumda fiyat stopun altına indiysse pozisyon
    stoplanır → ters seçilim (adverse selection) doğal olarak modelde.

Mum bazında muhafazakâr sıralama: aynı mumda stop ve TP ikisi de
dokunulduysa ÖNCE stop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from math import isfinite
from typing import Sequence

from core.config import SuperConfig
from core.indicators import atr as atr_fn
from core.risk import KillSwitchState, RiskManager
from core.spike import candle_rvol
from core.strategy import (
    FadeEngine,
    MarketContext,
    RegimeDetector,
    Signal,
    SignalResolver,
    TrendEngine,
)
from exec.orders import Order, OrderSide, OrderType
from exec.paper import PaperBroker
from infra.market_data.models import Candle

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    initial_balance: float
    final_balance: float
    trades: tuple[dict, ...] = ()
    equity_curve: list[float] = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    expired_orders: int = 0
    partial_fills: int = 0

    @property
    def net_pnl(self) -> float:
        return self.final_balance - self.initial_balance

    @property
    def trade_count(self) -> int:
        return sum(t.get("type") == "CLOSE" for t in self.trades)

    @property
    def win_rate(self) -> float:
        closes = [t for t in self.trades if t.get("type") == "CLOSE"]
        if not closes:
            return 0.0
        return sum(float(t.get("pnl", 0.0)) > 0 for t in closes) / len(closes)


@dataclass
class _PendingLimit:
    symbol: str
    signal: Signal
    plan_limit_price: float
    quantity: float
    created_ms: int
    direction: float
    reserved_margin: float = 0.0


class BacktestEngine:
    """Portföy düzeyinde çoklu sembol simülasyonu (5m mumlar)."""

    def __init__(
        self,
        config: SuperConfig | None = None,
        initial_balance: float | None = None,
        max_positions: int | None = None,
    ) -> None:
        self.base_config = config or SuperConfig()
        self.initial_balance = (
            initial_balance or self.base_config.account.initial_balance
        )
        self.max_positions_override = max_positions

    def _build_config(self) -> SuperConfig:
        if self.max_positions_override is None:
            return self.base_config
        portfolio = replace(
            self.base_config.portfolio,
            max_positions=self.max_positions_override,
        )
        return replace(self.base_config, portfolio=portfolio)

    # ------------------------------------------------------------------
    # Ana akış
    # ------------------------------------------------------------------

    def run(
        self,
        candles_by_symbol: dict[str, list[Candle]],
        funding_rates: dict[str, list[tuple[int, float]]] | None = None,
        btc_symbol: str = "BTCUSDT",
    ) -> BacktestResult:
        config = self._build_config()
        broker = PaperBroker(config, self.initial_balance)
        risk = RiskManager(config)
        broker.risk_manager_ref = risk
        fade = FadeEngine(config)
        trend = TrendEngine(config)
        resolver = SignalResolver(config)
        regime_detector = RegimeDetector(config.signal)

        timeline: list[tuple[int, str, Candle]] = []
        for symbol, candles in candles_by_symbol.items():
            for candle in candles:
                timeline.append((candle.timestamp, symbol, candle))
        timeline.sort(key=lambda item: item[0])

        symbols = set(candles_by_symbol)
        history: dict[str, list[Candle]] = {s: [] for s in symbols}
        pending_limits: dict[str, _PendingLimit] = {}

        rejection_counts: dict[str, int] = {}
        equity_curve: list[float] = [self.initial_balance]
        last_equity_ts = 0
        expired_orders = 0
        partial_fills = 0

        for ts_ms, symbol, candle in timeline:
            # 1) Bu mumun kapanışı: açık pozisyonu yönet (stop/TP1/funding/likidasyon)
            if symbol in broker.portfolio.positions:
                atr_value = self._atr(history.get(symbol, []))
                rate = None
                if funding_rates and symbol in funding_rates:
                    rate = self._funding_rate_at(funding_rates[symbol], ts_ms)
                events = broker.manage_position_candle(
                    symbol, candle, ts_ms, atr=atr_value, funding_rate=rate,
                )
                partial_fills += sum(
                    1 for e in events if e.get("type") == "PARTIAL_CLOSE"
                )

            # 2) Bekleyen limit emirlerinin dolum denetimi (SONRAKİ mumla)
            pending = pending_limits.get(symbol)
            if pending is not None:
                touched = (
                    candle.low <= pending.plan_limit_price
                    if pending.direction > 0
                    else candle.high >= pending.plan_limit_price
                )
                if touched:
                    self._fill_order(broker, pending, candle, ts_ms, risk, config)
                    # Aynı mumda stop altına inildiyse hemen stoplanır
                    if symbol in broker.portfolio.positions:
                        atr_value = self._atr(history.get(symbol, []))
                        broker.manage_position_candle(
                            symbol, candle, ts_ms, atr=atr_value,
                        )
                    del pending_limits[symbol]
                elif ts_ms - pending.created_ms > self._limit_ttl_ms():
                    expired_orders += 1
                    rejection_counts["emir_dolmadi"] = (
                        rejection_counts.get("emir_dolmadi", 0) + 1
                    )
                    del pending_limits[symbol]

            # 3) Mumu kapanmış geçmişe ekle
            history[symbol].append(candle)

            # 4) Sinyal değerlendirmesi (yalnızca kapanmış mumlarla)
            if (
                symbol not in broker.portfolio.positions
                and symbol not in pending_limits
                and risk.kill_switch_state != KillSwitchState.HARD_HALT
                and len(history[symbol]) >= 30
            ):
                filled = self._evaluate_signal(
                    broker, risk, fade, trend, resolver, regime_detector,
                    config, symbol, history, btc_symbol, ts_ms,
                    pending_limits, rejection_counts,
                )

            # 5) Kill switch + equity takibi
            prices = {s: h[-1].close for s, h in history.items() if h}
            daily_realized = self._daily_realized(broker, ts_ms)
            state = risk.evaluate_kill_switch(broker.portfolio, prices, daily_realized)
            if state == KillSwitchState.HARD_HALT and broker.portfolio.positions:
                closed = broker.close_all(prices, ts_ms, reason="kill_switch_hard")
                rejection_counts["kill_switch_flatten"] = len(closed)
            if ts_ms - last_equity_ts >= 5 * 60_000:
                equity_curve.append(broker.mark_to_market(prices))
                last_equity_ts = ts_ms

        final_prices = {s: h[-1].close for s, h in history.items() if h}
        end_ts = timeline[-1][0] if timeline else 0
        for symbol in list(broker.portfolio.positions):
            price = final_prices.get(symbol)
            if price is not None:
                broker.close_position_market(
                    symbol, price, "end_of_backtest", end_ts,
                )
        return BacktestResult(
            initial_balance=self.initial_balance,
            final_balance=broker.portfolio.balance,
            trades=tuple(broker.trades),
            equity_curve=equity_curve,
            rejection_counts=rejection_counts,
            expired_orders=expired_orders,
            partial_fills=partial_fills,
        )

    # ------------------------------------------------------------------

    def _limit_ttl_ms(self) -> int:
        # Canlıdaki 45 sn TTL'in mum ölçeğinde karşılığı: bir mum boyunca geçerli.
        return self.base_config.data.timeframe_ms

    def _evaluate_signal(
        self,
        broker: PaperBroker,
        risk: RiskManager,
        fade: FadeEngine,
        trend: TrendEngine,
        resolver: SignalResolver,
        regime_detector: RegimeDetector,
        config: SuperConfig,
        symbol: str,
        history: dict[str, list[Candle]],
        btc_symbol: str,
        ts_ms: int,
        pending_limits: dict[str, _PendingLimit],
        rejection_counts: dict[str, int],
    ) -> bool:
        sym_history = history[symbol]
        regime = regime_detector.classify(sym_history)
        btc_history = history.get(btc_symbol)
        if btc_history and btc_symbol != symbol:
            btc_ctx = self._pct_change(btc_history, 3)
        else:
            # BTC verisi yoksa bağlam nötrdür (kendi düşüşünü BTC sanma!).
            btc_ctx = 0.0
        ctx = MarketContext(
            symbol=symbol, candles=sym_history, spike=None,
            btc_change_pct_15m=btc_ctx, config=config,
        )
        # FINAL v1.4: motor seçimi (canlı ile AYNI kural)
        motors = config.signal.enabled_motors
        fade_signal = (
            fade.evaluate(ctx) if "fade" in motors
            else Signal("HOLD", "fade", 0.0, 0.0, None)
        )
        trend_signal = (
            trend.evaluate(ctx) if "trend" in motors
            else Signal("HOLD", "trend", 0.0, 0.0, None)
        )
        signal = resolver.resolve(fade_signal, trend_signal, regime)
        if signal.side == "HOLD":
            code = signal.rejection_code or "sinyal_yok"
            rejection_counts[code] = rejection_counts.get(code, 0) + 1
            return False
        stop_distance = signal.stop_distance_fraction
        if stop_distance is None or not 0 < stop_distance < 1:
            rejection_counts["gecersiz_stop"] = (
                rejection_counts.get("gecersiz_stop", 0) + 1
            )
            return False

        entry_ref = sym_history[-1].close
        plan = risk.plan(entry_ref, stop_distance, signal.side, motor=signal.motor)
        prices = {s: h[-1].close for s, h in history.items() if h}
        daily_realized = self._daily_realized(broker, ts_ms)
        daily_unrealized = broker.portfolio.unrealized_pnl(prices)
        reserved = sum(p.reserved_margin for p in pending_limits.values())
        decision = risk.check_portfolio(
            broker.portfolio, symbol, signal.side, plan.notional,
            plan.net_risk_at_stop, prices, daily_realized, daily_unrealized,
            reserved_margin=reserved,
        )
        if not decision.allowed:
            rejection_counts[decision.reason or "risk_blocked"] = (
                rejection_counts.get(decision.reason or "risk_blocked", 0) + 1
            )
            return False

        direction = 1.0 if signal.side == "LONG" else -1.0
        tick_adj = entry_ref * 0.0002
        limit_price = entry_ref - direction * tick_adj
        pending_limits[symbol] = _PendingLimit(
            symbol=symbol,
            signal=signal,
            plan_limit_price=limit_price,
            quantity=plan.quantity,
            created_ms=ts_ms,
            direction=direction,
            reserved_margin=plan.margin * (1.0 + config.account.maker_fee_rate),
        )
        rejection_counts["limit_bekliyor"] = (
            rejection_counts.get("limit_bekliyor", 0) + 1
        )
        return True

    def _fill_order(
        self,
        broker: PaperBroker,
        pending: _PendingLimit,
        candle: Candle,
        ts_ms: int,
        risk: RiskManager,
        config: SuperConfig,
    ) -> None:
        # Sinyaldeki plan, güncel fiyatla yeniden planlanır (dolum anı fiyatı)
        plan = risk.plan(
            pending.plan_limit_price,
            pending.signal.stop_distance_fraction or 0.003,
            pending.signal.side,
            motor=pending.signal.motor,
        )
        order = Order(
            symbol=pending.symbol,
            side=OrderSide.BUY if pending.signal.side == "LONG" else OrderSide.SELL,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=plan.quantity,
            limit_price=pending.plan_limit_price,
            created_ms=pending.created_ms,
            ttl_ms=self._limit_ttl_ms(),
        )
        broker.bind_plan(order, plan, pending.signal.motor)
        order.apply_fill(pending.plan_limit_price, plan.quantity, ts_ms, is_maker=True)
        broker.portfolio.balance -= order.total_fee
        broker._open_position_from_order(pending.symbol, order, ts_ms)
        broker.trades.append({
            "type": "ORDER_FILL", "order_id": order.id,
            "symbol": pending.symbol,
            "price": pending.plan_limit_price, "quantity": plan.quantity,
            "fee": order.total_fee, "maker": True, "partial": False,
            "timestamp": ts_ms, "mode": "paper",
        })

    # ------------------------------------------------------------------

    @staticmethod
    def _atr(history: list[Candle]) -> float | None:
        if len(history) < 20:
            return None
        recent = history[-100:]
        high = [c.high for c in recent]
        low = [c.low for c in recent]
        close = [c.close for c in recent]
        value = atr_fn(high, low, close, 14)[-1]
        return value if value is not None and isfinite(value) and value > 0 else None

    @staticmethod
    def _pct_change(history: list[Candle], steps: int) -> float:
        if len(history) < steps + 1:
            return 0.0
        base = history[-steps - 1].close
        if base <= 0:
            return 0.0
        return (history[-1].close / base - 1.0) * 100.0

    @staticmethod
    def _funding_rate_at(rates: list[tuple[int, float]], ts_ms: int) -> float | None:
        best = None
        for ts, rate in rates:
            if ts <= ts_ms:
                best = rate
            else:
                break
        return best

    @staticmethod
    def _daily_realized(broker: PaperBroker, ts_ms: int) -> float:
        day_start = ts_ms - (ts_ms % 86_400_000)
        return sum(
            float(t.get("pnl", 0.0))
            for t in broker.trades
            if t.get("type") == "CLOSE"
            and isinstance(t.get("timestamp"), (int, float))
            and t["timestamp"] >= day_start
        )
