"""v15 — aynı tiklerde alternatif çıkışların gölge simülasyonu."""
from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

import ws_bot
from portfolio.exit_shadow import ShadowPosition, ShadowVariant, default_variants
from scanner.ws_scanner import Sinyal


def _tracker(side="LONG", variant=None):
    variant = variant or ShadowVariant("baseline", 1.25, 2.0)
    return ShadowPosition("binance", "TESTUSDT", side, 100.0, 2.5, 0.125,
                          1_000_000, fee_rate=0.0005, variants=(variant,))


def test_baseline_long_tp_gercek_fiyattan_kapanir() -> None:
    tr = _tracker()
    tr.evaluate(101.3, 1_005_000)
    row = tr.rows()[0]
    assert row["reason"] == "take_profit"
    assert row["close_source"] == "rule"
    assert row["exit_price"] == 101.3
    assert row["realized_pnl"] == pytest.approx(3.25 - 0.125 - 101.3 * 2.5 * 0.0005)


def test_baseline_short_sl_gercek_fiyattan_kapanir() -> None:
    tr = _tracker("SHORT")
    tr.evaluate(102.1, 1_005_000)
    row = tr.rows()[0]
    assert row["reason"] == "stop_loss"
    assert row["realized_pnl"] == pytest.approx(-5.25 - 0.125 - 102.1 * 2.5 * 0.0005)


def test_ucret_dahil_basabas_stopu_net_sifira_yakin() -> None:
    tr = _tracker(variant=ShadowVariant("be", 1.25, 2.0,
                                       activation_mfe_pct=0.75, breakeven=True))
    tr.evaluate(100.8, 1_005_000)
    st = tr.states["be"]
    assert st.activated and st.stop_kind == "breakeven_stop"
    assert st.stop_price > 100.0
    stop = st.stop_price
    tr.evaluate(stop, 1_010_000)
    row = tr.rows()[0]
    assert row["reason"] == "breakeven_stop"
    assert abs(row["realized_pnl"]) < 1e-9


def test_long_trailing_ratchet_ve_kapanis() -> None:
    tr = _tracker(variant=ShadowVariant("trail", 1.25, 2.0,
                                       activation_mfe_pct=0.75,
                                       trailing_distance_pct=0.50))
    tr.evaluate(100.8, 1_005_000)
    tr.evaluate(101.2, 1_010_000)
    st = tr.states["trail"]
    assert st.stop_price == pytest.approx(101.2 * 0.995)
    peak_stop = st.stop_price
    tr.evaluate(100.9, 1_015_000)
    assert st.is_open and st.stop_price == peak_stop
    tr.evaluate(100.5, 1_020_000)
    row = tr.rows()[0]
    assert row["reason"] == "trailing_stop"
    assert row["mfe_pct"] == pytest.approx(1.2)
    assert row["realized_pnl"] > 0


def test_short_trailing_isaretleri_dogru() -> None:
    tr = _tracker("SHORT", ShadowVariant("trail", 1.25, 2.0,
                                        activation_mfe_pct=0.75,
                                        trailing_distance_pct=0.50))
    tr.evaluate(99.2, 1_005_000)
    st = tr.states["trail"]
    assert st.stop_price == pytest.approx(99.2 * 1.005)
    tr.evaluate(99.8, 1_010_000)
    row = tr.rows()[0]
    assert row["reason"] == "trailing_stop"
    assert row["mfe_pct"] == pytest.approx(0.8)
    assert row["realized_pnl"] > 0


def test_varsayilan_arastirma_seti_alti_varyant() -> None:
    variants = default_variants(1.25, 2.0)
    assert [v.name for v in variants] == [
        "baseline", "tp_100", "tp_075", "be_075", "trail_050_075", "trail_050_100"
    ]


@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    monkeypatch.setattr(ws_bot, "OLAY_CSV", str(tmp_path / "logs" / "ws_olay.csv"))
    monkeypatch.setattr(ws_bot, "DURUM_JSON", str(tmp_path / "logs" / "ws_durum.json"))
    monkeypatch.setattr(ws_bot, "TELEMETRI_CSV", str(tmp_path / "logs" / "ws_cikis_telemetri.csv"))
    monkeypatch.setattr(ws_bot, "GOLGE_CSV", str(tmp_path / "logs" / "ws_golge_cikis.csv"))
    bots = []

    def _yap(**kwargs):
        ayar = dict(strateji="fade", tp=1.25, sl=2.0, tut_dk=240.0,
                    giris_modu="market", min_genislik=0.0, acilis_freni=0,
                    golge_cikis=True)
        ayar.update(kwargs)
        bot = ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}),
                         sure_dk=0, binance_mod="rest", **ayar)
        bots.append(bot)
        return bot

    yield _yap
    for bot in bots:
        bot.olay_yazici.close()


def test_entegrasyon_golge_baseline_ana_islemle_birebir(bot_yap) -> None:
    t0 = 1_000_000
    bot = bot_yap()
    s = Sinyal(ts_ms=t0, exchange="binance", symbol="TESTUSDT", yon="LONG",
               etiket="TEST", fiyat=100.0, ret_pct=-0.6, rvol=6.0,
               hacim_usd=10_000.0, gecen_ms=60_000)
    assert bot._pozisyon_ac(s) == "acildi"
    bot._fiyat_guncelle("binance", "TESTUSDT", 101.3, t0 + 5_000)
    bot._cikisleri_kontrol_et(t0 + 5_000)
    assert bot.kapanan == 1
    rec = bot.portfoy.closed_trades[0]
    assert rec.reason == "take_profit"
    with open(ws_bot.GOLGE_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 6
    baseline = next(r for r in rows if r["variant"] == "baseline")
    assert baseline["reason"] == "take_profit"
    assert baseline["close_source"] == "rule"
    assert float(baseline["exit_price"]) == pytest.approx(rec.exit_price)
    assert float(baseline["realized_pnl"]) == pytest.approx(rec.realized_pnl)
    assert bot.golge_kayitlari == 6
    assert bot.golge_hatalari == 0


def test_arastirma_bayragi_kapaliysa_dosya_uretmez(bot_yap) -> None:
    t0 = 1_000_000
    bot = bot_yap(golge_cikis=False)
    s = Sinyal(ts_ms=t0, exchange="binance", symbol="TESTUSDT", yon="LONG",
               etiket="TEST", fiyat=100.0, ret_pct=-0.6, rvol=6.0,
               hacim_usd=10_000.0, gecen_ms=60_000)
    assert bot._pozisyon_ac(s) == "acildi"
    bot._kapat_ve_kaydet("binance", "TESTUSDT", 100.0, t0 + 5_000, "manual")
    assert not Path(ws_bot.GOLGE_CSV).exists()
