"""v5.6 — kullanıcı şartnamesi (kasa 1000 / marj 50 / 10x / stop 25 USD)."""
from __future__ import annotations

import pytest

from core.sizing_audit import SizingSpec, audit, required_timeframe_scale


class TestSpecMath:
    def test_notional(self):
        assert SizingSpec().notional == pytest.approx(500.0)

    def test_required_stop(self):
        s = SizingSpec()
        assert s.required_stop_fraction == pytest.approx(0.047861, abs=1e-5)

    def test_measured_5m_stop_violates_spec(self):
        a = audit(0.0033)
        assert a["hukum"] == "SARTNAME_IHLALI"
        assert a["marj_sisme_katsayisi"] > 9.0

    def test_spec_stop_is_consistent(self):
        a = audit(SizingSpec().required_stop_fraction)
        assert a["hukum"] == "TUTARLI"
        assert a["uygulanacak_risk"] == pytest.approx(25.0, abs=0.01)
        assert a["uygulanacak_marj"] == pytest.approx(50.0, abs=0.01)

    def test_wide_stop_is_safe(self):
        """Geniş stopta KAYIP TAVANI bağlayıcı olur, marj küçülür."""
        a = audit(0.08)
        assert a["hukum"] == "KAYIP_TAVANI_BAGLAYICI"
        assert a["sabit_marjda_risk_HIPOTETIK"] > 25.0
        assert a["uygulanacak_marj"] < 50.0
        assert a["uygulanacak_risk"] == pytest.approx(25.0)

    def test_cost_share_drops_with_wider_stop(self):
        narrow = audit(0.0033)["maliyet_risk_payi"]
        wide = audit(0.047861)["maliyet_risk_payi"]
        assert wide < narrow / 5, "geniş stop maliyet payını düşürmeli"
        assert wide == pytest.approx(0.0428, abs=1e-3)

    def test_timeframe_scale(self):
        r = required_timeframe_scale(0.0033)
        assert r["zaman_katsayisi"] > 200
        assert r["onerilen_saat"] > 15

    def test_bad_stop_rejected(self):
        with pytest.raises(ValueError):
            audit(0.0)
        with pytest.raises(ValueError):
            audit(1.5)


class TestKasa1000Profile:
    def _cfg(self, profile):
        from app.main import apply_profile, build_parser
        from core.config import SuperConfig

        args = build_parser().parse_args(
            ["--mode", "paper", "--paper", "--profile", profile])
        return apply_profile(args, SuperConfig())

    def test_profile_enforces_margin(self):
        c = self._cfg("kasa1000")
        assert c.account.margin_per_position == pytest.approx(50.0)
        assert c.account.max_notional_per_position == pytest.approx(500.0)
        assert c.account.leverage == pytest.approx(10.0)
        assert c.account.max_loss_per_position == pytest.approx(25.0)

    def test_apex_is_unbounded_research_only(self):
        c = self._cfg("apex")
        assert c.account.margin_per_position == 0.0
        assert c.account.max_notional_per_position == 0.0

    def test_narrow_stop_margin_capped(self):
        from core.risk import RiskManager

        c = self._cfg("kasa1000")
        p = RiskManager(c).plan(100.0, 0.0033, "LONG")
        assert p.margin <= 50.0 + 1e-6
        assert p.notional <= 500.0 + 1e-6
        assert p.net_risk_at_stop < 25.0

    def test_apex_inflates_margin_nine_fold(self):
        """Kusurun regresyon kilidi: apex marjı 9x şişiriyor."""
        from core.risk import RiskManager

        c = self._cfg("apex")
        p = RiskManager(c).plan(100.0, 0.0033, "LONG")
        assert p.margin > 450.0, "apex sınırsız — şartnameyi aşar"

    def test_kasa1000_keeps_portfolio_caps(self):
        c = self._cfg("kasa1000")
        assert c.portfolio.max_positions == 6
        assert c.portfolio.total_open_risk_cap == pytest.approx(150.0)
        assert c.portfolio.daily_hard_loss == pytest.approx(150.0)

    def test_spec_stop_gives_full_risk_within_margin(self):
        from core.risk import RiskManager

        c = self._cfg("kasa1000")
        p = RiskManager(c).plan(100.0, SizingSpec().required_stop_fraction, "LONG")
        assert p.margin <= 50.0 + 1e-6
        assert p.net_risk_at_stop == pytest.approx(25.0, abs=0.6)
