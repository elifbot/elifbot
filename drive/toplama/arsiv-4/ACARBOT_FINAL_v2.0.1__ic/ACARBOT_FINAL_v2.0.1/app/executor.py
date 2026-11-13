"""Sinyal → risk → emir orkestrasyonu (canlı ve backtest ortak katman).

v2.0 entegrasyonu (kullanıcı şartnamesi):
  - Ortak sinyal boru hattı: akıllı rejim + FADE/TREND + 4 uzman + Hakem
    + MTF çelişki kapısı + 100 puanlık skorlama (core/pipeline.py).
  - Giriş kapıları: haber/sweep (v1.1) + BTC şok testi + beta ayarlı yön
    tavanı + giriş hız limiti + stop-sonrası yeniden giriş beklemesi.
  - Order flow: gerçek defter (imbalance/küme/absorption), tick-kuralı CVD,
    OI değişimi (borsa destekliyorsa).
  - Gölge sinyal: haber/sweep'in engellediği girişlerin 30/60/120 dk
    hipotetik getirisi kaydedilir.
  - Ters sinyal çıkışı: güçlü ters sinyal (skor >= 80) açık pozisyonu
    erken kapatabilir; stoplar/çıkışlar her koşulda çalışmaya devam eder.
"""

from __future__ import annotations

import logging
from math import isfinite

