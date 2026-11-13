"""v16 — gerçek taker para-akışı ölçümü; ana strateji değişmez."""
from __future__ import annotations

import asyncio
import csv
import json
import time
from types import SimpleNamespace

import pytest

import ws_bot
from scanner.money_flow import AkisDefteri, YuvarlananAkis, akis_csv_alanlari
from scanner.ws_scanner import OKXAkisi, Sinyal


def test_cvd_alis_orani_ve_vwap_gercek_islemlerden() -> None:
    a = YuvarlananAkis()
    t0 = 1_000_000
    a.ekle(t0, 100.0, 1.0, "buy")
    a.ekle(t0 + 1000, 102.0, 0.5, "sell")
    s = a.anlik(t0 + 1000, 60)
    assert s.hazir
    assert s.alis_usd == pytest.approx(100.0)
    assert s.satis_usd == pytest.approx(51.0)
    assert s.cvd_usd == pytest.approx(49.0)
    assert s.alis_orani == pytest.approx(100.0 / 151.0)
    assert s.vwap == pytest.approx(151.0 / 1.5)
    assert s.islem_adedi == 2


def test_kisa_pencere_ve_eski_islem_budamasi() -> None:
    a = YuvarlananAkis()
    t0 = 1_000_000
    a.ekle(t0, 100, 1, "buy")
    a.ekle(t0 + 10_000, 100, 2, "sell")
    assert a.anlik(t0 + 10_000, 5).cvd_usd == pytest.approx(-200)
    assert a.anlik(t0 + 10_000, 15).cvd_usd == pytest.approx(-100)
    assert not a.anlik(t0 + 400_000, 60).hazir


def test_okx_kontrat_usd_donusumu_ve_aggregasyon() -> None:
    d = AkisDefteri()
    # 2 kontrat × 0.01 BTC × 80.000 = 1.600 USD agresif alış.
    d.okx_ekle("BTC-USDT-SWAP", 80_000, 2, "buy", 1_000_000, 0.01)
    d.okx_ekle("BTC-USDT-SWAP", 80_000, 1, "sell", 1_000_100, 0.01)
    s = d.anlik("okx", "BTC-USDT-SWAP", 1_000_100, 60)
    assert s.alis_usd == pytest.approx(1600)
    assert s.satis_usd == pytest.approx(800)
    assert s.cvd_usd == pytest.approx(800)
    assert d.trade_sayisi == 2
    assert d.hata_sayisi == 0


def test_eksik_kontrat_carpani_akisi_zehirlemez() -> None:
    d = AkisDefteri()
    d.okx_ekle("BTC-USDT-SWAP", 80_000, 2, "buy", 1_000_000, 0)
    assert d.trade_sayisi == 0
    assert d.hata_sayisi == 1
    assert not d.anlik("okx", "BTC-USDT-SWAP", 1_000_000, 60).hazir


def test_okx_trades_kanali_taker_yonunu_iletir() -> None:
    got = []
    akis = OKXAkisi(SimpleNamespace(), ["BTC-USDT-SWAP"], None,
                    akis_cb=lambda *args: got.append(args),
                    kontrat_carpanlari={"BTC-USDT-SWAP": 0.01})
    mesaj = {"arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
             "data": [{"instId": "BTC-USDT-SWAP", "tradeId": "1", "px": "80000",
                       "sz": "2.5", "side": "sell", "ts": "1000000"}]}
    asyncio.run(akis._isle(json.dumps(mesaj)))
    assert got == [("BTC-USDT-SWAP", 80_000.0, 2.5, "sell", 1_000_000, 0.01)]


def test_csv_alanlari_giris_cikis_cakismaz() -> None:
    a = set(akis_csv_alanlari("giris_"))
    b = set(akis_csv_alanlari("cikis_"))
    assert a and b and not (a & b)


@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    monkeypatch.setattr(ws_bot, "OLAY_CSV", str(tmp_path / "logs" / "ws_olay.csv"))
    monkeypatch.setattr(ws_bot, "DURUM_JSON", str(tmp_path / "logs" / "ws_durum.json"))
    monkeypatch.setattr(ws_bot, "TELEMETRI_CSV", str(tmp_path / "logs" / "ws_cikis_telemetri.csv"))
    monkeypatch.setattr(ws_bot, "GOLGE_CSV", str(tmp_path / "logs" / "ws_golge_cikis.csv"))
    monkeypatch.setattr(ws_bot, "AKIS_SINYAL_CSV", str(tmp_path / "logs" / "ws_akis_sinyal.csv"))
    monkeypatch.setattr(ws_bot, "AKIS_KAPANIS_CSV", str(tmp_path / "logs" / "ws_akis_kapanis.csv"))
    bot = ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}),
                     strateji="momentum", min_genislik=0, acilis_freni=0,
                     akis_olcum=True, tut_dk=240, giris_modu="market")
    yield bot
    bot.olay_yazici.close()


def test_sinyal_giris_cikis_akislari_sonucla_baglanir(bot_yap) -> None:
    bot = bot_yap
    simdi = int(time.time() * 1000)
    bot._akis_trade("BTC-USDT-SWAP", 100.0, 10.0, "buy", simdi - 500, 0.01)
    bot._akis_trade("BTC-USDT-SWAP", 100.0, 2.0, "sell", simdi - 400, 0.01)
    s = Sinyal(ts_ms=simdi, exchange="okx", symbol="BTC-USDT-SWAP", yon="LONG",
               etiket="TEST", fiyat=100.0, ret_pct=0.6, rvol=6.0,
               hacim_usd=10_000.0, gecen_ms=60_000)
    asyncio.run(bot.sinyal(s))
    rec = bot._kapat_ve_kaydet("okx", "BTC-USDT-SWAP", 101.0, simdi + 1000, "test")
    assert rec is not None
    with open(ws_bot.AKIS_SINYAL_CSV, newline="", encoding="utf-8") as fh:
        sinyal = list(csv.DictReader(fh))
    with open(ws_bot.AKIS_KAPANIS_CSV, newline="", encoding="utf-8") as fh:
        kapanis = list(csv.DictReader(fh))
    assert len(sinyal) == len(kapanis) == 1
    assert sinyal[0]["durum"] == "acildi"
    assert float(sinyal[0]["60s_cvd_usd"]) == pytest.approx(8.0)
    assert kapanis[0]["giris_hazir"] == "1"
    assert kapanis[0]["cikis_hazir"] == "1"
    assert float(kapanis[0]["realized_pnl"]) == pytest.approx(rec.realized_pnl)
    assert bot.akis_sinyal_kayitlari == bot.akis_kapanis_kayitlari == 1
    assert bot.akis_kayit_hatalari == 0
