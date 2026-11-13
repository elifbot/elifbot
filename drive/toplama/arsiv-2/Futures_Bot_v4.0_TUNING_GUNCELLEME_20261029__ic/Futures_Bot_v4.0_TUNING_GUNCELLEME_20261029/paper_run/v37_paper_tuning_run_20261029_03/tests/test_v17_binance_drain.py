"""v17 — Binance üretim akışı, tek-varlık koruması ve doğal çıkış drain'i."""
from __future__ import annotations

import asyncio
import csv
import json
import time
from types import SimpleNamespace

import pytest

import ws_bot
from portfolio import flow_runner
from portfolio.flow_runner import FlowShadowEngine, binance_tamamlanmis_mumlar
from scanner.binance_flow import BinanceAggTradeFlow
from scanner.money_flow import AkisDefteri
from scanner.ws_scanner import Sinyal

OKX = "BTC-USDT-SWAP"
BNC = "BTCUSDT"
ETH = "ETHUSDT"


def candles(n=30):
    out = []
    for i in range(n):
        ts = i * 60_000
        c = 100 + (i % 3) * 0.1
        out.append([str(ts), str(c), str(c + 0.5), str(c - 0.5), str(c),
                    "100", "100", "10000", "1"])
    return out


def motor():
    book = AkisDefteri()
    events, closed = [], []
    e = FlowShadowEngine(book, events.append, closed.append)
    e.teknik_hazirla("okx", OKX, candles())
    e.teknik_hazirla("binance", BNC, candles())
    return e, book, events, closed


def trade(e, book, exchange, symbol, ts, price, side):
    book.ekle(exchange, symbol, price, 1, side, ts)
    e.on_trade(exchange, symbol, ts, price)


def open_okx_long(e, book, t0=1_800_000):
    trade(e, book, "okx", OKX, t0 - 2000, 100, "sell")
    e.sinyal("okx", OKX, "LONG", t0, 100)
    trade(e, book, "okx", OKX, t0, 101, "buy")
    trade(e, book, "okx", OKX, t0 + 500, 101, "buy")
    trade(e, book, "okx", OKX, t0 + 1100, 101, "buy")
    return e.pozisyonlar[("okx", OKX)]


def test_binance_market_aggtrade_taker_yonu_ve_id_tekrari() -> None:
    got = []
    flow = BinanceAggTradeFlow(["BTCUSDT"], lambda *row: got.append(row))
    assert "/market/stream?streams=" in flow._url(["BTCUSDT"])
    assert "binancefuture.com" not in flow._url(["BTCUSDT"])
    base = {"e": "aggTrade", "s": "BTCUSDT", "a": 10,
            "p": "100.5", "q": "2", "T": 1_700_000_000_000}
    flow._isle(json.dumps({"stream": "btcusdt@aggTrade", "data": base | {"m": True}}))
    flow._isle(json.dumps({"data": base | {"m": False}}))  # aynı aggregate id
    flow._isle(json.dumps({"data": base | {"a": 9, "m": False}}))  # eski id
    flow._isle(json.dumps({"data": base | {"a": 11, "m": False}}))
    assert [(r[4], r[2], r[3]) for r in got] == [("sell", 100.5, 2.0),
                                                   ("buy", 100.5, 2.0)]
    assert flow.mesaj_sayisi == 4 and flow.trade_sayisi == 2


def test_binance_base_miktar_usd_cvd_ve_borsa_ayrimi() -> None:
    book = AkisDefteri()
    book.binance_ekle(BNC, 100, 2, "buy", 10_000)
    book.binance_ekle(BNC, 101, 1, "sell", 11_000)
    book.ekle("okx", BNC, 100, 5, "sell", 11_000)
    a = book.anlik("binance", BNC, 12_000, 60)
    o = book.anlik("okx", BNC, 12_000, 60)
    assert a.cvd_usd == pytest.approx(200 - 101)
    assert a.toplam_usd == pytest.approx(301)
    assert a.vwap == pytest.approx(301 / 3)
    assert o.cvd_usd == -500


def test_ayni_base_iki_borsada_yalniz_bir_golge_aday() -> None:
    e, book, events, closed = motor()
    e.sinyal("okx", OKX, "LONG", 1_800_000, 100)
    e.sinyal("binance", BNC, "LONG", 1_800_001, 100)
    assert list(e.adaylar) == [("okx", OKX)]
    assert e.reddedilen == 1
    assert events[-1]["detay"] == "çapraz-borsa aynı varlık koruması"
    e.sinyal("binance", ETH, "LONG", 1_800_002, 2000)
    assert ("binance", ETH) in e.adaylar


def test_acik_pozisyon_varken_diger_borsa_sinyali_reddedilir() -> None:
    e, book, events, closed = motor()
    open_okx_long(e, book)
    e.sinyal("binance", BNC, "SHORT", 1_810_000, 101)
    assert ("binance", BNC) not in e.adaylar
    assert ("binance", BNC) not in e.pozisyonlar
    assert len(e.pozisyonlar) == 1


def test_drain_adaylari_iptal_eder_acik_pozisyon_dogal_kapanir() -> None:
    e, book, events, closed = motor()
    p = open_okx_long(e, book)
    e.sinyal("binance", ETH, "LONG", p.entry_ts, 2000)
    e.adaylari_iptal_et(p.entry_ts + 100, "drain_start")
    assert not e.adaylar and ("okx", OKX) in e.pozisyonlar
    trade(e, book, "okx", OKX, p.entry_ts + 1000, p.initial_stop, "sell")
    assert closed[-1]["reason"] == "disaster_2atr"
    assert not e.pozisyonlar


