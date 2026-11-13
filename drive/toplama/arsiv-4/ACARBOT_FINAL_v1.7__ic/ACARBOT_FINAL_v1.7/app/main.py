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
    parser.add_argument(
        "--min-rvol", type=float, default=None,
        help="5m mum RVOL giriş eşiği (vars. 1.5); düşürmek daha çok sinyal "
             "üretir, ör. 1.2",
    )
    parser.add_argument(
        "--fade-impulse", type=float, default=None,
        help="FADE 10dk impuls eşiği %% (vars. 0.35); ör. 0.25",
    )
    parser.add_argument(
        "--spike-multiplier", type=float, default=None,
        help="canlı hacim patlaması çarpanı (vars. 3.0); ör. 2.5",
    )
    parser.add_argument(
        "--motors", choices=("both", "trend", "fade"), default="both",
        help="aktif sinyal motorları: both (varsayılan), trend (FADE kapalı), "
             "fade (TREND kapalı)",
    )
    parser.add_argument(
        "--scan-all", action="store_true",
        help="TÜM USDT coinlerini tara (Binance 500+ / OKX 500+); "
             "--symbols yok sayılır, coin listesi borsadan otomatik keşfedilir",
    )
    parser.add_argument(
        "--scan-cycle-seconds", type=float, default=60.0,
        help="tam tarama döngüsü hedefi (sn, vars. 60); yalnız --scan-all ile etkili",
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
    # FINAL v1.3: sinyal eşikleri CLI'dan ayarlanabilir (varsayılanlar korunur)
    signal_overrides = {}
    if args.min_rvol is not None:
        if args.min_rvol <= 0:
            raise ValueError("--min-rvol pozitif olmalı")
        signal_overrides["min_rvol_for_entry"] = args.min_rvol
    if args.fade_impulse is not None:
        if args.fade_impulse <= 0:
            raise ValueError("--fade-impulse pozitif olmalı")
        signal_overrides["fade_impulse_pct"] = args.fade_impulse
    if args.spike_multiplier is not None:
        if args.spike_multiplier <= 1:
            raise ValueError("--spike-multiplier 1'den büyük olmalı")
        signal_overrides["spike_multiplier"] = args.spike_multiplier
    if signal_overrides:
        config.signal = _dc_replace(config.signal, **signal_overrides)
    # FINAL v1.4: motor seçimi
    motors_map = {
        "both": ("fade", "trend"),
        "trend": ("trend",),
        "fade": ("fade",),
    }
    config.signal = _dc_replace(
        config.signal, enabled_motors=motors_map[args.motors],
    )
    # FINAL v1.5: tam pazar veri bütünlüğü kuralları
    if getattr(args, "scan_all", False):
        config.data = _dc_replace(config.data, full_market=True)
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

        # FINAL v1.5: ortak borsa istemcileri + coin evreni
        from infra.exchanges.binance import BinancePublic
        from infra.exchanges.okx import OKXPublic
        from infra.symbol_universe import discover
        _registry = {"binance": BinancePublic, "okx": OKXPublic}
        market_clients = {n: _registry[n]() for n in names if n in _registry}
        if args.scan_all:
            universe: dict[str, list[str]] = {}
            for n, client in market_clients.items():
                universe[n] = await asyncio.to_thread(discover, n, client)
            # Sweep koruması tam taramada isteğe bağlı çalışır: giriş adayı
            # sembolün defteri sinyal anında tazelenir (1000+ defteri sürekli
            # çekmek rate limitlerine sığmaz).
            def _sweep_book_fetcher(key: str) -> None:
                if sweep_guard is None:
                    return
                ex_name, _, ex_symbol = key.partition(":")
                client = market_clients.get(ex_name)
                if client is None:
                    return
                book = client.fetch_order_book(ex_symbol, config.sweep.book_levels)
                now = int(datetime.now(timezone.utc).timestamp() * 1000)
                sweep_guard.update_book(key, book.bids, book.asks, now)
            executor.book_fetcher = _sweep_book_fetcher
            logger.info(
                "TAM PAZAR TARAMASI: %s | toplam %d feed | döngü hedefi %.0f sn",
                " + ".join(f"{n}={len(s)}" for n, s in universe.items()),
                sum(len(s) for s in universe.values()),
                args.scan_cycle_seconds,
            )
        else:
            symbols_raw = [
                s.strip().upper() for s in args.symbols.split(",") if s.strip()
            ]
            universe = {n: _symbols_for(n, symbols_raw) for n in names}
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
        logger.info(
            "Sinyal eşikleri: RVOL≥%.2f | FADE impuls≥%.2f%% | spike≥%.1fx",
            config.signal.min_rvol_for_entry,
            config.signal.fade_impulse_pct,
            config.signal.spike_multiplier,
        )
        logger.info(
            "Aktif motorlar: %s", "+".join(m.upper() for m in config.signal.enabled_motors),
        )
        if args.duration_minutes and args.duration_minutes > 0:
            logger.info(
                "Süreli oturum: %.1f dakika sonra otomatik kapanacak ve rapor yazılacak",
                args.duration_minutes,
            )

        stop_event = asyncio.Event()

        async def candle_refresher() -> None:
            """FINAL v1.5: paralel mum taraması + tek iş parçacıklı değerlendirme.

            Tüm semboller her döngüde tazelenir (tam pazar ~60 sn, dar liste
            ~5 sn). Değerlendirme kuyruğu tek tüketiciyle işler → executor
            paylaşılan durumu için yarış yoktur. Aynı kapanmış mum iki kez
            değerlendirilmez (last_closed damgası).
            """
            timeframe = config.data.timeframe
            sems = {
                n: asyncio.Semaphore(10 if n == "binance" else 4)
                for n in market_clients
            }

            class _Pacer:
                """Saniyelik istek hızı sınırlayıcı (rate limit koruması)."""

                def __init__(self, rate_per_sec: float) -> None:
                    self.interval = 1.0 / rate_per_sec
                    self.lock = asyncio.Lock()
                    self.next_at = 0.0

                async def wait(self) -> None:
                    async with self.lock:
                        now = loop.time()
                        delay = self.next_at - now
                        if delay > 0:
                            await asyncio.sleep(delay)
                        self.next_at = max(now, self.next_at) + self.interval

            # Binance ayna: 6000 weight/dk (klines=2) → 25 istek/sn güvenli.
            # OKX: /market/candles 20 istek/2sn → 8 istek/sn güvenli pay.
            pacers = {
                n: _Pacer(25.0 if n == "binance" else 8.0)
                for n in market_clients
            }
            work = [(n, s) for n in market_clients for s in universe.get(n, [])]
            cycle_target = args.scan_cycle_seconds if args.scan_all else 5.0
            eval_queue: asyncio.Queue = asyncio.Queue()
            last_closed: dict[str, int] = {}

            async def evaluator() -> None:
                while True:
                    key, candles = await eval_queue.get()
                    try:
                        executor.update_candles(key, candles)
                        last = candles[-2] if len(candles) > 1 else candles[-1]
                        if last_closed.get(key) != last.timestamp:
                            last_closed[key] = last.timestamp
                            # v1.6: değerlendirme ANA event loop'ta çalışır
                            # (SQLite bağlantısı ana thread'de; v1.5'teki
                            # to_thread çağrısı thread hatası yaratıyordu).
                            # Tek tüketici kuyruğu zaten sıralı erişim sağlar.
                            events = executor.on_candle_closed(key, last)
                            await _report_events(alerts, events)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("değerlendirme hatası [%s]: %s", key, exc)
                    finally:
                        eval_queue.task_done()

            async def fetch_one(name: str, symbol: str) -> None:
                key = f"{name}:{symbol}"
                async with sems[name]:
                    await pacers[name].wait()
                    try:
                        candles = await asyncio.to_thread(
                            market_clients[name].fetch_candles,
                            symbol, timeframe, config.data.candle_history,
                        )
                        if candles:
                            await eval_queue.put((key, candles))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("mum yenileme hatası [%s]: %s", key, exc)

            eval_task = asyncio.create_task(evaluator())
            try:
                while not stop_event.is_set():
                    cycle_start = loop.time()
                    await asyncio.gather(*(fetch_one(n, s) for n, s in work))
                    await eval_queue.join()
                    elapsed = loop.time() - cycle_start
                    metrics.inc("full_scan_cycles")
                    if args.scan_all:
                        logger.info(
                            "TAM TARAMA: %d sembol, %.1f sn (hedef %.0f sn)",
                            len(work), elapsed, cycle_target,
                        )
                    await asyncio.sleep(max(1.0, cycle_target - elapsed))
            except asyncio.CancelledError:
                raise
            finally:
                eval_task.cancel()

        async def ticker_consumer() -> None:
            """Borsa ticker akışlarını tüketir: dolum/çıkış/kill switch."""
            tasks = []
            for name, exchange in market_clients.items():
                tasks.append(asyncio.create_task(
                    _stream_one(name, exchange, args, executor, alerts, metrics,
                                universe.get(name, [])),
                ))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        async def guards_refresher() -> None:
            """FINAL v1.1: haber takvimi + orderbook duvar taraması.

            v1.5 tam pazar modunda toplu defter taraması KAPALI: 1000+
            sembolün defterini periyodik çekmek rate limitlerine sığmaz.
            Bunun yerine giriş adayı sembolün defteri sinyal anında
            executor.book_fetcher ile tazelenir (isteğe bağlı koruma).
            """
            exchanges = market_clients
            last_books_ms = 0
            while not stop_event.is_set():
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                if news_guard is not None:
                    try:
                        await asyncio.to_thread(news_guard.refresh, now_ms)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Haber takvimi görevi hatası: %s", exc)
                if not args.scan_all and sweep_guard is not None and (
                    now_ms - last_books_ms >= config.sweep.refresh_seconds * 1000
                ):
                    last_books_ms = now_ms
                    for name, exchange in exchanges.items():
                        for symbol in universe.get(name, []):
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
                    session_start_ms, start_balance, universe=universe,
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
    universe: dict[str, list[str]] | None = None,
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
    signal_cfg = getattr(getattr(executor, "config", None), "signal", None)
    signal_thresholds = {
        "min_rvol_for_entry": getattr(signal_cfg, "min_rvol_for_entry", None),
        "fade_impulse_pct": getattr(signal_cfg, "fade_impulse_pct", None),
        "spike_multiplier": getattr(signal_cfg, "spike_multiplier", None),
        "enabled_motors": list(getattr(signal_cfg, "enabled_motors", ())),
    } if signal_cfg is not None else {}
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
        "signal_thresholds": signal_thresholds,
        "started_at_utc": datetime.fromtimestamp(
            session_start_ms / 1000, tz=timezone.utc,
        ).isoformat(),
        "ended_at_utc": datetime.fromtimestamp(
            now_ms / 1000, tz=timezone.utc,
        ).isoformat(),
        "duration_seconds": round((now_ms - session_start_ms) / 1000.0, 1),
        "exchange": args.exchange,
        "scan_all": bool(getattr(args, "scan_all", False)),
        "universe_sizes": (
            {n: len(s) for n, s in universe.items()} if universe else {}
        ),
        "symbols": (
            "ALL-USDT" if getattr(args, "scan_all", False) else args.symbols
        ),
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


async def _stream_one(name, exchange, args, executor, alerts, metrics,
                      symbols: list[str]) -> None:
    try:
        if args.scan_all:
            # v1.5: evren zaten borsadan keşfedildi; ekstra meta çağrısı yok.
            stream_symbols = list(symbols)
        else:
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
                base_volume_24h=ticker.base_volume_24h,
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


def _symbols_for(exchange_name: str, symbols: list[str]) -> list[str]:
    """FINAL v1.2: tek sembol listesini borsa biçimine çevirir.

    BTCUSDT ↔ BTC-USDT-SWAP dönüşümü sayesinde --exchange all modunda
    her iki borsa aynı listeden doğru enstrümanı izler.
    """
    out: list[str] = []
    for raw in symbols:
        s = raw.strip().upper()
        if not s:
            continue
        if exchange_name == "binance":
            s = s.replace("-", "").replace("_", "")
            if s.endswith("SWAP"):
                s = s[:-4]
        elif exchange_name == "okx":
            if "-" not in s:
                for quote in ("USDT", "USDC"):
                    if s.endswith(quote) and len(s) > len(quote):
                        s = f"{s[:-len(quote)]}-{quote}-SWAP"
                        break
        if s not in out:
            out.append(s)
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    if args.mode == "backtest":
        return run_backtest(args)
    return asyncio.run(run_paper(args))


if __name__ == "__main__":
    raise SystemExit(main())
