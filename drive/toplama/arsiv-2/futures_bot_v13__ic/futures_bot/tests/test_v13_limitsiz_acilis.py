"""v13 — yapay açılış limitleri kapalı, muhasebe ve çift-varlık koruması açık."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import ws_bot
from scanner.ws_scanner import Sinyal


@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    monkeypatch.setattr(ws_bot, "OLAY_CSV", str(tmp_path / "logs" / "ws_olay.csv"))
    monkeypatch.setattr(ws_bot, "DURUM_JSON", str(tmp_path / "logs" / "ws_durum.json"))
    bots = []

    def _yap(**kwargs):
        ayar = dict(strateji="fade", tp=99.0, sl=2.0, tut_dk=240.0,
                    giris_modu="market", min_genislik=0.0, acilis_freni=0)
        ayar.update(kwargs)
        bot = ws_bot.Bot(
            SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}),
            sure_dk=0, binance_mod="rest", **ayar,
        )
        bots.append(bot)
        return bot

    yield _yap
    for bot in bots:
        bot.olay_yazici.close()


def _sinyal(symbol: str, exchange: str = "binance", yon: str = "LONG") -> Sinyal:
    return Sinyal(
        ts_ms=int(time.time() * 1000), exchange=exchange, symbol=symbol,
        yon=yon, etiket="TEST", fiyat=100.0, ret_pct=-0.6,
        rvol=6.0, hacim_usd=10_000.0, gecen_ms=60_000,
    )


def test_v13_varsayilan_butun_yapay_limitler_kapali(bot_yap) -> None:
    bot = bot_yap()
    pf = bot.portfoy
    assert bot.acilis_freni == 0
    assert pf.max_open_positions is None
    assert pf.max_same_direction is None
    assert pf.max_utilisation is None
    assert pf.daily_loss_limit_pct is None
    assert pf.balance_floor == 0.0


def test_eski_40_tavaninin_ustunde_45_farkli_sembol_acilir(bot_yap, monkeypatch) -> None:
    monkeypatch.setattr(ws_bot, "MARJ", 1.0)
    bot = bot_yap()
    sonuc = [bot._pozisyon_ac(_sinyal(f"S{i}USDT")) for i in range(45)]
    assert sonuc == ["acildi"] * 45
    assert bot.portfoy.open_count() == 45
    assert bot.reddedilen == 0


def test_iki_borsadan_aynı_kod_yalnizca_bir_kez_alinir(bot_yap) -> None:
    bot = bot_yap()
    assert bot._pozisyon_ac(_sinyal("BTC-USDT-SWAP", "okx")) == "acildi"
    assert bot._pozisyon_ac(_sinyal("BTCUSDT", "binance")).startswith("engel:cift_borsa")
    assert bot.portfoy.open_count() == 1


def test_gercek_bakiye_yeterliligi_korunur(bot_yap, monkeypatch) -> None:
    monkeypatch.setattr(ws_bot, "MARJ", 900.0)
    bot = bot_yap()
    assert bot._pozisyon_ac(_sinyal("AUSDT")) == "acildi"
    assert bot._pozisyon_ac(_sinyal("BUSDT")) == "engel:marj_yetersiz"
    assert bot.portfoy.open_count() == 1


def test_gunluk_zarar_giris_kilidi_v13te_kapali(bot_yap) -> None:
    bot = bot_yap()
    bot.portfoy.day_start_balance = 2_000.0
    assert bot.portfoy.daily_pnl() < 0
    assert not bot.portfoy.daily_loss_limit_hit()
    assert bot._pozisyon_ac(_sinyal("AUSDT")) == "acildi"
