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

from backtest.costs import CostModel
from backtest.intrabar import IntrabarPath, overshoot_ratio
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
from core.risk_scaling import RiskScaler
from exec.orders import Order, OrderSide, OrderType
from exec.paper import PaperBroker
from infra.market_data.models import Candle

logger = logging.getLogger(__name__)


def audit_trade_risk(trades, breach_ratio: float = 1.3) -> dict:
    """v5.1 — GERÇEKLEŞEN / HEDEF kayıp denetimi.

    Her kapanış için `pnl / target_net_risk` oranı hesaplanır. Zararlı
    işlemlerde bu oran 1.0'dan büyükse hedef aşılmış demektir. `breach_ratio`
    (varsayılan 1,3) üstündekiler İŞARETLENİR ve raporda listelenir.

    Ayrıca stop AŞIMI (overshoot) ölçülür: çıkış fiyatı stop seviyesinin ne
    kadar ötesinde gerçekleşti, stop mesafesine oranla. Bu, "mum ucu
    kötümserliği mi yoksa gerçek gap mi?" sorusunu sayısallaştırır.
    """
    closes = [t for t in trades if t.get("type") == "CLOSE"]
    rows: list[dict] = []
    breaches: list[dict] = []
    for trade in closes:
        target = float(trade.get("target_net_risk") or 0.0)
        pnl = float(trade.get("pnl", 0.0))
        ratio = (abs(pnl) / target) if (pnl < 0 and target > 0) else 0.0
        entry = float(trade.get("entry") or 0.0)
        stop = float(trade.get("stop_loss") or 0.0)
        price = float(trade.get("price") or 0.0)
        over = (
            overshoot_ratio(str(trade.get("side", "LONG")), entry, stop, price)
            if entry > 0 and stop > 0 and price > 0 else 0.0
        )
        row = {
            "symbol": trade.get("symbol"),
            "reason": trade.get("reason"),
            "pnl": round(pnl, 4),
            "target_net_risk": round(target, 4),
            "realized_over_target": round(ratio, 4),
            "stop_overshoot_ratio": round(over, 4),
            "breach": ratio > breach_ratio,
        }
        rows.append(row)
        if row["breach"]:
            breaches.append(row)
    losses = [r["realized_over_target"] for r in rows if r["realized_over_target"] > 0]
    stop_rows = [r for r in rows if str(r["reason"] or "").endswith("stop")
                 or str(r["reason"] or "") in ("stop_loss", "trailing_stop",
                                               "position_loss_stop")]
    return {
        "breach_ratio_threshold": breach_ratio,
        "closed_trades": len(rows),
        "losing_trades": len(losses),
        "breaches": breaches,
        "breach_count": len(breaches),
        "breach_rate": round(len(breaches) / len(losses), 4) if losses else 0.0,
        "max_realized_over_target": round(max(losses), 4) if losses else 0.0,
        "mean_realized_over_target": (
            round(sum(losses) / len(losses), 4) if losses else 0.0
        ),
        "max_stop_overshoot_ratio": (
            round(max((r["stop_overshoot_ratio"] for r in stop_rows), default=0.0), 4)
        ),
        "trades": rows,
    }


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
    # v5.1 şeffaflık alanları
    path_source: str = "single_candle"
    intrabar: dict = field(default_factory=dict)
    cost_model: dict = field(default_factory=dict)
    risk_audit: dict = field(default_factory=dict)
    exit_slippage_bps: float = 0.0
    grid_symbols: int = 0
    # v5.2 seffaflik alani
    risk_scaling: dict = field(default_factory=dict)
    # v5.2: dolum iyimserligi — TTL disi dolum olcumu
    fill_optimism: dict = field(default_factory=dict)

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
    risk_budget: float = 0.0          # v5.2: dolumda ayni butce kullanilir


