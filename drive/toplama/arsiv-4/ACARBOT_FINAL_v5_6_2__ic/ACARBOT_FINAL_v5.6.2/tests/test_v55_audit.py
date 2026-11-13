"""v5.5 — denetim düzeltmelerinin testleri.

Denetimde bulunan 6 kusurun her biri için regresyon testi.
"""

from __future__ import annotations

import pytest

from backtest.robust_stats import (
    bonferroni,
    clustering_report,
    cluster_bootstrap,
    dedupe_cluster,
    verdict,
)


def _row(sym, ts, score=50.0, r=0.0, cost=0.5):
    return {
        "symbol": sym, "ts_ms": ts, "score": score,
        "sym_kotumser_r": r, "cost_r": cost,
    }


class TestDedupeCluster:
    def test_close_candidates_collapse(self):
        tf = 300_000
        rows = [_row("A", i * tf, score=float(i)) for i in range(10)]
        kept, info = dedupe_cluster(rows, cluster_bars=12, timeframe_ms=tf)
        assert len(kept) == 1
        assert info["elenen"] == 9
        assert kept[0]["score"] == 9.0, "kümede en yüksek skor tutulmalı"

    def test_far_candidates_kept(self):
        tf = 300_000
        rows = [_row("A", 0), _row("A", 20 * tf), _row("A", 40 * tf)]
        kept, _ = dedupe_cluster(rows, cluster_bars=12, timeframe_ms=tf)
        assert len(kept) == 3

    def test_different_symbols_not_merged(self):
        rows = [_row("A", 0), _row("B", 0), _row("C", 0)]
        kept, _ = dedupe_cluster(rows, cluster_bars=12, timeframe_ms=300_000)
        assert len(kept) == 3


class TestClusterBootstrap:
    def test_wider_than_iid_when_clustered(self):
        """Aynı gün içinde özdeş adaylar → küme SE, iid SE'den BÜYÜK."""
        day = 86_400_000
        rows = []
        for d in range(10):
            val = 1.0 if d % 2 == 0 else -1.0
            for k in range(20):
                rows.append(_row("A", d * day + k * 1000, r=val))
        res = cluster_bootstrap(rows, "sym_kotumser_r", iterations=400, seed=1)
        assert res["kume"] == 10
        assert res["n"] == 200
        assert res["genisleme_katsayisi"] is not None
        assert res["genisleme_katsayisi"] > 2.0, (
            "gün içi bağımlılık GA'yı genişletmeli"
        )

    def test_empty(self):
        res = cluster_bootstrap([], "x")
        assert res["n"] == 0 and res["mean"] is None

    def test_interval_contains_point(self):
        day = 86_400_000
        rows = [_row("A", d * day, r=float(d % 5) - 2) for d in range(60)]
        res = cluster_bootstrap(rows, "sym_kotumser_r", iterations=500, seed=7)
        assert res["lo"] <= res["mean"] <= res["hi"]


class TestClusteringReport:
    def test_measures_neighbourhood(self):
        tf = 300_000
        rows = [_row("A", i * tf) for i in range(5)]
        rep = clustering_report(rows, timeframe_ms=tf, cluster_bars=12)
        assert rep["komsusu_olan"] == 5
        assert rep["komsu_orani"] == 1.0


class TestBonferroni:
    def test_multiplies(self):
        assert bonferroni(0.028, 15) == pytest.approx(0.42)

    def test_capped_at_one(self):
        assert bonferroni(0.5, 15) == 1.0

    def test_none(self):
        assert bonferroni(None, 15) is None

    def test_v54_long_horizon_claim_dies(self):
        """v5.4'ün 48 bar p=0,028 iddiası 15 test düzeltmesiyle ölür."""
        assert bonferroni(0.028, 15) > 0.05
        assert bonferroni(0.034, 15) > 0.05


