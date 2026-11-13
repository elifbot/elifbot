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
from logging.handlers import RotatingFileHandler
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import __version__
from app.executor import Executor
from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics, format_metrics_report, regime_breakdown
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
        help="v3.1: 5m mum RVOL giriş eşiği (vars. 1.5); düşürmek daha çok "
             "sinyal üretir, ör. 1.2",
    )
    parser.add_argument(
        "--fade-impulse", type=float, default=None,
        help="v3.1: FADE 10dk impuls eşiği %% (vars. 0.35); ör. 0.25",
    )
    parser.add_argument(
        "--spike-multiplier", type=float, default=None,
        help="v3.1: canlı hacim patlaması çarpanı (vars. 3.0); ör. 2.5",
    )
    parser.add_argument(
        "--motors", choices=("both", "trend", "fade"), default="both",
        help="v3.1: aktif sinyal motorları — both (varsayılan), trend "
             "(FADE kapalı), fade (TREND kapalı); kapalı motor hiç "
             "değerlendirilmez (canlı + backtest aynı kural)",
    )
    parser.add_argument(
        "--scan-all", action="store_true",
        help="v3.1: TÜM USDT coinlerini tara (Binance 500+ / OKX 500+, "
             "hacimsel sıralı evren borsadan keşfedilir); --symbols yok "
             "sayılır; paralel tarama + rate pacer + OKX WS parçalama",
    )
    parser.add_argument(
        "--scan-cycle-seconds", type=float, default=60.0,
        help="v3.1: tam tarama döngüsü hedefi (sn, vars. 60); yalnız "
             "--scan-all ile etkili",
    )
    parser.add_argument(
        "--strategy", default=None,
        choices=("classic", "confluence", "rsirev", "macd", "bollkir",
                 "bolldon"),
        help="v4.0: sinyal stratejisi — classic (v1.2 FADE/TREND, vars.), "
             "confluence (10 filtre oylama), rsirev, macd, bollkir, bolldon",
    )
    parser.add_argument(
        "--confluence-threshold", type=float, default=None,
        help="v4.0: confluence 10 filtre oylama eşiği 0-1 (vars. 0.6)",
    )
    parser.add_argument(
        "--session", default=None,
        help='v4.0: seans (saat) filtresi — off | asia | eu | us | "HH-HH" '
             '(UTC aralığı); kapalı pencerede yeni giriş yok',
    )
    parser.add_argument(
        "--dca", action="store_true",
        help="v4.0: DCA güvenlik emirlerini AÇ (vars. kapalı; yalnız LONG; "
             "2 güvenlik emri, %1 adım, adım 1.5x — config DcaConfig)",
    )
    parser.add_argument(
        "--us-market", default=None, choices=("off", "flag", "block"),
        help="v4.0: ABD piyasası ajanı (SPX/Nasdaq/DXY/VIX) — flag (vars. "
             "yalnız bayrak) | block (risk_off'ta yeni giriş yok) | off",
    )
    parser.add_argument(
        "--news-rss", default=None, choices=("off", "flag", "block"),
        help="v4.0: RSS haber ajanı — flag (vars. yalnız bayrak) | block "
             "(risk bayrağı aktifken yeni giriş yok) | off",
    )
    parser.add_argument(
        "--live-entry-style", default=None,
        choices=("post_only", "post_only_market_fallback", "market"),
        help="v4.0: canlı eşleme giriş tipi — post_only (saf maker), "
             "post_only_market_fallback (vars.; dolum süresi/reddi halinde "
             "MARKET yedek), market (v3.0 davranışı)",
    )
    parser.add_argument(
        "--position-mode", default=None,
        choices=("auto", "one_way", "hedge"),
        help="v4.0: borsa pozisyon modu — auto (vars.; borsadan sorgulanır "
             "ve emirlere positionSide/posSide o modda eklenir)",
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
    # ------------------------------------------------------------------
    # ACARBOT v2.0 bayrakları
    # ------------------------------------------------------------------
    parser.add_argument(
        "--no-v2", action="store_true",
        help="v2.0 geliştirme paketini kapat (v1.2 davranışı)",
    )
    parser.add_argument(
        "--margin-mode", choices=("isolated", "cross"), default=None,
        help="marj modu (varsayılan isolated; cross: hesap bazlı teminat)",
    )
    parser.add_argument(
        "--equity-floor-pct", type=float, default=None,
        help="equity eşiği: başlangıç bakiyesinin -%%X'i → HARD_HALT (vars. 15)",
    )
    parser.add_argument(
        "--entry-rate-limit", type=int, default=None,
        help="dakikada en fazla kaç GERÇEK giriş (vars. 3)",
    )
    parser.add_argument(
        "--reentry-cooldown-minutes", type=float, default=None,
        help="stop sonrası yeniden giriş beklemesi dk (vars. 15)",
    )
    parser.add_argument(
        "--scoring-threshold", type=float, default=None,
        help="işlem için minimum sinyal puanı (vars. 70)",
    )
    parser.add_argument("--no-mtf", action="store_true",
                        help="çoklu zaman dilimi analizini kapat")
    parser.add_argument("--no-orderflow", action="store_true",
                        help="order flow motorunu kapat")
    parser.add_argument("--no-experts", action="store_true",
                        help="uzman motorları/Hakem'i kapat (v1.2 çözümleyicisi)")
    parser.add_argument(
        "--dashboard-seconds", type=float, default=None,
        help="kontrol paneli yenileme aralığı sn (vars. 60; 0 = kapalı)",
    )
    parser.add_argument(
        "--live-testnet", action="store_true",
        help="paper kararlarını Binance Testnet/OKX Demo'ya EŞLE "
             "(API anahtarları ortamdan; anahtar üzerinde para çekme izni KAPALI olmalı)",
    )
    parser.add_argument(
        "--live-exchange", choices=("binance", "okx"), default="binance",
        help="testnet eşleme borsası",
    )
    parser.add_argument(
        "--emergency-flatten", action="store_true",
        help="(yalnızca --live-testnet ile) acil durum: tüm testnet emirlerini "
             "iptal et, pozisyonları reduce-only kapat ve çık",
    )
    parser.add_argument(
        "--deadman-seconds", type=int, default=0,
        help="v3.0 dead-man's switch: N sn içinde kalp gelmezse borsa ACIK "
             "EMIRLERI iptal eder (0 = kapalı, varsayılan)",
    )
    parser.add_argument(
        "--deadman-confirm", action="store_true",
        help="v3.0: deadman'ın koruyucu stopları DA iptal edeceğini kabul "
             "edersiniz — --deadman-seconds bunun olmadan çalışmaz",
    )
    return parser


def setup_logging(level: str) -> None:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    # v3.0: log ROTASYONU — 7/24 oturumda paper_bot.log sınırsız büyümez
    # (5 MB x 5 yedek). ELK/Grafana gibi merkezi sistemlere akış bilinçli
    # olarak kapsamda değil (bkz. DEGISIKLIKLER_FINAL_v3.0.md notlar).
    file_handler = RotatingFileHandler(
        "paper_bot.log", maxBytes=5 * 1024 * 1024, backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
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
    # v4.0: funding CSV'leri (<SYM>_funding.csv) mum verisinden ayrılır
    candle_files = [p for p in files if not p.stem.endswith("_funding")]
    funding_rates: dict[str, list[tuple[int, float]]] = {}
    for path in sorted(data_dir.glob("*_funding.csv")):
        symbol = path.stem.replace("_funding", "").upper()
        rows: list[tuple[int, float]] = []
        with open(path, encoding="utf-8") as handle:
            header = handle.readline().strip().split(",")
            idx = {name: i for i, name in enumerate(header)}
            for line in handle:
                parts = line.strip().split(",")
                if len(parts) < len(header):
                    continue
                rows.append((
                    int(float(parts[idx["timestamp"]])),
                    float(parts[idx["rate"]]),
                ))
        funding_rates[symbol] = rows
        logger.info(
            "Funding geçmişi yüklendi: %s → %d dönem (GERÇEK oranlar)",
            symbol, len(rows),
        )
    if not candle_files:
        logger.error("Backtest verisi yok: %s altında mum CSV bulunamadı", data_dir)
        return 1
    candles_by_symbol = {}
    for path in candle_files:
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
    result = engine.run(
        candles_by_symbol,
        funding_rates=funding_rates or None,
    )
    metrics = compute_metrics(
        list(result.trades), args.balance, result.final_balance,
        result.equity_curve,
    )
    # v4.0: çok rejimli döküm (madde 23: boğa / ayı / yatay ayrımı)
    regime_table = regime_breakdown(list(result.trades))
    # v2.0: Monte Carlo simülasyonu (şartname 7: "özellikle Monte Carlo önemli")
    from backtest.montecarlo import monte_carlo
    close_pnls = [
        float(t.get("pnl", 0.0)) for t in result.trades
        if t.get("type") == "CLOSE"
    ]
    mc = monte_carlo(close_pnls, initial_balance=args.balance)
    report = format_metrics_report(metrics, "BACKTEST (çoklu sembol)")
    print(report)
    print(mc.summary_text())
    # v4.0: çok rejimli döküm tablosu (boğa / ayı / yatay)
    if regime_table:
        print("\nREJİM BAZLI DÖKÜM (madde 23: çok rejimli backtest)")
        print(f"{'rejim':<12} {'işlem':>6} {'net PnL':>12} {'kazanma':>9}")
        for regime_name, stats in regime_table.items():
            print(
                f"{regime_name:<12} {stats['trades']:>6} "
                f"{stats['net_pnl']:>+12.2f} %{stats['win_rate']*100:>8.1f}"
            )
    else:
        print("\nREJİM BAZLI DÖKÜM: kapanış işlemi yok (uygulanmadı)")
    print(f"Red kodları: {dict(sorted(result.rejection_counts.items(), key=lambda kv: -kv[1]))}")
    print(f"Dolmayan emir: {result.expired_orders} | Kısmi dolum: {result.partial_fills}")
    spread_note = (
        "spread: ölçülen veri uygulandı" if result.spread_applied
        else "spread simülasyonu: uygulanmadı (ölçülmüş veri verilmedi)"
    )
    print(spread_note)
    slip_note = (
        f"kayma: {result.slippage_bps} bps | gecikme: {result.latency_ms} ms"
        if result.slippage_bps > 0 or result.latency_ms > 0
        else "kayma/gecikme: uygulanmadı (bt_slippage_bps=0, bt_latency_ms=0)"
    )
    print(slip_note)
    if result.betas:
        print(f"Betalar (5m getirilerden): {({k: round(v, 2) for k, v in result.betas.items()})}")
    out = Path("backtest_result.json")
    out.write_text(json.dumps({
        "metrics": metrics.as_dict(),
        "rejection_counts": result.rejection_counts,
        "expired_orders": result.expired_orders,
        "partial_fills": result.partial_fills,
        "monte_carlo": mc.as_dict(),
        "shock_tests": result.shock_tests,
        "betas": result.betas,
        "spread": "applied" if result.spread_applied else "uygulanmadi",
        "slippage_bps": result.slippage_bps,
        "latency_ms": result.latency_ms,
        "data_source": config.v2.data_source,
        "regime_breakdown": regime_table,
        "funding_history_loaded": sorted(funding_rates),
        "strategy": config.signal.strategy,
        "session_filter": config.signal.session_filter,
        "dca_enabled": config.dca.enabled,
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
    # ------------------------------------------------------------------
    # v2.0 overrides (CLI her zaman profile baskın)
    # ------------------------------------------------------------------
    if args.no_v2:
        config.v2 = _dc_replace(config.v2, enabled=False)
    if args.margin_mode is not None:
        config.v2 = _dc_replace(
            config.v2,
            margin=_dc_replace(config.v2.margin, mode=args.margin_mode),
        )
    gate_overrides = {}
    if args.equity_floor_pct is not None:
        if args.equity_floor_pct < 0 or args.equity_floor_pct > 90:
            raise ValueError("--equity-floor-pct [0, 90] aralığında olmalı")
        gate_overrides["equity_floor_pct"] = args.equity_floor_pct
    if args.entry_rate_limit is not None:
        if args.entry_rate_limit < 1:
            raise ValueError("--entry-rate-limit >= 1 olmalı")
        gate_overrides["entry_rate_per_min"] = args.entry_rate_limit
    if args.reentry_cooldown_minutes is not None:
        if args.reentry_cooldown_minutes < 0:
            raise ValueError("--reentry-cooldown-minutes negatif olamaz")
        gate_overrides["reentry_cooldown_min"] = args.reentry_cooldown_minutes
    if gate_overrides:
        config.v2 = _dc_replace(
            config.v2, gates=_dc_replace(config.v2.gates, **gate_overrides),
        )
    if args.scoring_threshold is not None:
        if not 0 < args.scoring_threshold <= 100:
            raise ValueError("--scoring-threshold (0, 100] aralığında olmalı")
        config.v2 = _dc_replace(
            config.v2,
            scoring=_dc_replace(
                config.v2.scoring, min_score_to_trade=args.scoring_threshold,
            ),
        )
    v2_kwargs = {}
    if args.no_mtf:
        v2_kwargs["mtf"] = _dc_replace(config.v2.mtf, enabled=False)
    if args.no_orderflow:
        v2_kwargs["orderflow"] = _dc_replace(config.v2.orderflow, enabled=False)
    if args.no_experts:
        v2_kwargs["experts"] = _dc_replace(config.v2.experts, enabled=False)
    if args.dashboard_seconds is not None:
        v2_kwargs["dashboard_seconds"] = args.dashboard_seconds
    if v2_kwargs:
        config.v2 = _dc_replace(config.v2, **v2_kwargs)
    if args.live_testnet:
        config.v2 = _dc_replace(
            config.v2,
            live=_dc_replace(
                config.v2.live, enabled=True, exchange=args.live_exchange,
            ),
        )
    # v3.1: sinyal eşikleri CLI'dan ayarlanabilir (v1.3 kuralı; kod
    # varsayılanları DEĞİŞMEDİ — bayrak verilmezse eski davranış birebir).
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
    # v3.1: motor seçimi (v1.4 kuralı) — pipeline tek kapıdan uygular
    motors_map = {
        "both": ("fade", "trend"),
        "trend": ("trend",),
        "fade": ("fade",),
    }
    config.signal = _dc_replace(
        config.signal, enabled_motors=motors_map[args.motors],
    )
    # v3.1: tam pazar veri bütünlüğü kuralları (v1.5 kuralı)
    if getattr(args, "scan_all", False):
        config.data = _dc_replace(config.data, full_market=True)
    # ------------------------------------------------------------------
    # v4.0 overrides
    # ------------------------------------------------------------------
    if getattr(args, "strategy", None):
        config.signal = _dc_replace(config.signal, strategy=args.strategy)
    if getattr(args, "confluence_threshold", None) is not None:
        if not 0 < args.confluence_threshold <= 1:
            raise ValueError("--confluence-threshold (0, 1] aralığında olmalı")
        config.signal = _dc_replace(
            config.signal, confluence_threshold=args.confluence_threshold,
        )
    if getattr(args, "session", None):
        config.signal = _dc_replace(config.signal, session_filter=args.session)
    if getattr(args, "dca", False):
        if not config.dca.enabled:
            config.dca = _dc_replace(config.dca, enabled=True)
    live_overrides = {}
    if getattr(args, "live_entry_style", None):
        live_overrides["entry_style"] = args.live_entry_style
    if getattr(args, "position_mode", None):
        live_overrides["position_mode"] = args.position_mode
    if live_overrides:
        config.v2 = _dc_replace(
            config.v2, live=_dc_replace(config.v2.live, **live_overrides),
        )
    agent_overrides = {}
    if getattr(args, "us_market", None):
        agent_overrides["us_market_mode"] = args.us_market
    if getattr(args, "news_rss", None):
        agent_overrides["rss_news_mode"] = args.news_rss
    if agent_overrides:
        config.v2 = _dc_replace(
            config.v2,
            agents=_dc_replace(config.v2.agents, **agent_overrides),
        )
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

        # v4.0: ajanlar — ASLA işlem açmaz; flag = bayrak, block = yeni giriş
        # engeli (opsiyonel). Kongre ajanı dürüst "uygulanmadı" durumundadır.
        from agents import (
            AnalystAgent,
            CongressAgent,
            RssNewsAgent,
            USMarketAgent,
        )
        agents_cfg = config.v2.agents
        us_agent = USMarketAgent(
            mode=agents_cfg.us_market_mode,
            refresh_seconds=agents_cfg.us_market_refresh_seconds,
        )
        rss_agent = RssNewsAgent(
            mode=agents_cfg.rss_news_mode,
            refresh_seconds=agents_cfg.rss_news_refresh_seconds,
        )
        congress_agent = CongressAgent(mode=agents_cfg.rss_news_mode and "off")
        executor.agent_guards = [
            agent for agent in (us_agent, rss_agent) if agent.mode != "off"
        ]
        executor.us_agent = us_agent
        executor.rss_agent = rss_agent
        executor.congress_agent = congress_agent
        executor.analyst = AnalystAgent(llm_enabled=agents_cfg.analyst_llm)
        if executor.agent_guards:
            logger.info(
                "AJANLAR: %s",
                ", ".join(
                    f"{agent.name}={agent.mode}" for agent in executor.agent_guards
                ) + " | kongre=uygulanmadı (veri kaynağı yok)",
            )

        # v2.0: canlı eşleme (yalnızca açıkça istenirse; varsayılan kapalı)
        # v3.0: yığın — LiveMirror + EmergencyController + RestartRecovery
        live_mirror = emergency = recovery = None
        if config.v2.live.enabled:
            live_mirror, emergency, recovery = _build_live_stack(config, store)
            if live_mirror is not None:
                logger.info(
                    "CANLI EŞLEME: %s testnet/demo aktif — paper kararları "
                    "idempotent clientOrderId ile eşlenir; durum SQLite'a "
                    "yazılır (restart güvenli)",
                    config.v2.live.exchange,
                )
            if args.deadman_seconds > 0 and not args.deadman_confirm:
                logger.warning(
                    "--deadman-seconds verildi ama --deadman-confirm yok → "
                    "deadman KAPALI (countdown koruyucu stopları da iptal eder)"
                )

        names = _selected_exchanges(args.exchange)

        # v3.1: ortak borsa istemcileri + sembol evreni (tam pazar taraması)
        from infra.exchanges.binance import BinancePublic
        from infra.exchanges.okx import OKXPublic
        _registry = {"binance": BinancePublic, "okx": OKXPublic}
        market_clients = {n: _registry[n]() for n in names if n in _registry}
        symbols_raw = [
            s.strip().upper() for s in args.symbols.split(",") if s.strip()
        ]
        if args.scan_all:
            # v3.1: evren borsadan keşfedilir (fetch_top_usdt_futures tüm
            # canlı USDT sözleşmelerini döndürür, hacimsel sıralı;
            # --symbols yok sayılır). Sıralama tarama önceliğidir: en likit
            # coinler önce değerlendirilir. İşlem kararı yine sembol başına
            # tam boru hattından geçer (evren listesi karar ÜRETMEZ).
            universe: dict[str, list[str]] = {}
            for n, client in market_clients.items():
                try:
                    markets = await asyncio.to_thread(
                        client.fetch_top_usdt_futures, 10_000,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "EVREN KEŞFİ BAŞARISIZ [%s]: %s — tam pazar modunda "
                        "kısmi evrenle devam EDİLMEZ (fail-closed)", n, exc,
                    )
                    return 1
                universe[n] = _scan_all_universe(markets, n)
            # Sweep koruması tam taramada isteğe bağlı çalışır: giriş adayı
            # sembolün defteri sinyal ANINDA tazelenir (1000+ defteri sürekli
            # çekmek rate limitlerine sığmaz).
            def _sweep_book_fetcher(key: str) -> None:
                if sweep_guard is None:
                    return
                ex_name, _, ex_symbol = key.partition(":")
                client = market_clients.get(ex_name)
                if client is None:
                    return
                book = client.fetch_order_book(
                    ex_symbol, config.sweep.book_levels,
                )
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
            universe = {n: _symbols_for(n, symbols_raw) for n in names}
        session_start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_balance = broker.portfolio.balance
        max_pos_text = (
            "SINIRSIZ" if config.portfolio.max_positions <= 0
            else str(config.portfolio.max_positions)
        )
        logger.info(
            "ACARBOT v%s | PAPER mod | borsa=%s | bakiye=%.2f | maks pozisyon=%s",
            __version__, ",".join(names), broker.portfolio.balance, max_pos_text,
        )
        logger.info(
            "v2.0: skorlama=%s | uzmanlar=%s | MTF=%s | orderflow=%s | "
            "marj=%s | equity eşiği=-%%%s | giriş hızı=%s/dk | "
            "yeniden giriş=%s dk",
            "açık" if config.v2.enabled else "kapalı",
            "açık" if config.v2.experts.enabled else "kapalı",
            "açık" if config.v2.mtf.enabled else "kapalı",
            "açık" if config.v2.orderflow.enabled else "kapalı",
            config.v2.margin.mode,
            config.v2.gates.equity_floor_pct,
            config.v2.gates.entry_rate_per_min,
            config.v2.gates.reentry_cooldown_min,
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
        # v3.1: aktif eşikler + motorlar afişte (v1.3/v1.4 kuralı)
        logger.info(
            "v3.1: sinyal eşikleri RVOL≥%.2f | FADE impuls≥%.2f%% | spike≥%.1fx "
            "| aktif motorlar: %s",
            config.signal.min_rvol_for_entry,
            config.signal.fade_impulse_pct,
            config.signal.spike_multiplier,
            "+".join(m.upper() for m in config.signal.enabled_motors),
        )
        if args.scan_all:
            logger.info("Sembol evreni: TAM PAZAR (--scan-all)")
        else:
            logger.info("Sembol evreni: %s", args.symbols)
        # v4.0: strateji + seans + DCA afişi
        logger.info(
            "v4.0: strateji=%s%s | seans=%s | DCA=%s",
            config.signal.strategy,
            f" (confluence eşiği {config.signal.confluence_threshold:.2f})"
            if config.signal.strategy == "confluence" else "",
            config.signal.session_filter,
            "AÇIK (yalnız LONG)" if config.dca.enabled else "kapalı",
        )
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
            """v3.1: paralel mum taraması + tek iş parçacıklı değerlendirme.

            Tüm semboller her döngüde tazelenir (tam pazar hedefi
            --scan-cycle-seconds, dar liste ~5 sn). Değerlendirme kuyruğu
            TEK tüketiciyle işler → executor paylaşılan durumu ve SQLite
            için yarış yoktur; değerlendirme ANA event loop'ta çalışır.
            Aynı kapanmış mum iki kez değerlendirilmez (last_closed damgası).
            """
            timeframe = config.data.timeframe
            sems = {
                n: asyncio.Semaphore(10 if n == "binance" else 4)
                for n in market_clients
            }

            # Binance ayna: 6000 weight/dk (klines weight=2) → 25 istek/sn
            # güvenli. OKX: /market/candles 20 istek/2sn → 8 istek/sn güvenli pay.
            pacers = {
                n: _ScanPacer(25.0 if n == "binance" else 8.0, loop)
                for n in market_clients
            }
            work = [
                (n, s) for n in market_clients for s in universe.get(n, [])
            ]
            cycle_target = args.scan_cycle_seconds if args.scan_all else 5.0
            eval_queue: asyncio.Queue = asyncio.Queue()
            last_closed: dict[str, int] = {}

            async def evaluator() -> None:
                while True:
                    key, candles = await eval_queue.get()
                    try:
                        ex_name = key.split(":", 1)[0]
                        client = market_clients.get(ex_name)
                        # v2.0: veri kaynağı etiketi (ayna = spot verisi)
                        mirror_mode = getattr(client, "mirror_mode", False)
                        executor.set_data_source(
                            "spot-mirror" if mirror_mode else "perp",
                        )
                        executor.update_candles(key, candles)
                        last = candles[-2] if len(candles) > 1 else candles[-1]
                        if last_closed.get(key) != last.timestamp:
                            last_closed[key] = last.timestamp
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
                    _stream_one(name, exchange, args, executor, alerts,
                                metrics, universe.get(name, [])),
                ))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        async def guards_refresher() -> None:
            """FINAL v1.1: haber takvimi + orderbook duvar taraması.

            v3.1 tam pazar modunda toplu defter taraması KAPALI: 1000+
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
                # v4.0: ajan tazelemeleri (bayrak üretimi; işlem açmaz)
                for agent in (us_agent, rss_agent):
                    if agent.mode == "off":
                        continue
                    try:
                        await asyncio.to_thread(agent.tick, now_ms)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "ajan tazeleme hatası (%s): %s", agent.name, exc,
                        )
                if (
                    not args.scan_all
                    and sweep_guard is not None
                    and now_ms - last_books_ms >= config.sweep.refresh_seconds * 1000
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

        async def mtf_refresher() -> None:
            """v2.0: üst zaman dilimi mumları (15m/1h/4h) REST'ten yenilenir.

            Yalnızca KAPANMIŞ mumlar kullanılır: dönen listenin son
            (forming) mumu atılır; analize girmesin diye executor'a
            enjekte edilmeden önce düşürülür.
            v3.1: tam pazar modunda BU GÖREV ÇALIŞMAZ — 1000+ sembol × 3 TF
            rate limitlerine sığmaz; pipeline 5m mumlardan yeniden
            örnekleme (resampled) yedeğini kullanır.
            """
            from infra.exchanges.binance import BinancePublic
            from infra.exchanges.okx import OKXPublic
            registry = {"binance": BinancePublic, "okx": OKXPublic}
            exchanges = {n: registry[n]() for n in names if n in registry}
            tf_schedule = {
                "1m": 30.0,
                "15m": config.v2.mtf.refresh_seconds_15m,
                "1h": config.v2.mtf.refresh_seconds_1h,
                "4h": config.v2.mtf.refresh_seconds_4h,
            }
            last_refresh: dict[str, float] = {}
            loop = asyncio.get_running_loop()
            while not stop_event.is_set():
                try:
                    now_s = loop.time()
                    for name, exchange in exchanges.items():
                        for symbol in universe.get(name, []):
                            key = f"{name}:{symbol}"
                            for tf, period in tf_schedule.items():
                                cache_key = f"{key}:{tf}"
                                if now_s - last_refresh.get(cache_key, 0.0) < period:
                                    continue
                                last_refresh[cache_key] = now_s
                                try:
                                    candles = await asyncio.to_thread(
                                        exchange.fetch_candles, symbol, tf, 120,
                                    )
                                    if not candles:
                                        continue
                                    # forming mumu at (son kayıt tamamlanmadı)
                                    closed = candles[:-1] if len(candles) > 1 else []
                                    if closed:
                                        executor.update_htf_candles(key, tf, closed)
                                        metrics.inc("mtf_updates")
                                except Exception as exc:  # noqa: BLE001
                                    logger.warning(
                                        "MTF yenileme hatası [%s %s]: %s",
                                        key, tf, exc,
                                    )
                                await asyncio.sleep(0.2)
                    await asyncio.sleep(5.0)
                except asyncio.CancelledError:
                    raise

        async def oi_refresher() -> None:
            """v2.0: açık pozisyon (OI) — GERÇEK borsa verisi.

            Ayna (spot) modunda veya desteklenmeyen borsada veri gelmez;
            order flow bileşeni 'uygulanmadı' olarak raporlanır.
            v3.1: tam pazar modunda BU GÖREV ÇALIŞMAZ (1000+ semborda OI
            sorgusu rate limitlerine sığmaz; bileşen 'uygulanmadı' raporlar).
            """
            from infra.exchanges.binance import BinancePublic
            from infra.exchanges.okx import OKXPublic
            registry = {"binance": BinancePublic, "okx": OKXPublic}
            exchanges = {n: registry[n]() for n in names if n in registry}
            last_oi_ms = 0.0
            loop = asyncio.get_running_loop()
            while not stop_event.is_set():
                try:
                    now_s = loop.time()
                    if now_s - last_oi_ms >= config.v2.orderflow.oi_refresh_seconds:
                        last_oi_ms = now_s
                        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                        for name, exchange in exchanges.items():
                            for symbol in universe.get(name, []):
                                key = f"{name}:{symbol}"
                                try:
                                    oi = await asyncio.to_thread(
                                        exchange.fetch_open_interest, symbol,
                                    )
                                    if oi is not None:
                                        executor.update_open_interest(key, oi, now_ms)
                                        metrics.inc("oi_updates")
                                except Exception as exc:  # noqa: BLE001
                                    logger.debug(
                                        "OI alınamadı [%s]: %s", key, exc,
                                    )
                                await asyncio.sleep(0.2)
                    await asyncio.sleep(5.0)
                except asyncio.CancelledError:
                    raise

        async def moneyflow_refresher() -> None:
            """v4.0: açık pozisyon sembolleri için GERÇEK funding + L/S oranı.

            Yalnız açık pozisyon sembolleri sorgulanır (API nazikliği);
            veri gelmezse o bileşen 'uygulanmadı' kalır (uydurulmaz).
            """
            loop = asyncio.get_running_loop()
            last_run_s = 0.0
            while not stop_event.is_set():
                await asyncio.sleep(5.0)
                try:
                    now_s = loop.time()
                    if now_s - last_run_s < max(
                        config.v2.orderflow.funding_refresh_seconds, 60.0,
                    ):
                        continue
                    last_run_s = now_s
                    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                    positions = list(executor.broker.portfolio.positions)
                    for name, exchange in market_clients.items():
                        for symbol in universe.get(name, []):
                            key = f"{name}:{symbol}"
                            if key not in positions:
                                continue
                            funding = await asyncio.to_thread(
                                exchange.fetch_funding_rate, symbol,
                            )
                            if funding is not None:
                                executor.set_funding_rate(key, funding)
                                metrics.inc("moneyflow_updates")
                            ls_ratio = await asyncio.to_thread(
                                exchange.fetch_long_short_ratio, symbol,
                            )
                            if ls_ratio is not None:
                                executor.update_long_short(key, ls_ratio, now_ms)
                                metrics.inc("moneyflow_updates")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("para akışı tazeleme hatası: %s", exc)

        async def liquidation_stream_task() -> None:
            """v4.0: Binance !forceOrder@arr likidasyon akışı (para akışı).

            Kopma halinde 5 sn bekleyip yeniden bağlanır. OKX likidasyon
            kanal şeması bu pakette doğrulanamadığı için OKX tarafı
            'uygulanmadı' olarak belgelenmiştir (uydurulmaz).
            """
            for name, exchange in market_clients.items():
                if name != "binance":
                    continue
                if getattr(exchange, "mirror_mode", False):
                    logger.warning(
                        "Likidasyon akışı: spot aynasında yoktur (uygulanmadı)",
                    )
                    continue
                while not stop_event.is_set():
                    try:
                        async for event in exchange.stream_liquidations():
                            key = f"{name}:{event.symbol}"
                            executor.update_liquidation(
                                key, event.liquidated_side,
                                event.notional_usd, event.timestamp_ms,
                            )
                            metrics.inc("liquidations_total")
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "likidasyon akışı kesildi: %s — 5 sn sonra "
                            "yeniden bağlanıyor", exc,
                        )
                        await asyncio.sleep(5.0)

        async def dashboard_task() -> None:
            """v2.0: profesyonel kontrol panelini periyodik loglar."""
            if config.v2.dashboard_seconds <= 0:
                return
            from monitor.dashboard import collect_snapshot, render_text
            loop = asyncio.get_running_loop()
            next_due = loop.time() + config.v2.dashboard_seconds
            while not stop_event.is_set():
                await asyncio.sleep(1.0)
                if stop_event.is_set() or loop.time() < next_due:
                    continue
                next_due = loop.time() + config.v2.dashboard_seconds
                try:
                    snapshot = collect_snapshot(executor, metrics)
                    logger.info("\n%s", render_text(snapshot))
                    metrics.inc("dashboard_rendered")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("panel hatası: %s", exc)

        async def live_mirror_task() -> None:
            """v3.0: paper OPEN/CLOSE/STOP_UPDATE kayıtlarını testnet'e eşler.

            Tüm borsa çağrıları asyncio.to_thread içinde yapılır — senkron
            HTTP (urllib, 15 sn'e kadar timeout) artık event loop'u
            kilitLEMEZ; tick/stop işleme engellenmez.
            """
            if live_mirror is None:
                return
            last_seen = 0
            poll = max(float(config.v2.live.poll_seconds), 2.0)
            while not stop_event.is_set():
                await asyncio.sleep(poll)
                trades = broker.trades
                new_items = trades[last_seen:]
                last_seen = len(trades)
                for trade in new_items:
                    ttype = trade.get("type")
                    signal_key = str(
                        trade.get("signal_key")
                        or trade.get("order_id")
                        or trade.get("timestamp", "")
                    )
                    if ttype == "OPEN":
                        actions = await asyncio.to_thread(
                            live_mirror.mirror_open,
                            str(trade.get("symbol", "")),
                            str(trade.get("side", "LONG")),
                            float(trade.get("quantity", 0.0)),
                            float(trade.get("stop_loss", 0.0)),
                            signal_key,
                            # v4.0: post-only maker limiti = paper dolum fiyatı
                            float(trade.get("price", 0.0) or 0.0),
                        )
                        for action in actions:
                            logger.info("TESTNET EŞLEME: %s", action)
                    elif ttype == "DCA":
                        # v4.0: DCA güvenlik emri → borsada market ek giriş
                        # (koruyucu stop closePosition zaten tümünü kapsar)
                        actions = await asyncio.to_thread(
                            live_mirror.mirror_dca,
                            str(trade.get("symbol", "")),
                            str(trade.get("side", "LONG")),
                            float(trade.get("quantity", 0.0)),
                            str(
                                trade.get("order_id")
                                or trade.get("signal_key", ""),
                            ),
                        )
                        for action in actions:
                            logger.info("TESTNET DCA: %s", action)
                    elif ttype == "CLOSE":
                        actions = await asyncio.to_thread(
                            live_mirror.mirror_close,
                            str(trade.get("symbol", "")),
                            str(trade.get("side", "LONG")),
                            float(trade.get("quantity", 0.0)),
                            signal_key,
                        )
                        for action in actions:
                            logger.info("TESTNET KAPANIŞ: %s", action)
                # v3.0: paper stop değişimleri (break-even/trailing/TP1) →
                # borsadaki koruyucu stop güncellenir.
                for update in executor.drain_stop_updates():
                    actions = await asyncio.to_thread(
                        live_mirror.mirror_stop_update,
                        str(update.get("symbol", "")),
                        str(update.get("side", "LONG")),
                        float(update.get("new_stop", 0.0)),
                        str(update.get("signal_key", "")),
                    )
                    for action in actions:
                        logger.info("TESTNET STOP GÜNCELLEME: %s", action)

        async def restart_recovery_task() -> None:
            """v3.0: başlangıçta borsa tarafını güvenli duruma getirir.

            Bayat giriş emirleri iptal edilir; koruyucu stopu olmayan
            pozisyonlara stop kurulur (stop fiyatları mirror durumundan).
            """
            if recovery is None or live_mirror is None:
                return
            try:
                stop_prices = live_mirror.stop_prices
                if recovery.binance is not None:
                    report = await asyncio.to_thread(
                        recovery.recover_binance, stop_prices,
                    )
                else:
                    report = await asyncio.to_thread(
                        recovery.recover_okx, stop_prices,
                    )
                logger.info("RESTART KURTARMA: %s", report.as_dict())
            except Exception as exc:  # noqa: BLE001
                logger.error("Restart kurtarma hatası: %s", exc)

        async def emergency_watch_task() -> None:
            """v3.0: HARD_HALT tetiklenince borsa pozisyonlarını da kapatır.

            -%15 equity eşiği (veya cross likidasyon) yerelde pozisyonları
            kapatır; bu görev aynı anda testnet/demo tarafını da flatten
            eder. Eski sürümde borsa pozisyonları AÇIK kalıyordu.
            """
            if emergency is None:
                return
            while not stop_event.is_set():
                await asyncio.sleep(2.0)
                try:
                    state = executor.risk.kill_switch_state
                    if (
                        state == KillSwitchState.HARD_HALT
                        and not emergency.triggered
                    ):
                        logger.error(
                            "HARD_HALT gözlendi → testnet/demo acil durum "
                            "flatten başlatılıyor"
                        )
                        await asyncio.to_thread(
                            emergency.trigger, "hard_halt",
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Acil durum izleyici hatası: %s", exc)

        async def deadman_task() -> None:
            """v3.0 (opt-in): borsa tarafı dead-man's switch kalp atışı.

            Bot ölürse: son kalpten --deadman-seconds sonra borsa o
            semboldeki TÜM açık emirleri iptal eder. DİKKAT: koruyucu
            stoplar da iptal edilir; bu yüzden çift onay (--deadman-confirm)
            gerekir ve varsayılan KAPALIDIR.
            """
            if (
                live_mirror is None
                or args.deadman_seconds <= 0
                or not args.deadman_confirm
            ):
                return
            interval = max(args.deadman_seconds / 3.0, 2.0)
            if args.scan_all:
                # v3.1: tam pazarda countdown'u 1000+ sembole göndermek borsa
                # hız limitini patlatır. Borsa tarafında YALNIZCA paper'a
                # eşlenmiş (dolmuş) pozisyonların emirleri vardır; giriş
                # emirleri borsaya zaten ancak dolumdan sonra gider. Bu
                # yüzden kapsam = açık paper pozisyonları (giriş + koruyucu
                # stoplarını kapsar) — yoksa tüm evren hiçbir koruma ekler
                # ama rate limitini yakar.
                raw = sorted({
                    str(sym).split(":", 1)[-1]
                    for sym in executor.broker.portfolio.positions
                })
                symbols = _symbols_for(config.v2.live.exchange, raw)
                logger.warning(
                    "TAM PAZAR deadman kapsamı: açık pozisyonlar %s "
                    "(giriş emirleri borsaya dolumdan sonra gider; kapsam "
                    "yeterlidir)",
                    symbols,
                )
            else:
                symbols = _symbols_for(
                    config.v2.live.exchange,
                    [
                        s.strip().upper()
                        for s in args.symbols.split(",") if s.strip()
                    ],
                )
            logger.warning(
                "DEAD-MAN'S SWITCH AKTİF: %s sn — kalp kesilirse %s için "
                "açık emirler (koruyucu stoplar DÂHİL) iptal edilir",
                args.deadman_seconds, symbols,
            )
            while not stop_event.is_set():
                await asyncio.sleep(interval)
                try:
                    if live_mirror.binance is not None:
                        for symbol in symbols:
                            await asyncio.to_thread(
                                live_mirror.binance.countdown_cancel_all,
                                symbol, args.deadman_seconds * 1000,
                            )
                    elif live_mirror.okx is not None:
                        await asyncio.to_thread(
                            live_mirror.okx.cancel_all_after,
                            args.deadman_seconds,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Deadman kalp atışı hatası: %s", exc)

        candle_task = asyncio.create_task(candle_refresher())
        ticker_task = asyncio.create_task(ticker_consumer())
        daily_task = asyncio.create_task(
            _daily_reporter(reporter, executor, alerts, metrics, stop_event),
        )
        guards_task = asyncio.create_task(guards_refresher())
        moneyflow_task = asyncio.create_task(moneyflow_refresher())
        liq_task = (
            asyncio.create_task(liquidation_stream_task())
            if "binance" in market_clients else None
        )
        mtf_task = (
            asyncio.create_task(mtf_refresher())
            if config.v2.mtf.enabled and not args.scan_all else None
        )
        oi_task = (
            asyncio.create_task(oi_refresher())
            if config.v2.orderflow.enabled and not args.scan_all else None
        )
        if args.scan_all and (
            config.v2.mtf.enabled or config.v2.orderflow.enabled
        ):
            logger.warning(
                "TAM PAZAR: MTF REST yenileme ve OI sorguları KAPALI "
                "(1000+ semborda rate limitlerine sığmaz); MTF için 5m "
                "yeniden örnekleme yedeği kullanılır, order flow 'uygulanmadı' "
                "raporlanır"
            )
        dash_task = asyncio.create_task(dashboard_task())
        mirror_task = (
            asyncio.create_task(live_mirror_task()) if live_mirror else None
        )
        # v3.0 görevleri: restart kurtarma, acil durum izleyici, deadman
        recovery_task = (
            asyncio.create_task(restart_recovery_task())
            if recovery and live_mirror else None
        )
        emergency_task = (
            asyncio.create_task(emergency_watch_task())
            if emergency and live_mirror else None
        )
        deadman = (
            asyncio.create_task(deadman_task())
            if live_mirror and args.deadman_seconds > 0
            and args.deadman_confirm else None
        )

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
            tasks = [candle_task, ticker_task, daily_task, guards_task,
                     dash_task, moneyflow_task]
            if liq_task:
                tasks.append(liq_task)
            if mtf_task:
                tasks.append(mtf_task)
            if oi_task:
                tasks.append(oi_task)
            if mirror_task:
                tasks.append(mirror_task)
            for extra in (recovery_task, emergency_task, deadman):
                if extra:
                    tasks.append(extra)
            for task in tasks:
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


def _build_live_stack(config, store):
    """v3.0: canlı eşleme yığını (yalnızca testnet/demo; varsayılan kapalı).

    API anahtarları ortam değişkenlerinden okunur (veya <AD>_FILE dosyasından):
      Binance: BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET
      OKX:     OKX_DEMO_API_KEY / OKX_DEMO_API_SECRET / OKX_API_PASSPHRASE
    Anahtar yoksa eşleme başlatılmaz ve uyarı loglanır (fail-closed).
    Kontrol listesi (para çekme izni KAPALI olmalı) loglanır.

    Dönüş: (LiveMirror, EmergencyController, RestartRecovery) veya (None,)*3.
    v3.0: OKX için de TAM emir eşlemesi (conditional algo stop dâhil);
    mirror durumu store.save_mirror_state/load_mirror_state ile kalıcıdır;
    RestartRecovery başlangıçta bağlanır (bayat emir iptali + stop restore).
    """
    from live import (
        BinanceFuturesTestnet,
        EmergencyController,
        LiveMirror,
        OkxDemoTrading,
        OkxSignedClient,
        RestartRecovery,
        SignedHttpClient,
        security_checklist,
    )
    from live.clients import default_transport
    exchange = config.v2.live.exchange
    for item in security_checklist():
        logger.warning("API GÜVENLİK: %s → %s (%s)",
                       item["check"], item["required"], item["note"])
    state_saver = store.save_mirror_state
    state_loader = store.load_mirror_state
    if exchange == "binance":
        client = SignedHttpClient(
            "https://testnet.binancefuture.com",
            "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
            default_transport(),
            rate_retries=config.v2.live.rate_retries,
        )
        if not client.configured:
            logger.error(
                "CANLI EŞLEME KAPALI: BINANCE_TESTNET_API_KEY/SECRET yok "
                "(fail-closed; paper mod sürer)"
            )
            return None, None, None
        # v4.0: borsa saat senkronu (imzalı istekler ofsetle damgalanır)
        if config.v2.live.time_sync:
            try:
                offset = client.sync_time()
                logger.info("SAAT SENKRONU (Binance): ofset %d ms", offset)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Saat senkronu başarısız (devam): %s", exc)
        broker_client = BinanceFuturesTestnet(client)
        # v4.0: pozisyon modu (hedge/one-way) — auto: borsadan sorgulanır
        requested_mode = config.v2.live.position_mode
        try:
            hedge = broker_client.detect_position_mode()
            actual = "hedge" if hedge else "one_way"
            if requested_mode not in ("auto", actual):
                logger.error(
                    "POZİSYON MODU ÇELİŞKİSİ: hesap %s, istek %s — emirler "
                    "GERÇEK hesap moduna (%s) göre gönderilecek; testnet "
                    "ayarını değiştirin veya --position-mode auto kullanın",
                    actual, requested_mode, actual,
                )
            logger.info(
                "POZİSYON MODU: %s%s",
                actual,
                " (emirlere positionSide eklenir)" if hedge else "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pozisyon modu sorgulanamadı (one-way varsayıldı): %s", exc)
        mirror = LiveMirror(
            binance=broker_client,
            state_saver=state_saver, state_loader=state_loader,
            margin_mode=config.v2.margin.mode,
            leverage=10,
            entry_style=config.v2.live.entry_style,
            entry_fill_timeout_s=config.v2.live.entry_fill_timeout_s,
        )
        emergency = EmergencyController(binance=broker_client)
        recovery = RestartRecovery(binance=broker_client)
        return mirror, emergency, recovery
    if exchange == "okx":
        client = OkxSignedClient(
            "https://www.okx.com",
            "OKX_DEMO_API_KEY", "OKX_DEMO_API_SECRET",
            default_transport(),
            rate_retries=config.v2.live.rate_retries,
        )
        if not client.configured:
            logger.error(
                "CANLI EŞLEME KAPALI: OKX_DEMO_API_KEY/SECRET yok "
                "(fail-closed; paper mod sürer)"
            )
            return None, None, None
        # v4.0: borsa saat senkronu
        if config.v2.live.time_sync:
            try:
                offset = client.sync_time()
                logger.info("SAAT SENKRONU (OKX): ofset %d ms", offset)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Saat senkronu başarısız (devam): %s", exc)
        # v3.0: OKX demo için TAM eşleme (market giriş + conditional algo
        # stop + reduce-only çıkış + stop güncelleme). Eski "uygulanmadı"
        # kısıtı kaldırıldı; pozisyon büyüklüğü ctVal ile kontrata çevrilir.
        broker_client = OkxDemoTrading(
            client, td_mode=config.v2.margin.mode,
        )
        # v4.0: OKX pozisyon modu (net / long-short)
        try:
            pos_mode = broker_client.detect_position_mode()
            logger.info(
                "POZİSYON MODU (OKX): %s%s",
                pos_mode,
                " (emirlere posSide eklenir)"
                if pos_mode == "long_short_mode" else "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OKX posMode sorgulanamadı (net varsayıldı): %s", exc)
        logger.warning(
            "OKX demo TAM eşleme aktif: %s giriş + sunucu tarafı "
            "conditional stop + reduce-only çıkış (sz kontrata çevrilir)",
            config.v2.live.entry_style,
        )
        mirror = LiveMirror(
            okx=broker_client,
            state_saver=state_saver, state_loader=state_loader,
            margin_mode=config.v2.margin.mode,
            leverage=10,
            entry_style=config.v2.live.entry_style,
            entry_fill_timeout_s=config.v2.live.entry_fill_timeout_s,
        )
        emergency = EmergencyController(okx=broker_client)
        recovery = RestartRecovery(okx=broker_client)
        return mirror, emergency, recovery
    logger.error("CANLI EŞLEME: bilinmeyen borsa %s", exchange)
    return None, None, None


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
    # v2.0 alanları; eski/sahte executor'larla uyum için savunmacı erişim
    risk_stats = getattr(executor, "risk_stats", {})
    v2_cfg = getattr(getattr(executor, "config", None), "v2", None)
    if v2_cfg is None:
        from core.config import V2Config
        v2_cfg = V2Config()
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
    # v3.1: sinyal eşikleri + motorlar (eski/sahte executor'larla uyum için savunmacı)
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
        # v3.1: sinyal eşikleri + motorlar raporun içinde (v1.3/v1.4 kuralı)
        "signal_thresholds": signal_thresholds,
        "started_at_utc": datetime.fromtimestamp(
            session_start_ms / 1000, tz=timezone.utc,
        ).isoformat(),
        "ended_at_utc": datetime.fromtimestamp(
            now_ms / 1000, tz=timezone.utc,
        ).isoformat(),
        "duration_seconds": round((now_ms - session_start_ms) / 1000.0, 1),
        "exchange": args.exchange,
        # v3.1: tam pazar taraması alanları (v1.5 kuralı)
        "scan_all": bool(getattr(args, "scan_all", False)),
        "universe_sizes": (
            {n: len(s) for n, s in universe.items()} if universe else {}
        ),
        "symbols": (
            "ALL-USDT" if getattr(args, "scan_all", False) else args.symbols
        ),
        "stale_entry_cancels": getattr(executor, "stale_entry_cancels", 0),
        # v4.0: ajanlar (bayrak durumları) + para akışı özeti
        "agents": {
            agent.name: agent.status()
            for agent in (
                getattr(executor, "us_agent", None),
                getattr(executor, "rss_agent", None),
                getattr(executor, "congress_agent", None),
            ) if agent is not None
        },
        "money_flow": (
            executor.money_flow_summary(now_ms)
            if hasattr(executor, "money_flow_summary") else {}
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
        "halt_reason": getattr(executor.risk, "last_halt_reason", None),
        "safe_mode": bool(executor.data_integrity.safe_mode),
        "counters": dict(metrics.counters),
        # -------------------------------------------------------------
        # v2.0 ekleri (şartname B-7/B-8: veri kaynağı etiketi + oturum
        # ölçümleri + gölge sinyal + uzman performansı)
        # -------------------------------------------------------------
        "data_source": getattr(executor, "data_source", "perp"),
        "risk_stats": {
            "max_concurrent_positions": risk_stats.get(
                "max_concurrent_positions", 0.0
            ),
            "max_margin_used": round(
                risk_stats.get("max_margin_used", 0.0), 4
            ),
            "min_free_margin": round(
                risk_stats.get("min_free_margin", 0.0), 4
            ),
            "equity_peak": round(risk_stats.get("equity_peak", 0.0), 4),
            "equity_trough": round(risk_stats.get("equity_trough", 0.0), 4),
        },
        "entry_rate_limiter": (
            executor.rate_limiter.stats()
            if hasattr(executor, "rate_limiter") else {}
        ),
        "shock_tests": getattr(
            executor, "last_shock_summary",
            {"checked": 0, "blocked": 0, "unavailable": 0},
        ),
        "expert_performance": (
            executor.expert_performance.as_dict()
            if hasattr(executor, "expert_performance") else {}
        ),
        "shadow_signals": (
            executor.shadow_tracker.summary()
            if hasattr(executor, "shadow_tracker") else {}
        ),
        "margin_mode": v2_cfg.margin.mode,
        "v2_enabled": v2_cfg.enabled,
    }
    text = reporter.daily_report(
        equity=equity,
        unrealized_pnl=unrealized,
        open_positions=report["open_positions"],
        kill_switch_state=report["kill_switch"],
        safe_mode=report["safe_mode"],
        session_trades=session_trades,
    )
    # v4.0: analist ajanı — raporu yorumlar, ÖNERİ verir (işlem kararı vermez)
    analyst = getattr(executor, "analyst", None)
    if analyst is not None:
        try:
            report["analyst"] = analyst.analyze(report)
            for obs in report["analyst"].get("observations", []):
                logger.info("ANALİST | %s", obs)
            for sug in report["analyst"].get("suggestions", []):
                logger.info("ANALİST ÖNERİ | %s", sug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Analist ajanı hatası (rapor etkilenmez): %s", exc)
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
        if getattr(args, "scan_all", False):
            # v3.1: evren zaten borsadan keşfedildi; ekstra meta çağrısı yok.
            stream_symbols = list(symbols)
        else:
            resolved = _symbols_for(name, symbols)
            markets = await asyncio.to_thread(
                exchange.fetch_top_usdt_futures, 10_000,
            )
            symbol_set = set(resolved)
            stream_symbols = [
                m.symbol for m in markets
                if m.symbol in symbol_set or m.base_asset in symbol_set
            ] or resolved
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


def _scan_all_universe(markets, exchange_name: str) -> list[str]:
    """v3.1: tam pazar evreni — YALNIZ perpetual enstrümanlar.

    Binance: PERPETUAL (ayna modunda SPOT); vadeli sözleşmeler
    (CURRENT/NEXT_QUARTER) likidite/vade riskiyle dışarıda.
    OKX: SWAP (lineer USDT perpetual); FUTURES (vadeliler) dışarıda.
    Hacimsel sıra KORUNUR: taramada en likit coinler önce değerlendirilir.
    """
    keep = ("SWAP",) if exchange_name == "okx" else ("PERPETUAL", "SPOT")
    return [m.symbol for m in markets if m.contract_type in keep]


class _ScanPacer:
    """v3.1: saniyelik istek hızı sınırlayıcı (429 rate limit koruması).

    Tam pazar taramasında binlerce REST çağrısı tek pacer'da kuyruklanır;
    borsa limitlerinin altında güvenli pay kalır (Binance 25/sn, OKX 8/sn).
    """

    def __init__(self, rate_per_sec: float,
                 loop: asyncio.AbstractEventLoop) -> None:
        self.interval = 1.0 / rate_per_sec
        self.loop = loop
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self) -> None:
        async with self.lock:
            now = self.loop.time()
            delay = self.next_at - now
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = max(now, self.next_at) + self.interval


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
    # v2.0: acil durum (yalnızca canlı eşleme açıkken anlamlı)
    if args.emergency_flatten:
        if not args.live_testnet:
            logger.error(
                "--emergency-flatten yalnızca --live-testnet ile kullanılabilir "
                "(paper modda kapatılacak pozisyon zaten simülasyondur)"
            )
            return 1
        result = _run_emergency_flatten(args)
        logger.info("ACİL DURUM SONUCU: %s", result)
        return 0 if not result.get("errors") else 1
    if args.mode == "backtest":
        return run_backtest(args)
    return asyncio.run(run_paper(args))


def _run_emergency_flatten(args: argparse.Namespace) -> dict:
    """v2.0: acil durum — tüm emirleri iptal + pozisyonları reduce-only kapat."""
    from live import (
        BinanceFuturesTestnet,
        EmergencyController,
        OkxDemoTrading,
        OkxSignedClient,
        SignedHttpClient,
    )
    from live.clients import default_transport
    if args.live_exchange == "binance":
        client = SignedHttpClient(
            "https://testnet.binancefuture.com",
            "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
            default_transport(),
        )
        broker_client = BinanceFuturesTestnet(client) if client.configured else None
        okx_client = None
    else:
        client = OkxSignedClient(
            "https://www.okx.com",
            "OKX_DEMO_API_KEY", "OKX_DEMO_API_SECRET",
            default_transport(),
        )
        okx_client = OkxDemoTrading(client) if client.configured else None
        broker_client = None
    controller = EmergencyController(
        binance=broker_client, okx=okx_client,
    )
    return controller.trigger(reason="emergency-flatten")


if __name__ == "__main__":
    raise SystemExit(main())
