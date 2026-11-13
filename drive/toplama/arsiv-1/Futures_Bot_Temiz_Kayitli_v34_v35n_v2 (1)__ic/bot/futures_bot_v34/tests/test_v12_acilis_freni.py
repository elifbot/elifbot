"""v12 — yalnızca 10 sn açılış freninin kaldırılması testleri."""
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
        ayar = dict(
            strateji="fade", tp=99.0, sl=2.0, tut_dk=240.0,
            giris_modu="market", min_genislik=0.0,
        )
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


def test_varsayilan_fren_kapali_dort_acilis_ayni_pencerede_acilir(bot_yap) -> None:
    bot = bot_yap()
    assert bot.acilis_freni == 0
    sonuc = [bot._pozisyon_ac(_sinyal(f"S{i}USDT")) for i in range(4)]
    assert sonuc == ["acildi"] * 4
    assert bot.portfoy.open_count() == 4
    assert bot.reddedilen == 0


def test_fren_istenirse_yeniden_acilabilir(bot_yap) -> None:
    bot = bot_yap(acilis_freni=3)
    for i in range(3):
        assert bot._pozisyon_ac(_sinyal(f"S{i}USDT")) == "acildi"
    assert bot._pozisyon_ac(_sinyal("S3USDT")) == "engel:korelasyon_freni"
    assert bot.portfoy.open_count() == 3


def test_cift_varlik_korumasi_fren_kapalyken_de_korunur(bot_yap) -> None:
    bot = bot_yap(acilis_freni=0)
    assert bot._pozisyon_ac(_sinyal("BTC-USDT-SWAP", "okx")) == "acildi"
    ret = bot._pozisyon_ac(_sinyal("BTCUSDT", "binance"))
    assert ret.startswith("engel:cift_borsa")
    assert bot.portfoy.open_count() == 1


def test_negatif_fren_degeri_reddedilir(bot_yap) -> None:
    with pytest.raises(ValueError):
        bot_yap(acilis_freni=-1)
