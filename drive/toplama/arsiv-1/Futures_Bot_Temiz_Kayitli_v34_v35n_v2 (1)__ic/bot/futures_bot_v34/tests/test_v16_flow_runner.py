"""v16 — CVD/VWAP onaylı, sabit TP'siz ATR akış gölgesi."""
from __future__ import annotations

import asyncio
import csv
import time
from types import SimpleNamespace

import pytest

import ws_bot
from portfolio.flow_runner import CanliTeknik, FlowShadowEngine
from scanner.money_flow import AkisDefteri
from scanner.ws_scanner import Sinyal

SYM = "TEST-USDT-SWAP"


def candles(n=30):
    out = []
    for i in range(n):
        ts = i * 60_000
        c = 100 + (i % 3) * 0.1
        out.append([str(ts), str(c), str(c + 0.5), str(c - 0.5), str(c),
                    "100", "100", "10000", "1"])
    return out


def engine():
    book = AkisDefteri()
    events, closed = [], []
    e = FlowShadowEngine(book, events.append, closed.append)
    e.teknik_hazirla("okx", SYM, candles())
    return e, book, events, closed


def trade(e, book, ts, price, side):
    book.okx_ekle(SYM, price, 1, side, ts, 1)
    e.on_trade("okx", SYM, ts, price)


def open_long(e, book, t0=1_800_000):
    trade(e, book, t0 - 2000, 100, "sell")
    e.sinyal("okx", SYM, "LONG", t0, 100)
    trade(e, book, t0, 101, "buy")
    trade(e, book, t0 + 500, 101, "buy")
    trade(e, book, t0 + 1100, 101, "buy")
    return e.pozisyonlar[("okx", SYM)]


def test_giris_tek_tikle_degil_bir_saniye_onayla_acilir() -> None:
    e, book, events, closed = engine()
    t0 = 1_800_000
    trade(e, book, t0 - 2000, 100, "sell")
    e.sinyal("okx", SYM, "LONG", t0, 100)
    trade(e, book, t0, 101, "buy")
    trade(e, book, t0 + 500, 101, "buy")
    assert not e.pozisyonlar
    trade(e, book, t0 + 1100, 101, "buy")
    p = e.pozisyonlar[("okx", SYM)]
    assert p.entry == 101
    assert p.entry_ts - t0 == 1100
    assert e.acilan == 1


def test_sabit_tp_yok_ve_chandelier_kazanci_takip_eder() -> None:
    e, book, events, closed = engine()
    p = open_long(e, book)
    t = p.entry_ts
    trade(e, book, t + 1000, 103, "buy")  # +%1,98; eski %1,25 TP'de kapanırdı
    assert ("okx", SYM) in e.pozisyonlar
    p = e.pozisyonlar[("okx", SYM)]
    assert p.mfe > 1.25
    stop = p.stop
    assert stop > p.initial_stop
    trade(e, book, t + 2000, stop, "sell")
    assert closed and closed[0]["reason"] == "chandelier_3atr"
    assert closed[0]["mfe_pct"] > 1.25
    assert not e.pozisyonlar


def test_long_baslangic_felaket_stopu_iki_atr() -> None:
    e, book, events, closed = engine()
    p = open_long(e, book)
    trade(e, book, p.entry_ts + 1000, p.initial_stop, "sell")
    assert closed[0]["reason"] == "disaster_2atr"
    assert closed[0]["realized_pnl"] < 0


def test_short_onay_ve_stop_isaretleri_dogru() -> None:
    e, book, events, closed = engine()
    t0 = 1_800_000
    trade(e, book, t0 - 2000, 100, "buy")
    e.sinyal("okx", SYM, "SHORT", t0, 100)
    trade(e, book, t0, 99, "sell")
    trade(e, book, t0 + 500, 99, "sell")
    trade(e, book, t0 + 1600, 99, "sell")
    p = e.pozisyonlar[("okx", SYM)]
    assert p.side == "SHORT" and p.initial_stop > p.entry
    trade(e, book, t0 + 2600, p.initial_stop, "buy")
    assert closed[0]["reason"] == "disaster_2atr"


def test_onay_gelmezse_aday_altmis_saniyede_duser() -> None:
    e, book, events, closed = engine()
    t0 = 1_800_000
    e.sinyal("okx", SYM, "LONG", t0, 100)
    trade(e, book, t0 + 61_000, 99, "sell")
    assert not e.adaylar and not e.pozisyonlar
    assert e.suresi_dolan == 1


def test_canli_teknik_gelecek_mumu_kullanmaz() -> None:
    t = CanliTeknik(candles())
    ilk_atr = t.atr
    t.on_trade(30 * 60_000 + 1000, 110)
    assert t.atr == ilk_atr
    t.on_trade(31 * 60_000 + 1000, 111)
    assert t.atr != ilk_atr
    assert t.bar_close_ms == 31 * 60_000


@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    for ad in ("OLAY_CSV", "DURUM_JSON", "TELEMETRI_CSV", "GOLGE_CSV",
               "AKIS_SINYAL_CSV", "AKIS_KAPANIS_CSV",
               "AKIS_GOLGE_OLAY_CSV", "AKIS_GOLGE_KAPANIS_CSV"):
        dosya = ad.lower() + (".json" if ad == "DURUM_JSON" else ".csv")
        monkeypatch.setattr(ws_bot, ad, str(tmp_path / "logs" / dosya))
    bot = ws_bot.Bot(SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}),
                     strateji="momentum", min_genislik=0, acilis_freni=0,
                     akis_golge=True, tut_dk=240)
    bot.akis_motor.teknik_hazirla("okx", SYM, candles())
    yield bot
    bot.olay_yazici.close()


def test_ana_pozisyon_ve_akis_golgesi_birbirini_degistirmez(bot_yap) -> None:
    bot = bot_yap
    t0 = int(time.time() * 1000)
    bot._akis_trade(SYM, 100, 1, "sell", t0 - 2000, 1)
    s = Sinyal(ts_ms=t0, exchange="okx", symbol=SYM, yon="LONG", etiket="TEST",
               fiyat=100, ret_pct=-0.6, rvol=6, hacim_usd=10_000, gecen_ms=60_000)
    asyncio.run(bot.sinyal(s))
    assert bot.acilan == 1                         # ana baseline hemen açtı
    assert len(bot.akis_motor.adaylar) == 1       # gölge hâlâ onay bekliyor
    assert not bot.akis_motor.pozisyonlar
    bot._akis_trade(SYM, 101, 1, "buy", t0, 1)
    bot._akis_trade(SYM, 101, 1, "buy", t0 + 1100, 1)
    assert bot.acilan == 1                         # gölge açılışı ana sayacı değiştirmez
    assert bot.akis_motor.acilan == 1
    assert len(bot.portfoy.positions) == 1
    bot._tumunu_kapat()
    assert bot.kapanan == 1 and bot.akis_motor.kapanan == 1
    with open(ws_bot.AKIS_GOLGE_KAPANIS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]["reason"] == "session_end"
    assert bot.akis_golge_hatalari == 0