class TestVerdictThreeWay:
    def test_insufficient_sample_not_no_edge(self):
        """1h durumu: n=105, GA üst +0,09 → ÖLÇÜLEMEDİ, kenar yok DEĞİL."""
        v = verdict(net_lo=-0.27, net_hi=0.09, n_independent=105, cost_r=0.154)
        assert v["hukum"] == "YETERSIZ_ORNEKLEM"
        assert "elenmiş DEĞİL" in v["neden"]

    def test_enough_n_and_upper_below_zero_is_no_edge(self):
        v = verdict(net_lo=-0.61, net_hi=-0.51, n_independent=900, cost_r=0.535)
        assert v["hukum"] == "GIRIS_KENARI_YOK"

    def test_positive_lower_bound_is_edge(self):
        v = verdict(net_lo=0.05, net_hi=0.30, n_independent=900,
                    cost_r=0.15, p_adjusted=0.01)
        assert v["hukum"] == "GIRIS_KENARI_VAR"

    def test_edge_needs_adjusted_p(self):
        v = verdict(net_lo=0.05, net_hi=0.30, n_independent=900,
                    cost_r=0.15, p_adjusted=0.42)
        assert v["hukum"] == "BELIRSIZ"

    def test_straddling_zero_with_enough_n(self):
        v = verdict(net_lo=-0.02, net_hi=0.16, n_independent=900, cost_r=0.33)
        assert v["hukum"] == "BELIRSIZ"


class TestStoppedHorizon:
    def test_stop_cuts_path_that_unstopped_would_win(self):
        """Stopsuz +2R görünen yol, 1R stopla −1R'de kesilir."""
        from infra.market_data.models import Candle
        from tools.entry_edge import horizon_return, stopped_horizon

        entry, r_price = 100.0, 1.0
        # önce 98.5'e düşer (stop 99), sonra 102'ye çıkar
        fwd = [
            Candle(timestamp=i * 60_000, open=100.0, high=100.5,
                   low=98.5 if i == 1 else 99.5, close=100.0, volume=1.0)
            for i in range(5)
        ]
        fwd[-1] = Candle(timestamp=4 * 60_000, open=100.0, high=102.0,
                         low=99.8, close=102.0, volume=1.0)
        unstopped = horizon_return("LONG", entry, r_price, fwd, 5)
        stopped = stopped_horizon("LONG", entry, r_price, fwd, 5)
        assert unstopped == pytest.approx(2.0)
        assert stopped["kotumser"]["r"] == pytest.approx(-1.0)
        assert stopped["kotumser"]["exit"] == "stop"
        assert stopped["kotumser"]["bars"] == 2

    def test_no_stop_equals_unstopped(self):
        from infra.market_data.models import Candle
        from tools.entry_edge import horizon_return, stopped_horizon

        fwd = [
            Candle(timestamp=i * 60_000, open=100.0, high=100.6,
                   low=99.5, close=100.0 + 0.1 * (i + 1), volume=1.0)
            for i in range(4)
        ]
        u = horizon_return("LONG", 100.0, 1.0, fwd, 4)
        s = stopped_horizon("LONG", 100.0, 1.0, fwd, 4)
        assert s["kotumser"]["exit"] == "zaman_stopu"
        assert s["kotumser"]["r"] == pytest.approx(u)

    def test_short_side(self):
        from infra.market_data.models import Candle
        from tools.entry_edge import stopped_horizon

        fwd = [
            Candle(timestamp=0, open=100.0, high=101.5, low=99.0,
                   close=101.0, volume=1.0),
            Candle(timestamp=60_000, open=101.0, high=101.0, low=97.0,
                   close=97.0, volume=1.0),
        ]
        s = stopped_horizon("SHORT", 100.0, 1.0, fwd, 2)
        assert s["kotumser"]["r"] == pytest.approx(-1.0)


