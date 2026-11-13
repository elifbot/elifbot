"""v5.2 — ÇOK SEMBOLLÜ, ÇOK REJİMLİ DOĞRULAMA KOŞUCUSU.

TEK KOMUTLA:
  1. 90+ gün, çok sembollü 5m mum indirir (önbellekli)
  2. İKİ GEÇİŞLİ 1m: önce 5m ile koşar, sonra YALNIZCA işlem açılan
     aralıkların 1m verisini indirir ve yeniden koşar (v5.2)
  3. Maliyet modelini yükler; kaynağı borsa bazında DÜRÜST etiketler
  4. Birincil koşuyu MALİYET AÇIK + dinamik risk ölçekleme ile koşar
  5. Sentetik ALT/ÜST SINIR koşuları (v5.2: VARSAYILAN AÇIK)
  6. Maliyetsiz karşılaştırma (v5.2: VARSAYILAN AÇIK) → iyimserlik farkı
  7. Walk-forward + Monte Carlo + rejim kırılımı
     (v5.2: WF de aynı maliyet + mum içi yol ile koşar)
  8. Gerçekleşen/hedef kayıp denetimi (1,3x aşımı işaretler)
  9. Yapılandırılmış HÜKÜM: walk-forward öncelikli (v5.2)
 10. Hepsini TEK JSON + TEK Markdown rapora yazar

v5.2'DE DÜZELTİLEN RAPOR HATALARI
---------------------------------
  • Walk-forward satırı `0/[{...}] pencere` basıyordu → total_windows
  • "ÖLÇÜLMÜŞ" etiketi ölçülmemiş borsalara da uygulanıyordu → provenance
  • Birincil koşu kapsama %0 iken "1m yol" diye etiketleniyordu → gerçek
    kapsama oranından türetilen etiket
  • JSON'a `Infinity` yazılıyordu (by_symbol.profit_factor) → json_safe
  • Hüküm yalnızca birincil koşunun işlem sayısına bakıyordu → backtest.verdict

Kullanım:
    python3 -m tools.validate_strategy --days 90 \
        --costs docs/maliyet_olcum.json --out docs/dogrulama.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from app import __version__
from backtest.costs import CostModel
from backtest.engine import BacktestEngine
from backtest.intrabar import IntrabarPath
from backtest.metrics import compute_metrics, format_metrics_report
from backtest.montecarlo import monte_carlo
from backtest.verdict import DEFAULT_MIN_WF_TRADES, decide
from backtest.walkforward import walk_forward
from core.config import SuperConfig
from infra.market_data.models import Candle
from tools.download_history import (
    fetch_binance,
    fetch_okx,
    fetch_okx_windows,
    merge_windows,
    write_csv,
)

logger = logging.getLogger("validate")

DEFAULT_SYMBOLS = (
    "BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP,"
    "XRP-USDT-SWAP,DOGE-USDT-SWAP,ADA-USDT-SWAP"
)
COARSE_MS = 300_000


def json_safe(value):
    """Sonsuz/NaN değerleri JSON'a yazılabilir hâle getirir (özyinelemeli).

    v5.1 yalnızca üst düzey profit_factor'ı temizliyordu; by_symbol
    içindeki `inf` JSON'a kaçıyor ve dosya katı JSON olarak geçersiz
    oluyordu.
    """
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float):
        if math.isinf(value) or math.isnan(value):
            return 0.0
        return value
    return value


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


def _rows_to_candles(rows) -> list[Candle]:
    return [
        Candle(timestamp=int(r[0]), open=float(r[1]), high=float(r[2]),
               low=float(r[3]), close=float(r[4]), volume=float(r[5]))
        for r in rows
    ]


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
    return _rows_to_candles(raw)


# ---------------------------------------------------------------------------
# v5.2: İKİ GEÇİŞLİ 1m — işlem aralıklarını hedefle
# ---------------------------------------------------------------------------

def trade_windows(trades, coarse_ms: int = COARSE_MS, pad_bars: int = 1):
    """İşlem açılan/kapanılan aralıkları 5m hizalı [start,end) olarak verir.

    Yalnız giriş barı değil, TÜM TUTMA SÜRESİ hedeflenir: stopun hangi
    1m barda tetiklendiği asıl sorudur.
    """
    pad = pad_bars * coarse_ms
    open_at: dict[str, int] = {}
    spans: dict[str, list[tuple[int, int]]] = {}
    ordered = sorted(trades, key=lambda t: int(t.get("timestamp", 0)))
    for event in ordered:
        kind = event.get("type")
        symbol = str(event.get("symbol", ""))
        ts = int(event.get("timestamp", 0))
        if not symbol or ts <= 0:
            continue
        if kind == "ORDER_FILL":
            open_at.setdefault(symbol, ts)
        elif kind == "CLOSE":
            start = open_at.pop(symbol, ts)
            lo = (start // coarse_ms) * coarse_ms - pad
            hi = (ts // coarse_ms) * coarse_ms + coarse_ms + pad
            spans.setdefault(symbol, []).append((lo, hi))
    last_ts = int(ordered[-1].get("timestamp", 0)) if ordered else 0
    for symbol, start in open_at.items():
        lo = (start // coarse_ms) * coarse_ms - pad
        hi = (last_ts // coarse_ms) * coarse_ms + coarse_ms + pad
        spans.setdefault(symbol, []).append((lo, hi))
    return spans


def candidate_windows(probe, coarse_ms: int = COARSE_MS):
    """v5.4: ADAY pencereleri — işlem olmasa da 1m gerekir.

    Dürüst TTL modeli (fine_window) dolumu yalnız 1m alt mumda arar.
    İndirici yalnız işlem gören aralığa 1m çekerse KİLİTLENME olur:
    1m yok -> dolum yok -> işlem yok -> hedef pencere yok -> 1m yok.
    Bu yüzden her adayın giriş barı hedeflenir.
    """
    spans: dict[str, list[tuple[int, int]]] = {}
    for cand in probe or []:
        symbol = str(cand.get("symbol", ""))
        ts = int(cand.get("ts_ms", 0) or 0)
        if not symbol or ts <= 0:
            continue
        lo = (ts // coarse_ms) * coarse_ms
        # Sinyal barı + giriş barı (emir kapanışta kurulur, sonraki barda dolar)
        spans.setdefault(symbol, []).append((lo, lo + 2 * coarse_ms))
    return spans


def _covered(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(a <= start and end <= b for a, b in spans)


def refine_fine_data(
    exchange: str, candles: dict[str, list[Candle]],
    fine: dict[str, list[Candle]], result, data_dir: Path, pause: float,
    requested: dict[str, list[tuple[int, int]]], max_requests: int,
    stats: dict,
) -> tuple[dict[str, list[Candle]], bool]:
    """Bu koşuda işlem gören aralıkların 1m'ini indirir.

    Dönüş: (güncel fine, yeni veri geldi mi)
    """
    spans = trade_windows(result.trades)
    # v5.4: aday pencerelerini de hedefle (kilitlenmeyi önler)
    probe = getattr(result, "gate_probe", None)
    for key, wins in candidate_windows(probe).items():
        spans.setdefault(key, []).extend(wins)
    if not spans:
        return fine, False
    changed = False
    for key, windows in spans.items():
        symbol = key.split(":", 1)[-1]
        merged = merge_windows(windows)
        todo = [
            (a, b) for a, b in merged
            if not _covered(requested.get(key, []), a, b)
        ]
        stats["targeted_windows"] += len(merged)
        if not todo:
            continue
        if exchange != "okx":
            stats["unsupported_exchange_skips"] += 1
            logger.warning(
                "[%s] hedefli 1m yalnızca OKX'te destekli — atlandı", key,
            )
            continue
        budget = max_requests - stats["requests"]
        if budget <= 0:
            stats["truncated"] = True
            logger.warning("[%s] istek bütçesi bitti — kalan aralıklar atlandı", key)
            continue
        try:
            rows, used, truncated = fetch_okx_windows(
                symbol, todo, interval="1m", pause=pause, max_requests=budget,
            )
        except Exception as exc:  # noqa: BLE001
            stats["failures"] += 1
            logger.error("[%s] hedefli 1m indirilemedi: %s", key, exc)
            continue
        stats["requests"] += used
        stats["truncated"] = stats["truncated"] or truncated
        requested.setdefault(key, []).extend(todo)
        requested[key] = merge_windows(requested[key])
        if not rows:
            stats["empty_windows"] += 1
            continue
        existing = {c.timestamp: c for c in fine.get(key, [])}
        before = len(existing)
        for candle in _rows_to_candles(rows):
            existing[candle.timestamp] = candle
        fine[key] = [existing[t] for t in sorted(existing)]
        gained = len(existing) - before
        stats["fine_bars_gained"] += gained
        if gained:
            changed = True
            logger.info(
                "[%s] hedefli 1m: +%d bar (toplam %d, %d aralık)",
                key, gained, len(fine[key]), len(todo),
            )
    if changed:
        safe_dir = data_dir / "fine_targeted"
        safe_dir.mkdir(parents=True, exist_ok=True)
        for key, rows in fine.items():
            safe = key.replace("-", "").replace(":", "_").upper()
            write_csv(
                safe_dir / f"{safe}_1m_targeted.csv",
                [(c.timestamp, c.open, c.high, c.low, c.close, c.volume)
                 for c in rows],
            )
    return fine, changed


def load_targeted_cache(
    data_dir: Path, symbols: list[str],
) -> dict[str, list[Candle]]:
    """Önceki koşudan kalan hedefli 1m önbelleğini yükler."""
    out: dict[str, list[Candle]] = {}
    cache_dir = data_dir / "fine_targeted"
    if not cache_dir.exists():
        return out
    for key in symbols:
        safe = key.replace("-", "").replace(":", "_").upper()
        path = cache_dir / f"{safe}_1m_targeted.csv"
        if path.exists():
            rows = _read_csv(path)
            if rows:
                out[key] = rows
    return out


# ---------------------------------------------------------------------------
# Koşu blokları
# ---------------------------------------------------------------------------

def _path_label(prefix: str, intrabar_stats: dict, costs_on: bool) -> str:
    """Etiketi GERÇEK kapsama oranından türetir (v5.2).

    v5.1 kapsama %0 iken bile "1m yol" yazıyordu.
    """
    ratio = float((intrabar_stats or {}).get("real_coverage_ratio", 0.0))
    if ratio >= 0.999:
        path = "gerçek 1m yol"
    elif ratio > 0:
        path = f"karma yol (gerçek 1m %{ratio * 100:.1f})"
    else:
        path = "sentetik yol (1m YOK)"
    return f"{prefix} ({path}{'' if costs_on else ' · MALİYETSİZ'})"


def _run_block(
    label: str, config, candles, fine, costs, initial_balance, windows,
    tick_sizes=None, intrabar_order: str = "adverse_first",
    forced_path: IntrabarPath | None = None,
    funding_rates=None, funding_info=None,
) -> tuple[dict, object]:
    engine = BacktestEngine(config, initial_balance=initial_balance)
    if forced_path is not None:
        intrabar = forced_path
    elif fine:
        intrabar = IntrabarPath(
            fine_by_symbol=fine, synthetic_order=intrabar_order,
        )
    else:
        intrabar = IntrabarPath(
            synthetic_order=intrabar_order, mode="synthetic",
        )
    engine.gate_probe = []
    # v5.6: TARİHSEL FUNDING. Önceden bu parametre hiç geçilmiyordu;
    # backtest funding'i sıfır sayıyor ve rapor bunu "0" diye yazıyordu.
    result = engine.run(
        candles, cost_model=costs, intrabar=intrabar, tick_sizes=tick_sizes,
        funding_rates=funding_rates or None,
    )
    # v5.4: adaylar hedefli 1m indirmesi için sonuçla taşınır
    result.gate_probe = list(engine.gate_probe)
    metrics = compute_metrics(
        list(result.trades), initial_balance, result.final_balance,
        result.equity_curve,
    )
    pnls = [
        float(t.get("pnl", 0.0)) for t in result.trades
        if t.get("type") == "CLOSE"
    ]
    mc = monte_carlo(pnls, initial_balance=initial_balance)
    if windows > 0:
        wf = walk_forward(
            candles, windows=windows, config=config,
            initial_balance=initial_balance,
            # v5.2: WF artık birincil koşuyla AYNI koşullarda
            cost_model=costs, intrabar=intrabar, tick_sizes=tick_sizes,
        ).as_dict()
    else:
        wf = {}
    block = {
        "label": _path_label(label, result.intrabar, costs.enabled),
        "label_requested": label,
        "path_source": result.path_source,
        "metrics": metrics.as_dict(),
        "metrics_text": format_metrics_report(metrics, title=label.upper()),
        "monte_carlo": mc.as_dict(),
        "walk_forward": wf,
        "intrabar": result.intrabar,
        "risk_audit": result.risk_audit,
        "risk_scaling": result.risk_scaling,
        "drawdown_peak": result.drawdown_peak,
        "rejection_counts": result.rejection_counts,
        "expired_orders": result.expired_orders,
        "partial_fills": result.partial_fills,
        "cost_model_source": result.cost_model.get("source"),
        "net_pnl": round(result.net_pnl, 4),
        "trade_count": result.trade_count,
    }
    return block, result


def build_markdown(report: dict) -> str:
    ds = report["dataset"]
    lines = [
        f"# ACARBOT Doğrulama Raporu — {report['version']}",
        "",
        f"**Üretim:** {report['generated_at']}",
        f"**Veri:** {ds['exchange']} · {ds['symbols']} sembol · "
        f"{ds['days']} gün · {ds['total_bars']} adet 5m bar",
        f"**1m alt çözünürlük:** {ds.get('fine_mode', '?')} · "
        f"{ds['fine_bars']} bar · {ds['fine_symbols']} sembol",
        f"**Profil:** {report['profile']} · işlem başı TABAN net risk "
        f"{report['target_net_risk']} USDT",
        "",
    ]
    fine = report.get("fine_pass") or {}
    if fine:
        lines += [
            "## 1m kapsamı (iki geçişli)",
            "",
            f"- Geçiş sayısı: **{fine.get('passes', 0)}** · "
            f"hedeflenen aralık: {fine.get('targeted_windows', 0)} · "
            f"istek: {fine.get('requests', 0)}",
            f"- Kazanılan 1m bar: **{fine.get('fine_bars_gained', 0)}** · "
            f"boş aralık: {fine.get('empty_windows', 0)} · "
            f"hata: {fine.get('failures', 0)}",
            "",
            "| Geçiş | Gerçek 1m bar | Sentetik bar | Kapsama |",
            "|---|---|---|---|",
        ]
        for row in fine.get("history", []):
            lines.append(
                f"| {row['pass']} | {row['real_1m_bars']} | "
                f"{row['synthetic_bars']} | %{row['coverage'] * 100:.1f} |"
            )
        lines.append("")
        if fine.get("truncated"):
            lines += ["> 🟡 İstek bütçesi doldu; bazı aralıkların 1m'i "
                      "indirilemedi. `--fine-max-requests` artırılabilir.", ""]

    lines += ["## Maliyet modeli", "", report["cost_summary"], ""]
    cov = report.get("cost_coverage") or {}
    if cov:
        lines += [
            f"**Veri kümesi kapsamasi:** {cov.get('measured_symbols', 0)}/"
            f"{cov.get('dataset_symbols', 0)} sembol ölçülmüş "
            f"(%{cov.get('coverage_ratio', 0) * 100:.0f}).",
            "",
        ]
        if cov.get("unmeasured_symbols"):
            lines += [
                "> 🟡 Ölçülmeyen semboller borsa VARSAYIMI ile koştu: "
                + ", ".join(cov["unmeasured_symbols"][:12]),
                "",
            ]
    prov = (report.get("cost_model") or {}).get("exchange_provenance") or {}
    if prov:
        lines += ["| Borsa | Kaynak | Ölçülen sembol | Varsayılan kayma |",
                  "|---|---|---|---|"]
        for ex, info in prov.items():
            src = ("ÖLÇÜLDÜ (sembol bazlı)"
                   if info["source"] == "measured_symbols"
                   else "**VARSAYIM — ÖLÇÜLMEDİ**")
            lines.append(
                f"| {ex} | {src} | {info['measured_symbol_count']} | "
                f"{info['fallback_slippage_bps']:.2f} bps |"
            )
        lines.append("")
    quality = report.get("cost_quality") or {}
    if quality:
        lines += [
            f"**Ölçüm tabanı:** {quality.get('samples_per_symbol', '?')} "
            f"örnek/sembol · {quality.get('rounds', '?')} tur · "
            f"pencere {quality.get('window_seconds', 0):.0f} sn · "
            f"değerlendirme: **{quality.get('grade', '?')}**",
            "",
        ]
        if quality.get("grade") == "thin":
            lines += ["> 🟡 Ölçüm tabanı İNCE. Küçük coinlerde gerçek kayma "
                      "daha kötü olabilir; sonuçlar bu yönde iyimserdir.", ""]

    if report["cost_model"].get("optimistic_warning"):
        lines += ["> 🔴 **MALİYETLER KAPALI** — sonuçlar iyimser, "
                  "kârlılık iddiası geçersiz.", ""]

    lines += ["## Koşular", "",
              "| Koşu | Yol kaynağı | Net PnL | İşlem | Kazanma | PF | "
              "Maks DD | MC kayıp olasılığı |",
              "|---|---|---|---|---|---|---|---|"]
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
    lines.append("")

    # --- v5.2: iyimserlik farkı + sınır aralığı -------------------------
    gap = report.get("optimism_gap") or {}
    if gap:
        lines += [
            "## İyimserlik farkı (maliyetlerin etkisi)",
            "",
            f"- Maliyetli net: **{gap['with_costs_net_pnl']:.4f}** USDT · "
            f"{gap['with_costs_trades']} işlem",
            f"- Maliyetsiz net: **{gap['without_costs_net_pnl']:.4f}** USDT · "
            f"{gap['without_costs_trades']} işlem",
            f"- **Fark: {gap['delta_net_pnl']:.4f} USDT** "
            f"(maliyetsiz koşu bu kadar iyimser)",
            "",
        ]
    bounds = report.get("bounds_interval") or {}
    if bounds and bounds.get("hesaplanabilir") is False:
        bounds = {}
    if bounds:
        lines += [
            "## Sentetik sınır aralığı (mum içi belirsizlik)",
            "",
            f"- Kötümser (ALT): **{bounds['adverse_net_pnl']:.4f}** USDT · "
            f"{bounds['adverse_trades']} işlem",
            f"- İyimser (ÜST): **{bounds['favorable_net_pnl']:.4f}** USDT · "
            f"{bounds['favorable_trades']} işlem",
            f"- **Genişlik: {bounds['width_usdt']:.4f} USDT** — "
            f"mum içi sıra bilinmediğinde sonuç bu aralıkta belirsizdir.",
            "",
        ]
        if bounds["adverse_net_pnl"] <= 0 <= bounds["favorable_net_pnl"]:
            lines += ["> 🟡 Aralık sıfırı KAPSIYOR: tek bir sayı ile kârlılık "
                      "iddia edilemez. Gerçek 1m kapsaması artırılmalı.", ""]

    lines += ["## Dinamik risk ölçekleme (v5.2)", ""]
    for block in report["runs"]:
        rs = block.get("risk_scaling") or {}
        if not rs:
            continue
        lines.append(
            f"- **{block['label']}**: {rs.get('budgets_issued', 0)} bütçe · "
            f"ort ölçek {rs.get('mean_scale', 1):.3f} · "
            f"min ölçek {rs.get('min_scale_seen', 1):.3f} · "
            f"maliyet kapısı reddi {rs.get('blocked_count', 0)} · "
            f"bağlayan: {rs.get('binding_counts', {})}"
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

    # --- v5.2: walk-forward satırı DÜZELTİLDİ ---------------------------
    lines += ["## Walk-forward", ""]
    for block in report["runs"]:
        wf = block.get("walk_forward") or {}
        if not wf:
            lines.append(f"- **{block['label']}**: koşulmadı")
            continue
        windows = wf.get("windows") or []
        total_trades = sum(int(w.get("trades", 0)) for w in windows)
        lines.append(
            f"- **{block['label']}**: "
            f"{wf.get('profitable_windows', 0)}/{wf.get('total_windows', 0)} "
            f"pencere kârlı · {total_trades} işlem · "
            f"toplam {wf.get('total_net_pnl', 0):.4f} USDT · "
            f"en kötü pencere {wf.get('worst_window_net_pnl', 0):.4f} USDT"
        )
        if windows:
            lines.append("")
            lines.append("| Pencere | İşlem | Net PnL | Kazanma | Maks DD | Kârlı |")
            lines.append("|---|---|---|---|---|---|")
            for w in windows:
                lines.append(
                    f"| {w['index']} | {w['trades']} | {w['net_pnl']:.4f} | "
                    f"{w['win_rate'] * 100:.1f}% | {w['max_dd_pct']:.2f}% | "
                    f"{'✅' if w['profitable'] else '❌'} |"
                )
            lines.append("")

    lines += ["## Red sayaçları", ""]
    for block in report["runs"]:
        top = sorted(
            block["rejection_counts"].items(), key=lambda kv: -kv[1],
        )[:8]
        lines.append(
            f"- **{block['label']}**: "
            + (", ".join(f"{k}={v}" for k, v in top) or "yok")
        )
    verdict = report.get("verdict_detail") or {}
    lines += [
        "", "## Hüküm", "",
        f"**Kod:** `{verdict.get('code', '?')}` · "
        f"**Önem:** {verdict.get('severity', '?')}",
        "", report["verdict"], "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Çok sembollü doğrulama koşucusu")
    parser.add_argument("--exchange", choices=("okx", "binance"), default="okx")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--fine-days", type=int, default=0,
                        help="BAŞTAN indirilecek 1m penceresi (gün). "
                             "v5.2 varsayılanı 0: bunun yerine iki geçişli "
                             "hedefli indirme kullanılır.")
    parser.add_argument("--fine-mode", choices=("targeted", "head", "off"),
                        default="targeted",
                        help="targeted = işlem aralıklarını indir (v5.2); "
                             "head = eski davranış (son N gün); off = 1m yok")
    parser.add_argument("--fine-passes", type=int, default=3,
                        help="hedefli indirme kaç kez yinelensin")
    parser.add_argument("--fine-max-requests", type=int, default=600,
                        help="hedefli 1m için toplam sayfa isteği tavanı")
    parser.add_argument("--profile", default="apex")
    parser.add_argument("--max-loss", type=float, default=None,
                        help="işlem başı TABAN net risk (USDT)")
    parser.add_argument("--balance", type=float, default=1_000.0)
    parser.add_argument("--windows", type=int, default=6)
    parser.add_argument("--trailing-variant", default="A_mevcut",

        choices=["A_mevcut","B_tp1_sonrasi","C_tp1_be","D_atr_dinamik"],

        help="v5.6 F bölümü: trailing varyantı")
    parser.add_argument("--drawdown-peak-mode", default="all_time",
                        choices=["all_time", "rolling", "daily"],
                        help="Tepe equity penceresi. all_time=v5.4 davranışı "
                             "(tepe hiç sıfırlanmaz, ilk büyük DD kilitler)")
    parser.add_argument("--drawdown-peak-days", type=int, default=7,
                        help="rolling modda tepe penceresi (gün)")
    parser.add_argument("--costs", default=None,
                        help="ölçülmüş maliyet JSON'u (tools/measure_costs.py)")
    parser.add_argument("--require-cost-coverage", action="store_true",
                        help="Her sembolde spread/giriş-çıkış kayma ölçümü yoksa dur; "
                             "ücret ve gecikmenin gerçek ölçümünü garanti ETMEZ")
    parser.add_argument("--no-costs", action="store_true",
                        help="maliyetleri KAPAT (yalnızca karşılaştırma)")
    parser.add_argument("--compare-no-costs", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="maliyetsiz karşılaştırma koşusu (v5.2: AÇIK)")
    parser.add_argument("--bounds", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="sentetik alt/üst sınır koşuları (v5.2: AÇIK)")
    parser.add_argument("--no-risk-scaling", action="store_true",
                        help="dinamik risk ölçeklemeyi kapat (karşılaştırma)")
    parser.add_argument("--min-trades", type=int, default=200)
    parser.add_argument("--min-wf-trades", type=int, default=DEFAULT_MIN_WF_TRADES,
                        help="WF'de 'kenar yok' demek için asgari işlem")
    parser.add_argument("--data-dir", default="data/validation")
    parser.add_argument("--pause", type=float, default=0.15)
    parser.add_argument("--out", default="docs/dogrulama.json")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    config = _profile_config(args.profile, args.max_loss)
    # v5.6 (F): trailing varyantı — dört çıkış geometrisi ayrı test edilir
    if getattr(args, "trailing_variant", "A_mevcut") != "A_mevcut":
        from dataclasses import replace as _rt

        from backtest.trailing_experiment import VARIANTS, apply_variant
        _v = next(v for v in VARIANTS if v.key == args.trailing_variant)
        config = _rt(config, exit=apply_variant(config.exit, _v))
        logger.info(
            "TRAILING VARYANTI: %s — %s (trail %.2fR / ATR %.1f)",
            _v.key, _v.label, _v.trail_activation_r, _v.trail_atr_multiple,
        )
    if args.drawdown_peak_mode != "all_time":
        from dataclasses import replace as _rp
        config = _rp(config, portfolio=_rp(
            config.portfolio,
            drawdown_peak_mode=args.drawdown_peak_mode,
            drawdown_peak_window_days=args.drawdown_peak_days,
        ))
        logger.info(
            "Tepe equity modu: %s (%d gün) — drawdown kilidi dönemsel çözülür",
            args.drawdown_peak_mode, args.drawdown_peak_days,
        )
    if args.no_risk_scaling:
        from dataclasses import replace

        config = replace(
            config,
            risk_scaling=replace(config.risk_scaling, enabled=False),
        )
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.no_costs:
        costs = CostModel.disabled()
    elif args.costs:
        costs = CostModel.load(args.costs)
    else:
        costs = CostModel()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    keys = [f"{args.exchange}:{s}" for s in symbols]
    if args.require_cost_coverage:
        missing = [key for key in keys if not costs.enabled or any(
            key not in mapping for mapping in (
                costs.measured_spread_bps, costs.measured_slippage_bps,
                costs.measured_exit_slippage_bps,
            )
        )]
        if missing:
            logger.error("Ölçülmüş spread/giriş/çıkış kayması eksik: %s", ", ".join(missing))
            return 2
    logger.info("%s", costs.summary_text(keys))

    bars_5m = args.days * 288
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
    if not candles:
        logger.error("Hiç veri alınamadı — doğrulama yapılamaz")
        return 1

    requested: dict[str, list[tuple[int, int]]] = {}
    fine_stats = {
        "mode": args.fine_mode, "passes": 0, "targeted_windows": 0,
        "requests": 0, "fine_bars_gained": 0, "empty_windows": 0,
        "failures": 0, "truncated": False, "unsupported_exchange_skips": 0,
        "history": [],
    }

    if args.fine_mode == "head" and args.fine_days > 0:
        bars_1m = args.fine_days * 1440
        for symbol in symbols:
            key = f"{args.exchange}:{symbol}"
            if key not in candles:
                continue
            fine_rows = _load_or_fetch(
                args.exchange, symbol, bars_1m, "1m", data_dir, args.pause,
            )
            if fine_rows:
                fine[key] = fine_rows
    elif args.fine_mode == "targeted":
        fine = load_targeted_cache(data_dir, list(candles))
        if fine:
            logger.info(
                "Hedefli 1m önbelleği: %d sembol, %d bar",
                len(fine), sum(len(v) for v in fine.values()),
            )
            for key, rows in fine.items():
                if rows:
                    # Cache may contain disjoint windows: do not label gaps as covered.
                    requested[key] = merge_windows([
                        (c.timestamp, c.timestamp + 60_000) for c in rows
                    ])

    # v5.6: tarihsel funding BİR KEZ yüklenir, tüm bloklara geçirilir.
    from backtest.funding import load_funding_dir
    _ts = [int(c.timestamp) for cs in candles.values() for c in cs]
    funding_rates, _fcov = load_funding_dir(
        data_dir,
        start_ts_ms=min(_ts) if _ts else 0,
        end_ts_ms=max(_ts) if _ts else 0,
    )
    # Funding file names omit exchange (BTC-USDT-SWAP_funding.csv),
    # while engine keys include it (okx:BTC-USDT-SWAP). Exact symbol match,
    # never silently report full coverage for unmatched candle symbols.
    from backtest.funding import match_funding_symbols
    funding_rates, funding_info = match_funding_symbols(
        funding_rates, _fcov, list(candles),
    )
    logger.info(
        "Funding: %s — %s", funding_info["durum"], funding_info["neden"],
    )

    # --- BİRİNCİL KOŞU (iki geçişli 1m ile yinelenir) -------------------
    logger.info("=== BİRİNCİL KOŞU: maliyet açık + dinamik risk ===")
    passes = max(1, args.fine_passes) if args.fine_mode == "targeted" else 1
    primary = None
    result = None
    for pass_no in range(1, passes + 1):
        primary, result = _run_block(
            "birincil", config, candles, fine, costs, args.balance,
            # WF yalnızca son geçişte: her geçişte koşmak gereksiz maliyet
            args.windows if pass_no == passes else 0,
            funding_rates=funding_rates, funding_info=funding_info,
        )
        stats = primary["intrabar"]
        fine_stats["passes"] = pass_no
        fine_stats["history"].append({
            "pass": pass_no,
            "real_1m_bars": stats.get("real_1m_bars", 0),
            "synthetic_bars": stats.get("synthetic_bars", 0),
            "coverage": stats.get("real_coverage_ratio", 0.0),
            "trades": primary["trade_count"],
            "net_pnl": primary["net_pnl"],
        })
        logger.info(
            "Geçiş %d/%d: %d işlem, net %.4f, gerçek 1m kapsama %%.1f".replace("%%", "%"),
            pass_no, passes, primary["trade_count"], primary["net_pnl"],
            stats.get("real_coverage_ratio", 0.0) * 100,
        )
        if args.fine_mode != "targeted" or pass_no == passes:
            break
        fine, changed = refine_fine_data(
            args.exchange, candles, fine, result, data_dir, args.pause,
            requested, args.fine_max_requests, fine_stats,
        )
        if not changed:
            logger.info("Hedefli 1m: yeni veri yok — yineleme durdu")
            # Son geçişte WF koşulmamış olabilir; tamamla.
            if not primary["walk_forward"] and args.windows > 0:
                primary, result = _run_block(
                    "birincil", config, candles, fine, costs, args.balance,
                    args.windows,
            funding_rates=funding_rates, funding_info=funding_info,
        )
                fine_stats["history"][-1]["coverage"] = primary[
                    "intrabar"
                ].get("real_coverage_ratio", 0.0)
            break

    runs: list[dict] = [primary]

    if args.bounds:
        logger.info("=== SENTETİK SINIR KOŞULARI (ALT/ÜST) ===")
        bound_blocks = {}
        for order, label in (
            ("adverse_first", "sentetik ALT sınır (kötümser)"),
            ("favorable_first", "sentetik ÜST sınır (iyimser)"),
        ):
            forced = IntrabarPath(synthetic_order=order, mode="synthetic")
            block, _ = _run_block(
                label, config, candles, fine, costs, args.balance, 0,
                forced_path=forced,
            funding_rates=funding_rates, funding_info=funding_info,
        )
            runs.append(block)
            bound_blocks[order] = block
        adverse = bound_blocks["adverse_first"]
        favorable = bound_blocks["favorable_first"]
        bounds_interval = {
            "adverse_net_pnl": adverse["net_pnl"],
            "adverse_trades": adverse["trade_count"],
            "favorable_net_pnl": favorable["net_pnl"],
            "favorable_trades": favorable["trade_count"],
            "width_usdt": round(
                abs(favorable["net_pnl"] - adverse["net_pnl"]), 4,
            ),
            "spans_zero": adverse["net_pnl"] <= 0 <= favorable["net_pnl"],
        }
        # v5.4: dürüst TTL modeli (fine_window) sentetik yolda dolum
        # ÇÖZEMEZ → iki sınır da 0 işlem üretir. Bunu "0 sınırı" diye
        # raporlamak YANILTICI: gerçek bir sıfır sonuç değil, ölçüm yok.
        if adverse["trade_count"] == 0 and favorable["trade_count"] == 0:
            bounds_interval = {
                "hesaplanabilir": False,
                "neden": (
                    "Sentetik yol 45 sn TTL'i ÇÖZEMEZ; dürüst model dolum "
                    "yapmaz. İki sınır da 0 işlem verdi — bu bir SONUÇ "
                    "değil, ÖLÇÜM YOKLUĞUDUR. Sınır aralığı için gerçek "
                    "1m/tick yolu gerekir."
                ),
                "adverse_trades": 0,
                "favorable_trades": 0,
                "spans_zero": None,
            }
        else:
            bounds_interval["hesaplanabilir"] = True
    else:
        bounds_interval = {}

    optimism_gap = {}
    if args.compare_no_costs and not args.no_costs:
        logger.info("=== KARŞILAŞTIRMA: maliyetsiz (iyimserlik farkı) ===")
        block, _ = _run_block(
            "maliyetsiz karşılaştırma (İYİMSER)", config, candles, fine,
            CostModel.disabled(), args.balance, 0,
            funding_rates=funding_rates, funding_info=funding_info,
        )
        runs.append(block)
        optimism_gap = {
            "with_costs_net_pnl": primary["net_pnl"],
            "with_costs_trades": primary["trade_count"],
            "without_costs_net_pnl": block["net_pnl"],
            "without_costs_trades": block["trade_count"],
            "delta_net_pnl": round(block["net_pnl"] - primary["net_pnl"], 4),
        }

    coverage = costs.coverage(list(candles))
    verdict = decide(
        runs, min_trades=args.min_trades, min_wf_trades=args.min_wf_trades,
        cost_model=costs.as_dict(), min_trades_source="all",
    )
    cost_quality = {}
    if args.costs:
        try:
            raw_costs = json.loads(Path(args.costs).read_text(encoding="utf-8"))
            cost_quality = raw_costs.get("measurement_quality") or {}
        except (OSError, ValueError):
            cost_quality = {}

    report = json_safe({
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
            "fine_mode": args.fine_mode,
            "fine_days": args.fine_days,
            "fine_bars": sum(len(v) for v in fine.values()),
            "fine_symbols": len(fine),
        },
        "fine_pass": fine_stats,
        "funding": funding_info,
        "cost_model": costs.as_dict(),
        "cost_summary": costs.summary_text(list(candles)),
        "cost_coverage": coverage,
        "cost_quality": cost_quality,
        "risk_scaling_config": {
            "enabled": config.risk_scaling.enabled,
            "min_risk_usdt": config.risk_scaling.min_risk_usdt,
            "max_risk_usdt": config.risk_scaling.max_risk_usdt,
            "drawdown_start_pct": config.risk_scaling.drawdown_start_pct,
            "drawdown_floor_pct": config.risk_scaling.drawdown_floor_pct,
            "hard_cost_fraction_of_risk":
                config.risk_scaling.hard_cost_fraction_of_risk,
        },
        "runs": runs,
        "optimism_gap": optimism_gap,
        "bounds_interval": bounds_interval,
        "verdict": verdict.render(),
        "verdict_detail": verdict.as_dict(),
    })
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    md = out.with_suffix(".md")
    md.write_text(build_markdown(report), encoding="utf-8")
    logger.info("Rapor: %s", out)
    logger.info("Rapor (Markdown): %s", md)
    logger.info("HÜKÜM [%s]: %s", verdict.code, verdict.headline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
