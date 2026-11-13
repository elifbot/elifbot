"""ACARBOT FINAL v1.0 CLI — yalnızca paper trading; gerçek emir GÖNDERİLMEZ.

FINAL eklemeleri (süper sürüm tabanı üzerine):
  - --duration-minutes: süreli oturum (ör. 15 dk test), sonunda otomatik kapanış
  - --report-file: oturum sonunda JSON oturum raporu
  - Sürüm bilgisi ve başlangıç afişi

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

from app import __version__
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
    parser.add_argument(
        "--max-positions", type=int, default=None,
        help="0 = SINIRSIZ (bakiye/teminat sınırlar); verilmezse profil varsayılanı",
    )
    parser.add_argument(
        "--profile", choices=("guarded", "apex"), default="guarded",
        help="guarded: 6 pozisyon + günlük fren (varsayılan). "
             "apex: APEX v1.1 profili — sınırsız pozisyon, günlük fren yok, "
             "portföy tavanları kapalı; teminat + 25 USDT net risk korunur",
    )
    parser.add_argument(
        "--no-daily-brake", action="store_true",
        help="günlük zarar soft/hard frenini kapat (profilden bağımsız)",
    )
    parser.add_argument(
        "--no-news-guard", action="store_true",
        help="makro haber korumasını kapat (varsayılan: açık)",
    )
    parser.add_argument(
        "--no-sweep-guard", action="store_true",
        help="stop-hunt duvar korumasını kapat (varsayılan: açık)",
    )
    parser.add_argument(
        "--news-buffer-minutes", type=float, default=None,
        help="haber olayı öncesi/sonrası giriş yasağı penceresi (vars. 30)",
    )
    parser.add_argument("--data-dir", default="data",
                        help="backtest mum CSV'leri: <SYMBOL>_5m.csv")
    parser.add_argument("--warmup-seconds", type=float, default=90.0)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--duration-minutes", type=float, default=0.0,
        help="0 = süresiz (Ctrl+C ile kapanır); >0 ise bu kadar dakika sonra "
             "oturum kendiliğinden kapanır ve rapor yazılır (ör. 15)",
    )
    parser.add_argument(
        "--report-file", default="session_report.json",
        help="oturum sonunda yazılacak JSON rapor dosyası",
    )
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
    config = apply_profile(args, SuperConfig())
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
        max_positions=(
            args.max_positions if args.max_positions is not None
            else config.portfolio.max_positions
        ),
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

def apply_profile(args: argparse.Namespace, config: SuperConfig) -> SuperConfig:
    """FINAL v1.1: profil + CLI overrides (CLI her zaman profile baskın)."""
    from dataclasses import replace as _dc_replace
    if args.profile == "apex":
        # APEX v1.1 profili: pozisyon adedi sınırsız, günlük fren yok,
        # portföy tavanları kapalı. Doğal sınır: serbest bakiye/teminat.
        # Korunanlar: pozisyon başı 25 USDT NET risk, teminat yeterliliği,
        # drawdown koruması, likidasyon modeli, haber + sweep kapıları.
        config.portfolio = _dc_replace(
            config.portfolio,
            max_positions=0,
            max_positions_per_group=0,
            max_group_notional=0.0,
            gross_notional_cap=0.0,
            net_directional_notional_cap=0.0,
            total_open_risk_cap=0.0,
            daily_soft_loss=0.0,
            daily_hard_loss=0.0,
        )
    if args.max_positions is not None:
        if args.max_positions < 0:
            raise ValueError("--max-positions negatif olamaz (0 = sınırsız)")
        config.portfolio = _dc_replace(
            config.portfolio, max_positions=args.max_positions,
        )
    if args.no_daily_brake:
        config.portfolio = _dc_replace(
            config.portfolio, daily_soft_loss=0.0, daily_hard_loss=0.0,
        )
    if args.warmup_seconds is not None and args.warmup_seconds >= 0:
        config.data = _dc_replace(
            config.data, warmup_seconds=args.warmup_seconds,
        )
    news_overrides = {}
    if args.no_news_guard:
        news_overrides["enabled"] = False
    if args.news_buffer_minutes is not None:
        if args.news_buffer_minutes < 0:
            raise ValueError("--news-buffer-minutes negatif olamaz")
        news_overrides["buffer_minutes"] = args.news_buffer_minutes
    if news_overrides:
        config.news = _dc_replace(config.news, **news_overrides)
    if args.no_sweep_guard:
        config.sweep = _dc_replace(config.sweep, enabled=False)
    return config


async def run_paper(args: argparse.Namespace) -> int:
    if not args.paper:
        raise ValueError("yalnızca --paper modu mevcut")
    config = apply_profile(args, SuperConfig())
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
        # FINAL v1.1 korumaları
        from core.sweep_guard import SweepGuard
        from safety.news_guard import NewsGuard
        news_guard = NewsGuard(config.news) if config.news.enabled else None
        sweep_guard = SweepGuard(config.sweep) if config.sweep.enabled else None
        executor = Executor(
            broker, risk, config, store, integrity,
            news_guard=news_guard, sweep_guard=sweep_guard,
        )
        executor.restore_state()
        reporter = PerformanceReporter(store)
        metrics = SimpleMetrics()

        names = _selected_exchanges(args.exchange)
        session_start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_balance = broker.portfolio.balance
        max_pos_text = (
            "SINIRSIZ" if config.portfolio.max_positions <= 0
            else str(config.portfolio.max_positions)
        )
        logger.info(
            "ACARBOT FINAL v%s | PAPER mod | borsa=%s | bakiye=%.2f | maks pozisyon=%s",
            __version__, ",".join(names), broker.portfolio.balance, max_pos_text,
        )
        if args.profile == "apex":
            logger.info(
                "PROFİL: APEX v1.1 — sınırsız pozisyon (bakiye/teminat sınırlar), "
                "günlük fren KAPALI, portföy tavanları kapalı; "
                "pozisyon başı %.0f USDT net risk tavanı AKTİF",
                config.account.max_loss_per_position,
            )
        if config.portfolio.daily_soft_loss <= 0 and config.portfolio.daily_hard_loss <= 0:
            logger.info("Günlük zarar freni: KAPALI")
        logger.info(
            "Korumalar: haber=%s | sweep=%s",
            "AÇIK" if news_guard else "kapalı",
            "AÇIK" if sweep_guard else "kapalı",
        )
        if args.duration_minutes and args.duration_minutes > 0:
            logger.info(
                "Süreli oturum: %.1f dakika sonra otomatik kapanacak ve rapor yazılacak",
                args.duration_minutes,
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

        async def guards_refresher() -> None:
            """FINAL v1.1: haber takvimi + orderbook duvar taraması."""
            from infra.exchanges.binance import BinancePublic
            from infra.exchanges.okx import OKXPublic
            registry = {"binance": BinancePublic, "okx": OKXPublic}
            exchanges = {n: registry[n]() for n in names if n in registry}
            symbols = [
                s.strip().upper() for s in args.symbols.split(",") if s.strip()
            ]
            last_books_ms = 0
            while not stop_event.is_set():
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                if news_guard is not None:
                    try:
                        await asyncio.to_thread(news_guard.refresh, now_ms)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Haber takvimi görevi hatası: %s", exc)
                if sweep_guard is not None and (
                    now_ms - last_books_ms >= config.sweep.refresh_seconds * 1000
                ):
                    last_books_ms = now_ms
                    for name, exchange in exchanges.items():
                        for symbol in symbols:
                            if stop_event.is_set():
                                break
                            key = f"{name}:{symbol}"
                            try:
                                book = await asyncio.to_thread(
                                    exchange.fetch_order_book,
                                    symbol, config.sweep.book_levels,
                                )
                                sweep_guard.update_book(
                                    key, book.bids, book.asks, now_ms,
                                )
                                metrics.inc("sweep_books_updated")
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "defter alınamadı [%s]: %s", key, exc,
                                )
                            await asyncio.sleep(0.2)  # rate limit nazikliği
                await asyncio.sleep(1.0)

        candle_task = asyncio.create_task(candle_refresher())
        ticker_task = asyncio.create_task(ticker_consumer())
        daily_task = asyncio.create_task(
            _daily_reporter(reporter, executor, alerts, metrics, stop_event),
        )
        guards_task = asyncio.create_task(guards_refresher())

        try:
            if args.duration_minutes and args.duration_minutes > 0:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=args.duration_minutes * 60.0,
                    )
                except asyncio.TimeoutError:
                    logger.info(
                        "Süre doldu (%.1f dk) — oturum kapatılıyor",
                        args.duration_minutes,
                    )
            else:
                await asyncio.Event().wait()  # sonsuz; Ctrl+C ile kesilir
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Kapanış sinyali alındı")
        finally:
            stop_event.set()
            for task in (candle_task, ticker_task, daily_task, guards_task):
                task.cancel()
            await alerts.stop()
            # Son durumu kalıcılaştır
            store.save_state(executor.snapshot())
            # FINAL: oturum sonu raporu (log + JSON dosyası)
            try:
                write_session_report(
                    args, executor, reporter, metrics,
                    session_start_ms, start_balance,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Oturum raporu yazılamadı: %s", exc)
    return 0


def write_session_report(
    args: argparse.Namespace,
    executor,
    reporter: PerformanceReporter,
    metrics: SimpleMetrics,
    session_start_ms: int,
    start_balance: float,
) -> dict:
    """Oturum kapanışında özet: PnL, işlem sayıları, sayaçlar, risk durumu."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    prices = executor._latest_prices
    equity = executor.broker.mark_to_market(prices)
    unrealized = executor.broker.portfolio.unrealized_pnl(prices)
    session_trades = [
        t for t in executor.broker.trades
        if isinstance(t.get("timestamp"), (int, float))
        and t["timestamp"] >= session_start_ms
    ]
    closes = [t for t in session_trades if t.get("type") == "CLOSE"]
    realized = sum(float(t.get("pnl", 0.0)) for t in closes)
    guards_status = {}
    news_guard = getattr(executor, "news_guard", None)
    sweep_guard = getattr(executor, "sweep_guard", None)
    if news_guard is not None:
        guards_status["news"] = news_guard.status()
    if sweep_guard is not None:
        guards_status["sweep"] = sweep_guard.status()
    portfolio_cfg = getattr(getattr(executor, "config", None), "portfolio", None)
    max_positions_cfg = getattr(portfolio_cfg, "max_positions", None)
    daily_soft = getattr(portfolio_cfg, "daily_soft_loss", None)
    daily_hard = getattr(portfolio_cfg, "daily_hard_loss", None)
    report = {
        "version": __version__,
        "mode": "paper",
        "profile": getattr(args, "profile", "guarded"),
        "max_positions": (
            "unlimited" if max_positions_cfg is not None and max_positions_cfg <= 0
            else max_positions_cfg
        ),
        "daily_brake": (
            "off" if daily_soft is not None and daily_soft <= 0
            and daily_hard is not None and daily_hard <= 0 else "on"
        ),
        "guards": guards_status,
        "started_at_utc": datetime.fromtimestamp(
            session_start_ms / 1000, tz=timezone.utc,
        ).isoformat(),
        "ended_at_utc": datetime.fromtimestamp(
            now_ms / 1000, tz=timezone.utc,
        ).isoformat(),
        "duration_seconds": round((now_ms - session_start_ms) / 1000.0, 1),
        "exchange": args.exchange,
        "symbols": args.symbols,
        "start_balance": round(start_balance, 4),
        "end_balance": round(executor.broker.portfolio.balance, 4),
        "end_equity": round(equity, 4),
        "realized_pnl_session": round(realized, 4),
        "unrealized_pnl": round(unrealized, 4),
        "entries": sum(1 for t in session_trades if t.get("type") == "OPEN"),
        "closes": len(closes),
        "open_positions": len(executor.broker.portfolio.positions),
        "kill_switch": executor.risk.kill_switch_state.value,
        "safe_mode": bool(executor.data_integrity.safe_mode),
        "counters": dict(metrics.counters),
    }
    text = reporter.daily_report(
        equity=equity,
        unrealized_pnl=unrealized,
        open_positions=report["open_positions"],
        kill_switch_state=report["kill_switch"],
        safe_mode=report["safe_mode"],
        session_trades=session_trades,
    )
    logger.info(
        "OTURUM RAPORU | süre=%.1f sn | bakiye %.2f → %.2f | equity %.2f\n%s",
        report["duration_seconds"], start_balance,
        report["end_balance"], equity, text,
    )
    path = Path(args.report_file)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("Oturum raporu yazıldı: %s", path)
    return report


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