class TestDrawdownPeakWindow:
    def test_all_time_never_resets(self):
        from core.portfolio import Portfolio as PortfolioManager

        p = PortfolioManager(1_000.0)
        p.configure_peak("all_time")
        p.balance = 1_200.0
        p.last_ts_ms = 0
        p.equity({})
        p.balance = 900.0
        p.last_ts_ms = 40 * 86_400_000
        p.equity({})
        assert p.equity_peak == pytest.approx(1_200.0)
        assert p.peak_resets == []
        assert p.drawdown_pct({}) == pytest.approx(25.0)

    def test_rolling_peak_decays(self):
        from core.portfolio import Portfolio as PortfolioManager

        p = PortfolioManager(1_000.0)
        p.configure_peak("rolling", window_days=7)
        p.balance = 1_200.0
        p.last_ts_ms = 0
        p.equity({})
        p.balance = 900.0
        # pencere dışına çık: tepe düşmeli
        for d in range(1, 10):
            p.last_ts_ms = d * 86_400_000
            p.equity({})
        assert p.equity_peak == pytest.approx(900.0)
        assert p.drawdown_pct({}) == pytest.approx(0.0)
        assert p.peak_resets, "tepe düşünce kayıt bırakılmalı"

    def test_daily_reset(self):
        from core.portfolio import Portfolio as PortfolioManager

        p = PortfolioManager(1_000.0)
        p.configure_peak("daily")
        p.balance = 1_200.0
        p.last_ts_ms = 0
        p.equity({})
        p.balance = 900.0
        p.last_ts_ms = 86_400_000
        p.equity({})
        assert p.equity_peak == pytest.approx(900.0)
        assert p.peak_resets[0]["tur"] == "daily"

    def test_default_is_backward_compatible(self):
        from core.config import PortfolioConfig

        assert PortfolioConfig().drawdown_peak_mode == "all_time"

    def test_bad_mode_rejected(self):
        from core.portfolio import Portfolio as PortfolioManager

        p = PortfolioManager(1_000.0)
        with pytest.raises(ValueError):
            p.configure_peak("bogus")

    def test_engine_reports_lock(self):
        from backtest.engine import BacktestEngine
        from tests.helpers import apex_config

        engine = BacktestEngine(apex_config(), initial_balance=1_000.0)
        res = engine.run({})
        assert "mod" in res.drawdown_peak
        assert "taban_alti_red" in res.drawdown_peak


class TestCandidateScanIndependence:
    def test_scan_has_no_portfolio_dependency(self):
        """Aday sayısı portföy durumundan etkilenmemeli.

        Aynı veri iki kez taranırsa birebir aynı adaylar çıkmalı;
        broker/cooldown hiç kurulmadığı için durum taşınmaz.
        """
        from backtest.candidate_scan import scan_candidates
        from tests.helpers import apex_config, make_candles

        closes = [100.0 + ((i * 7) % 23) * 0.3 for i in range(320)]
        candles = {"TESTUSDT": make_candles(closes)}
        cfg = apex_config()
        a = scan_candidates(candles, cfg, min_bars=30, window_bars=400)
        b = scan_candidates(candles, cfg, min_bars=30, window_bars=400)
        assert a.evaluated == b.evaluated
        assert len(a.candidates) == len(b.candidates)
        assert [c["ts_ms"] for c in a.candidates] == [c["ts_ms"] for c in b.candidates]

    def test_scope_note_is_honest(self):
        from backtest.candidate_scan import KAPSAM_NOTU

        assert "kendi ön filtreleri" in KAPSAM_NOTU
        assert "UYGULANIR" in KAPSAM_NOTU

    def test_rejections_recorded(self):
        from backtest.candidate_scan import scan_candidates
        from tests.helpers import apex_config, make_candles

        candles = {"TESTUSDT": make_candles([100.0] * 60)}
        res = scan_candidates(candles, apex_config(), min_bars=30)
        assert res.evaluated == 30
        assert sum(res.rejections.values()) + len(res.candidates) == 30


class TestGrossNetLabel:
    def test_symmetric_summary_is_labelled_gross(self):
        """v5.4 'net' diyordu; artık BRÜT etiketi ve ayrı NET alanı var."""
        import inspect

        from tools import entry_edge

        src = inspect.getsource(entry_edge.main)
        assert "simetrik_1R_brut" in src
        assert "simetrik_1R_net" in src
        assert "BRÜT — maliyet düşülmemiş" in src


