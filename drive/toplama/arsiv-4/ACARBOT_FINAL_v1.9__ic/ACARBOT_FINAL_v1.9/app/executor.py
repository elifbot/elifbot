"""Sinyal → risk → emir orkestrasyonu (canlı ve backtest ortak katman).

Eski `app/executor.py`'nin süper sürümü:
  - Girişler emir yaşam döngüsüyle açılır (anında dolum yok).
  - Pozisyon yönetimi tick + mum yollarının birleşimi.
  - Kill switch, güvenli mod, portföy limitleri burada devreye girer.
"""

from __future__ import annotations

import logging
import time
from math import isfinite

from core.config import SuperConfig
from core.risk import (
    KillSwitchState,
    RiskManager,
    TradePlan,
)
from core.spike import SpikeEvent, SpikeDetector, estimate_secondly_base_volume
from core.strategy import (
    FadeEngine,
    MarketContext,
    RegimeDetector,
    Signal,
    SignalResolver,
    TrendEngine,
)
from exec.paper import PaperBroker
from infra.feed import DataIntegrityManager
from infra.market_data.models import Candle
from state.store import StateStore

logger = logging.getLogger(__name__)


class Executor:
    def __init__(
        self,
        broker: PaperBroker,
        risk: RiskManager,
        config: SuperConfig | None = None,
        store: StateStore | None = None,
        data_integrity: DataIntegrityManager | None = None,
        news_guard=None,
        sweep_guard=None,
    ) -> None:
        self.config = config or SuperConfig()
        self.broker = broker
        self.risk = risk
        self.store = store
        self.data_integrity = data_integrity or DataIntegrityManager()
        # FINAL v1.1 giriş kapıları (None = kapalı; geriye dönük uyumlu)
        self.news_guard = news_guard
        self.sweep_guard = sweep_guard
        # FINAL v1.5: tam pazar modunda giriş anında defter tazeleme çağrısı.
        # İmza: (symbol_key: str) -> None; sweep_guard'ı besler. None = kapalı.
        self.book_fetcher = None
        self.fade = FadeEngine(self.config)
        self.trend = TrendEngine(self.config)
        self.resolver = SignalResolver(self.config)
        self.regime_detector = RegimeDetector(self.config.signal)
        self.spike_detector = SpikeDetector(
            multiplier=self.config.signal.spike_multiplier,
            lookback_seconds=self.config.data.timeframe_ms // 1000,
            window_seconds=self.config.signal.spike_window_seconds,
            direction_seconds=self.config.signal.spike_direction_seconds,
            sanity_cap=self.config.signal.spike_rvol_sanity_cap,
            min_baseline_notional_per_second=(
                self.config.signal.spike_min_baseline_notional_per_second
            ),
        )
        self._candles: dict[str, list[Candle]] = {}
        self._latest_prices: dict[str, float] = {}
        self._btc_history: list[Candle] = []
        self._last_volume_24h: dict[str, float] = {}
        # v1.6: baz hacim takibi (fiyattan bağımsız, doğru RVOL)
        self._last_base_volume_24h: dict[str, float] = {}
        self._last_signal_ts: dict[str, int] = {}
        # v1.9: hacim filtresi sayaçları + sembol başına log kısıtlama
        self.rvol_suspect_count = 0
        self.low_liquidity_count = 0
        self._last_volume_log_ms: dict[str, int] = {}
        self._volume_log_suppressed: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Veri besleme
    # ------------------------------------------------------------------

    def update_candles(self, symbol: str, candles: list[Candle]) -> None:
        if not candles:
            return
        self._candles[symbol] = list(candles)
        if symbol.upper().startswith("BTC"):
            self._btc_history = list(candles)

    def process_price_update(
        self,
        symbol: str,
        price: float,
        timestamp_ms: int,
        volume_24h_quote: float | None = None,
        exchange: str = "binance",
        base_volume_24h: float | None = None,
    ) -> list[dict]:
        """Tick işleme: dolum simülasyonu, çıkış yönetimi, funding, kill switch.

        Dönen değer: oluşan işlem/olay kayıtları (log + Telegram için).
        """
        if not isfinite(price) or price <= 0 or timestamp_ms < 0:
            raise ValueError("tick fiyatı/zamanı geçersiz")
        events: list[dict] = []
        self.data_integrity.record_tick(symbol, timestamp_ms)
        self._latest_prices[symbol] = price

        # Saniyelik baz hacim → spike dedektörü.
        # v1.6: ÖNCELİK baz hacim deltasında (fiyattan bağımsız). Eski
        # quote=baz×fiyat yaklaşımı fiyat oynaklığını sahte hacim sanıyordu
        # (RVOL 100-500x şişmesi → gerçek sinyaller "şüpheli" diye engelleniyordu).
        spike: SpikeEvent | None = None
        base_volume: float | None = None
        if base_volume_24h is not None:
            last_b = self._last_base_volume_24h.get(symbol)
            self._last_base_volume_24h[symbol] = base_volume_24h
            if last_b is not None and base_volume_24h >= last_b:
                base_volume = base_volume_24h - last_b
        elif volume_24h_quote is not None:
            last = self._last_volume_24h.get(symbol)
            self._last_volume_24h[symbol] = volume_24h_quote
            if last is not None and volume_24h_quote >= last:
                delta = volume_24h_quote - last
                base_volume = estimate_secondly_base_volume(
                    delta, price, contract_size=1.0,
                )
        if base_volume is not None:
            spike = self.spike_detector.update(
                symbol, price, base_volume, timestamp_ms,
            )
            if spike is not None and (spike.suspect or spike.illiquid):
                # v1.9: likiditesizlik ile veri hatası AYRI etiketlenir ve
                # sembol başına kısıtlanarak loglanır (log seli yok).
                self._log_volume_filter(symbol, spike, timestamp_ms)
                spike = None

        # Bekleyen giriş emirlerini besle.
        # v1.9 DÜZELTMESİ: dolum simülasyonu GERÇEK tick baz hacmiyle beslenir.
        # Eski kod hacmi yalnızca spike geçerliyse veriyordu; filtre devreye
        # girince tick_volume=0 oluyor ve maker emirleri dolmuyordu. Ayrıca
        # 3 sn pencere TOPLAMI her tick'te yeniden verildiği için hacim
        # mükerrer sayılıyordu. Artık tek tick deltası kullanılır.
        tick_volume = base_volume if base_volume is not None else 0.0
        fill = self.broker.process_entry_tick(
            symbol, price, tick_volume, timestamp_ms,
        )
        if fill is not None:
            events.append({
                "type": "ENTRY_FILLED", "symbol": symbol,
                "price": fill.price, "quantity": fill.quantity,
                "timestamp": timestamp_ms,
            })

        # Açık pozisyonu yönet
        if symbol in self.broker.portfolio.positions:
            management = self.broker.manage_position_tick(
                symbol, price, timestamp_ms,
                atr=self._atr_for(symbol),
                funding_rate=None,
            )
            events.extend(management)
            position = self.broker.portfolio.positions.get(symbol)
            if position is not None:
                payment = self.risk.apply_funding_if_due(
                    position, price, timestamp_ms,
                )
                if payment is not None:
                    self.broker.apply_funding(symbol, payment, timestamp_ms)
                    events.append({
                        "type": "FUNDING", "symbol": symbol,
                        "payment": payment, "timestamp": timestamp_ms,
                    })
                if self.risk.margin_warning(position, price):
                    events.append({
                        "type": "MARGIN_WARNING", "symbol": symbol,
                        "timestamp": timestamp_ms,
                    })

        # Kill switch değerlendirmesi
        daily_realized = self._daily_realized()
        state = self.risk.evaluate_kill_switch(
            self.broker.portfolio, self._latest_prices, daily_realized,
        )
        if state == KillSwitchState.HARD_HALT:
            if self.broker.portfolio.positions:
                closed = self.broker.close_all(
                    self._latest_prices, timestamp_ms, reason="kill_switch_hard",
                )
                events.extend(closed)
            self.broker.cancel_pending_entries(timestamp_ms, reason="kill_switch")
        return events

    def on_candle_closed(self, symbol: str, candle: Candle) -> list[dict]:
        """5m mum kapanışı: veri bütünlüğü + sinyal değerlendirmesi."""
        events: list[dict] = []
        status = self.data_integrity.on_candle_closed(
            symbol, candle.timestamp, candle.timestamp,
        )
        if status == "gap_blocked":
            self.data_integrity.mark_symbol_stale(symbol, candle.timestamp)
            return [{"type": "GAP_BLOCKED", "symbol": symbol}]

        # Güncel mum listesini tazele
        candles = self._candles.get(symbol)
        if candles is None:
            return []
        if candles[-1].timestamp != candle.timestamp:
            candles = [*candles[1:], candle]
            self._candles[symbol] = candles

        self.broker.manage_position_candle(
            symbol, candle, candle.timestamp, atr=self._atr_for(symbol),
            impulse_pct=self._impulse(candles), rvol=self._rvol(candles),
        )

        # Sinyal değerlendirmesi
        allowed, reason = self.data_integrity.entry_allowed(
            symbol, candle.timestamp,
        )
        if not allowed:
            return [{"type": "ENTRY_BLOCKED", "symbol": symbol,
                     "reason": reason}]
        self._evaluate_entry(symbol, candles, candle.timestamp)
        return events

    # ------------------------------------------------------------------
    # Sinyal ve giriş
    # ------------------------------------------------------------------

    def _log_volume_filter(
        self, symbol: str, spike: SpikeEvent, now_ms: int,
    ) -> None:
        """v1.9: hacim filtresi logu — doğru etiket + sembol başına kısıtlama.

        - Likiditesiz enstrüman (taban hacim < eşik): BİLGİ, veri hatası değil.
        - Likit tabanda absürt sapma: UYARI, gerçek veri/birim şüphesi.
        Aynı sembol için yapılandırılan aralıkta tek satır yazılır; aradaki
        tekrarlar sayılıp bastırılır.
        """
        if spike.illiquid:
            self.low_liquidity_count += 1
            label = "LİKİDİTE DÜŞÜK"
        else:
            self.rvol_suspect_count += 1
            label = "RVOL ŞÜPHELİ"

        interval_ms = int(self.config.signal.rvol_log_interval_seconds * 1000)
        last = self._last_volume_log_ms.get(symbol)
        if last is not None and now_ms - last < interval_ms:
            self._volume_log_suppressed[symbol] = (
                self._volume_log_suppressed.get(symbol, 0) + 1
            )
            return
        self._last_volume_log_ms[symbol] = now_ms
        suppressed = self._volume_log_suppressed.pop(symbol, 0)
        extra = f" (+{suppressed} tekrar bastırıldı)" if suppressed else ""
        if spike.illiquid:
            logger.info(
                "%s: [%s] rvol=%.1f | taban %.4f USDT/sn — likidite yetersiz, "
                "hacim patlaması sinyal sayılmadı%s",
                label, symbol, spike.rvol,
                spike.baseline_notional_per_second, extra,
            )
        else:
            logger.warning(
                "%s: [%s] rvol=%.1f | taban %.2f USDT/sn — aşırı sapma, "
                "sinyal engellendi%s",
                label, symbol, spike.rvol,
                spike.baseline_notional_per_second, extra,
            )

    def _evaluate_entry(self, symbol: str, candles: list[Candle], ts_ms: int) -> None:
        if symbol in self.broker.portfolio.positions or self.broker.pending(symbol):
            return
        if self.risk.kill_switch_state == KillSwitchState.HARD_HALT:
            return
        if self._last_signal_ts.get(symbol) == ts_ms:
            return
        self._last_signal_ts[symbol] = ts_ms

        regime = self.regime_detector.classify(candles)
        btc_ctx = self._btc_context()
        ctx = MarketContext(
            symbol=symbol, candles=candles, spike=None,
            btc_change_pct_15m=btc_ctx, config=self.config,
        )
        # FINAL v1.4: motor seçimi (kapalı motor HOLD üretir, red kodu taşımaz
        # ki resolver diğer motorun açıklayıcı kodunu gösterebilsin)
        motors = self.config.signal.enabled_motors
        fade_signal = (
            self.fade.evaluate(ctx) if "fade" in motors
            else Signal("HOLD", "fade", 0.0, 0.0, None)
        )
        trend_signal = (
            self.trend.evaluate(ctx) if "trend" in motors
            else Signal("HOLD", "trend", 0.0, 0.0, None)
        )
        signal = self.resolver.resolve(fade_signal, trend_signal, regime)
        if signal.side == "HOLD":
            logger.info(
                "SİNYAL YOK: [%s] %s", symbol,
                signal.rejection_code or "-",
            )
            return
        if signal.stop_distance_fraction is None:
            return

        # FINAL v1.1 giriş kapıları: makro haber + stop-hunt duvarı.
        # Yalnızca YENİ girişi engeller; açık pozisyon yönetimi sürer.
        if self.news_guard is not None:
            blocked, reason = self.news_guard.blackout(ts_ms)
            if blocked:
                logger.info("RİSK ENGELİ: [%s] %s", symbol, reason)
                return
        if self.sweep_guard is not None:
            # v1.5 tam pazar: aday sembolün defterini giriş anında tazele.
            if self.book_fetcher is not None:
                try:
                    self.book_fetcher(symbol)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "sweep defter tazeleme hatası [%s]: %s", symbol, exc,
                    )
            reason = self.sweep_guard.entry_block(symbol, signal.side, ts_ms)
            if reason:
                logger.info("RİSK ENGELİ: [%s] %s", symbol, reason)
                return

        entry_ref = candles[-1].close
        plan = self.risk.plan(
            entry_ref, signal.stop_distance_fraction, signal.side,
            motor=signal.motor,
        )
        # FINAL v1.7: canlı fiyat stop doğrulaması. Sinyal mum kapanışından
        # gelir ama değerlendirme gecikmeli olabilir; canlı fiyat zaten stopun
        # ötesindeyse giriş ANINDA stop-out olur (FTT vakası: -4.44 USDT, 0 sn).
        # Bunu önle: canlı fiyat stopu aşmışsa girişi iptal et.
        live_price = self._latest_prices.get(symbol)
        if live_price is not None and isfinite(live_price) and live_price > 0:
            breached = (
                (signal.side == "LONG" and live_price <= plan.stop_loss)
                or (signal.side == "SHORT" and live_price >= plan.stop_loss)
            )
            if breached:
                logger.info(
                    "GİRİŞ İPTAL: [%s] canlı fiyat %.6g zaten stop %.6g "
                    "ötesinde (bayat sinyal) — giriş yapılmadı",
                    symbol, live_price, plan.stop_loss,
                )
                return
        daily_realized = self._daily_realized()
        daily_unrealized = self.broker.portfolio.unrealized_pnl(
            self._latest_prices
        )
        decision = self.risk.check_portfolio(
            self.broker.portfolio, symbol, signal.side, plan.notional,
            plan.net_risk_at_stop, self._latest_prices,
            daily_realized, daily_unrealized,
            reserved_margin=self.broker.reserved_margin(),
        )
        if not decision.allowed:
            logger.info(
                "RİSK ENGELİ: [%s] %s", symbol, decision.reason,
            )
            return

        baseline = self._baseline_liquidity(symbol)
        order = self.broker.place_entry(
            symbol, plan, ts_ms, baseline_per_second=baseline,
        )
        self.broker.bind_plan(order, plan, signal.motor)
        if self.store is not None:
            self.store.append_order_event(
                order.id, ts_ms, symbol, order.status.value,
                {"limit_price": order.limit_price, "qty": order.quantity},
            )
            self.store.mark_dirty()
        logger.info(
            "GİRİŞ EMRİ: [%s] %s limit=%.8f qty=%.6f ttl=%ss "
            "net_risk=%.2f notional=%.2f margin=%.2f",
            symbol, signal.side, order.limit_price or 0.0, order.quantity,
            self.config.exit.order_ttl_seconds, plan.net_risk_at_stop,
            plan.notional, plan.margin,
        )

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _atr_for(self, symbol: str) -> float | None:
        candles = self._candles.get(symbol) or []
        if len(candles) < 20:
            return None
        from core.indicators import atr as atr_fn
        recent = candles[-100:]
        value = atr_fn(
            [c.high for c in recent],
            [c.low for c in recent],
            [c.close for c in recent],
            self.config.exit.atr_period,
        )[-1]
        return value

    def _impulse(self, candles: list[Candle]) -> float:
        if len(candles) < 3:
            return 0.0
        return (candles[-1].close / candles[-3].close - 1.0) * 100.0

    def _rvol(self, candles: list[Candle]) -> float:
        from core.spike import candle_rvol
        return candle_rvol(
            [c.volume for c in candles],
            self.config.signal.candle_rvol_lookback,
        )

    def _btc_context(self) -> float:
        if len(self._btc_history) < 3:
            return 0.0
        return (self._btc_history[-1].close / self._btc_history[-3].close - 1.0) * 100.0

    def _baseline_liquidity(self, symbol: str) -> float:
        """Yerleştirme anındaki tahmini saniyelik baz hacim (kuyruk modeli)."""
        candles = self._candles.get(symbol) or []
        if not candles:
            return 0.0
        avg_candle = sum(c.volume for c in candles[-20:]) / min(len(candles), 20)
        return avg_candle / (self.config.data.timeframe_ms / 1000.0)

    def _daily_realized(self) -> float:
        if self.store is not None:
            return self.store.realized_pnl_since_utc_midnight()
        from datetime import datetime, timezone
        day_start = (
            int(datetime.now(timezone.utc).timestamp() * 1000) // 86_400_000
        ) * 86_400_000
        return sum(
            float(t.get("pnl", 0.0))
            for t in self.broker.trades
            if t.get("type") == "CLOSE"
            and isinstance(t.get("timestamp"), (int, float))
            and t["timestamp"] >= day_start
        )

    def restore_state(self) -> None:
        """Yeniden başlatma sonrası bakiye/pozisyon kurtarma."""
        if self.store is None:
            return
        saved = self.store.load_state()
        if not saved:
            return
        if saved.get("mode") != "paper":
            raise ValueError("paper olmayan durum geri yüklenemez")
        self.broker.portfolio.balance = float(saved.get("balance", 0))
        self.broker.portfolio.initial_balance = float(
            saved.get("initial_balance", self.broker.portfolio.initial_balance)
        )
        from core.portfolio import compute_liquidation_price
        for symbol, raw in (saved.get("positions") or {}).items():
            position = Position_from_snapshot(symbol, raw)
            position.liquidation_price = compute_liquidation_price(
                position.entry, position.side, position.leverage,
                self.config.funding,
            )
            self.broker.portfolio.positions[symbol] = position
        logger.info(
            "DURUM GERİ YÜKLENDİ: balance=%.2f pozisyon=%d",
            self.broker.portfolio.balance,
            len(self.broker.portfolio.positions),
        )

    def snapshot(self) -> dict:
        portfolio = self.broker.portfolio
        return {
            "mode": "paper",
            "balance": portfolio.balance,
            "initial_balance": portfolio.initial_balance,
            "kill_switch": self.risk.kill_switch_state.value,
            "positions": {
                symbol: {
                    "side": p.side, "entry": p.entry, "quantity": p.quantity,
                    "initial_quantity": p.initial_quantity,
                    "margin": p.margin, "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "liquidation_price": p.liquidation_price,
                    "opened_at_ms": p.opened_at_ms,
                    "entry_fee": p.entry_fee, "motor": p.motor,
                    "leverage": p.leverage,
                    "funding_paid": p.funding_paid,
                    "tp1_done": p.tp1_done,
                    "tp1_realized_pnl": p.tp1_realized_pnl,
                    "trailing_active": p.trailing_active,
                    "best_price": p.best_price,
                    "initial_net_risk": p.initial_net_risk,
                    "bars_held": p.bars_held,
                    "last_candle_timestamp": p.last_candle_timestamp,
                }
                for symbol, p in portfolio.positions.items()
            },
        }

    def persist_if_due(self, now_ms: int) -> None:
        if self.store is None:
            return
        self.store.save_state_if_due(self.snapshot(), now_ms)