from core.config import SuperConfig
from core.experts import ExpertPerformanceTracker
from core.gates import (
    EntryRateLimiter,
    ReentryCooldown,
    ShadowSignalTracker,
)
from core.mtf import MtfAnalyzer, MtfReading
from core.orderflow import OrderFlowEngine
from core.pipeline import SignalPipeline
from core.portfolio_risk import (
    BetaEstimator,
    BtcShockTester,
    base_asset_of,
    beta_adjusted_directional_notional,
)
from core.risk import (
    KillSwitchState,
    RiskManager,
    TradePlan,
)
from core.spike import SpikeEvent, SpikeDetector, estimate_secondly_base_volume
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
        # v2.0 bileşenleri
        self.pipeline = SignalPipeline(self.config)
        self.orderflow = OrderFlowEngine(self.config.v2.orderflow)
        self.mtf_analyzer = MtfAnalyzer(self.config.v2.mtf)
        self.rate_limiter = EntryRateLimiter(self.config.v2.gates)
        self.cooldown = ReentryCooldown(self.config.v2.gates)
        self.shadow_tracker = ShadowSignalTracker()
        self.beta_estimator = BetaEstimator(self.config.v2.gates)
        self.shock_tester = BtcShockTester(self.config.v2.gates)
        self.expert_performance = ExpertPerformanceTracker(self.config.v2.experts)
        # v1.2 uyumluluğu: eski motorlar da tutulur (dashboard/diagnostik)
        self.fade = self.pipeline.fade
        self.trend = self.pipeline.trend
        self.resolver = self.pipeline.resolver
        self.regime_detector = self.pipeline.legacy_regime
        self.spike_detector = SpikeDetector(
            multiplier=self.config.signal.spike_multiplier,
            lookback_seconds=self.config.data.timeframe_ms // 1000,
            window_seconds=self.config.signal.spike_window_seconds,
            direction_seconds=self.config.signal.spike_direction_seconds,
            sanity_cap=self.config.signal.spike_rvol_sanity_cap,
        )
        self._candles: dict[str, list[Candle]] = {}
        self._latest_prices: dict[str, float] = {}
        self._btc_history: list[Candle] = []
        self._last_volume_24h: dict[str, float] = {}
        self._last_signal_ts: dict[str, int] = {}
        # v2.0 durumu
        self._htf_candles: dict[str, dict[str, list[Candle]]] = {}
        self.last_eval: dict[str, dict] = {}
        self.last_block_reason: dict[str, str] = {}
        self._last_regime: dict[str, object] = {}
        self._shadow_ids: dict[int, int] = {}   # record id → store id
        self.data_source: str = self.config.v2.data_source
        self.last_beta_directional: float | None = None
        self.last_shock_summary: dict = {"checked": 0, "blocked": 0,
                                         "unavailable": 0}
        self.risk_stats: dict[str, float] = {
            "max_concurrent_positions": 0.0,
            "max_margin_used": 0.0,
            "min_free_margin": float(broker.portfolio.initial_balance),
            "equity_peak": broker.portfolio.initial_balance,
            "equity_trough": broker.portfolio.initial_balance,
        }

    # ------------------------------------------------------------------
    # Veri besleme
    # ------------------------------------------------------------------

    def update_candles(self, symbol: str, candles: list[Candle]) -> None:
        if not candles:
            return
        self._candles[symbol] = list(candles)
        if symbol.upper().startswith("BTC"):
            self._btc_history = list(candles)

    def update_htf_candles(
        self, symbol: str, timeframe: str, candles: list[Candle],
    ) -> None:
        """v2.0: üst zaman dilimi mumları (15m/1h/4h, kapanmışlar)."""
        if not candles:
            return
        self._htf_candles.setdefault(symbol, {})[timeframe] = list(candles)

    def update_order_book(self, key: str, bids, asks, ts_ms: int) -> None:
        """v2.0: order flow motoruna gerçek defter anlık görüntüsü."""
        self.orderflow.update_book(key, bids, asks, ts_ms)

    def update_open_interest(self, key: str, oi_value: float, ts_ms: int) -> None:
        """v2.0: borsadan gelen gerçek açık pozisyon (OI)."""
        self.orderflow.update_open_interest(key, oi_value, ts_ms)

    def set_data_source(self, label: str) -> None:
        """v2.0: veri kaynağı etiketi ('perp' | 'spot-mirror').

        Etiket executor'da tutulur (config frozen'dır; canlıda parametre
        nesnesi değiştirilmez — şartname güvenlik kuralı).
        """
        if label != self.data_source:
            logger.warning("VERİ KAYNAĞI: %s → %s (raporlar etiketlenir)",
                           self.data_source, label)
            self.data_source = label

    def process_price_update(
        self,
        symbol: str,
        price: float,
        timestamp_ms: int,
        volume_24h_quote: float | None = None,
        exchange: str = "binance",
    ) -> list[dict]:
        """Tick işleme: dolum simülasyonu, çıkış yönetimi, funding, kill switch.

        Dönen değer: oluşan işlem/olay kayıtları (log + Telegram için).
        """
        if not isfinite(price) or price <= 0 or timestamp_ms < 0:
            raise ValueError("tick fiyatı/zamanı geçersiz")
        events: list[dict] = []
        self.data_integrity.record_tick(symbol, timestamp_ms)
        self._latest_prices[symbol] = price

        # Saniyelik baz hacim (24s gösterge deltasından) → spike dedektörü
        spike: SpikeEvent | None = None
        base_delta = 0.0
        if volume_24h_quote is not None:
            last = self._last_volume_24h.get(symbol)
            self._last_volume_24h[symbol] = volume_24h_quote
            if last is not None and volume_24h_quote >= last:
                delta = volume_24h_quote - last
                base_volume = estimate_secondly_base_volume(
                    delta, price, contract_size=1.0,
                )
                base_delta = base_volume
                spike = self.spike_detector.update(
                    symbol, price, base_volume, timestamp_ms,
                )
                if spike is not None and spike.suspect:
                    logger.error(
                        "RVOL ŞÜPHELİ: [%s] rvol=%.1f — birim/veri hatası, "
                        "sinyal engellendi",
                        symbol, spike.rvol,
                    )
                    spike = None

        # v2.0: tick kuralı CVD (gerçek fiyat + hacim deltasından)
        if base_delta > 0:
            self.orderflow.update_tick(symbol, price, base_delta, timestamp_ms)

        # Bekleyen giriş emirlerini besle
        tick_volume = base_delta if spike is not None else 0.0
        fill = self.broker.process_entry_tick(
            symbol, price, tick_volume, timestamp_ms,
        )
        if fill is not None:
            events.append({
                "type": "ENTRY_FILLED", "symbol": symbol,
                "price": fill.price, "quantity": fill.quantity,
                "timestamp": timestamp_ms,
            })
            # v2.0: hız limiti sayaçları GERÇEK girişleri sayar
            if self.config.v2.enabled:
                self.rate_limiter.record(timestamp_ms)

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

        # v2.0: çıkış kayıtları → yeniden giriş beklemesi + uzman performansı
        self._record_exits(events, timestamp_ms)
        # v2.0: gölge sinyal fiyat takibi
        if self.shadow_tracker.records:
            self._update_shadow(symbol, price, timestamp_ms)
        # v2.0: risk istatistikleri (oturum raporu için)
        self._update_risk_stats(timestamp_ms)

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
            if candles[-1].timestamp > candle.timestamp:
                # v2.0 (şartname 2): eksik/forming mum değerlendirmeye alınmaz —
                # REST listesinin sonu forming mumdur; kapanan mumla değiştir.
                # Kapanan mum listede zaten varsa yalnızca forming düşürülür.
                trimmed = candles[:-1]
                if trimmed and trimmed[-1].timestamp == candle.timestamp:
                    candles = trimmed
                else:
                    candles = [*trimmed, candle]
            else:
                candles = [*candles[1:], candle]
            self._candles[symbol] = candles

        self.broker.manage_position_candle(
            symbol, candle, candle.timestamp, atr=self._atr_for(symbol),
            impulse_pct=self._impulse(candles), rvol=self._rvol(candles),
        )
        self._record_exits(events, candle.timestamp)
        if self.shadow_tracker.records:
            self._update_shadow(symbol, candle.close, candle.timestamp)

        # Sinyal değerlendirmesi
        allowed, reason = self.data_integrity.entry_allowed(
            symbol, candle.timestamp,
        )
        if not allowed:
            self.last_block_reason[symbol] = f"veri: {reason}"
            return [{"type": "ENTRY_BLOCKED", "symbol": symbol,
                     "reason": reason}]
        self._flush_deferred(candle.timestamp)
        self._evaluate_entry(symbol, candles, candle.timestamp)
        return events

    # ------------------------------------------------------------------
    # Sinyal ve giriş (v2.0 boru hattı)
    # ------------------------------------------------------------------

    def _evaluate_entry(self, symbol: str, candles: list[Candle], ts_ms: int) -> None:
        if symbol in self.broker.portfolio.positions or self.broker.pending(symbol):
            return
        if self.risk.kill_switch_state == KillSwitchState.HARD_HALT:
            self.last_block_reason[symbol] = "kill_switch (HARD_HALT)"
            return
        if self._last_signal_ts.get(symbol) == ts_ms:
            return
        self._last_signal_ts[symbol] = ts_ms

        btc_ctx = self._btc_context()
        mtf_reading = self._mtf_for(symbol)
        decision = self.pipeline.evaluate(
            symbol=symbol, candles=candles,
            btc_change_pct_15m=btc_ctx,
            mtf_reading=mtf_reading,
            orderflow_engine=self.orderflow if self.config.v2.enabled else None,
            orderflow_key=symbol,
        )
        self._last_regime[symbol] = decision.regime
        self.last_eval[symbol] = {
            "ts": ts_ms,
            "side": decision.signal.side,
            "score": decision.score.total if decision.score else 0.0,
            "grade": decision.score.grade if decision.score else "-",
            "regime": decision.regime.regime.value,
            "reason": decision.reason_text(),
            "components": (
                decision.score.as_dict()["components"] if decision.score else []
            ),
            "votes": [v.__dict__ for v in decision.votes],
            "rejection": decision.rejection_code,
        }
        signal = decision.signal
        if signal.side == "HOLD":
            self.last_block_reason[symbol] = decision.reason_text()
            logger.info(
                "SİNYAL YOK: [%s] %s", symbol,
                decision.rejection_code or signal.rejection_code or "-",
            )
            return
        if signal.stop_distance_fraction is None:
            self.last_block_reason[symbol] = "geçersiz stop mesafesi"
            return

        # FINAL v1.1 giriş kapıları: makro haber + stop-hunt duvarı.
        # Yalnızca YENİ girişi engeller; açık pozisyon yönetimi sürer.
        if self.news_guard is not None:
            blocked, reason = self.news_guard.blackout(ts_ms)
            if blocked:
                self.last_block_reason[symbol] = f"haber koruması: {reason}"
                self._record_shadow(symbol, signal, "NEWS_GUARD",
                                    candles[-1].close, ts_ms)
                logger.info("RİSK ENGELİ: [%s] %s", symbol, reason)
                return
        if self.sweep_guard is not None:
            reason = self.sweep_guard.entry_block(symbol, signal.side, ts_ms)
            if reason:
                self.last_block_reason[symbol] = f"sweep koruması: {reason}"
                self._record_shadow(symbol, signal, "SWEEP_GUARD",
                                    candles[-1].close, ts_ms)
                logger.info("RİSK ENGELİ: [%s] %s", symbol, reason)
                return

        # v2.0: stop-sonrası yeniden giriş beklemesi
        wait = self.cooldown.blocked(symbol, ts_ms)
        if wait is not None:
            self.last_block_reason[symbol] = (
                f"yeniden giriş beklemesi ({wait:.0f} dk, "
                f"önceki: {self.cooldown.last_reason(symbol)})"
            )
            logger.info(
                "RİSK ENGELİ: [%s] yeniden giriş beklemesi %.1f dk",
                symbol, wait,
            )
            return

        entry_ref = candles[-1].close
        # v2.0: spread-duyarlı giriş — taze defter ölçümü varsa limit,
        # yarım spread kadar kötüleştirilir (gerçek veri; yoksa dokunulmaz).
        spread_bps_live = None
        flow_snapshot = self.orderflow._snapshots.get(symbol)
        if flow_snapshot is not None and flow_snapshot.spread_bps is not None:
            spread_bps_live = flow_snapshot.spread_bps
        half_spread = (
            entry_ref * (spread_bps_live / 10_000.0) / 2.0
            if spread_bps_live is not None and spread_bps_live > 0 else 0.0
        )
        direction_sign = 1.0 if signal.side == "LONG" else -1.0
        # Plan, spread-duyarlı referansla HEMEN kurulur (şok testi notional
        # kullanır; limit yerleştirme aynı planla yapılır).
        adjusted_ref = entry_ref - direction_sign * half_spread
        plan = self.risk.plan(
            adjusted_ref, signal.stop_distance_fraction, signal.side,
            motor=signal.motor,
        )
        daily_realized = self._daily_realized()
        daily_unrealized = self.broker.portfolio.unrealized_pnl(
            self._latest_prices
        )

        # v2.0: BTC şok testi + beta ayarlı yön tavanı (GERÇEK betalar)
        beta_directional = None
        if self.config.v2.enabled:
            symbol_betas = self._current_betas()
            planned_beta = symbol_betas.get(base_asset_of(symbol))
            equity = self.broker.portfolio.equity(self._latest_prices)
            shock = self.shock_tester.evaluate(
                positions=self.broker.portfolio.positions,
                prices=self._latest_prices,
                planned_symbol=symbol,
                planned_side=signal.side,
                planned_notional=plan.notional,
                planned_beta=planned_beta,
                betas=symbol_betas,
                equity=equity,
            )
            if not shock.available:
                self.last_shock_summary["unavailable"] = (
                    self.last_shock_summary.get("unavailable", 0) + 1
                )
            else:
                self.last_shock_summary["checked"] = (
                    self.last_shock_summary.get("checked", 0) + 1
                )
                if shock.blocked:
                    self.last_shock_summary["blocked"] = (
                        self.last_shock_summary.get("blocked", 0) + 1
                    )
                    self.last_block_reason[symbol] = (
                        f"BTC şok testi: {shock.worst_loss:.0f} USDT > "
                        f"{shock.cap:.0f} USDT tavanı"
                    )
                    logger.info("RİSK ENGELİ: [%s] %s", symbol,
                                self.last_block_reason[symbol])
                    return
            if symbol_betas:
                beta_directional = beta_adjusted_directional_notional(
                    self.broker.portfolio.positions, self._latest_prices,
                    symbol, signal.side, plan.notional, planned_beta,
                    symbol_betas,
                )
                self.last_beta_directional = beta_directional

        decision_risk = self.risk.check_portfolio(
            self.broker.portfolio, symbol, signal.side, plan.notional,
            plan.net_risk_at_stop, self._latest_prices,
            daily_realized, daily_unrealized,
            beta_adjusted_directional=beta_directional,
        )
        if not decision_risk.allowed:
            self.last_block_reason[symbol] = f"risk: {decision_risk.reason}"
            logger.info(
                "RİSK ENGELİ: [%s] %s", symbol, decision_risk.reason,
            )
            return

        # v2.0: giriş hız limiti (dakikada en fazla N GERÇEK giriş)
        if self.config.v2.enabled and not self.rate_limiter.allow(ts_ms):
            score = decision.score.total if decision.score else 0.0
            self.rate_limiter.defer(symbol, signal.side, score, ts_ms)
            self.last_block_reason[symbol] = (
                f"giriş hız limiti ({self.config.v2.gates.entry_rate_per_min}/dk); "
                "aday kuyruğa alındı"
            )
            logger.info(
                "RİSK ENGELİ: [%s] giriş hız limiti — aday kuyruğa alındı",
                symbol,
            )
            return

        # v2.0: 1 dakikalık giriş zamanlaması (veri varsa)
        if self.config.v2.enabled and self.config.v2.mtf.enabled:
            by_tf = self._htf_candles.get(symbol) or {}
            timing = self.mtf_analyzer.entry_timing(
                by_tf.get("1m"), signal.side,
            )
            if timing == "wait":
                self.last_block_reason[symbol] = (
                    "1m zamanlama ters: bir sonraki mumda yeniden denenecek"
                )
                logger.info(
                    "RİSK ENGELİ: [%s] 1m giriş zamanlaması ters", symbol,
                )
                return

        baseline = self._baseline_liquidity(symbol)
        # Plan yukarıda spread-duyarlı referansla kuruldu; doğrudan yerleştir
        order = self.broker.place_entry(
            symbol, plan, ts_ms, baseline_per_second=baseline,
        )
        self.broker.bind_plan(order, plan, signal.motor, meta={
            "score": decision.score.total if decision.score else 0.0,
            "regime": decision.regime.regime.value,
            "experts": ",".join(
                f"{v.motor}:{v.side}" for v in decision.votes if v.side != "NONE"
            ),
        })
        if self.store is not None:
            self.store.append_order_event(
                order.id, ts_ms, symbol, order.status.value,
                {"limit_price": order.limit_price, "qty": order.quantity},
            )
            self.store.mark_dirty()
        self.last_block_reason.pop(symbol, None)
        logger.info(
            "GİRİŞ EMRİ: [%s] %s limit=%.8f qty=%.6f ttl=%ss net_risk=%.2f skor=%.0f",
            symbol, signal.side, order.limit_price or 0.0, order.quantity,
            self.config.exit.order_ttl_seconds, plan.net_risk_at_stop,
            decision.score.total if decision.score else 0.0,
        )

    # ------------------------------------------------------------------
    # v2.0 yardımcıları
    # ------------------------------------------------------------------

    def _record_exits(self, events: list[dict], ts_ms: int) -> None:
        for event in events:
            if event.get("type") != "CLOSE":
                continue
            reason = str(event.get("reason", ""))
            self.cooldown.record_exit(event.get("symbol", ""), ts_ms, reason)
            r_value = event.get("r_multiple")
            if isinstance(r_value, (int, float)):
                self.expert_performance.record(
                    str(event.get("motor", "fade")), float(r_value),
                )

    def _record_shadow(self, symbol: str, signal, reason: str,
                       entry_ref: float, ts_ms: int) -> None:
        if not self.config.v2.enabled:
            return
        stop_fraction = signal.stop_distance_fraction or 0.0
        record = self.shadow_tracker.record_blocked(
            symbol, signal.side, reason, entry_ref, stop_fraction, ts_ms,
        )
        if record is not None and self.store is not None:
            store_id = self.store.append_shadow_signal(
                ts_ms, symbol, signal.side, reason, entry_ref, {}, False,
            )
            self._shadow_ids[id(record)] = store_id

    def _update_shadow(self, symbol: str, price: float, ts_ms: int) -> None:
        updated = self.shadow_tracker.on_price(symbol, price, ts_ms)
        if not updated or self.store is None:
            return
        for record in self.shadow_tracker.records:
            if record.symbol != symbol:
                continue
            store_id = self._shadow_ids.get(id(record))
            if store_id is not None:
                self.store.update_shadow_signal(
                    store_id, record.returns, record.matured,
                )

    def _current_betas(self) -> dict[str, float]:
        """Tüm izlenen semboller için güncel beta seti (GERÇEK 5m kapanışları)."""
        betas: dict[str, float] = {}
        btc_closes = [c.close for c in self._btc_history]
        if not btc_closes:
            return betas
        for symbol, candles in self._candles.items():
            if symbol.upper().startswith("BTC"):
                continue
            beta = self.beta_estimator.beta(
                [c.close for c in candles], btc_closes,
            )
            if beta is not None:
                betas[base_asset_of(symbol)] = beta
        return betas

    def _mtf_for(self, symbol: str) -> MtfReading | None:
        """REST'ten gelen üst TF mumları varsa onları kullan (canlı yolu)."""
        by_tf = self._htf_candles.get(symbol)
        if not by_tf:
            return None
        return self.mtf_analyzer.analyze_rest(by_tf)

    def _flush_deferred(self, ts_ms: int) -> None:
        """Hız limitine takılan adayları skora göre yeniden dener."""
        if not self.config.v2.enabled:
            return
        candidates = self.rate_limiter.flush(ts_ms)
        for candidate in candidates:
            candles = self._candles.get(candidate.symbol)
            if not candles:
                continue
            if (
                candidate.symbol in self.broker.portfolio.positions
                or self.broker.pending(candidate.symbol)
            ):
                self.rate_limiter._deferred.remove(candidate)
                continue
            if self.rate_limiter.allow(ts_ms):
                self.rate_limiter._deferred.remove(candidate)
                self._last_signal_ts.pop(candidate.symbol, None)
                self._evaluate_entry(candidate.symbol, candles, ts_ms)

    def _update_risk_stats(self, now_ms: int) -> None:
        portfolio = self.broker.portfolio
        prices = self._latest_prices
        unrealized = portfolio.unrealized_pnl(prices)
        equity = portfolio.balance + unrealized
        free_margin = portfolio.balance + unrealized - portfolio.used_margin
        stats = self.risk_stats
        stats["max_concurrent_positions"] = max(
            stats["max_concurrent_positions"], float(len(portfolio.positions)),
        )
        stats["max_margin_used"] = max(
            stats["max_margin_used"], portfolio.used_margin,
        )
        stats["min_free_margin"] = min(stats["min_free_margin"], free_margin)
        stats["equity_peak"] = max(stats["equity_peak"], equity)
        stats["equity_trough"] = min(stats["equity_trough"], equity)

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
            "data_source": self.data_source,
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
                    "score": p.score, "regime": p.regime,
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
        score=float(raw.get("score", 0.0)),
        regime=str(raw.get("regime", "")),
    )