class TestEnginePeakSingleSource:
    """v5.5'te bulunan ikinci hata: motor kendi tepe max'ini tutuyordu.

    Portföye pencere eklemek tek başına YETMİYORDU — motor
    `peak_equity`'yi kendi max()'iyle güncelleyip ölçekleyiciye
    geçiriyordu. rolling/daily bu yüzden hiçbir şey değiştirmiyordu.
    """

    def test_engine_uses_portfolio_peak(self):
        import inspect

        from backtest import engine

        src = inspect.getsource(engine.BacktestEngine.run)
        assert "peak_equity = broker.portfolio.equity_peak" in src
        assert "if _equity_now > peak_equity:" not in src

    def test_rolling_mode_actually_reaches_scaler(self):

        from core.portfolio import Portfolio

        p = Portfolio(1_000.0)
        p.configure_peak("rolling", window_days=7)
        p.balance = 1_200.0
        p.last_ts_ms = 0
        p.equity({})
        p.balance = 1_000.0
        for d in range(1, 12):
            p.last_ts_ms = d * 86_400_000
            p.equity({})
        # pencere geçmiş tepeyi düşürdü → drawdown 0
        assert p.drawdown_pct({}) == pytest.approx(0.0)
        from core.config import PortfolioConfig

        assert PortfolioConfig(
            drawdown_peak_mode="rolling",
        ).drawdown_peak_mode == "rolling"


class TestLossAttributionAccounting:
    """Zarar atfı muhasebesi — çift sayım ve eksik brüt tuzakları."""

    def _trade(self, **kw):
        base = {
            "type": "CLOSE", "symbol": "A", "side": "LONG",
            "entry": 100.0, "stop_loss": 99.0, "pnl": -10.0,
            "entry_fee": 0.5, "fee": 0.5, "funding_paid": 0.2,
            "slippage": 1.0, "gross_pnl": -9.0, "r_multiple": -1.0,
            "target_net_risk": 10.0, "reason": "stop", "hold_ms": 600_000,
            "timestamp": 1_000_000, "tp1_done": False,
        }
        base.update(kw)
        return base

    def test_gross_reconstructed_not_from_gross_pnl_field(self):
        """gross_pnl TP1 kârını içermez → brüt olarak kullanılmamalı."""
        from tools.loss_attribution import _decompose

        d = _decompose([self._trade()], r_base=10.0)
        # net(-10) + fee(1.0) + slip(1.0) + funding(0.2) = -7.8
        assert d["brut_pnl"] == pytest.approx(-7.8)
        assert d["gross_pnl_alani_toplami"] == pytest.approx(-9.0)
        assert "İÇERMEZ" in d["gross_pnl_alani_uyarisi"]

    def test_funding_added_back_not_subtracted(self):
        from tools.loss_attribution import _decompose

        a = _decompose([self._trade(funding_paid=0.0)], 10.0)
        b = _decompose([self._trade(funding_paid=2.0)], 10.0)
        assert b["brut_pnl"] > a["brut_pnl"], "funding brüte GERİ eklenmeli"

    def test_cost_components_separate(self):
        from tools.loss_attribution import _decompose

        d = _decompose([self._trade()], 10.0)
        assert d["komisyon"] == pytest.approx(1.0)
        assert d["kayma"] == pytest.approx(1.0)
        assert d["funding"] == pytest.approx(0.2)
        assert d["dogrudan_maliyet"] == pytest.approx(2.0)

    def test_breakeven_winrate_formula(self):
        """Ödeme oranı 0.19 ise başabaş kazanma oranı %84."""
        payoff = 0.1909
        be = 1.0 / (1.0 + payoff)
        assert be == pytest.approx(0.8397, abs=1e-3)

    def test_payoff_ratio_reported(self):
        from tools.loss_attribution import _decompose

        trades = [self._trade(pnl=1.3734), self._trade(pnl=-7.1955),
                  self._trade(pnl=-7.1955), self._trade(pnl=-7.1955)]
        d = _decompose(trades, 8.0853)
        assert d["kazanma_orani"] == pytest.approx(0.25)
        assert d["odeme_orani"] == pytest.approx(0.1909, abs=1e-3)

    def test_exit_reasons_grouped(self):
        from tools.loss_attribution import _exit_reasons

        trades = [self._trade(reason="stop", pnl=-7.0),
                  self._trade(reason="stop", pnl=-7.0),
                  self._trade(reason="tp1_trail", pnl=1.4, tp1_done=True)]
        r = _exit_reasons(trades, 8.0)
        assert r["stop"]["islem"] == 2
        assert r["tp1_trail"]["tp1_yapilmis"] == 1
        assert r["stop"]["net_pnl"] == pytest.approx(-14.0)

    def test_empty_trades(self):
        from tools.loss_attribution import _decompose

        assert _decompose([], 10.0) == {"islem": 0}


