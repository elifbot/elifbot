"""v5.1 — ÇOK SEMBOLLÜ, ÇOK REJİMLİ DOĞRULAMA KOŞUCUSU.

TEK KOMUTLA:
  1. 90+ gün, çok sembollü 5m mum indirir (önbellekli)
  2. Mum içi yol için 1m alt çözünürlük indirir (gerçek sıra)
  3. Maliyet modelini yükler (ölçülmüş yoksa muhafazakâr varsayım)
  4. Backtest'i MALİYET AÇIK koşar
  5. 1m yoksa sentetik ALT/ÜST SINIR koşar (tek sayı değil ARALIK)
  6. Walk-forward + Monte Carlo + rejim kırılımı
  7. Gerçekleşen/hedef kayıp denetimi (1,3x aşımı işaretler)
  8. Hepsini TEK JSON + TEK Markdown rapora yazar

Böylece "kenar var mı?" sorusu her sürümde AYNI yöntemle cevaplanır.

Kullanım:
    python3 -m tools.validate_strategy --days 90 --fine-days 5 \\
        --symbols BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP \\
        --profile apex --costs docs/maliyet_olcum.json \\
        --out docs/dogrulama_v5.1.json
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app import __version__
from backtest.costs import CostModel
from backtest.engine import BacktestEngine
from backtest.intrabar import IntrabarPath
from backtest.metrics import compute_metrics, format_metrics_report
from backtest.montecarlo import monte_carlo
from backtest.walkforward import walk_forward
from core.config import SuperConfig
from infra.market_data.models import Candle
from tools.download_history import fetch_binance, fetch_okx, write_csv

logger = logging.getLogger("validate")

DEFAULT_SYMBOLS = (
    "BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP,"
    "XRP-USDT-SWAP,DOGE-USDT-SWAP,ADA-USDT-SWAP"
)


def _profile_config(profile: str, max_loss: float | None) -> SuperConfig:
    from app.main import apply_profile, build_parser

    args = build_parser().parse_args(
        ["--mode", "paper", "--paper", "--profile", profile],
    )
    config = apply_profile(args, SuperConfig())
    if max_loss is not None:
        from dataclasses import replace

        config = replace(
            config,
            account=replace(config.account, max_loss_per_position=max_loss),
        )
    return config


def _load_or_fetch(
    exchange: str, symbol: str, bars: int, interval: str, data_dir: Path,
    pause: float,
) -> list[Candle]:
    """Önbellekli indirme. Aynı sembol+aralık+bar sayısı tekrar indirilmez."""
    safe = symbol.replace("-", "").replace(":", "_").upper()
    path = data_dir / f"{safe}_{interval}_{bars}.csv"
    if path.exists():
        rows = _read_csv(path)
        if len(rows) >= bars * 0.95:
            logger.info("[%s %s] önbellek: %d bar", symbol, interval, len(rows))
            return rows
    logger.info("[%s %s] indiriliyor: %d bar hedefi", symbol, interval, bars)
    fetch = fetch_okx if exchange == "okx" else fetch_binance
    try:
        raw = fetch(symbol, bars, interval=interval)
    except TypeError:
        raw = fetch(symbol, bars)
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s %s] indirme başarısız: %s", symbol, interval, exc)
        return []
    if not raw:
        logger.error("[%s %s] veri boş", symbol, interval)
        return []
    write_csv(path, raw)
    time.sleep(pause)
    return [
        Candle(timestamp=int(r[0]), open=float(r[1]), high=float(r[2]),
               low=float(r[3]), close=float(r[4]), volume=float(r[5]))
        for r in raw
    ]


def _read_csv(path: Path) -> list[Candle]:
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
                open=float(parts[idx["open"]]), high=float(parts[idx["high"]]),
                low=float(parts[idx["low"]]), close=float(parts[idx["close"]]),
                volume=float(parts[idx["volume"]]),
            ))
    return candles


def _run_block(
    label: str, config, candles, fine, costs, initial_balance, windows,
) -> dict:
    engine = BacktestEngine(config, initial_balance=initial_balance)
    intrabar = IntrabarPath(fine_by_symbol=fine) if fine else None
    result = engine.run(candles, cost_model=costs, intrabar=intrabar)
    metrics = compute_metrics(
        list(result.trades), initial_balance, result.final_balance,
        result.equity_curve,
    )
    pnls = [
        float(t.get("pnl", 0.0)) for t in result.trades
        if t.get("type") == "CLOSE"
    ]
    mc = monte_carlo(pnls, initial_balance=initial_balance)
    wf = walk_forward(
        candles, windows=windows, config=config,
        initial_balance=initial_balance,
    )
    return {
        "label": label,
        "path_source": result.path_source,
        "metrics": metrics.as_dict(),
        "metrics_text": format_metrics_report(metrics, title=label.upper()),
        "monte_carlo": mc.as_dict(),
        "walk_forward": wf.as_dict(),
        "intrabar": result.intrabar,
        "risk_audit": result.risk_audit,
        "rejection_counts": result.rejection_counts,
        "expired_orders": result.expired_orders,
        "partial_fills": result.partial_fills,
        "cost_model_source": result.cost_model.get("source"),
        "net_pnl": round(result.net_pnl, 4),
        "trade_count": result.trade_count,
    }


def build_markdown(report: dict) -> str:
    lines = [
        f"# ACARBOT Doğrulama Raporu — {report['version']}",
        "",
        f"**Üretim:** {report['generated_at']}",
        f"**Veri:** {report['dataset']['exchange']} · "
        f"{report['dataset']['symbols']} sembol · "
        f"{report['dataset']['days']} gün · "
        f"{report['dataset']['total_bars']} adet 5m bar",
        f"**1m alt çözünürlük:** {report['dataset']['fine_days']} gün · "
        f"{report['dataset']['fine_bars']} bar",
        f"**Profil:** {report['profile']} · işlem başı hedef net risk "
        f"{report['target_net_risk']} USDT",
        "",
        "## Maliyet modeli",
        "",
        report["cost_summary"],
        "",
    ]
    if report["cost_model"].get("optimistic_warning"):
        lines += ["> 🔴 **MALİYETLER KAPALI** — sonuçlar iyimser, "
                  "kârlılık iddiası geçersiz.", ""]
    elif report["cost_model"].get("source") != "measured":
        lines += ["> 🟡 Maliyetler **ölçülmedi**, muhafazakâr varsayım "
                  "kullanıldı. `tools/measure_costs.py` ile ölçüm alınmalı.", ""]

    lines += ["## Koşular", "",
              "| Koşu | Yol kaynağı | Net PnL | İşlem | Kazanma | PF | "
              "Maks DD | MC kayıp olasılığı |", "|---|---|---|---|---|---|---|---|"]
    for block in report["runs"]:
        m = block["metrics"]
        lines.append(
            f"| {block['label']} | {block['path_source']} | "
            f"{block['net_pnl']:.4f} | {block['trade_count']} | "
            f"{m.get('win_rate', 0) * 100:.1f}% | "
            f"{m.get('profit_factor', 0):.4f} | "
            f"{m.get('max_drawdown_usdt', 0):.4f} | "
            f"{block['monte_carlo'].get('prob_loss', 0) * 100:.1f}% |"
        )
    lines += ["", "## Risk denetimi (gerçekleşen / hedef kayıp)", ""]
    for block in report["runs"]:
        audit = block["risk_audit"]
        lines.append(
            f"- **{block['label']}**: {audit['losing_trades']} zararlı işlem · "
            f"ort {audit['mean_realized_over_target']:.3f}x · "
            f"maks {audit['max_realized_over_target']:.3f}x · "
            f"aşım {audit['breach_count']}/{audit['losing_trades']} "
            f"(eşik {audit['breach_ratio_threshold']}x) · "
            f"maks stop aşımı {audit['max_stop_overshoot_ratio']:.3f}x"
        )
    lines += ["", "## Rejim kırılımı", ""]
    for block in report["runs"]:
        by_regime = block["metrics"].get("by_regime") or {}
        if not by_regime:
            continue
        lines.append(f"### {block['label']}")
        lines.append("")
        lines.append("| Rejim | İşlem | Net PnL | Kazanma |")
        lines.append("|---|---|---|---|")
        for regime, stats in sorted(
            by_regime.items(), key=lambda kv: -kv[1].get("trades", 0),
        ):
            lines.append(
                f"| {regime} | {stats.get('trades', 0)} | "
                f"{stats.get('net_pnl', 0):.4f} | "
                f"{stats.get('win_rate', 0) * 100:.1f}% |"
            )
        lines.append("")
    lines += ["## Walk-forward", ""]
    for block in report["runs"]:
        wf = block["walk_forward"]
        lines.append(
            f"- **{block['label']}**: {wf.get('profitable_windows', 0)}/"
            f"{wf.get('windows', 0)} pencere kârlı · "
            f"toplam {wf.get('total_net_pnl', 0):.4f} USDT"
        )
    lines += ["", "## Red sayaçları", ""]
    for block in report["runs"]:
        top = sorted(
            block["rejection_counts"].items(), key=lambda kv: -kv[1],
        )[:8]
        lines.append(
            f"- **{block['label']}**: "
            + (", ".join(f"{k}={v}" for k, v in top) or "yok")
        )
    lines += ["", "## Hüküm", "", report["verdict"], ""]
    return "\n".join(lines)


def _verdict(runs: list[dict], min_trades: int) -> str:
    primary = runs[0]
    count = primary["trade_count"]
    pnl = primary["net_pnl"]
    prob_loss = primary["monte_carlo"].get("prob_loss", 0.0)
    breaches = primary["risk_audit"]["breach_count"]
    if count < min_trades:
        return (
            f"🔴 **KENAR KANITLANMADI — örneklem yetersiz.** Birincil koşuda "
            f"{count} işlem var; istatistiksel hüküm için en az {min_trades} "
            f"gerekir. Daha uzun veri veya daha çok sembol ile tekrar koşun. "
            f"Bu sonuçla gerçek paraya ölçekleme YAPILMAMALIDIR."
        )
    if pnl <= 0 or prob_loss > 0.5:
        return (
            f"🔴 **KENAR YOK.** {count} işlemde net {pnl:.2f} USDT, "
            f"Monte Carlo kayıp olasılığı %{prob_loss * 100:.1f}. "
            f"Strateji maliyetler altında kâr üretmiyor. "
            f"`max_loss_per_position` 2,5–5 USDT'de tutulmalı."
        )
    if breaches:
        return (
            f"🟡 **KENAR VAR AMA RİSK HEDEFİ SAPKIYOR.** Net {pnl:.2f} USDT, "
            f"fakat {breaches} işlemde gerçekleşen kayıp hedefin 1,3 katını "
            f"aştı. Ölçeklemeden önce stop/mum içi yol kalibrasyonu gerekir."
        )
    return (
        f"🟢 **KENAR ADAYI.** {count} işlemde net {pnl:.2f} USDT, "
        f"kayıp olasılığı %{prob_loss * 100:.1f}, risk aşımı yok. "
        f"Yine de gerçek/testnet oturumuyla doğrulanmadan ölçeklenmemeli."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Çok sembollü doğrulama koşucusu")
    parser.add_argument("--exchange", choices=("okx", "binance"), default="okx")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--fine-days", type=int, default=5,
                        help="1m alt çözünürlük penceresi (gün); 0 = kapalı")
    parser.add_argument("--profile", default="apex")
    parser.add_argument("--max-loss", type=float, default=None,
                        help="işlem başı hedef net risk (USDT); varsayılan profil değeri")
    parser.add_argument("--balance", type=float, default=1_000.0)
    parser.add_argument("--windows", type=int, default=6)
    parser.add_argument("--costs", default=None,
                        help="ölçülmüş maliyet JSON'u (tools/measure_costs.py)")
    parser.add_argument("--no-costs", action="store_true",
                        help="maliyetleri KAPAT (yalnızca karşılaştırma; rapor bayraklanır)")
    parser.add_argument("--compare-no-costs", action="store_true",
                        help="maliyetsiz karşılaştırma koşusu da yap (süreyi 2 katına çıkarır)")
    parser.add_argument("--bounds", action="store_true",
                        help="1m yoksa sentetik alt/üst sınır koşularını da ekle")
    parser.add_argument("--min-trades", type=int, default=200)
    parser.add_argument("--data-dir", default="data/validation")
    parser.add_argument("--pause", type=float, default=0.15)
    parser.add_argument("--out", default="docs/dogrulama.json")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    config = _profile_config(args.profile, args.max_loss)
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.no_costs:
        costs = CostModel.disabled()
    elif args.costs:
        costs = CostModel.load(args.costs)
    else:
        costs = CostModel()
    logger.info("%s", costs.summary_text())

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    bars_5m = args.days * 288
    bars_1m = args.fine_days * 1440
    candles: dict[str, list[Candle]] = {}
    fine: dict[str, list[Candle]] = {}
    for symbol in symbols:
        key = f"{args.exchange}:{symbol}"
        rows = _load_or_fetch(
            args.exchange, symbol, bars_5m, "5m", data_dir, args.pause,
        )
        if len(rows) < 100:
            logger.warning("[%s] yetersiz 5m veri — atlandı", key)
            continue
        candles[key] = rows
        if bars_1m > 0:
            fine_rows = _load_or_fetch(
                args.exchange, symbol, bars_1m, "1m", data_dir, args.pause,
            )
            if fine_rows:
                fine[key] = fine_rows
    if not candles:
        logger.error("Hiç veri alınamadı — doğrulama yapılamaz")
        return 1

    runs: list[dict] = []
    logger.info("=== BİRİNCİL KOŞU: gerçek 1m yol + maliyet açık ===")
    runs.append(_run_block(
        "birincil (1m yol + maliyet)", config, candles, fine, costs,
        args.balance, args.windows,
    ))
    if args.bounds or not fine:
        logger.info("=== SENTETİK SINIR KOŞULARI (1m kapsaması sınırlı) ===")
        for order, label in (
            ("adverse_first", "sentetik ALT sınır (kötümser)"),
            ("favorable_first", "sentetik ÜST sınır (iyimser)"),
        ):
            engine_path = IntrabarPath(synthetic_order=order, mode="synthetic")
            engine = BacktestEngine(config, initial_balance=args.balance)
            result = engine.run(candles, cost_model=costs, intrabar=engine_path)
            metrics = compute_metrics(
                list(result.trades), args.balance, result.final_balance,
                result.equity_curve,
            )
            pnls = [float(t.get("pnl", 0.0)) for t in result.trades
                    if t.get("type") == "CLOSE"]
            runs.append({
                "label": label, "path_source": result.path_source,
                "metrics": metrics.as_dict(),
                "metrics_text": format_metrics_report(metrics, title=label.upper()),
                "monte_carlo": monte_carlo(pnls, initial_balance=args.balance).as_dict(),
                "walk_forward": {}, "intrabar": result.intrabar,
                "risk_audit": result.risk_audit,
                "rejection_counts": result.rejection_counts,
                "expired_orders": result.expired_orders,
                "partial_fills": result.partial_fills,
                "cost_model_source": result.cost_model.get("source"),
                "net_pnl": round(result.net_pnl, 4),
                "trade_count": result.trade_count,
            })
    if args.compare_no_costs and not args.no_costs:
        logger.info("=== KARŞILAŞTIRMA: maliyetsiz (iyimserlik farkı) ===")
        runs.append(_run_block(
            "maliyetsiz karşılaştırma (İYİMSER)", config, candles, fine,
            CostModel.disabled(), args.balance, args.windows,
        ))

    report = {
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": args.profile,
        "target_net_risk": config.account.max_loss_per_position,
        "initial_balance": args.balance,
        "dataset": {
            "exchange": args.exchange,
            "symbols": len(candles),
            "symbol_list": sorted(candles),
            "days": args.days,
            "total_bars": sum(len(v) for v in candles.values()),
            "fine_days": args.fine_days,
            "fine_bars": sum(len(v) for v in fine.values()),
            "fine_symbols": len(fine),
        },
        "cost_model": costs.as_dict(),
        "cost_summary": costs.summary_text(),
        "runs": runs,
        "verdict": _verdict(runs, args.min_trades),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    md = out.with_suffix(".md")
    md.write_text(build_markdown(report), encoding="utf-8")
    logger.info("Rapor: %s", out)
    logger.info("Rapor (Markdown): %s", md)
    logger.info("HÜKÜM: %s", report["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