class BacktestEngine:
    """Portföy düzeyinde çoklu sembol simülasyonu (5m mumlar)."""

    def __init__(
        self,
        config: SuperConfig | None = None,
        initial_balance: float | None = None,
        max_positions: int | None = None,
        max_history_bars: int = 400,
    ) -> None:
        # v5.1: gösterge pencereleri en fazla ~200 bar ister (EMA200, ADX14,
        # yapı 60). Tüm geçmişi taşımak her barda yeniden doğrulamaya yol
        # açıyordu → O(n²). 400 barlık kayan pencere anlamı değiştirmez.
        if max_history_bars < 250:
            raise ValueError("max_history_bars >= 250 olmalı (EMA200 için)")
        self.max_history_bars = max_history_bars
        self.base_config = config or SuperConfig()
        self.initial_balance = (
            initial_balance or self.base_config.account.initial_balance
        )
        self.max_positions_override = max_positions
        # v5.2: KAPI ATIF ANALIZI. None = kapali (uretim davranisi degismez).
        # Liste verilirse, SINYALI OLUSMUS her giris adayi kaydedilir ve
        # hangi kapinin reddettigi isaretlenir. Boylece "bu kapı bizi
        # kârdan etti mi?" sorusu olculebilir olur.
        self.gate_probe: list[dict] | None = None
        # v5.2: DOLUM İYİMSERLİĞİ ÖLÇÜMÜ. Backtest, bekleyen limiti
        # SONRAKİ 5m mumun tüm aralığıyla denetler; TTL yalnız emir
        # dokunulmamışsa uygulanır. Gerçekte emir 45 sn yaşar, burada
        # 300 sn şans alır. Kaç dolumun TTL dışında gerçekleştiği sayılır.
        self.fills_after_ttl: int = 0
        self.fills_total: int = 0
        self.expired_after_ttl: int = 0

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
        cost_model: CostModel | None = None,
        intrabar: IntrabarPath | None = None,
        tick_sizes: dict[str, float] | None = None,
        fine_candles_by_symbol: dict[str, list[Candle]] | None = None,
    ) -> BacktestResult:
        config = self._build_config()
        broker = PaperBroker(config, self.initial_balance)
        risk = RiskManager(config)
        broker.risk_manager_ref = risk
        # v5.1: fiyat ızgarası backtest'te de uygulanır (v5.0'da uygulanmıyordu)
        if tick_sizes:
            broker.tick_sizes = dict(tick_sizes)
        # v5.1: maliyet modeli — verilmezse MUHAFAZAKÂR varsayılan (kapalı DEĞİL)
        costs = cost_model if cost_model is not None else CostModel()
        # v5.2: dinamik risk olcekleme — her giristen once butce uretir
        scaler = RiskScaler(config.risk_scaling)
        peak_equity = self.initial_balance
        seen_trades = 0
        # v5.1: mum içi yol — 1m verilirse gerçek sıra, yoksa sentetik sınır
        path = intrabar
        if path is None and fine_candles_by_symbol:
            path = IntrabarPath(fine_by_symbol=fine_candles_by_symbol)
        base_extra_slippage = broker.extra_slippage_rate
        pipeline = SignalPipeline(config)
        rate_limiter = EntryRateLimiter(config.v2.gates)
        cooldown = ReentryCooldown(config.v2.gates)
        beta_estimator = BetaEstimator(config.v2.gates)
        shock_tester = BtcShockTester(config.v2.gates)
        participant_cap = config.data.bt_participant_cap
        # v5.1: sembol başına maliyet; config değerleri yalnızca ölçüm yoksa
        # devreye giren eski yol olarak korunur (geriye uyum).
        _symbols_all = set(candles_by_symbol)
        if cost_model is not None or spread_bps is None:
            spread_bps = costs.spread_map(_symbols_all)
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
            # v5.2: yeni kapanan islemleri olcekleyiciye besle (NET pnl)
            if len(broker.trades) > seen_trades:
                for event in broker.trades[seen_trades:]:
                    if event.get("type") == "CLOSE":
                        scaler.observe(
                            float(event.get("pnl", 0.0)),
                            float(event.get("target_net_risk") or 0.0),
                        )
                seen_trades = len(broker.trades)
            # 1) Bu mumun kapanışı: açık pozisyonu yönet (stop/TP1/funding/likidasyon)
            if symbol in broker.portfolio.positions:
                rate = None
                if funding_rates and symbol in funding_rates:
                    rate = self._funding_rate_at(funding_rates[symbol], ts_ms)
                events = self._manage_path(
                    broker, symbol, candle, ts_ms, history, path, costs,
                    base_extra_slippage, funding_rate=rate,
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
                _latency = max(latency_ms, costs.latency_ms(symbol))
                if touched and _latency > 0 and (
                    ts_ms - pending.created_ms < _latency
                ):
                    touched = False
                if touched:
                    # v5.2: bu dolum gerçekte olur muydu? Emir TTL'i
                    # dolmuşsa canlıda emir çoktan iptal edilmişti.
                    self.fills_total += 1
                    if ts_ms - pending.created_ms > self._limit_ttl_ms():
                        self.fills_after_ttl += 1
                    fill_qty = self._partial_fill_quantity(
                        pending, candle, participant_cap,
                    )
                    if fill_qty > 0:
                        self._fill_order(
                            broker, pending, candle, ts_ms, fill_qty,
                            max(slippage_bps, costs.slippage_bps(symbol)),
                            tick_size=(tick_sizes or {}).get(symbol, 0.0),
                        )
                        if fill_qty < pending.quantity - 1e-12:
                            partial_fills += 1
                            rejection_counts["kismi_dolum"] = (
                                rejection_counts.get("kismi_dolum", 0) + 1
                            )
                        # Aynı mumda stop altına inildiyse hemen stoplanır
                        if symbol in broker.portfolio.positions:
                            stop_events = self._manage_path(
                                broker, symbol, candle, ts_ms, history, path,
                                costs, base_extra_slippage,
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

            # 3) Mumu kapanmış geçmişe ekle (v5.1: kayan pencere)
            bucket = history[symbol]
            bucket.append(candle)
            if len(bucket) > self.max_history_bars:
                del bucket[: len(bucket) - self.max_history_bars]

            # 4) Sinyal değerlendirmesi (yalnızca kapanmış mumlarla)
            if (
                symbol not in broker.portfolio.positions
                and symbol not in pending_limits
                and risk.kill_switch_state != KillSwitchState.HARD_HALT
                and len(history[symbol]) >= 30
            ):
                _probe_len = (
                    len(self.gate_probe) if self.gate_probe is not None else 0
                )
                _rej_before = (
                    dict(rejection_counts) if self.gate_probe is not None else {}
                )
                self._evaluate_signal(
                    broker, risk, pipeline, rate_limiter, cooldown,
                    beta_estimator, shock_tester, config, symbol, history,
                    btc_symbol, ts_ms, pending_limits, rejection_counts,
                    betas, shock_summary, spread_bps or {},
                    scaler, peak_equity, costs,
                )
                if self.gate_probe is not None and len(self.gate_probe) > _probe_len:
                    _rec = self.gate_probe[-1]
                    if symbol in broker.portfolio.positions:
                        _rec["reason"] = "ACILDI"
                    elif symbol in pending_limits:
                        _rec["reason"] = "LIMIT_BEKLIYOR"
                        _rec["limit_price"] = getattr(
                            pending_limits[symbol], "entry", None,
                        )
                    else:
                        _delta = [
                            k for k, v in rejection_counts.items()
                            if v > _rej_before.get(k, 0)
                        ]
                        _rec["reason"] = _delta[-1] if _delta else "BILINMIYOR"

            # 5) Kill switch + equity takibi
            prices = {s: h[-1].close for s, h in history.items() if h}
            daily_realized = self._daily_realized(broker, ts_ms)
            state = risk.evaluate_kill_switch(broker.portfolio, prices, daily_realized)
            if state == KillSwitchState.HARD_HALT and broker.portfolio.positions:
                closed = broker.close_all(prices, ts_ms, reason="kill_switch_hard")
                rejection_counts["kill_switch_flatten"] = len(closed)
            # v5.2: tepe equity — drawdown olcegi bunun uzerinden hesaplanir
            _equity_now = broker.portfolio.equity(prices)
            if _equity_now > peak_equity:
                peak_equity = _equity_now
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
            path_source=(
                "real_1m" if path is not None and path.stats.real_bars
                else (path.synthetic_order if path is not None else "single_candle")
            ),
            intrabar=path.stats.as_dict() if path is not None else {},
            cost_model=costs.as_dict(),
            risk_audit=audit_trade_risk(broker.trades),
            exit_slippage_bps=(
                sum(costs.exit_slippage_bps(s) for s in _symbols_all)
                / max(1, len(_symbols_all))
            ),
            grid_symbols=len(tick_sizes or {}),
            risk_scaling=scaler.stats(),
            fill_optimism={
                "toplimit_dolum": self.fills_total,
                "ttl_disi_dolum": self.fills_after_ttl,
                "ttl_disi_oran": (
                    round(self.fills_after_ttl / self.fills_total, 4)
                    if self.fills_total else 0.0
                ),
                "ttl_ms": self._limit_ttl_ms(),
                "kaba_bar_ms": 300_000,
                "uyari": (
                    "Backtest bekleyen limiti sonraki 5m mumun TÜM aralığıyla "
                    "denetler; emir gerçekte TTL kadar yaşar. ttl_disi_dolum "
                    "> 0 ise canlıda bu dolumların bir kısmı HİÇ olmazdı."
                ),
            },
        )

    # ------------------------------------------------------------------

    def _manage_path(
        self,
        broker: PaperBroker,
        symbol: str,
        candle: Candle,
        ts_ms: int,
        history: dict[str, list[Candle]],
        path: IntrabarPath | None,
        costs: CostModel,
        base_extra_slippage: float,
        funding_rate: float | None = None,
    ) -> list[dict]:
        """v5.1: pozisyonu mum İÇİ yolda yürütür.

        İnce veri varsa gerçek 1m sırası kullanılır; her alt mumda çıkış
        denetlenir ve İLK tetiklenen kazanır. Bar sayacı kaba bar başına bir
        kez artar (alt mumlar `intrabar=True` ile çağrılır).

        Çıkış kayması sembol başına maliyet modelinden uygulanır; giriş
        boyutlaması etkilenmesin diye yalnızca bu adım boyunca geçerlidir.
        """
        atr_value = self._atr(history.get(symbol, []))
        steps = [candle] if path is None else path.steps(symbol, candle)[0]
        events: list[dict] = []
        previous_extra = broker.extra_slippage_rate
        broker.extra_slippage_rate = (
            base_extra_slippage + costs.exit_slippage_bps(symbol) / 10_000.0
        )
        try:
            for index, step in enumerate(steps):
                last = index == len(steps) - 1
                step_events = broker.manage_position_candle(
                    symbol, step, ts_ms if last else step.timestamp,
                    atr=atr_value,
                    funding_rate=funding_rate if last else None,
                    intrabar=not last,
                )
                events.extend(step_events)
                if symbol not in broker.portfolio.positions:
                    break
        finally:
            broker.extra_slippage_rate = previous_extra
        return events

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
        scaler: RiskScaler | None = None,
        peak_equity: float = 0.0,
        costs: CostModel | None = None,
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
        if self.gate_probe is not None:
            self.gate_probe.append({
                "symbol": symbol, "ts_ms": ts_ms, "side": signal.side,
                "entry_ref": entry_ref, "stop_fraction": stop_distance,
                "motor": signal.motor,
                "score": (decision.score.total if decision.score else 0.0),
                "reason": None,
            })
        prices = {s: h[-1].close for s, h in history.items() if h}
        # ---------------------------------------------------------------
        # v5.2: DINAMIK RISK BUTCESI
        #   drawdown + ardisik kayip + beklenti + maliyet payi -> olcek
        #   Sert maliyet kapisi asilirsa islem HIC acilmaz.
        # ---------------------------------------------------------------
        risk_budget = 0.0
        if scaler is not None and config.risk_scaling.enabled:
            _equity = broker.portfolio.equity(prices)
            _dd_pct = (
                max(0.0, (peak_equity - _equity) / peak_equity * 100.0)
                if peak_equity > 0 else 0.0
            )
            _cost_rate = risk.round_trip_cost_rate()
            if costs is not None:
                # olculmus sembol maliyeti varsa onu kullan (bps -> oran)
                _cost_rate = (
                    costs.spread_bps(symbol) / 2.0
                    + costs.slippage_bps(symbol)
                    + costs.exit_slippage_bps(symbol)
                ) / 10_000.0 + config.account.maker_fee_rate + config.account.taker_fee_rate
            budget = scaler.budget(
                config.account.max_loss_per_position,
                drawdown_pct=_dd_pct,
                cost_rate=_cost_rate,
                stop_fraction=stop_distance,
            )
            if budget.blocked:
                rejection_counts[budget.block_reason] = (
                    rejection_counts.get(budget.block_reason, 0) + 1
                )
                return False
            risk_budget = budget.budget_usdt
        plan = risk.plan(
            entry_ref, stop_distance, signal.side, motor=signal.motor,
            risk_budget=risk_budget or None,
        )
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
            risk_budget=risk_budget,
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
        tick_size: float = 0.0,
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
            tick_size=tick_size,
            risk_budget=pending.risk_budget or None,
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
        }, risk_budget=pending.risk_budget or None)
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