def Position_from_snapshot(symbol: str, raw: dict):
    from core.portfolio import Position
    return Position(
        symbol=symbol,
        side=str(raw.get("side", "LONG")),
        entry=float(raw["entry"]),
        quantity=float(raw["quantity"]),
        initial_quantity=float(raw.get("initial_quantity", raw["quantity"])),
        margin=float(raw["margin"]),
        stop_loss=float(raw["stop_loss"]),
        opened_at_ms=int(raw.get("opened_at_ms", 0)),
        entry_fee=float(raw.get("entry_fee", 0.0)),
        motor=str(raw.get("motor", "fade")),
        leverage=float(raw.get("leverage", 10.0)),
        liquidation_price=float(raw.get("liquidation_price", 0.0)),
        funding_paid=float(raw.get("funding_paid", 0.0)),
        take_profit=(
            float(raw["take_profit"])
            if raw.get("take_profit") is not None else None
        ),
        tp1_done=bool(raw.get("tp1_done", False)),
        tp1_realized_pnl=float(raw.get("tp1_realized_pnl", 0.0)),
        trailing_active=bool(raw.get("trailing_active", False)),
        best_price=(
            float(raw["best_price"])
            if raw.get("best_price") is not None else None
        ),
        initial_net_risk=float(raw.get("initial_net_risk", 0.0)),
        bars_held=int(raw.get("bars_held", 0)),
        last_candle_timestamp=int(raw.get("last_candle_timestamp", 0)),
    )
