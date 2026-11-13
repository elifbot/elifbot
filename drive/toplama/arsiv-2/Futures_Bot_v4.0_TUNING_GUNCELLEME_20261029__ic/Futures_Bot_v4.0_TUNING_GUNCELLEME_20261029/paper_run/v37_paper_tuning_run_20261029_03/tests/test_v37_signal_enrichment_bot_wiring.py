"""Bot callback wiring: fade direction is confirmed before any paper entry."""
from __future__ import annotations

import asyncio
import csv
import time
from types import SimpleNamespace

import ws_bot
from scanner.ws_scanner import Sinyal


class _FakeEnricher:
    def __init__(self, result):
        self.result = result
        self.seen = None

    async def evaluate(self, session, **kwargs):
        self.seen = kwargs
        return self.result


def _result(accepted):
    return {
        "accepted": accepted,
        "reasons": [] if accepted else ["cvd_opposes_entry"],
        "mtf": {"available": True, "trend": "NEUTRAL", "score": 0,
                "1h": {"score": 0}, "4h": {"score": 0}},
        "derivatives": {"available": True, "funding_rate": 0.0,
                        "oi_usd": 1_000_000, "oi_change_pct": None,
                        "oi_signal": "NOTR", "funding_crowding": "DENGELI"},
        "flow": {"accepted": accepted, "cvd15_usd": 1_500,
                 "cvd60_usd": 1_500, "taker_buy_sell_ratio": 4.0,
                 "total15_usd": 2_500, "trades15": 5, "age_ms": 50},
    }


def _bot(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr(ws_bot, "TABAN", str(tmp_path))
    monkeypatch.setattr(ws_bot, "OLAY_CSV", str(tmp_path / "logs" / "ws_olay.csv"))
    monkeypatch.setattr(ws_bot, "AKIS_SINYAL_CSV", str(tmp_path / "logs" / "ws_akis_sinyal.csv"))
    settings = dict(
        strateji="fade", sinyal_zenginlestirme=True, kar_kilidi_aktif=True,
        teyit_aktif=False, defter_golge=False, funding_aktif=False,
        min_genislik=0.0, binance_mod="rest",
    )
    settings.update(overrides)
    bot = ws_bot.Bot(
        SimpleNamespace(genislik=0, genislik_oran=0.0, durumlar={}), **settings,
    )
    return bot


def _signal():
    return Sinyal(
        ts_ms=int(time.time() * 1000), exchange="binance", symbol="BTCUSDT",
        yon="LONG", etiket="breakout", fiyat=100.0, ret_pct=0.6,
        rvol=3.0, hacim_usd=10_000.0, gecen_ms=60_000,
    )


def test_bot_applies_fade_then_confirms_before_paper_entry(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    fake = _FakeEnricher(_result(True))
    bot.signal_enricher = fake
    opened = []
    bot._pozisyon_ac = lambda signal: opened.append(signal) or "paper_test"
    try:
        asyncio.run(bot.sinyal(_signal()))
        assert fake.seen["side"] == "SHORT"
        assert len(opened) == 1 and opened[0].yon == "SHORT"
        assert bot.signal_filter_counts["fade_applied"] == 1
        assert bot.signal_filter_counts["entry_eligible"] == 1
        with open(bot.signal_intel_csv, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["raw_side"] == "LONG"
        assert rows[0]["paper_side"] == "SHORT"
    finally:
        bot.olay_yazici.close()


def test_failed_signal_confirmation_never_calls_paper_entry(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    bot.signal_enricher = _FakeEnricher(_result(False))
    opened = []
    bot._pozisyon_ac = lambda signal: opened.append(signal) or "paper_test"
    try:
        asyncio.run(bot.sinyal(_signal()))
        assert opened == []
        assert bot.reddedilen == 1
        assert bot.signal_filter_counts["orderflow_block"] == 1
        assert bot.signal_filter_counts["entry_blocked"] == 1
    finally:
        bot.olay_yazici.close()


def test_stale_signal_is_blocked_after_slow_enrichment(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    bot.signal_enricher = _FakeEnricher(_result(True))
    opened = []
    bot._pozisyon_ac = lambda signal: opened.append(signal) or "paper_test"
    stale = _signal()
    stale.ts_ms -= 20_000
    try:
        asyncio.run(bot.sinyal(stale))
        assert opened == []
        assert bot.signal_filter_counts["stale_at_decision"] == 1
        assert bot.signal_filter_counts["entry_blocked"] == 1
    finally:
        bot.olay_yazici.close()


def test_profit_protection_mfe_state_survives_restart(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch, sinyal_zenginlestirme=False)
    opened = bot.portfoy.open_position(
        "binance", "BTCUSDT", "LONG", 100.0, 100.0,
        leverage=5.0, step_size=0.001, now_ms=1,
    )
    assert opened.ok and opened.position
    bot.portfoy.mark_price("binance", "BTCUSDT", 101.0, 2)
    protection = bot.portfoy.update_profit_protection("binance", "BTCUSDT")
    assert protection["stage"] == 2 and protection["mfe_active"]
    bot._durum_kaydet(strict=True)
    bot.olay_yazici.close()

    restored = _bot(tmp_path, monkeypatch, sinyal_zenginlestirme=False, durum_devam=True)
    try:
        pos = restored.portfoy.positions[("binance", "BTCUSDT")]
        assert pos.peak_price == 101.0
        assert pos.mfe_usdt == 5.0
        assert pos.profit_lock_stage == 2
        assert pos.mfe_lock_active is True
    finally:
        restored.olay_yazici.close()