class TestEmergencyStopOrdering:
    """v5.5 ana bulgusu: acil stop mumun dibinden kapatıyordu.

    Pozisyon, yapısal stopta net riski max_loss_per_position olacak
    şekilde boyutlanır → tam boyutlu işlemde iki eşik ÇAKIŞIR.
    Eski kod acil stopu seçip mumun EN KÖTÜ fiyatından + ekstra
    kaymayla kapatıyordu. Ölçülen aşım 1,346x (90 gün) ve 4,5R
    (yapay uç durum).
    """

    def _broker_pos(self, stop=99.7, side="LONG", risk=25.0):
        from core.portfolio import Position
        from exec.paper import PaperBroker
        from tests.helpers import apex_config

        b = PaperBroker(apex_config(), 1_000.0)
        p = Position(
            symbol="T", side=side, entry=100.0, quantity=100.0,
            initial_quantity=100.0, margin=1_000.0, stop_loss=stop,
            opened_at_ms=0, entry_fee=0.5, leverage=10.0,
            liquidation_price=50.0 if side == "LONG" else 150.0,
            take_profit=101.0 if side == "LONG" else 99.0,
            initial_net_risk=risk, initial_stop_loss=stop,
            motor="trend", score=90.0, regime="TREND_UP", signal_key="k1",
        )
        b.portfolio.positions["T"] = p
        b.max_loss_per_position = risk
        return b, p

    def test_structural_stop_wins_when_closer_long(self):
        from infra.market_data.models import Candle

        b, _ = self._broker_pos()
        c = Candle(timestamp=300_000, open=100.0, high=100.2,
                   low=99.0, close=99.5, volume=1_000.0)
        ev = b.manage_position_candle("T", c, 300_000)
        assert ev, "çıkış olmalı"
        assert ev[0]["reason"] == "stop_loss", (
            "yapısal stop girişe daha yakınsa o vurmalı"
        )
        # dolum yapısal stop civarında olmalı, mum dibi (99.0) DEĞİL
        assert ev[0]["price"] > 99.5

    def test_structural_stop_wins_when_closer_short(self):
        from infra.market_data.models import Candle

        b, _ = self._broker_pos(stop=100.3, side="SHORT")
        c = Candle(timestamp=300_000, open=100.0, high=101.0,
                   low=99.8, close=100.5, volume=1_000.0)
        ev = b.manage_position_candle("T", c, 300_000)
        assert ev
        assert ev[0]["reason"] == "stop_loss"
        assert ev[0]["price"] < 100.5

    def test_emergency_still_fires_when_structural_not_hit(self):
        """Yapısal stop bu mumda vurmayacaksa acil stop çalışmalı."""
        from infra.market_data.models import Candle

        # yapısal stop çok uzakta (95), acil eşik 25 USDT'de
        b, _ = self._broker_pos(stop=95.0, risk=25.0)
        c = Candle(timestamp=300_000, open=100.0, high=100.2,
                   low=99.5, close=99.6, volume=1_000.0)
        ev = b.manage_position_candle("T", c, 300_000)
        assert ev
        assert ev[0]["reason"] == "position_loss_stop", (
            "yapısal stop vurmadıysa acil stop güvenlik ağı olmalı"
        )

    def test_loss_reduced_versus_old_behaviour(self):
        """Ölçülen: eski 113.37 USDT → yeni ~40.47 USDT."""
        from infra.market_data.models import Candle

        b, _ = self._broker_pos()
        c = Candle(timestamp=300_000, open=100.0, high=100.2,
                   low=99.0, close=99.5, volume=1_000.0)
        ev = b.manage_position_candle("T", c, 300_000)
        assert abs(ev[0]["pnl"]) < 60.0, "aşım giderilmeli"

    def test_initial_stop_recorded(self):
        """İşlem yeniden üretilebilir olmalı: açılış stopu saklanıyor."""
        from infra.market_data.models import Candle

        b, _ = self._broker_pos()
        c = Candle(timestamp=300_000, open=100.0, high=100.2,
                   low=99.0, close=99.5, volume=1_000.0)
        ev = b.manage_position_candle("T", c, 300_000)
        assert ev[0]["initial_stop_loss"] == pytest.approx(99.7)
