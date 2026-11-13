"""v11 — izole çıkış ve kapanan işlem kayıt mutabakatı testleri."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import ws_bot
from logger.trade_logger import TradeLogger
from portfolio.paper_futures import LONG, PaperPortfolio
from scanner.ws_scanner import Sinyal


@pytest.fixture
def bot_yap(tmp_path, monkeypatch):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    monkeypatch.setattr(ws_bot, "OLAY_CSV", str(tmp_path / "logs" / "ws_olay.csv"))
    monkeypatch.setattr(ws_bot, "DURUM_JSON", str(tmp_path / "logs" / "ws_durum.json"))
    bots = []

    def _yap(**kwargs):
        detektor = SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={})
        bot = ws_bot.Bot(detektor, sure_dk=0, binance_mod="rest", **kwargs)
        bots.append(bot)
        return bot

    yield _yap
    for bot in bots:
        bot.olay_yazici.close()


def _sinyal(yon: str = LONG, fiyat: float = 100.0) -> Sinyal:
    return Sinyal(
        ts_ms=int(time.time() * 1000), exchange="okx",
        symbol="BTC-USDT-SWAP", yon=yon, etiket="TEST", fiyat=fiyat,
        ret_pct=0.5, rvol=5.0, hacim_usd=10_000.0, gecen_ms=60_000,
    )


def test_izole_cikis_genel_sl_yerine_pozisyon_stopunu_kullanir(bot_yap) -> None:
    bot = bot_yap(strateji="fade", tp=99.0, sl=3.0, tut_dk=240.0, izole=True)
    s = _sinyal(LONG)
    assert bot._pozisyon_ac(s) == "acildi"
    key = (s.exchange, s.symbol)
    pos = bot.portfoy.positions[key]
    expected_stop = 100.0 * (1 - (100.0 / ws_bot.KALDIRAC) / 100)
    assert pos.stop_price == pytest.approx(expected_stop)

    # Eski kod burada genel %3 SL ile kapatırdı; izole stop henüz vurulmadı.
    pos.last_price = 97.0
    assert bot._cikisleri_kontrol_et(s.ts_ms + 1_000) == 0
    assert key in bot.portfoy.positions

    pos.last_price = expected_stop - 0.01
    assert bot._cikisleri_kontrol_et(s.ts_ms + 2_000) == 1
    assert key not in bot.portfoy.positions
    assert bot.portfoy.closed_trades[-1].reason == "LIQUIDATION:stop_loss"
    assert bot.acilan == 1  # kapanışta karşıt/kurtarma pozisyonu açılmadı


def test_normal_modda_kendi_tp_ve_sl_seviyeleri_kullanilir(bot_yap) -> None:
    bot = bot_yap(strateji="fade", tp=1.0, sl=2.0, tut_dk=240.0, izole=False)
    s = _sinyal(LONG)
    assert bot._pozisyon_ac(s) == "acildi"
    key = (s.exchange, s.symbol)
    pos = bot.portfoy.positions[key]
    pos.last_price = 101.0
    assert bot._cikisleri_kontrol_et(s.ts_ms + 1_000) == 1
    assert bot.portfoy.closed_trades[-1].reason == "take_profit"


def test_log_missing_yalnizca_eksik_kapanisi_ekler(tmp_path) -> None:
    path = tmp_path / "trades.csv"
    logger = TradeLogger(str(path))
    pf = PaperPortfolio(1_000.0, fee_rate=0.0005)
    for symbol in ("A", "B"):
        result = pf.open_position("okx", symbol, LONG, 100.0, 100.0,
                                  leverage=1.0, step_size=1.0, now_ms=1)
        assert result.ok
        rec = pf.close_position("okx", symbol, 101.0, now_ms=2)
        assert rec is not None
    assert logger.log_trades([pf.closed_trades[0]]) == 1
    assert logger.log_missing(pf.closed_trades) == 1
    assert logger.log_missing(pf.closed_trades) == 0
    assert len(logger.read_rows(str(path))) == 2


def test_csv_hatasi_kapanisi_geri_almaz_ve_mutabakat_tamamlar(bot_yap, monkeypatch) -> None:
    bot = bot_yap(strateji="fade", tp=1.0, sl=2.0, tut_dk=240.0)
    s = _sinyal(LONG)
    assert bot._pozisyon_ac(s) == "acildi"
    original = bot.ticaret.log_trades

    def fail(_records):
        raise OSError("test: yazma hatası")

    monkeypatch.setattr(bot.ticaret, "log_trades", fail)
    rec = bot._kapat_ve_kaydet(s.exchange, s.symbol, 100.5, s.ts_ms + 1_000, "test")
    assert rec is not None
    assert bot.kapanan == 1 and bot.csv_kapanan == 0
    assert bot.kayit_hatalari == 1
    assert TradeLogger.read_rows(bot.ticaret.path) == []

    monkeypatch.setattr(bot.ticaret, "log_trades", original)
    bot._kayit_mutabakati()
    assert bot.mutabakat_eklenen == 1
    assert bot.csv_kapanan == bot.kapanan == 1
    assert len(TradeLogger.read_rows(bot.ticaret.path)) == 1

    bot.durum_yaz()
    status = json.loads(Path(ws_bot.DURUM_JSON).read_text(encoding="utf-8"))
    assert status["kayit_mutabakati"] is True
    assert status["csv_kapanan_islem"] == 1