def test_drain_end_ve_cikis_telemetrisi() -> None:
    e, book, events, closed = motor()
    p = open_okx_long(e, book)
    trade(e, book, "okx", OKX, p.entry_ts + 1000, 103, "buy")
    e.session_end(p.entry_ts + 2000, "drain_end")
    row = closed[-1]
    assert row["reason"] == "drain_end"
    assert row["close_ret_pct"] == pytest.approx((103 / 101 - 1) * 100)
    assert row["giveback_pct"] == pytest.approx(0)
    assert row["initial_stop"] == p.initial_stop
    assert row["stop_price"] >= p.initial_stop
    assert row["atr_at_exit"] > 0


class _Response:
    def __init__(self, body):
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self.body


class _Session:
    def __init__(self, body):
        self.body = body
        self.params = None

    def get(self, url, **kwargs):
        self.params = kwargs.get("params")
        return _Response(self.body)


def test_binance_yalniz_tamamlanmis_1m_mumlari_donusturur(monkeypatch) -> None:
    monkeypatch.setattr(flow_runner.time, "time", lambda: 120.5)
    rows = [
        [0, "100", "102", "99", "101", "12", 59_999, "1212", 4, "6", "606", "0"],
        [60_000, "101", "103", "100", "102", "10", 119_999, "1020", 3, "5", "510", "0"],
        [120_000, "102", "104", "101", "103", "9", 179_999, "927", 2, "4", "412", "0"],
    ]
    session = _Session(rows)
    got = asyncio.run(binance_tamamlanmis_mumlar(session, BNC))
    assert session.params == {"symbol": BNC, "interval": "1m", "limit": 100}
    assert len(got) == 2
    assert got[0][:5] == ["0", "100", "102", "99", "101"]
    assert got[0][8] == "1" and got[1][8] == "1"


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    for ad in ("OLAY_CSV", "DURUM_JSON", "TELEMETRI_CSV", "GOLGE_CSV",
               "AKIS_SINYAL_CSV", "AKIS_KAPANIS_CSV",
               "AKIS_GOLGE_OLAY_CSV", "AKIS_GOLGE_KAPANIS_CSV"):
        ext = ".json" if ad == "DURUM_JSON" else ".csv"
        monkeypatch.setattr(ws_bot, ad, str(tmp_path / "logs" / (ad.lower() + ext)))
    obj = ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}),
                     strateji="momentum", min_genislik=0, acilis_freni=0,
                     akis_golge=True, tut_dk=240, cikis_tamamlama_dk=5,
                     giris_modu="market")
    obj.akis_motor.teknik_hazirla("okx", OKX, candles())
    yield obj
    obj.olay_yazici.close()


def _sinyal(ts):
    return Sinyal(ts_ms=ts, exchange="okx", symbol=OKX, yon="LONG", etiket="TEST",
                  fiyat=100, ret_pct=0.6, rvol=6, hacim_usd=10_000, gecen_ms=60_000)


def test_bot_drain_yeni_sinyali_ve_ana_golge_girisini_keser(bot) -> None:
    t0 = int(time.time() * 1000)
    asyncio.run(bot.sinyal(_sinyal(t0)))
    assert bot.acilan == 1 and len(bot.akis_motor.adaylar) == 1
    bot._cikis_tamamlama_baslat()
    assert bot.yeni_giris_kapali and not bot.akis_motor.adaylar
    asyncio.run(bot.sinyal(_sinyal(t0 + 1000)))
    assert bot.sinyal_sayisi == 1 and bot.acilan == 1
    assert bot.drenaj_sinyal_red == 1
    assert len(bot.portfoy.positions) == 1


def test_drain_end_imzasi_ana_ve_golge_csvye_ayni_nedeni_yazar(bot) -> None:
    t0 = int(time.time() * 1000)
    bot._akis_trade(OKX, 100, 1, "sell", t0 - 2000, 1)
    asyncio.run(bot.sinyal(_sinyal(t0)))
    bot._akis_trade(OKX, 101, 1, "buy", t0, 1)
    bot._akis_trade(OKX, 101, 1, "buy", t0 + 1100, 1)
    assert bot.acilan == 1 and bot.akis_motor.acilan == 1
    bot._cikis_tamamlama_baslat()
    bot._tumunu_kapat("drain_end")
    assert not bot.portfoy.positions and not bot.akis_motor.pozisyonlar
    with open(ws_bot.AKIS_GOLGE_KAPANIS_CSV, newline="", encoding="utf-8") as f:
        shadow = list(csv.DictReader(f))
    with open(ws_bot.TELEMETRI_CSV, newline="", encoding="utf-8") as f:
        main = list(csv.DictReader(f))
    assert shadow[0]["reason"] == "drain_end"
    assert main[0]["reason"] == "drain_end"
    assert "giveback_pct" in shadow[0] and "stop_price" in shadow[0]


def test_negatif_drain_suresi_reddedilir() -> None:
    with pytest.raises(ValueError):
        ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}),
                   cikis_tamamlama_dk=-0.1)
