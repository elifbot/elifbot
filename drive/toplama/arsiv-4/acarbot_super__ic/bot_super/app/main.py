"""Süper sürüm CLI — yalnızca paper trading; gerçek emir GÖNDERİLMEZ.

Canlı akış:
  - Borsa WS ticker akışları (yeniden bağlanma + üstel geri çekilme)
  - Saniyelik spike dedektörü (birim-tutarlı RVOL)
  - Emir yaşam döngüsü ile paper girişler
  - Kill switch + güvenli mod + günlük rapor
Backtest:
  - --mode backtest: CSV/JSON mum verisiyle çoklu sembol simülasyonu
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.executor import Executor
from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics, format_metrics_report
from core.config import SuperConfig
from core.risk import KillSwitchState, RiskManager
from exec.paper import PaperBroker
from infra.feed import DataIntegrityManager
from infra.market_data.models import Candle
from monitor.report import PerformanceReporter, SimpleMetrics, utc_midnight_ms
from safety.alerts import AlertManager, TelegramNotifier
from state.store import StateStore

logger = logging.getLogger("paper_bot")

_EXCHANGES = {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Public-data paper trading bot (süper sürüm)",
    )
    parser.add_argument(
        "--mode", choices=("paper", "backtest"), default="paper",
    )
    parser.add_argument(
        "--paper", action="store_true", required=("--mode backtest" not in " ".join(sys.argv)),
        help="zorunlu onay: yalnızca simüle edilmiş emirler",
    )
    parser.add_argument("--exchange", default="binance",
                        choices=("binance", "okx", "all", "binance+okx"))
    parser.add_argument("--symbols", default="BTCUSDT",
                        help="virgülle ayrılmış semboller, örn. BTCUSDT,ETHUSDT")
    parser.add_argument("--balance", type=float, default=1_000.0)
    parser.add_argument("--state", default="paper_state.sqlite3")
    parser.add_argument("--max-positions", type=int, default=6)
    parser.add_argument("--data-dir", default="data",
                        help="backtest mum CSV'leri: <SYMBOL>_5m.csv")
    parser.add_argument("--warmup-seconds", type=float, default=90.0)
    parser.add_argument("--log-level", default="INFO")
    return parser


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    file_handler = logging.FileHandler("paper_bot.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(handler)
    root.addHandler(file_handler)


# ---------------------------------------------------------------------------
# Backtest modu
# ---------------------------------------------------------------------------

def _load_candles_csv(path: Path) -> list[Candle]:
    candles: list[Candle] = []
    with open(path, encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
        idx = {name: i for i, name in enumerate(header)}
        for line in handle:
            parts = line.strip().split(",")
            if len(parts) < len(header):
                continue
            candles.append(Candle(
                timestamp=int(float(parts[idx["timestamp"]])),
                open=float(parts[idx["open"]]),
                high=float(parts[idx["high"]]),
                low=float(parts[idx["low"]]),
                close=float(parts[idx["close"]]),
                volume=float(parts[idx["volume"]]),
            ))
    return candles


def run_backtest(args: argparse.Namespace) -> int:
    config = SuperConfig()
    data_dir = Path(args.data_dir)
    files = sorted(data_dir.glob("*_5m.csv"))
    if not files:
        files = sorted(data_dir.glob("*.csv"))
    if not files:
        logger.error("Backtest verisi yok: %s altında CSV bulunamadı", data_dir)
        return 1
    candles_by_symbol = {}
    for path in files:
        symbol = path.stem.replace("_5m", "").upper()
        candles_by_symbol[symbol] = _load_candles_csv(path)
        logger.info("Yüklendi: %s → %d mum", symbol, len(candles_by_symbol[symbol]))
    engine = BacktestEngine(
        config=config,
        initial_balance=args.balance,
        max_positions=args.max_positions,
    )
    result = engine.run(candles_by_symbol)
    metrics = compute_metrics(
        list(result.trades), args.balance, result.final_balance,
        result.equity_curve,
    )
    report = format_metrics_report(metrics, "BACKTEST (çoklu sembol)")
    print(report)
    print(f"Red kodları: {dict(sorted(result.rejection_counts.items(), key=lambda kv: -kv[1]))}")
    print(f"Dolmayan emir: {result.expired_orders} | Kısmi dolum: {result.partial_fills}")
    out = Path("backtest_result.json")
    out.write_text(json.dumps({
        "metrics": metrics.as_dict(),
        "rejection_counts": result.rejection_counts,
        "expired_orders": result.expired_orders,
        "partial_fills": result.partial_fills,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Sonuç dosyası: %s", out)
    return 0


# ---------------------------------------------------------------------------
# Paper (canlı veri) modu
# ---------------------------------------------------------------------------

async def run_paper(args: argparse.Namespace) -> int:
    if not args.paper:
        raise ValueError("yalnızca --paper modu mevcut")
    config = SuperConfig()
    loop = asyncio.get_running_loop()

    telegram = TelegramNotifier.from_environment()
    alerts = AlertManager(
        telegram=telegram,
        rate_limit_per_min=config.ops.telegram_rate_limit_per_min,
    )
    alerts.attach_loop(loop)

    with StateStore(args.state, config.ops) as store:
        if config.ops.backup_on_start:
            try:
                backup = store.backup()
                store.rotate_backups(config.ops.backup_keep)
                logger.info("Başlangıç yedeği: %s", backup)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Yedekleme başarısız (devam): %s", exc)

        broker = PaperBroker(config, args.balance)
        risk = RiskManager(config)
        integrity = DataIntegrityManager(config.data)
        executor = Executor(broker, risk, config, store, integrity)
        executor.restore_state()
        reporter = PerformanceReporter(store)
        metrics = SimpleMetrics()

        names = _selected_exchanges(args.exchange)
        logger.info(
            "PAPER mod | borsa=%s | bakiye=%.2f | maks pozisyon=%d",
            ",".join(names), broker.portfolio.balance,
            config.portfolio.max_positions,
        )

        stop_event = asyncio.Event()

        async def candle_refresher() -> None:
            """Her 5m kapanışında mumları yeniler ve sinyalleri değerlendirir."""
            from infra.exchanges.binance import BinancePublic
            from infra.exchanges.okx import OKXPublic
            registry = {"binance": BinancePublic, "okx": OKXPublic}
            exchanges = {n: registry[n]() for n in names if n in registry}
            symbols = [
                s.strip().upper() for s in args.symbols.split(",") if s.strip()
            ]
            timeframe = config.data.timeframe
            while not stop_event.is_set():
                try:
                    for name, exchange in exchanges.items():
                        for symbol in symbols:
                            key = f"{name}:{symbol}"
                            try:
                                candles = await asyncio.to_thread(
                                    exchange.fetch_candles,
                                    symbol, timeframe, config.data.candle_history,
                                )
                                if not candles:
                                    continue
                                executor.update_candles(key, candles)
                                last = candles[-2] if len(candles) > 1 else candles[-1]
                                events = executor.on_candle_closed(key, last)
                                await _report_events(alerts, events)
                                await asyncio.sleep(0.2)  # rate limit nazikliği
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "mum yenileme hatası [%s]: %s", key, exc,
                                )
                    await asyncio.sleep(5.0)
                except asyncio.CancelledError:
                    raise

        async def ticker_consumer() -> None:
            """Borsa ticker akışlarını tüketir: dolum/çıkış/kill switch."""
            from infra.exchanges.binance import BinancePublic
            from infra.exchanges.okx import OKXPublic
            registry = {"binance": BinancePublic, "okx": OKXPublic}
            markets_by_name: dict[str, dict[str, object]] = {}
            for name in names:
                if name not in registry:
                    continue
                exchange = registry[name]()
                markets_by_name[name] = exchange
            tasks = []
            for name, exchange in markets_by_name.items():
                tasks.append(asyncio.create_task(
                    _stream_one(name, exchange, args, executor, alerts, metrics),
                ))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        candle_task = asyncio.create_task(candle_refresher())
        ticker_task = asyncio.create_task(ticker_consumer())
        daily_task = asyncio.create_task(
            _daily_reporter(reporter, executor, alerts, metrics, stop_event),
        )

        try:
            await asyncio.Event().wait()  # sonsuz; Ctrl+C ile kesilir
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Kapanış sinyali alındı")
        finally:
            stop_event.set()
            for task in (candle_task, ticker_task, daily_task):
                task.cancel()
            await alerts.stop()
            # Son durumu kalıcılaştır
            store.save_state(executor.snapshot())
    return 0


async def _stream_one(name, exchange, args, executor, alerts, metrics) -> None:
    symbols = [
        s.strip().upper() for s in args.symbols.split(",") if s.strip()
    ]
    try:
        markets = await asyncio.to_thread(
            exchange.fetch_top_usdt_futures, 10_000,
        )
        symbol_set = set(symbols)
        stream_symbols = [
            m.symbol for m in markets
            if m.symbol in symbol_set or m.base_asset in symbol_set
        ] or symbols
        async for ticker in exchange.stream_tickers_reconnecting(
            tuple(stream_symbols),
            on_error=lambda exc: alerts.notify(
                f"{name} ticker akışı yeniden bağlanıyor: {exc}", "error",
            ),
        ):
            key = f"{name}:{ticker.symbol.upper()}"
            events = executor.process_price_update(
                key, ticker.last_price, ticker.timestamp_ms,
                volume_24h_quote=ticker.quote_volume_24h,
                exchange=name,
            )
            await _report_events(alerts, events)
            metrics.inc("ticks_total")
            executor.persist_if_due(ticker.timestamp_ms)
    except Exception as exc:  # noqa: BLE001
        alerts.notify(f"{name} akış hatası: {exc}", "error")


async def _report_events(alerts: AlertManager, events: list[dict]) -> None:
    for event in events:
        etype = event.get("type", "")
        if etype in {"ENTRY_FILLED", "OPEN", "PARTIAL_CLOSE", "CLOSE"}:
            alerts.notify_event(str(event))
        elif etype in {"MARGIN_WARNING", "GAP_BLOCKED", "FUNDING"}:
            alerts.notify(str(event), "warning")
        elif etype in {"liquidation"}:
            alerts.notify(str(event), "critical")


async def _daily_reporter(reporter, executor, alerts, metrics, stop_event) -> None:
    """UTC günü değişince günlük rapor + soft-stop reseti."""
    current_day = utc_midnight_ms()
    while not stop_event.is_set():
        await asyncio.sleep(30)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        today = utc_midnight_ms()
        if today != current_day:
            current_day = today
            equity = executor.broker.mark_to_market(executor._latest_prices)
            unrealized = executor.broker.portfolio.unrealized_pnl(
                executor._latest_prices
            )
            report = reporter.daily_report(
                equity=equity,
                unrealized_pnl=unrealized,
                open_positions=len(executor.broker.portfolio.positions),
                kill_switch_state=executor.risk.kill_switch_state.value,
                safe_mode=executor.data_integrity.safe_mode,
            )
            alerts.notify_event(report)
            executor.risk.reset_daily()
            store = executor.store
            if store is not None:
                store.append_equity_point(now_ms, equity, 0.0)


def _selected_exchanges(value: str) -> list[str]:
    if value in {"all", "binance+okx"}:
        return ["binance", "okx"]
    return [value]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    if args.mode == "backtest":
        return run_backtest(args)
    return asyncio.run(run_paper(args))


if __name__ == "__main__":
    raise SystemExit(main())
