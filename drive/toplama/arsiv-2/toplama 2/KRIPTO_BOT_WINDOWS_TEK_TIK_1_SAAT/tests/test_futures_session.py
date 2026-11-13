from __future__ import annotations

import asyncio
import copy
import time
from types import SimpleNamespace

from src.exchanges import ExchangeManager
from src.futures_catalog import build_futures_catalog, perpetual_symbol
from src.market_data import MarketData
from src.moneyflow import MoneyFlow
from src.state_store import StateStore
from src.telegram import InteractiveTelegramBot, telegram_message_chunks


def market(symbol: str, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "active": True,
        "swap": True,
        "contract": True,
        "linear": True,
        "quote": "USDT",
        "settle": "USDT",
        "limits": {"leverage": {"max": 100}},
    }
    row.update(overrides)
    return row


def test_catalog_only_active_usdt_perpetual_and_exchange_support():
    exchange_markets = {
        "binance": {
            "BTC": market("BTC/USDT:USDT"),
            "DATED": market("BTC/USDT:USDT-251226", swap=False),
            "SPOT": market("ETH/USDT", swap=False, contract=False),
            "INACTIVE": market("XMR/USDT:USDT", active=False),
            "LOWLEV": market("LOW/USDT:USDT", limits={"leverage": {"max": 5}}),
            "INVERSE": market("SOL/USDT:USD", linear=False, settle="USD"),
            "BIN": market("BINONLY/USDT:USDT"),
        },
        "okx": {
            "BTC": market("BTC/USDT:USDT"),
            "OK": market("OKONLY/USDT:USDT"),
        },
    }
    symbols, support = build_futures_catalog(
        exchange_markets, preferred_symbols=["BTC/USDT"], min_leverage=10
    )
    assert symbols == ["BTC/USDT", "BINONLY/USDT", "OKONLY/USDT"]
    assert support["BTC/USDT"] == ["binance", "okx"]
    assert support["BINONLY/USDT"] == ["binance"]
    assert support["OKONLY/USDT"] == ["okx"]
    assert perpetual_symbol(market("BAD/USDT:USDT", quote="USDC")) is None


def test_discovery_analyzes_low_leverage_but_does_not_make_it_tradeable():
    markets = {
        "BTC": market("BTC/USDT:USDT"),
        "LOW": market("LOW/USDT:USDT", limits={"leverage": {"max": 5}}),
    }

    class PublicExchange:
        async def load_markets(self):
            return markets

    manager = object.__new__(ExchangeManager)
    manager.default_type = "swap"
    manager._ex = {"binance": PublicExchange()}
    info = asyncio.run(manager.discover_futures(min_leverage=10))
    assert info["symbols"] == ["BTC/USDT", "LOW/USDT"]
    assert info["trade_symbols"] == ["BTC/USDT"]
    assert info["restricted_leverage_symbols"] == ["LOW/USDT"]
    assert manager.leverage_restricted_symbols == {"LOW/USDT"}


def test_symbol_exchange_never_fails_over_to_unsupported_exchange():
    manager = object.__new__(ExchangeManager)
    manager._ex = {"binance": object(), "okx": object()}
    manager.symbol_exchanges = {"OKONLY/USDT": ["okx"]}
    manager._default_primary = "binance"
    manager._active_primary = "binance"
    manager._ex_degraded_until = {"binance": 0.0, "okx": 0.0}
    assert manager.choose_symbol_exchange("OKONLY/USDT", "binance") == "okx"
    assert manager.get_failover_order("binance", symbol="OKONLY/USDT") == ["okx"]


def test_websocket_batches_are_exchange_specific():
    data = MarketData(
        ["BTC/USDT", "BINONLY/USDT", "OKONLY/USDT"],
        ["binance", "okx"],
        symbol_exchanges={
            "BTC/USDT": ["binance", "okx"],
            "BINONLY/USDT": ["binance"],
            "OKONLY/USDT": ["okx"],
        },
        stream_batch_size=1,
        depth_update_ms=500,
    )
    assert data.depth_update_ms == 500
    assert data.stream_batches("binance") == [["BTC/USDT"], ["BINONLY/USDT"]]
    assert data.stream_batches("okx") == [["BTC/USDT"], ["OKONLY/USDT"]]
    assert data.symbols_for_exchange("okx") == ["BTC/USDT", "OKONLY/USDT"]
    data.prices["binance:BTC/USDT"] = 100.0
    data.prices["okx:BTC/USDT"] = 101.0
    assert data.get_price("BTC/USDT", "okx") == 101.0
    assert data.get_price("BTC/USDT", "binance") == 100.0


def test_compact_orderflow_history_is_bounded():
    flow = MoneyFlow("BTC/USDT", compact_history=True)
    assert flow._trades.maxlen == 2_000
    assert flow._vpvr_trades.maxlen == 5_000
    assert flow._book_hist.maxlen == 200
    assert flow.liquidations.maxlen == 100


