"""Çoklu sembol backtest motoru — CANLI sistemi test eder (Y1-D, Y2-6).

Yorum 2, madde 6'nın ana eleştirisi: backtest canlı akıştaki filtreleri
kullanmıyordu. Bu motor canlıyla AYNI katmanları kullanır:

  - Aynı strateji motorları (FADE LONG/SHORT, TREND LONG/SHORT)
  - v2.0: AYNI sinyal boru hattı (rejim + uzmanlar + MTF + skorlama)
  - Aynı risk yöneticisi (portföy limitleri, kill switch, beta tavanı)
  - Aynı paper broker (maliyet-dâhil zarar tavanı, funding, likidasyon)
  - Maker giriş dolumu: sinyal mumu KAPANDIKTAN SONRA limit emri konur
    ve yalnızca SONRAKİ mum limit seviyesine değerse dolar. Değmezse
    emir düşer (dolmayan maker = gerçekçi).
  - v2.0 KISMİ DOLUM: mumda işlem gören baz hacmin yalnızca
    `bt_participant_cap` payı bizim emre gider; kalan miktar düşer
    (TTL semantics). Veri temelli model — sabit oran varsayımı değil.
  - v2.0 SPREAD: `spread_bps` GERÇEK ölçümle verilirse limit fiyatı
    yarım spread ile kötüleştirilir; verilmezse "uygulanmadı" notu düşer.
  - Dolduktan sonra AYNI mumda fiyat stopun altına indiysse pozisyon
    stoplanır → ters seçilim (adverse selection) doğal olarak modelde.

Mum bazında muhafazakâr sıralama: aynı mumda stop ve TP ikisi de
dokunulduysa ÖNCE stop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from math import isfinite

from core.config import SuperConfig
from core.gates import EntryRateLimiter, ReentryCooldown
from core.pipeline import SignalPipeline
from core.portfolio_risk import (
    BetaEstimator,
    BtcShockTester,
    base_asset_of,
    beta_adjusted_directional_notional,
)
from core.risk import KillSwitchState, RiskManager
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
    # v2.0 şeffaflık alanları
    spread_applied: bool = False
    slippage_bps: float = 0.0
    latency_ms: int = 0
    shock_tests: dict = field(default_factory=dict)
    betas: dict[str, float] = field(default_factory=dict)

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
    side: str
    stop_distance_fraction: float
    motor: str
    plan_limit_price: float
    quantity: float
    created_ms: int
    direction: float
    score: float = 0.0
    regime: str = ""
    experts: str = ""


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
        spread_bps: dict[str, float] | None = None,
    ) -> BacktestResult:
        config = self._build_config()
        broker = PaperBroker(config, self.initial_balance)
        risk = RiskManager(config)
        broker.risk_manager_ref = risk
        pipeline = SignalPipeline(config)
        rate_limiter = EntryRateLimiter(config.v2.gates)
        cooldown = ReentryCooldown(config.v2.gates)
        beta_estimator = BetaEstimator(config.v2.gates)
        shock_tester = BtcShockTester(config.v2.gates)
        participant_cap = config.data.bt_participant_cap
        slippage_bps = config.data.bt_slippage_bps
        latency_ms = config.data.bt_latency_ms

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
        betas: dict[str, float] = {}
        shock_summary: dict = {"checked": 0, "blocked": 0, "unavailable": 0}

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
                for event in events:
                    if event.get("type") == "CLOSE":
                        cooldown.record_exit(
                            symbol, ts_ms, str(event.get("reason", "")),
                        )

            # 2) Bekleyen limit emirlerinin dolum denetimi (SONRAKİ mumla)
            pending = pending_limits.get(symbol)
            if pending is not None:
                touched = (
                    candle.low <= pending.plan_limit_price
                    if pending.direction > 0
                    else candle.high >= pending.plan_limit_price
                )
                # v3.0: gecikme modeli — sinyal ile emir arası bt_latency_ms
                # geçmeden dolum denetlenmez (mum ölçeğinde mum atlatır).
                if touched and latency_ms > 0 and (
                    ts_ms - pending.created_ms < latency_ms
                ):
                    touched = False
                if touched:
                    fill_qty = self._partial_fill_quantity(
                        pending, candle, participant_cap,
                    )
                    if fill_qty > 0:
                        self._fill_order(
                            broker, pending, candle, ts_ms, fill_qty,
                            slippage_bps,
                        )
                        if fill_qty < pending.quantity - 1e-12:
                            partial_fills += 1
                            rejection_counts["kismi_dolum"] = (
                                rejection_counts.get("kismi_dolum", 0) + 1
                            )
                        # Aynı mumda stop altına inildiyse hemen stoplanır
                        if symbol in broker.portfolio.positions:
                            atr_value = self._atr(history.get(symbol, []))
                            stop_events = broker.manage_position_candle(
                                symbol, candle, ts_ms, atr=atr_value,
                            )
                            for event in stop_events:
                                if event.get("type") == "CLOSE":
                                    cooldown.record_exit(
                                        symbol, ts_ms,
                                        str(event.get("reason", "")),
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
                self._evaluate_signal(
                    broker, risk, pipeline, rate_limiter, cooldown,
                    beta_estimator, shock_tester, config, symbol, history,
                    btc_symbol, ts_ms, pending_limits, rejection_counts,
                    betas, shock_summary, spread_bps or {},
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
            spread_applied=any(v > 0 for v in (spread_bps or {}).values()),
            slippage_bps=slippage_bps,
            latency_ms=latency_ms,
            shock_tests=shock_summary,
            betas=dict(betas),
        )

    # ------------------------------------------------------------------

    def _limit_ttl_ms(self) -> int:
        # Canlıdaki 45 sn TTL'in mum ölçeğinde karşılığı: bir mum boyunca geçerli.
        return self.base_config.data.timeframe_ms

    @staticmethod
    def _partial_fill_quantity(
        pending: _PendingLimit, candle: Candle, participant_cap: float,
    ) -> float:
        """v2.0: mum bazlı kısmi dolum modeli (veri temelli).

        Mumda gerçekleşen baz hacmin `participant_cap` payı bizim seviyemize
        gelir; emrin kalanı düşer. Hacim 0 ise dolum olmaz.
        """
        if participant_cap <= 0 or candle.volume <= 0:
            return pending.quantity if candle.volume > 0 else 0.0
        available = candle.volume * participant_cap
        return min(pending.quantity, max(available, 0.0))

    def _evaluate_signal(
        self,
        broker: PaperBroker,
        risk: RiskManager,
        pipeline: SignalPipeline,
        rate_limiter: EntryRateLimiter,
        cooldown: ReentryCooldown,
        beta_estimator: BetaEstimator,
        shock_tester: BtcShockTester,
        config: SuperConfig,
        symbol: str,
        history: dict[str, list[Candle]],
        btc_symbol: str,
        ts_ms: int,
        pending_limits: dict[str, _PendingLimit],
        rejection_counts: dict[str, int],
        betas: dict[str, float],
        shock_summary: dict,
        spread_bps: dict[str, float],
    ) -> bool:
        sym_history = history[symbol]

        # v2.0: yeniden giriş beklemesi (stop/soft çıkış sonrası)
        wait = cooldown.blocked(symbol, ts_ms)
        if wait is not None:
            rejection_counts["yeniden_giris_beklemesi"] = (
                rejection_counts.get("yeniden_giris_beklemesi", 0) + 1
            )
            return False

        btc_history = history.get(btc_symbol)
        if btc_history and btc_symbol != symbol:
            btc_ctx = self._pct_change(btc_history, 3)
        else:
            # BTC verisi yoksa bağlam nötrdür (kendi düşüşünü BTC sanma!).
            btc_ctx = 0.0

        # v2.0 ortak boru hattı: rejim + temel sinyal + uzmanlar + MTF + skor
        decision = pipeline.evaluate(
            symbol=symbol, candles=sym_history,
            btc_change_pct_15m=btc_ctx,
        )
        signal = decision.signal
        if signal.side == "HOLD":
            code = decision.rejection_code or signal.rejection_code or "sinyal_yok"
            rejection_counts[code] = rejection_counts.get(code, 0) + 1
            return False
        stop_distance = signal.stop_distance_fraction
        if stop_distance is None or not 0 < stop_distance < 1:
            rejection_counts["gecersiz_stop"] = (
                rejection_counts.get("gecersiz_stop", 0) + 1
            )
            return False

        # v2.0: giriş hız limiti (dakikada en fazla N gerçek giriş)
        if not rate_limiter.allow(ts_ms):
            score = decision.score.total if decision.score else 0.0
            rate_limiter.defer(symbol, signal.side, score, ts_ms)
            rejection_counts["giris_hiz_limiti"] = (
                rejection_counts.get("giris_hiz_limiti", 0) + 1
            )
            return False

        entry_ref = sym_history[-1].close
        plan = risk.plan(entry_ref, stop_distance, signal.side, motor=signal.motor)
        prices = {s: h[-1].close for s, h in history.items() if h}
        daily_realized = self._daily_realized(broker, ts_ms)
        daily_unrealized = broker.portfolio.unrealized_pnl(prices)

        # v2.0: beta + BTC şok testi (GERÇEK 5m getirilerinden)
        beta_directional = None
        if config.v2.enabled:
            symbol_betas = self._compute_betas(
                beta_estimator, symbol, history, btc_symbol, betas,
            )
            equity = broker.portfolio.equity(prices)
            planned_beta = symbol_betas.get(base_asset_of(symbol))
            shock = shock_tester.evaluate(
                positions=broker.portfolio.positions,
                prices=prices,
                planned_symbol=symbol,
                planned_side=signal.side,
                planned_notional=plan.notional,
                planned_beta=planned_beta,
                betas=symbol_betas,
                equity=equity,
            )
            if not shock.available:
                shock_summary["unavailable"] = shock_summary.get("unavailable", 0) + 1
            else:
                shock_summary["checked"] = shock_summary.get("checked", 0) + 1
                if shock.blocked:
                    shock_summary["blocked"] = shock_summary.get("blocked", 0) + 1
                    rejection_counts["btc_shok_tavani"] = (
                        rejection_counts.get("btc_shok_tavani", 0) + 1
                    )
                    return False
            if symbol_betas:
                beta_directional = beta_adjusted_directional_notional(
                    broker.portfolio.positions, prices, symbol,
                    signal.side, plan.notional, planned_beta, symbol_betas,
                )

        decision_risk = risk.check_portfolio(
            broker.portfolio, symbol, signal.side, plan.notional,
            plan.net_risk_at_stop, prices, daily_realized, daily_unrealized,
            beta_adjusted_directional=beta_directional,
        )
        if not decision_risk.allowed:
            rejection_counts[decision_risk.reason or "risk_blocked"] = (
                rejection_counts.get(decision_risk.reason or "risk_blocked", 0) + 1
            )
            return False

        direction = 1.0 if signal.side == "LONG" else -1.0
        tick_adj = entry_ref * 0.0002
        half_spread = 0.0
        spread_value = spread_bps.get(symbol)
        if spread_value is not None and spread_value > 0:
            half_spread = entry_ref * (spread_value / 10_000.0) / 2.0
        limit_price = entry_ref - direction * (tick_adj + half_spread)
        pending_limits[symbol] = _PendingLimit(
            symbol=symbol,
            side=signal.side,
            stop_distance_fraction=stop_distance,
            motor=signal.motor,
            plan_limit_price=limit_price,
            quantity=plan.quantity,
            created_ms=ts_ms,
            direction=direction,
            score=decision.score.total if decision.score else 0.0,
            regime=decision.regime.regime.value,
            experts=",".join(
                f"{v.motor}:{v.side}" for v in decision.votes if v.side != "NONE"
            ),
        )
        rejection_counts["limit_bekliyor"] = (
            rejection_counts.get("limit_bekliyor", 0) + 1
        )
        return True

    def _compute_betas(
        self,
        estimator: BetaEstimator,
        symbol: str,
        history: dict[str, list[Candle]],
        btc_symbol: str,
        betas: dict[str, float],
    ) -> dict[str, float]:
        """Her değerlendirmede güncel beta seti (GERÇEK 5m kapanışlarından)."""
        btc_closes = [c.close for c in history.get(btc_symbol, [])]
        result: dict[str, float] = {}
        for name, candles in history.items():
            base = base_asset_of(name)
            if not btc_closes or len(candles) < 30:
                continue
            beta = estimator.beta([c.close for c in candles], btc_closes)
            if beta is not None:
                result[base] = beta
                betas[name] = beta
        return result

    def _fill_order(
        self,
        broker: PaperBroker,
        pending: _PendingLimit,
        candle: Candle,
        ts_ms: int,
        fill_qty: float,
        slippage_bps: float = 0.0,
    ) -> None:
        # Sinyaldeki plan, güncel fiyatla yeniden planlanır (dolum anı fiyatı)
        # v3.0: bt_slippage_bps > 0 ise dolum fiyatı aleyhte kaydırılır
        # (agresif senaryo: kuyruk/caydırıcılık etkisi). Varsayılan 0 = kapalı.
        risk = RiskManager(self._build_config())
        slip_factor = pending.direction * slippage_bps / 10_000.0
        fill_price = (
            pending.plan_limit_price * (1.0 + slip_factor)
            if slippage_bps > 0 else pending.plan_limit_price
        )
        plan = risk.plan(
            fill_price,
            pending.stop_distance_fraction,
            pending.side,
            motor=pending.motor,
        )
        qty = min(fill_qty, pending.quantity)
        if qty < plan.quantity - 1e-12 and plan.quantity > 0:
            fraction = qty / plan.quantity
            plan = replace(
                plan,
                quantity=qty,
                margin=plan.margin * fraction,
            )
        order = Order(
            symbol=pending.symbol,
            side=OrderSide.BUY if pending.side == "LONG" else OrderSide.SELL,
            order_type=OrderType.POST_ONLY_LIMIT,
            quantity=qty,
            limit_price=fill_price,
            created_ms=pending.created_ms,
            ttl_ms=self._limit_ttl_ms(),
        )
        broker.bind_plan(order, plan, pending.motor, meta={
            "score": pending.score, "regime": pending.regime,
            "experts": pending.experts,
        })
        order.apply_fill(fill_price, qty, ts_ms, is_maker=True)
        broker.portfolio.balance -= order.total_fee
        broker._open_position_from_order(pending.symbol, order, ts_ms)
        broker.trades.append({
            "type": "ORDER_FILL", "order_id": order.id,
            "symbol": pending.symbol,
            "price": fill_price, "quantity": qty,
            "fee": order.total_fee, "maker": True,
            "partial": qty < pending.quantity - 1e-12,
            "slipped": fill_price != pending.plan_limit_price,
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
        from core.indicators import atr as atr_fn
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
