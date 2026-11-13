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
from collections import deque
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
)
from core.spike import SpikeEvent, SpikeDetector, estimate_secondly_base_volume
from infra.tick_verify import GridObserver
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
            min_baseline_notional_per_second=(
                self.config.signal.spike_min_baseline_notional_per_second
            ),
        )
        self._candles: dict[str, list[Candle]] = {}
        self._latest_prices: dict[str, float] = {}
        self._btc_history: list[Candle] = []
        self._last_volume_24h: dict[str, float] = {}
        # v3.1: baz hacim takibi (fiyattan bağımsız, doğru RVOL)
        self._last_base_volume_24h: dict[str, float] = {}
        self._last_signal_ts: dict[str, int] = {}
        # v5.0: hacim filtresi sayaçları + sembol başına log kısıtlama
        self.rvol_suspect_count = 0
        self.low_liquidity_count = 0
        self._last_volume_log_ms: dict[str, int] = {}
        self._volume_log_suppressed: dict[str, int] = {}
        # v5.0: sembol -> borsa fiyat ızgarası (tickSize)
        self.tick_sizes: dict[str, float] = {}
        # v5.1: canlı ızgara gözlemi — fiyat iddia edilen tick üzerinde
        # değilse ızgara yanlıştır ve sembol işlem dışı kalır.
        self.grid_observer = GridObserver()
        self.grid_rejected_entries = 0
        # v3.1 (v1.5 kuralı): tam pazar modunda giriş anında defter tazeleme.
        # İmza: (symbol_key: str) -> None; sweep_guard'ı besler. None = kapalı.
        self.book_fetcher = None
        # v3.1 (v1.7 kuralı): bayat sinyal iptal sayacı (panel + rapor)
        self.stale_entry_cancels: int = 0
        # v2.0 durumu
        self._htf_candles: dict[str, dict[str, list[Candle]]] = {}
        self.last_eval: dict[str, dict] = {}
        self.last_block_reason: dict[str, str] = {}
        self._last_regime: dict[str, object] = {}
        self._shadow_ids: dict[int, int] = {}   # record id → store id
        self.data_source: str = self.config.v2.data_source
        self.last_beta_directional: float | None = None
        # v3.0: paper stop değişim kuyruğu (testnet stop güncellemesi için)
        self.stop_updates: list[dict] = []
        # v4.0: gerçek funding oranları (borsadan gelen canlı veri; None =
        # config varsayılanı), likidasyon akışı ve long/short oranı deposu
        self._funding_rates: dict[str, float] = {}
        self._liquidations: dict[str, deque] = {}
        self._long_short: dict[str, tuple[int, float]] = {}
        # v4.0: ajan giriş kapıları (ABD piyasası / RSS haber; None = kapalı)
        self.agent_guards: list = []
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
        # v5.1: ampirik ızgara doğrulaması (vadeli API'siz kanıt)
        _tick = self.tick_sizes.get(symbol, 0.0)
        if _tick > 0 and not self.grid_observer.observe(symbol, price, _tick):
            self.tick_sizes.pop(symbol, None)
            self.broker.tick_sizes.pop(symbol, None)

        # Saniyelik baz hacim → spike dedektörü.
        # v3.1 (v1.6 kuralı): ÖNCELİK baz hacim deltasında (fiyattan bağımsız).
        # Eski quote = baz×fiyat yaklaşımı fiyat oynaklığını sahte hacim
        # sanıyordu (RVOL 100-500x şişmesi → gerçek sinyaller "şüpheli"
        # diye engelleniyordu). Baz hacim yoksa quote yolu (geriye uyum).
        spike: SpikeEvent | None = None
        base_delta = 0.0
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
            base_delta = base_volume
            spike = self.spike_detector.update(
                symbol, price, base_volume, timestamp_ms,
            )
            if spike is not None and (spike.suspect or spike.illiquid):
                # v5.0: likiditesizlik ile veri hatası AYRI etiketlenir ve
                # sembol başına kısıtlanarak loglanır (log seli yok).
                self._log_volume_filter(symbol, spike, timestamp_ms)
                spike = None

        # v2.0: tick kuralı CVD (gerçek fiyat + hacim deltasından)
        if base_delta > 0:
            self.orderflow.update_tick(symbol, price, base_delta, timestamp_ms)

        # Bekleyen giriş emirlerini besle.
        # v5.0 DÜZELTMESİ: dolum simülasyonu GERÇEK tick baz hacmiyle beslenir.
        # Eski kod hacmi yalnızca spike geçerliyse veriyordu; hacim filtresi
        # devreye girince tick_volume=0 oluyor ve maker emirleri dolmuyordu.
        # Filtre yalnızca SİNYALİ iptal eder; ölçülen hacim gerçektir.
        tick_volume = base_delta
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
            before_stop = self.broker.portfolio.positions[symbol].stop_loss
            management = self.broker.manage_position_tick(
                symbol, price, timestamp_ms,
                atr=self._atr_for(symbol),
                funding_rate=None,
            )
            events.extend(management)
            position = self.broker.portfolio.positions.get(symbol)
            if position is not None:
                # v4.0: DCA güvenlik emirleri (varsayılan KAPALI, yalnız LONG)
                dca_event = self._maybe_dca(symbol, position, price, timestamp_ms)
                if dca_event is not None:
                    events.append(dca_event)
                payment = self.risk.apply_funding_if_due(
                    position, price, timestamp_ms,
                    funding_rate=self._funding_rates.get(symbol),
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
                # v3.0: paper stop değişimi (break-even/trailing/TP1) →
                # testnet eşlemesi için STOP_UPDATE kuyruğuna yazılır.
                self._detect_stop_change(symbol, position, before_stop)

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

        before_stop = None
        if symbol in self.broker.portfolio.positions:
            before_stop = self.broker.portfolio.positions[symbol].stop_loss
        self.broker.manage_position_candle(
            symbol, candle, candle.timestamp, atr=self._atr_for(symbol),
            impulse_pct=self._impulse(candles), rvol=self._rvol(candles),
        )
        if before_stop is not None and symbol in self.broker.portfolio.positions:
            # v3.0: mum yolu stop değişimi (trailing/funding/likidasyon) takibi
            self._detect_stop_change(
                symbol, self.broker.portfolio.positions[symbol], before_stop,
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

    def _log_volume_filter(
        self, symbol: str, spike: SpikeEvent, now_ms: int,
    ) -> None:
        """v5.0: hacim filtresi logu — doğru etiket + sembol başına kısıtlama.

        - Likiditesiz enstrüman (taban hacim < eşik): BİLGİ, veri hatası değil.
        - Likit tabanda absürt sapma: UYARI, gerçek veri/birim şüphesi.
        Aynı sembol için yapılandırılan aralıkta tek satır yazılır; aradaki
        tekrarlar sayılıp bastırılır. ERROR seviyesi kaldırıldı: bunlar sistem
        hatası değil, beklenen piyasa durumlarıdır.
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
            self.last_block_reason[symbol] = "kill_switch (HARD_HALT)"
            return
        if symbol in self.grid_observer.rejected:
            # v5.1: ızgarası yanlış çıkan sembolde işlem AÇILMAZ
            self.grid_rejected_entries += 1
            self.last_block_reason[symbol] = "tick_grid_rejected"
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
            # v3.1 (v1.5 kuralı): tam pazar taramasında 1000+ defteri sürekli
            # çekmek rate limitlerine sığmaz → giriş adayı sembolün defteri
            # sinyal ANINDA tazelenir (book_fetcher; dar listede None).
            if self.book_fetcher is not None:
                try:
                    self.book_fetcher(symbol)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "sweep defter tazeleme hatası [%s]: %s", symbol, exc,
                    )
            reason = self.sweep_guard.entry_block(symbol, signal.side, ts_ms)
            if reason:
                self.last_block_reason[symbol] = f"sweep koruması: {reason}"
                self._record_shadow(symbol, signal, "SWEEP_GUARD",
                                    candles[-1].close, ts_ms)
                logger.info("RİSK ENGELİ: [%s] %s", symbol, reason)
                return

        # v4.0: ajan giriş kapıları (ABD piyasası / RSS haber). Ajanlar ASLA
        # işlem açmaz; "block" modda bayrak aktifken YENİ GİRİŞ engellenir.
        for agent in self.agent_guards:
            reason = agent.entry_block(ts_ms)
            if reason:
                self.last_block_reason[symbol] = reason
                self._record_shadow(
                    symbol, signal, agent.name.upper(),
                    candles[-1].close, ts_ms,
                )
                logger.info("AJAN ENGELİ: [%s] %s", symbol, reason)
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
        try:
            plan = self.risk.plan(
                adjusted_ref, signal.stop_distance_fraction, signal.side,
                motor=signal.motor,
                tick_size=self.tick_sizes.get(symbol, 0.0),
            )
        except ValueError as exc:
            # v5.0: fiyat ızgarası stopu aşırı genişletiyorsa işlem açılmaz.
            logger.info("RİSK ENGELİ: [%s] %s", symbol, str(exc))
            return
        # v3.1 (v1.7 kuralı): bayat sinyal giriş koruması. Sinyal, kapanmış
        # mumdan gelir ama değerlendirme gecikmeli olabilir; canlı fiyat zaten
        # stopun ötesindeyse giriş ANINDA stop-out olur (FTT vakası: sinyal
        # ~4 dk önceki mumdan, canlı fiyat stopu aşmıştı → hold_ms=0, zararla
        # kapanış). Bunu önle: canlı fiyat stopu aşmışsa girişi iptal et.
        live_price = self._latest_prices.get(symbol)
        if live_price is not None and isfinite(live_price) and live_price > 0:
            breached = (
                (signal.side == "LONG" and live_price <= plan.stop_loss)
                or (signal.side == "SHORT" and live_price >= plan.stop_loss)
            )
            if breached:
                self.stale_entry_cancels += 1
                self.last_block_reason[symbol] = (
                    f"bayat sinyal: canlı fiyat {live_price:.6g} zaten stop "
                    f"{plan.stop_loss:.6g} ötesinde"
                )
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
            reserved_margin=self.broker.reserved_margin(),
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

    # ------------------------------------------------------------------
    # v4.0: DCA güvenlik emirleri (yalnız LONG; varsayılan kapalı)
    # ------------------------------------------------------------------

    def _maybe_dca(self, symbol: str, position, price: float, ts_ms: int):
        """DCA tetikleyicisi: fiyat ortalama girişin altına adım kadar düşer.

        Güvenlik kuralları (fail-closed):
          - Yalnız LONG; max_safety_orders aşılmasın.
          - Toplam net risk (DCA sonrası, maliyetler dâhil) pozisyon başı
            max_loss_per_position tavanını AŞMASIN.
          - Serbest bakiye ek marjı kaldırsın.
        Koşullar sağlanmazsa DCA yapılmaz ve sebep loglanır.
        """
        cfg = self.config.dca
        if not cfg.enabled or position.side != "LONG":
            return None
        if position.dca_count >= max(0, int(cfg.max_safety_orders)):
            return None
        step_pct = cfg.first_step_pct * (max(cfg.step_scale, 1.0) ** position.dca_count)
        trigger = position.entry * (1.0 - step_pct / 100.0)
        if price > trigger or price <= 0:
            return None
        initial_notional = position.margin * max(position.leverage, 1.0)
        dca_notional = initial_notional * (max(cfg.volume_scale, 0.0) ** position.dca_count)
        quantity = dca_notional / price
        if quantity <= 0 or not isfinite(quantity):
            return None
        new_qty = position.quantity + quantity
        new_entry = (
            position.entry * position.quantity + price * quantity
        ) / new_qty
        stop_frac = abs(new_entry - position.stop_loss) / new_entry
        cost = self.broker._cost_rate()
        new_net_risk = new_qty * new_entry * (stop_frac + cost)
        cap = self.config.account.max_loss_per_position
        if cap > 0 and new_net_risk > cap:
            logger.info(
                "DCA ATLANDI: [%s] net risk %.2f > %.2f tavanı",
                symbol, new_net_risk, cap,
            )
            return None
        margin_add = quantity * price / max(position.leverage, 1.0)
        portfolio = self.broker.portfolio
        if portfolio.balance - (portfolio.used_margin + margin_add) <= 0:
            logger.info("DCA ATLANDI: [%s] serbest bakiye yetersiz", symbol)
            return None
        event = self.broker.apply_dca(symbol, quantity, price, ts_ms)
        if event is not None:
            logger.info(
                "DCA GÜVENLİK EMRİ: [%s] qty=%.6f @ %.6g | ort=%.6g "
                "| güvenlik emri %d/%d",
                symbol, quantity, price, new_entry, position.dca_count,
                cfg.max_safety_orders,
            )
        return event

    # ------------------------------------------------------------------
    # v4.0: para akışı verileri (OI + CVD mevcut; likidasyon + L/S + funding)
    # ------------------------------------------------------------------

    def set_funding_rate(self, symbol: str, rate: float) -> None:
        """Borsadan gelen GERÇEK funding oranı (8s dönemlik ondalık)."""
        self._funding_rates[symbol] = float(rate)

    def update_long_short(self, symbol: str, ratio: float, ts_ms: int) -> None:
        """Borsa long/short hesap oranı (gösterge; skorlamaya dokunmaz)."""
        if isfinite(ratio) and ratio > 0:
            self._long_short[symbol] = (int(ts_ms), float(ratio))

    def update_liquidation(
        self, symbol: str, liquidated_side: str, notional_usd: float,
        ts_ms: int,
    ) -> None:
        """Likidasyon akışı: likide olan taraf ('LONG'|'SHORT') + nominal."""
        if notional_usd <= 0:
            return
        window = self._liquidations.setdefault(symbol, deque())
        window.append((int(ts_ms), str(liquidated_side), float(notional_usd)))
        max_age = self.config.v2.orderflow.liquidation_window_s * 1000.0
        while window and ts_ms - window[0][0] > max_age:
            window.popleft()

    def liquidation_flow(self, symbol: str, now_ms: int) -> dict:
        """Penceredeki likidasyon akışı: {long_liq_usd, short_liq_usd}."""
        window = self._liquidations.get(symbol)
        max_age = self.config.v2.orderflow.liquidation_window_s * 1000.0
        if not window:
            return {"long_liq_usd": 0.0, "short_liq_usd": 0.0,
                    "unavailable": True}
        long_usd = sum(n for ts, side, n in window
                       if side == "LONG" and now_ms - ts <= max_age)
        short_usd = sum(n for ts, side, n in window
                        if side == "SHORT" and now_ms - ts <= max_age)
        return {"long_liq_usd": round(long_usd, 2),
                "short_liq_usd": round(short_usd, 2), "unavailable": False}

    def long_short_ratio(self, symbol: str, now_ms: int) -> float | None:
        record = self._long_short.get(symbol)
        if record is None:
            return None
        ts, ratio = record
        if now_ms - ts > self.config.v2.orderflow.moneyflow_max_age_s * 1000.0:
            return None  # bayat veri 'uygulanmadı' sayılır
        return ratio

    def money_flow_summary(self, now_ms: int) -> dict:
        """Açık pozisyon sembolleri için para akışı özeti (panel/rapor)."""
        out: dict[str, dict] = {}
        for symbol in self.broker.portfolio.positions:
            ls = self.long_short_ratio(symbol, now_ms)
            flow = self.liquidation_flow(symbol, now_ms)
            out[symbol] = {
                "long_short_ratio": round(ls, 3) if ls is not None else None,
                "liquidation": flow,
                "funding_rate": self._funding_rates.get(symbol),
            }
        return out

    def _detect_stop_change(self, symbol: str, position, before_stop: float) -> None:
        """v3.0: paper stop değişimini yakalar ve eşleme kuyruğuna yazar.

        break-even / ATR trailing / TP1 sonrası stop kayması buradan
        live_mirror_task'a aktarılır (borsadaki koruyucu stop güncellenir).
        """
        new_stop = position.stop_loss
        if before_stop is None or abs(float(before_stop) - new_stop) < 1e-12:
            return
        import time as _time
        self.stop_updates.append({
            "type": "STOP_UPDATE", "symbol": symbol, "side": position.side,
            "new_stop": new_stop, "signal_key": position.signal_key or symbol,
            "timestamp": int(_time.time() * 1000),
        })

    def drain_stop_updates(self) -> list[dict]:
        """v3.0: stop güncelleme kuyruğunu boşaltır (canlı eşleme görevi)."""
        drained = list(self.stop_updates)
        self.stop_updates.clear()
        return drained

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
                    "dca_count": p.dca_count,
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
        dca_count=int(raw.get("dca_count", 0)),
    )
