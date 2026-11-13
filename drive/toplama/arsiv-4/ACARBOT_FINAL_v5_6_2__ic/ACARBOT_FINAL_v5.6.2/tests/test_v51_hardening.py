"""v5.1 — SERTLEŞTİRME regresyonları.

Kapsanan 6 madde:
  1. Mum içi yol modeli (1m alt çözünürlük + sentetik sınırlar)
  2. Gerçek maliyet modeli (spread/kayma/gecikme, çıkış kayması dâhil)
  3. Çok sembollü doğrulama koşucusu (yardımcı bileşenleri)
  4. Sürüm regresyon kapısı (bayat referans yakalama)
  5. Tick/lot doğrulaması + canlı ızgara gözlemi
  7. Oturum sonu gerçekleşen/hedef kayıp denetimi (1,3x işaretleme)
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app import __version__
from backtest.costs import CostModel, ExchangeCosts
from backtest.engine import BacktestEngine, audit_trade_risk
from backtest.intrabar import IntrabarPath, overshoot_ratio
from backtest.regression_gate import (
    build_fixture,
    check_reference,
    dataset_fingerprint,
    make_reference,
    run_fixture,
)
from infra.market_data.models import Candle
from infra.tick_verify import (
    MISMATCH,
    UNVERIFIED,
    GridObserver,
    TickVerifier,
    price_on_grid,
)
from tests.helpers import apex_config, legacy_ttl

BASE_MS = 1_699_999_800_000  # 5m ızgarasına hizalı


def _coarse(ts=BASE_MS, o=100.0, h=101.0, low=97.0, c=98.0) -> Candle:
    return Candle(timestamp=ts, open=o, high=h, low=low, close=c, volume=1000.0)


def _fine_from(coarse: Candle, lows=None, highs=None) -> list[Candle]:
    """5m barı 5 adet 1m bara böler; uçlar kaba barla tutarlı."""
    lows = lows or [coarse.open, coarse.low, 98.5, 99.0, coarse.close]
    highs = highs or [coarse.open, 99.0, 99.5, coarse.high, coarse.close]
    out = []
    prev = coarse.open
    for i in range(5):
        lo, hi = lows[i], highs[i]
        close = (lo + hi) / 2.0
        out.append(Candle(
            timestamp=coarse.timestamp + i * 60_000,
            open=prev, high=max(prev, hi, close), low=min(prev, lo, close),
            close=close, volume=coarse.volume / 5.0,
        ))
        prev = close
    # Uçları kaba bara eşitle (tutarlılık denetimi geçsin)
    out[1] = replace(out[1], low=coarse.low)
    out[3] = replace(out[3], high=coarse.high)
    return out


# ======================================================================
# 1) MUM İÇİ YOL
# ======================================================================

class TestIntrabarPath:
    def test_real_1m_used_when_available(self):
        coarse = _coarse()
        path = IntrabarPath(fine_by_symbol={"S": _fine_from(coarse)})
        steps, source = path.steps("S", coarse)
        assert source == "real_1m"
        assert len(steps) == 5
        assert path.stats.real_bars == 1

    def test_synthetic_fallback_when_no_fine(self):
        path = IntrabarPath()
        steps, source = path.steps("S", _coarse())
        assert source == "synthetic_adverse_first"
        assert len(steps) == 3
        assert path.stats.synthetic_bars == 1

    def test_adverse_first_hits_low_before_high(self):
        path = IntrabarPath(synthetic_order="adverse_first")
        steps, _ = path.steps("S", _coarse())  # bullish: close < open? 98<100 bearish
        # bearish bar → aleyhte uç HIGH, lehte uç LOW
        assert steps[0].high == pytest.approx(101.0)
        assert steps[1].low == pytest.approx(97.0)

    def test_favorable_first_reverses_order(self):
        path = IntrabarPath(synthetic_order="favorable_first")
        steps, source = path.steps("S", _coarse())
        assert source == "synthetic_favorable_first"
        assert steps[0].low == pytest.approx(97.0)
        assert steps[1].high == pytest.approx(101.0)

    def test_partial_coverage_falls_back(self):
        coarse = _coarse()
        fine = _fine_from(coarse)[:3]  # 5 yerine 3 → eksik kapsama
        path = IntrabarPath(fine_by_symbol={"S": fine})
        steps, source = path.steps("S", coarse)
        assert source.startswith("synthetic")
        assert path.stats.partial_coverage_bars == 1

    def test_inconsistent_fine_rejected(self):
        coarse = _coarse()
        fine = _fine_from(coarse)
        fine[1] = replace(fine[1], low=coarse.low * 0.5)  # kaba barla çelişir
        path = IntrabarPath(fine_by_symbol={"S": fine})
        _, source = path.steps("S", coarse)
        assert source.startswith("synthetic")
        assert path.stats.inconsistent_bars == 1

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            IntrabarPath(mode="bogus")
        with pytest.raises(ValueError):
            IntrabarPath(synthetic_order="bogus")

    def test_stats_report_coverage_ratio(self):
        coarse = _coarse()
        path = IntrabarPath(fine_by_symbol={"S": _fine_from(coarse)})
        path.steps("S", coarse)
        path.steps("Y", coarse)
        stats = path.stats.as_dict()
        assert stats["real_1m_bars"] == 1
        assert stats["synthetic_bars"] == 1
        assert stats["real_coverage_ratio"] == pytest.approx(0.5)

    def test_bar_counter_not_inflated_by_subcandles(self):
        """Alt mumlar bar sayacını şişirmemeli (zaman çıkışı erken olmasın)."""
        from exec.paper import PaperBroker
        from core.risk import RiskManager

        cfg = apex_config()
        broker = PaperBroker(cfg, 10_000.0)
        broker.risk_manager_ref = RiskManager(cfg)
        sym = "okx:TEST-USDT-SWAP"
        plan = broker.risk_manager_ref.plan(100.0, 0.02, "LONG")
        order = broker.place_entry(
            sym, plan, now_ms=BASE_MS - 120_000, baseline_per_second=1e12,
        )
        broker.bind_plan(order, plan, "trend")
        broker.process_entry_tick(sym, 99.0, 1e12, BASE_MS - 60_000)
        pos = broker.portfolio.positions[sym]
        start_bars = pos.bars_held
        coarse = _coarse(ts=BASE_MS, o=99.0, h=99.4, low=98.6, c=99.1)
        for step in _fine_from(coarse)[:-1]:
            broker.manage_position_candle(sym, step, step.timestamp, intrabar=True)
        broker.manage_position_candle(sym, coarse, BASE_MS)
        assert broker.portfolio.positions[sym].bars_held == start_bars + 1


class TestOvershoot:
    def test_zero_when_exit_at_stop(self):
        assert overshoot_ratio("LONG", 100.0, 99.0, 99.0) == pytest.approx(0.0)

    def test_half_stop_distance_beyond(self):
        assert overshoot_ratio("LONG", 100.0, 99.0, 98.5) == pytest.approx(0.5)

    def test_short_direction(self):
        assert overshoot_ratio("SHORT", 100.0, 101.0, 101.5) == pytest.approx(0.5)

    def test_favourable_exit_is_zero(self):
        assert overshoot_ratio("LONG", 100.0, 99.0, 99.5) == pytest.approx(0.0)


class TestIntrabarChangesOutcome:
    def test_real_1m_reduces_emergency_stop_loss(self):
        """Aynı 5m bar: yapısal stop en yakın tetikse yol fark yaratmaz.

        v5.5: bu testin ÖZGÜN beklentisi (kaba > ince kayıp) bir
        yürütme hatasından geliyordu — acil stop mumun dibinden
        kapatıyordu. Düzeltme sonrası iki yol eşitleniyor.
        Bkz. ZARAR_ANALIZI_v5.5.md §2.
        """
        from exec.paper import PaperBroker
        from core.risk import RiskManager

        cfg = apex_config()

        def run(with_fine: bool) -> float:
            broker = PaperBroker(cfg, 10_000.0)
            risk = RiskManager(cfg)
            broker.risk_manager_ref = risk
            sym = "okx:TEST-USDT-SWAP"
            plan = risk.plan(100.0, 0.01, "LONG")
            order = broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
            broker.bind_plan(order, plan, "trend")
            broker.process_entry_tick(sym, 99.5, 1e12, 1_000)
            # 5m bar: stopun ÇOK ötesine iğne atıyor (92.0)
            coarse = Candle(
                timestamp=BASE_MS, open=99.5, high=99.6, low=92.0,
                close=99.0, volume=1_000.0,
            )
            if with_fine:
                # 1m yol: ilk barda yalnız 98.9'a kadar iniyor → stop orada
                fine = [
                    Candle(BASE_MS + 0, 99.5, 99.6, 98.9, 99.0, 200.0),
                    Candle(BASE_MS + 60_000, 99.0, 99.2, 92.0, 93.0, 200.0),
                    Candle(BASE_MS + 120_000, 93.0, 96.0, 93.0, 95.5, 200.0),
                    Candle(BASE_MS + 180_000, 95.5, 98.0, 95.0, 97.5, 200.0),
                    Candle(BASE_MS + 240_000, 97.5, 99.6, 97.0, 99.0, 200.0),
                ]
                path = IntrabarPath(fine_by_symbol={sym: fine})
                steps, _ = path.steps(sym, coarse)
            else:
                steps = [coarse]
            events = []
            for index, step in enumerate(steps):
                last = index == len(steps) - 1
                events += broker.manage_position_candle(
                    sym, step, step.timestamp, intrabar=not last,
                )
                if sym not in broker.portfolio.positions:
                    break
            closes = [e for e in events if e.get("type") == "CLOSE"]
            assert closes, "pozisyon kapanmadı"
            return closes[0]["pnl"]

        coarse_loss = run(False)
        fine_loss = run(True)
        # v5.5 DÜZELTMESİ — bu testin eski beklentisi bir HATAYI
        # kodluyordu. Eski kod, yapısal stop ile acil sabit-zarar
        # eşiği çakıştığında MUMUN EN KÖTÜ fiyatından kapatıyordu;
        # kaba bar bu yüzden ince yoldan daha büyük kayıp veriyordu.
        # Oysa fiyat 92.0'a inmek için önce yapısal stopu GEÇMEK
        # ZORUNDA. Yapısal stop girişe daha yakınsa dolum orada olur —
        # bu yol bilgisinden bağımsızdır.
        # Doğru beklenti: kaba bar artık FAZLA cezalandırmıyor.
        assert coarse_loss == pytest.approx(fine_loss, abs=1e-6), (
            "yapısal stop en yakın tetikse kaba ve ince yol aynı olmalı: "
            f"kaba={coarse_loss}, ince={fine_loss}"
        )
        # Ve kayıp hedef riskin makul katını aşmamalı (aşım giderildi).
        assert abs(coarse_loss) < 40.0, (
            f"acil stop aşımı giderilmeliydi: {coarse_loss}"
        )
        # v5.5: eski "%20 daha küçük" beklentisi de aynı hataya
        # dayanıyordu; artık eşitlik doğru davranıştır.


# ======================================================================
# 2) MALİYET MODELİ
# ======================================================================

class TestCostModel:
    def test_defaults_are_on_not_zero(self):
        costs = CostModel()
        assert costs.spread_bps("okx:BTC-USDT-SWAP") > 0
        assert costs.slippage_bps("okx:BTC-USDT-SWAP") > 0
        assert costs.latency_ms("okx:BTC-USDT-SWAP") > 0
        assert costs.exit_slippage_bps("okx:BTC-USDT-SWAP") > 0
        assert costs.is_optimistic is False

    def test_disabled_is_flagged_optimistic(self):
        costs = CostModel.disabled()
        assert costs.spread_bps("okx:X-USDT-SWAP") == 0.0
        assert costs.is_optimistic is True
        assert "İYİMSER" in costs.summary_text()

    def test_measured_overrides_defaults(self):
        costs = CostModel(
            measured_spread_bps={"okx:X-USDT-SWAP": 9.5},
            measured_symbols=1, source="measured",
        )
        assert costs.spread_bps("okx:X-USDT-SWAP") == pytest.approx(9.5)
        assert costs.spread_bps("okx:Y-USDT-SWAP") == pytest.approx(2.5)
        assert costs.is_measured is True
        # v5.2: etiket borsa bazinda; okx olculdu, binance VARSAYIM
        text = costs.summary_text()
        assert "ÖLÇÜLDÜ" in text
        assert "VARSAYIM (ÖLÇÜLMEDİ)" in text

    def test_defaults_labelled_as_not_measured(self):
        assert "ölçülmedi" in CostModel().summary_text()

    def test_roundtrip_json(self, tmp_path):
        costs = CostModel(
            measured_spread_bps={"okx:X-USDT-SWAP": 3.0},
            measured_symbols=1, source="measured", measured_at="2026-11-07",
        )
        path = tmp_path / "c.json"
        costs.save(path)
        loaded = CostModel.load(path)
        assert loaded.spread_bps("okx:X-USDT-SWAP") == pytest.approx(3.0)
        assert loaded.is_measured is True

    def test_negative_costs_rejected(self):
        with pytest.raises(ValueError):
            ExchangeCosts(spread_bps=-1.0)
        with pytest.raises(ValueError):
            ExchangeCosts(latency_ms=-5)

    def test_engine_applies_costs_by_default(self):
        candles = build_fixture()["okx:FIXA-USDT-SWAP"]
        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        with_costs = engine.run({"okx:FIXA-USDT-SWAP": candles})
        assert with_costs.spread_applied is True
        assert with_costs.cost_model["optimistic_warning"] is False
        assert with_costs.exit_slippage_bps > 0

    def test_costs_reduce_pnl_versus_no_costs(self):
        candles = build_fixture()
        engine = legacy_ttl(BacktestEngine(apex_config(), initial_balance=1_000.0))
        cheap = engine.run(candles, cost_model=CostModel.disabled())
        real = engine.run(candles, cost_model=CostModel())
        assert real.trade_count > 0, "fixture işlem üretmeli"
        assert real.net_pnl <= cheap.net_pnl


# ======================================================================
# 4) SÜRÜM REGRESYON KAPISI
# ======================================================================

class TestRegressionGate:
    def test_fixture_is_deterministic(self):
        assert dataset_fingerprint(build_fixture()) == dataset_fingerprint(
            build_fixture(),
        )
        first, second = run_fixture(apex_config()), run_fixture(apex_config())
        assert first == second

    def test_fresh_reference_passes(self):
        reference = make_reference(__version__, None, apex_config())
        gate = check_reference(
            reference, __version__, strict_dataset=False,
        )
        assert gate.ok, gate.failures

    def test_stale_version_is_rejected(self):
        reference = make_reference("4.0-final", None, apex_config())
        gate = check_reference(reference, __version__, strict_dataset=False)
        assert not gate.ok
        assert any("BAYAT REFERANS" in f for f in gate.failures)

    def test_optimistic_reference_is_rejected(self):
        reference = make_reference(__version__, None, apex_config())
        reference["cost_model"] = CostModel.disabled().as_dict()
        gate = check_reference(reference, __version__, strict_dataset=False)
        assert not gate.ok
        assert any("MALİYETSİZ" in f for f in gate.failures)

    def test_changed_engine_metrics_detected(self):
        reference = make_reference(__version__, None, apex_config())
        reference["fixture_metrics"]["net_pnl"] += 1.0
        gate = check_reference(reference, __version__, strict_dataset=False)
        assert not gate.ok
        assert any("değişti" in f for f in gate.failures)

    def test_single_symbol_short_dataset_fails_strict(self):
        reference = make_reference(__version__, None, apex_config())
        reference["dataset"] = {"symbols": 1, "days": 7}
        gate = check_reference(reference, __version__, strict_dataset=True)
        assert not gate.ok
        assert any("Veri kümesi yetersiz" in f for f in gate.failures)

    def test_empty_reference_fails(self):
        gate = check_reference({}, __version__)
        assert not gate.ok

    def test_shipped_reference_is_current(self):
        """Paketteki referans dosyası paket sürümüyle aynı olmalı."""
        from backtest.regression_gate import REFERENCE_PATH, load_reference

        reference = load_reference(REFERENCE_PATH)
        if not reference:
            pytest.skip("Referans dosyası henüz üretilmedi")
        gate = check_reference(reference, __version__, strict_dataset=False)
        assert gate.ok, gate.failures


# ======================================================================
# 5) TICK / LOT DOĞRULAMA
# ======================================================================

class TestTickVerification:
    def test_price_on_grid(self):
        assert price_on_grid(75821.5, 0.1) is True
        assert price_on_grid(3.6e-07, 1e-08) is True
        assert price_on_grid(75821.55, 0.1) is False
        assert price_on_grid(0.0, 0.1) is False
        assert price_on_grid(100.0, 0.0) is False

    def test_mismatch_excludes_symbol(self):
        verifier = TickVerifier(policy="warn")
        verifier.futures_ticks = {"BTTCUSDT": 1e-09}
        verifier.source_used = "test"
        allowed, report = verifier.filter_grid({"binance:BTTCUSDT": 1e-08})
        assert "binance:BTTCUSDT" not in allowed
        assert report["mismatch"] == 1
        assert report["excluded_symbols"] == ["binance:BTTCUSDT"]

    def test_match_allows_symbol(self):
        verifier = TickVerifier()
        verifier.futures_ticks = {"BTCUSDT": 0.1}
        verifier.source_used = "test"
        allowed, report = verifier.filter_grid({"binance:BTCUSDT": 0.1})
        assert allowed == {"binance:BTCUSDT": 0.1}
        assert report["match"] == 1 and report["verified"] is True

    def test_unverified_warn_keeps_strict_excludes(self):
        verifier = TickVerifier(policy="warn", auto_fetch=False)
        verifier.futures_ticks = {}
        verifier.fetch_error = "451"
        allowed, report = verifier.filter_grid({"binance:BTCUSDT": 0.1})
        assert "binance:BTCUSDT" in allowed
        assert report["unverified"] == 1 and report["verified"] is False
        strict = TickVerifier(policy="strict", auto_fetch=False)
        strict.futures_ticks = {}
        allowed_strict, report_strict = strict.filter_grid({"binance:BTCUSDT": 0.1})
        assert allowed_strict == {}
        assert report_strict["excluded_symbols"] == ["binance:BTCUSDT"]

    def test_invalid_policy_rejected(self):
        with pytest.raises(ValueError):
            TickVerifier(policy="whatever")

    def test_verify_status_labels(self):
        verifier = TickVerifier()
        verifier.futures_ticks = {"A": 0.1, "B": 0.5}
        assert verifier.verify("binance:A", 0.1).status == "match"
        assert verifier.verify("binance:B", 0.1).status == MISMATCH
        assert verifier.verify("binance:C", 0.1).status == UNVERIFIED


class TestGridObserver:
    def test_consistent_prices_pass(self):
        observer = GridObserver()
        for _ in range(5):
            assert observer.observe("binance:BTCUSDT", 75821.5, 0.1) is True
        assert not observer.rejected

    def test_repeated_violation_rejects_symbol(self):
        observer = GridObserver(max_violations=3)
        results = [
            observer.observe("binance:BTTCUSDT", 3.5007e-07, 1e-06)
            for _ in range(3)
        ]
        assert results[-1] is False
        assert "binance:BTTCUSDT" in observer.rejected
        assert observer.as_dict()["rejected_symbols"] == ["binance:BTTCUSDT"]

    def test_single_violation_does_not_reject(self):
        observer = GridObserver(max_violations=3)
        assert observer.observe("binance:X", 100.05, 0.1) is True
        assert not observer.rejected

    def test_executor_blocks_rejected_symbol(self):
        from app.executor import Executor
        from core.risk import RiskManager
        from exec.paper import PaperBroker

        cfg = apex_config()
        broker = PaperBroker(cfg, 10_000.0)
        risk = RiskManager(cfg)
        broker.risk_manager_ref = risk
        executor = Executor(broker, risk, cfg)
        sym = "binance:BADUSDT"
        executor.tick_sizes[sym] = 1e-06
        broker.tick_sizes = executor.tick_sizes
        executor.grid_observer.max_violations = 2
        for i in range(4):
            executor.process_price_update(sym, 3.5007e-07, 1_000 + i * 1_000)
        assert sym in executor.grid_observer.rejected
        assert sym not in executor.tick_sizes
        executor._evaluate_entry(sym, [], 5_000)
        assert executor.grid_rejected_entries == 1
        assert executor.last_block_reason[sym] == "tick_grid_rejected"


# ======================================================================
# 7) OTURUM SONU RİSK DENETİMİ
# ======================================================================

class TestRiskAudit:
    def _close(self, pnl, target=25.0, entry=100.0, stop=99.0, price=99.0,
               side="LONG", reason="stop_loss", symbol="okx:X-USDT-SWAP"):
        return {
            "type": "CLOSE", "symbol": symbol, "side": side, "pnl": pnl,
            "target_net_risk": target, "entry": entry, "stop_loss": stop,
            "price": price, "reason": reason,
        }

    def test_on_target_not_flagged(self):
        audit = audit_trade_risk([self._close(-25.0)])
        assert audit["breach_count"] == 0
        assert audit["max_realized_over_target"] == pytest.approx(1.0)

    def test_1_61r_breach_is_flagged(self):
        """Kullanıcının canlı örneği: −40,31 USDT / 25 USDT = 1,61R."""
        audit = audit_trade_risk([
            self._close(-40.31, stop=99.0, price=98.39),
        ])
        assert audit["breach_count"] == 1
        assert audit["max_realized_over_target"] == pytest.approx(1.6124, abs=1e-3)
        row = audit["breaches"][0]
        assert row["breach"] is True
        assert row["stop_overshoot_ratio"] > 0

    def test_threshold_is_configurable(self):
        trades = [self._close(-30.0)]  # 1.2x
        assert audit_trade_risk(trades)["breach_count"] == 0
        assert audit_trade_risk(trades, breach_ratio=1.1)["breach_count"] == 1

    def test_profitable_trades_not_counted_as_loss(self):
        audit = audit_trade_risk([self._close(+40.0)])
        assert audit["losing_trades"] == 0
        assert audit["breach_count"] == 0
        assert audit["max_realized_over_target"] == 0.0

    def test_missing_target_does_not_crash(self):
        audit = audit_trade_risk([{"type": "CLOSE", "pnl": -10.0}])
        assert audit["closed_trades"] == 1
        assert audit["breach_count"] == 0

    def test_broker_close_records_target_and_stop(self):
        from core.risk import RiskManager
        from exec.paper import PaperBroker

        cfg = apex_config()
        broker = PaperBroker(cfg, 10_000.0)
        broker.risk_manager_ref = RiskManager(cfg)
        sym = "okx:TEST-USDT-SWAP"
        plan = broker.risk_manager_ref.plan(100.0, 0.01, "LONG")
        order = broker.place_entry(sym, plan, now_ms=0, baseline_per_second=1e12)
        broker.bind_plan(order, plan, "trend")
        broker.process_entry_tick(sym, 99.5, 1e12, 1_000)
        broker.manage_position_tick(sym, 90.0, 2_000)
        closes = [t for t in broker.trades if t.get("type") == "CLOSE"]
        assert closes
        assert closes[0]["target_net_risk"] == pytest.approx(25.0, abs=1e-3)
        assert closes[0]["stop_loss"] > 0

    def test_session_report_contains_realized_vs_target(self, tmp_path):

        from app.main import build_parser, write_session_report
        from app.executor import Executor
        from core.risk import RiskManager
        from exec.paper import PaperBroker

        class _Reporter:
            def daily_report(self, **kwargs):
                return "ok"

        class _Metrics:
            counters: dict = {}

            def as_dict(self):
                return {}

            def inc(self, *a, **k):
                pass

        cfg = apex_config()
        broker = PaperBroker(cfg, 10_000.0)
        risk = RiskManager(cfg)
        broker.risk_manager_ref = risk
        executor = Executor(broker, risk, cfg)
        args = build_parser().parse_args([
            "--mode", "paper", "--paper",
            "--report-file", str(tmp_path / "r.json"),
        ])
        report = write_session_report(
            args, executor, _Reporter(), _Metrics(), 0, 10_000.0,
        )
        audit = report["target_risk_audit"]["realized_vs_target"]
        assert audit["breach_ratio_threshold"] == pytest.approx(1.3)
        assert "breaches" in audit
        assert "tick_verification" in report
        assert "grid_observer" in report


# ======================================================================
# 3) DOĞRULAMA KOŞUCUSU — bileşenler
# ======================================================================

class TestValidationRunner:
    def test_verdict_insufficient_sample(self):
        from backtest.verdict import INSUFFICIENT_SAMPLE, decide

        runs = [{
            "trade_count": 8, "net_pnl": -6.68,
            "monte_carlo": {"prob_loss": 0.923},
            "risk_audit": {"breach_count": 0},
            "walk_forward": {},
        }]
        verdict = decide(runs, min_trades=200)
        assert verdict.code == INSUFFICIENT_SAMPLE
        assert "örneklem yetersiz" in verdict.headline

    def test_verdict_no_edge(self):
        from backtest.verdict import NO_EDGE, decide

        runs = [{
            "trade_count": 300, "net_pnl": -50.0,
            "monte_carlo": {"prob_loss": 0.9},
            "risk_audit": {"breach_count": 0},
            "walk_forward": {},
        }]
        assert decide(runs, min_trades=200).code == NO_EDGE

    def test_verdict_edge_with_risk_breach(self):
        from backtest.verdict import EDGE_RISK_DRIFT, decide

        runs = [{
            "trade_count": 300, "net_pnl": 120.0,
            "monte_carlo": {"prob_loss": 0.3},
            "risk_audit": {"breach_count": 4},
            "walk_forward": {},
        }]
        assert decide(runs, min_trades=200).code == EDGE_RISK_DRIFT

    def test_verdict_edge_candidate(self):
        from backtest.verdict import EDGE_CANDIDATE, decide

        runs = [{
            "trade_count": 300, "net_pnl": 120.0,
            "monte_carlo": {"prob_loss": 0.3},
            "risk_audit": {"breach_count": 0},
            "walk_forward": {},
        }]
        assert decide(runs, min_trades=200).code == EDGE_CANDIDATE

    def test_markdown_report_builds(self):
        from tools.validate_strategy import build_markdown

        block = {
            "label": "birincil", "path_source": "real_1m",
            "net_pnl": -6.68, "trade_count": 8,
            "metrics": {"win_rate": 0.5, "profit_factor": 0.31,
                        "max_drawdown_usdt": 8.15, "by_regime": {}},
            "monte_carlo": {"prob_loss": 0.923},
            "walk_forward": {"profitable_windows": 1, "total_windows": 6,
                             "windows": [], "total_net_pnl": -6.68,
                             "worst_window_net_pnl": -4.0},
            "risk_audit": {"losing_trades": 4, "mean_realized_over_target": 1.2,
                           "max_realized_over_target": 1.61, "breach_count": 1,
                           "breach_ratio_threshold": 1.3,
                           "max_stop_overshoot_ratio": 0.6},
            "rejection_counts": {"dusuk_hacim": 1531},
        }
        report = {
            "version": __version__, "generated_at": "2026-11-07",
            "dataset": {"exchange": "okx", "symbols": 6, "days": 90,
                        "total_bars": 155520, "fine_days": 5,
                        "fine_bars": 43200, "fine_mode": "targeted",
                        "fine_symbols": 6},
            "profile": "apex", "target_net_risk": 25.0,
            "cost_summary": CostModel().summary_text(),
            "cost_model": CostModel().as_dict(),
            "runs": [block], "verdict": "test hükmü",
            "verdict_detail": {"code": "NO_EDGE", "severity": "red"},
        }
        markdown = build_markdown(report)
        assert "# ACARBOT Doğrulama Raporu" in markdown
        assert "birincil" in markdown
        assert "ÖLÇÜLMEDİ" in markdown
        assert "1.61" in markdown or "1.610" in markdown
        # v5.2: walk-forward satiri liste değil SAYI basmali
        assert "1/6 pencere kârlı" in markdown
        assert "[{" not in markdown

    def test_sweep_bps_measures_depth_impact(self):
        from tools.measure_costs import sweep_bps

        levels = [(100.0, 10.0), (100.5, 10.0), (101.0, 10.0)]
        mid = 99.95
        small = sweep_bps(levels, mid, 100.0, "buy")
        large = sweep_bps(levels, mid, 2_000.0, "buy")
        assert small is not None and large is not None
        assert large > small  # daha büyük emir daha çok kayma
        assert sweep_bps(levels, mid, 1e9, "buy") is None  # defter yetersiz
