"""v14 — yalnızca ölçüm: MFE/MAE, giveback ve 10/30/60 sn telemetrisi."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ws_bot
from scanner.ws_scanner import Sinyal


@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    monkeypatch.setattr(ws_bot, "OLAY_CSV", str(tmp_path / "logs" / "ws_olay.csv"))
    monkeypatch.setattr(ws_bot, "DURUM_JSON", str(tmp_path / "logs" / "ws_durum.json"))
    monkeypatch.setattr(ws_bot, "TELEMETRI_CSV", str(tmp_path / "logs" / "ws_cikis_telemetri.csv"))
    bots = []

    def _yap(**kwargs):
        ayar = dict(strateji="fade", tp=99.0, sl=2.0, tut_dk=240.0,
                    giris_modu="market", min_genislik=0.0, acilis_freni=0)
        ayar.update(kwargs)
        bot = ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}),
                         sure_dk=0, binance_mod="rest", **ayar)
        bots.append(bot)
        return bot

    yield _yap
    for bot in bots:
        bot.olay_yazici.close()


def _sinyal(ts: int, yon: str = "LONG") -> Sinyal:
    return Sinyal(ts_ms=ts, exchange="binance", symbol="TESTUSDT", yon=yon,
                  etiket="TEST", fiyat=100.0, ret_pct=-0.6 if yon == "LONG" else 0.6,
                  rvol=6.0, hacim_usd=10_000.0, gecen_ms=60_000)


def _satir(bot) -> dict:
    with open(ws_bot.TELEMETRI_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    return rows[0]


def test_long_mfe_mae_zamanlari_giveback_ve_periyot_getirileri(bot_yap) -> None:
    t0 = 1_000_000
    bot = bot_yap()
    assert bot._pozisyon_ac(_sinyal(t0)) == "acildi"
    bot._fiyat_guncelle("binance", "TESTUSDT", 110.0, t0 + 5_000)
    bot._fiyat_guncelle("binance", "TESTUSDT", 108.0, t0 + 10_000)
    bot._fiyat_guncelle("binance", "TESTUSDT", 104.0, t0 + 30_000)
    bot._fiyat_guncelle("binance", "TESTUSDT", 102.0, t0 + 60_000)
    bot._fiyat_guncelle("binance", "TESTUSDT", 99.0, t0 + 70_000)
    rec = bot._kapat_ve_kaydet("binance", "TESTUSDT", 99.0, t0 + 70_000, "manual")
    assert rec is not None
    r = _satir(bot)
    assert float(r["mfe_pct"]) == pytest.approx(10.0)
    assert float(r["mae_pct"]) == pytest.approx(1.0)
    assert float(r["close_ret_pct"]) == pytest.approx(-1.0)
    assert float(r["time_to_mfe_s"]) == pytest.approx(5.0)
    assert float(r["time_to_mae_s"]) == pytest.approx(70.0)
    assert float(r["ret_10s_pct"]) == pytest.approx(8.0)
    assert float(r["ret_30s_pct"]) == pytest.approx(4.0)
    assert float(r["ret_60s_pct"]) == pytest.approx(2.0)
    assert r["peak_was_profitable"] == "1"
    assert float(r["giveback_usd"]) > 27.0
    assert float(r["max_net_est"]) > 24.0
    assert float(r["realized_pnl"]) < 0
    bot.durum_yaz()
    durum = json.loads(Path(ws_bot.DURUM_JSON).read_text())
    assert durum["telemetri_kayitlari"] == 1
    assert durum["telemetri_hatalari"] == 0


def test_short_mfe_mae_isaretleri_dogru(bot_yap) -> None:
    t0 = 2_000_000
    bot = bot_yap()
    assert bot._pozisyon_ac(_sinyal(t0, "SHORT")) == "acildi"
    bot._fiyat_guncelle("binance", "TESTUSDT", 95.0, t0 + 5_000)
    bot._fiyat_guncelle("binance", "TESTUSDT", 103.0, t0 + 15_000)
    rec = bot._kapat_ve_kaydet("binance", "TESTUSDT", 103.0, t0 + 20_000, "manual")
    assert rec is not None
    r = _satir(bot)
    assert float(r["mfe_pct"]) == pytest.approx(5.0)
    assert float(r["mae_pct"]) == pytest.approx(3.0)
    assert float(r["close_ret_pct"]) == pytest.approx(-3.0)
    assert float(r["ret_10s_pct"]) == pytest.approx(-3.0)
    assert float(r["giveback_usd"]) > 0


def test_erken_kapanista_gelecek_periyotlar_bos_ve_ana_csv_bozulmaz(bot_yap) -> None:
    t0 = 3_000_000
    bot = bot_yap()
    assert bot._pozisyon_ac(_sinyal(t0)) == "acildi"
    rec = bot._kapat_ve_kaydet("binance", "TESTUSDT", 100.0, t0 + 5_000, "manual")
    assert rec is not None
    r = _satir(bot)
    for sn in (10, 30, 60):
        assert r[f"ret_{sn}s_pct"] == ""
        assert r[f"pnl_{sn}s_net_est"] == ""
        assert r[f"olcum_{sn}s_sn"] == ""
    assert r["peak_was_profitable"] == "0"
    with open(Path(ws_bot.TABAN) / "live_trades.csv", newline="", encoding="utf-8") as fh:
        trades = list(csv.DictReader(fh))
    assert len(trades) == 1
    assert bot.kayit_hatalari == 0
    assert bot.telemetri_hatalari == 0