def test_long_telegram_report_is_split_without_oversize_chunks():
    text = "\n".join(f"BTC/USDT LONG | satır {i} | KZ $+1.00" for i in range(400))
    chunks = telegram_message_chunks(text)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 3900 for chunk in chunks)
    assert "satır 0" in chunks[0]
    assert "satır 399" in chunks[-1]


def test_daily_report_has_equity_costs_counts_and_net_pnl(tmp_path):
    store = StateStore(tmp_path / "daily.db")
    start = time.time() - 120
    store.record_trade("BTC/USDT", "LONG", 100, 110, 1, 10, "TRAIL", 10, 50, 200)
    store.record_trade("ETH/USDT", "SHORT", 100, 105, 1, -5, "STOP", 10, 50, -50)
    store.set_meta(
        "paper_24h_session",
        {
            "start_ts": start,
            "start_balance": 100_000.0,
            "start_equity": 100_000.0,
            "start_fees": 10.0,
            "start_funding": 2.0,
            "entries": 3,
        },
    )
    paper = SimpleNamespace(
        balance=100_125.0,
        start_balance=100_000.0,
        total_fees_usdt=30.0,
        total_funding_usdt=-3.0,
    )

    class Broker:
        mode = "paper"
        primary = "binance"

        async def fetch_balance_usdt(self):
            return paper.balance

    broker = Broker()
    broker.paper = paper
    executor = SimpleNamespace(
        positions={},
        last_prices={},
        stats={},
        total_unrealized_usdt=lambda: 25.0,
    )
    bot = InteractiveTelegramBot(
        executor=executor, broker=broker, state_store=store
    )
    report = asyncio.run(bot._format_daily_report())
    assert "Başlangıç özsermayesi: $100,000.00" in report
    assert "Bitiş/anlık özsermaye: $100,150.00" in report
    assert "NET OTURUM K/Z: $+150.00" in report
    assert "Gerçekleşen fiyat K/Z (brüt): $+150.00 | Açık K/Z: $+25.00" in report
    assert "Komisyon: $20.00" in report
    assert "Funding (ödeme - / alacak +): $-5.00" in report
    assert "Açılan işlem: 3" in report
    assert "Kapanan işlem: 2" in report and "1 kâr / 1 zarar" in report
    assert "Kazanma oranı: %50.0" in report
    assert "BTC/USDT: 1 işlem | $+200.00" in report
    assert "brüt fiyat K/Z'sidir" in report


def test_timed_main_writes_daily_report_and_shuts_down(tmp_path, monkeypatch):
    import src.main as main_module
    from src.config import load_config
    from src.market_data import MarketData
    from src.news import NewsEngine

    cfg = copy.deepcopy(load_config())
    cfg["genel"]["mod"] = "paper"
    cfg["genel"]["semboller"] = ["BTC/USDT"]
    cfg["futures"]["tum_pariteler"] = True
    cfg["health_check"]["aktif"] = False
    cfg["bildirimler"]["telegram_aktif"] = False
    cfg["bildirimler"]["discord_aktif"] = False
    cfg["bildirimler"]["pagerduty_aktif"] = False
    cfg["api"] = {key: "" for key in cfg.get("api", {})}

    async def fake_discover(self, **kwargs):
        self.symbols = ["BTC/USDT"]
        self.symbol_exchanges = {"BTC/USDT": ["binance"]}
        return {
            "symbols": self.symbols,
            "support": self.symbol_exchanges,
            "errors": {},
            "per_exchange": {"binance": 1},
        }

    async def no_contract_sizes(self):
        return {}

    async def idle(self):
        await asyncio.Future()

    async def fake_send_daily(self, text=None):
        return True

    monkeypatch.setattr(main_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(main_module, "load_config", lambda: cfg)
    monkeypatch.setattr(ExchangeManager, "discover_futures", fake_discover)
    monkeypatch.setattr(ExchangeManager, "get_contract_sizes", no_contract_sizes)
    monkeypatch.setattr(MarketData, "run_forever", idle)
    monkeypatch.setattr(NewsEngine, "run_forever", idle)
    monkeypatch.setattr(InteractiveTelegramBot, "send_daily_report", fake_send_daily)
    monkeypatch.setenv("PAPER_SESSION_HOURS", "0.00005")
    monkeypatch.setenv("BOT_DB_FILE", str(tmp_path / "session.db"))

    asyncio.run(main_module.main())

    reports = list((tmp_path / "reports").glob("gunluk_*.txt"))
    assert len(reports) == 1
    report = reports[0].read_text(encoding="utf-8")
    assert "Başlangıç özsermayesi: $100,000.00" in report
    assert "Açılan işlem: 0" in report
    assert "OTURUM BİLEŞEN / MALİYET ANALİZİ" in report
    assert "BORSA VERİ / PAPER FILL KANITI" in report
    assert len(list((tmp_path / "reports").glob("oturum_analizi_*.json"))) == 1
    assert len(list((tmp_path / "reports").glob("islem_gecmisi_*.json"))) == 1
    store = StateStore(tmp_path / "session.db")
    session = store.get_meta("paper_24h_session", {})
    assert session["report_sent"] is True
    assert session["report_delivered"] is True
    assert session["start_balance"] == 100_000.0
    assert session["entries"] == 0
