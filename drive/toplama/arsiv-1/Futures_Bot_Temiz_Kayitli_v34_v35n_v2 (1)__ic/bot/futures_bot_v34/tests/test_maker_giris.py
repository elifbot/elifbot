"""Maker/limit girişin fiyat ve komisyon muhasebesi regresyon testleri."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import config
import ws_bot
from scanner.ws_scanner import Sinyal


@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    """Bot dosya çıktılarını geçici dizine yönlendirir."""
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    monkeypatch.setattr(ws_bot, "OLAY_CSV", str(tmp_path / "logs" / "ws_olay.csv"))
    monkeypatch.setattr(ws_bot, "DURUM_JSON", str(tmp_path / "logs" / "ws_durum.json"))
    olusturulan = []

    def _yap(giris_modu: str):
        bot = ws_bot.Bot(
            SimpleNamespace(),
            sure_dk=0,
            binance_mod="rest",
            strateji="fade",
            tp=1.25,
            sl=2.0,
            tut_dk=240.0,
            giris_modu=giris_modu,
            limit_payi=0.05,
            limit_bekle_sn=30.0,
        )
        olusturulan.append(bot)
        return bot

    yield _yap
    for bot in olusturulan:
        bot.olay_yazici.close()


def _sinyal(yon: str, fiyat: float = 100.0) -> Sinyal:
    return Sinyal(
        ts_ms=int(time.time() * 1000),
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        yon=yon,
        etiket="TEST",
        fiyat=fiyat,
        ret_pct=0.5,
        rvol=5.0,
        hacim_usd=10_000.0,
        gecen_ms=60_000,
    )


@pytest.mark.parametrize(
    ("yon", "beklenen_limit"),
    [("LONG", 99.95), ("SHORT", 100.05)],
)
def test_limit_dolumunda_fiyat_ve_ucret_bir_kez_uygulanir(
    bot_yap, yon: str, beklenen_limit: float
) -> None:
    """Limit payı iki kez uygulanmamalı; giriş maker, çıkış taker olmalı."""
    bot = bot_yap("limit")
    sinyal = _sinyal(yon)

    assert bot._pozisyon_ac(sinyal) == "bekliyor:limit"
    anahtar = (sinyal.exchange, sinyal.symbol)
    _, limit_fiyat, _, _ = bot.bekleyen[anahtar]
    assert limit_fiyat == pytest.approx(beklenen_limit)

    bot._bekleyenleri_isle(sinyal.exchange, sinyal.symbol, limit_fiyat)
    pozisyon = bot.portfoy.positions[anahtar]

    # v8'de ikinci %0,05 uygulanıyordu: LONG 99,900025 / SHORT 100,100025.
    assert pozisyon.entry_price == pytest.approx(beklenen_limit)
    assert pozisyon.entry_fee == pytest.approx(
        pozisyon.notional * config.MAKER_FEE_RATE
    )

    rec = bot.portfoy.close_position(
        sinyal.exchange,
        sinyal.symbol,
        pozisyon.entry_price,
        now_ms=sinyal.ts_ms,
        reason="test",
    )
    assert rec is not None
    assert rec.exit_fee == pytest.approx(
        pozisyon.qty_base * pozisyon.entry_price * config.TAKER_FEE_RATE
    )


def test_market_giris_taker_ucreti_kullanir(bot_yap) -> None:
    """Market davranışı değişmemeli: giriş ve çıkış taker ücretiyle."""
    bot = bot_yap("market")
    sinyal = _sinyal("LONG")

    assert bot._pozisyon_ac(sinyal) == "acildi"
    pozisyon = bot.portfoy.positions[(sinyal.exchange, sinyal.symbol)]
    assert pozisyon.entry_price == pytest.approx(100.0)
    assert pozisyon.entry_fee == pytest.approx(
        pozisyon.notional * config.TAKER_FEE_RATE
    )
