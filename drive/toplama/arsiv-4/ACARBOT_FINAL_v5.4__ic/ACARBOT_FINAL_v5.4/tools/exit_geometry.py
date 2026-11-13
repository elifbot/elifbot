"""ÇIKIŞ GEOMETRİSİ KARŞILAŞTIRMASI — aynı adaylar, iki geometri.

Sorulan soru: "Önerilen yeni çıkış geometrisi (stop 2.0 ATR, trail 1.0 ATR,
activasyon 1.0R, TP1 1.5R) beklentiyi pozitife çeviriyor mu?"

Bu soru ancak GİRİŞ sabit tutularak cevaplanır. Aynı aday evreni, aynı
maliyetler, yalnız çıkış kuralları değişir. Böylece fark çıkışa atfedilir.

Ayrıca şu soru cevaplanır: maliyetin R'nin %15'ine inmesi için stop
mesafesi ne kadar geniş olmalı? Çünkü maliyet_R = maliyet_oranı /
stop_kesri — stop genişledikçe maliyet payı KÜÇÜLÜR. Bu, çıkış
parametrelerinden bağımsız yapısal bir kaldıraçtır.

Mum içi sıra belirsizliği: kötümser (stop önce) ve iyimser (hedef önce)
İKİ SINIR olarak raporlanır.

Kullanım:
    python3 -m tools.exit_geometry --days 90 \
        --costs docs/maliyet_olcum_v5.2.json --out docs/cikis_geometri.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np

from backtest.costs import CostModel
from backtest.engine import BacktestEngine
from infra.market_data.models import Candle
from tools.gate_attribution import _load_cached_or_fetch
from tools.validate_strategy import _profile_config

logger = logging.getLogger("exit_geometry")

DEFAULT_SYMBOLS = (
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP",
)

# Mevcut üretim geometrisi (core/config.py exit bloğu ile aynı)
CURRENT = {
    "ad": "MEVCUT",
    "stop_atr": 1.5,
    "tp1_r": 1.0,
    "be_activation_r": 1.0,
    "trail_activation_r": 0.75,
    "trail_atr": 2.0,
}
# Kullanıcının önerdiği geometri
PROPOSED = {
    "ad": "ONERILEN",
    "stop_atr": 2.0,
    "tp1_r": 1.5,
    "be_activation_r": 0.75,
    "trail_activation_r": 1.0,
    "trail_atr": 1.0,
}


def simulate(
    side: str,
    entry: float,
    base_stop_fraction: float,
    forward: list[Candle],
    geom: dict,
    max_bars: int,
    adverse_first: bool,
) -> dict | None:
    """Tek aday, tek geometri. Çıkış R cinsinden döner.

    Stop mesafesi ATR oranıyla ölçeklenir: sinyalin stop_fraction'ı
    referans stop_atr (1.5) ile üretilmiştir.
    """
    scale = geom["stop_atr"] / CURRENT["stop_atr"]
    stop_fraction = base_stop_fraction * scale
    r_price = entry * stop_fraction
    if r_price <= 0 or not forward:
        return None
    sign = 1.0 if side == "LONG" else -1.0
    trail_dist_r = geom["trail_atr"] / geom["stop_atr"]
    stop_r = -1.0
    best_r = 0.0
    tp1 = geom["tp1_r"]

    def excursion(candle) -> tuple[float, float]:
        if sign > 0:
            return (
                (candle.high - entry) / r_price,
                (candle.low - entry) / r_price,
            )
        return (
            (entry - candle.low) / r_price,
            (entry - candle.high) / r_price,
        )

    for index, candle in enumerate(forward[:max_bars]):
        hi_r, lo_r = excursion(candle)
        target_hit = hi_r >= tp1
        stop_hit = lo_r <= stop_r
        if target_hit and stop_hit:
            # Aynı mumda ikisi: sıra BİLİNMİYOR → sınır seçimi
            if adverse_first:
                return {"r": stop_r, "bars": index + 1, "exit": "stop_belirsiz"}
            return {"r": tp1, "bars": index + 1, "exit": "tp1_belirsiz"}
        if stop_hit:
            return {"r": stop_r, "bars": index + 1, "exit": "stop"}
        if target_hit:
            return {"r": tp1, "bars": index + 1, "exit": "tp1"}
        # Mum kapanışında korumaları güncelle (muhafazakâr: stop önce denendi)
        best_r = max(best_r, hi_r)
        if best_r >= geom["be_activation_r"]:
            stop_r = max(stop_r, 0.0)
        if best_r >= geom["trail_activation_r"]:
            stop_r = max(stop_r, best_r - trail_dist_r)

    window = forward[:max_bars]
    last_r = sign * (window[-1].close - entry) / r_price
    return {"r": last_r, "bars": len(window), "exit": "ufuk"}


def stat(values: list[float]) -> dict:
    n = len(values)
    if not n:
        return {"n": 0}
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    se = float(arr.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0
    wins = int((arr > 0).sum())
    gross_win = float(arr[arr > 0].mean()) if wins else 0.0
    losses = arr[arr <= 0]
    gross_loss = float(losses.mean()) if len(losses) else 0.0
    return {
        "n": n,
        "mean_r": round(mean, 6),
        "se": round(se, 6),
        "ci_low": round(mean - 1.96 * se, 6),
        "ci_high": round(mean + 1.96 * se, 6),
        "kazanma_orani": round(wins / n, 4),
        "ort_kazanc_r": round(gross_win, 6),
        "ort_kayip_r": round(gross_loss, 6),
        "odul_risk": (
            round(gross_win / abs(gross_loss), 6) if gross_loss else None
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Çıkış geometrisi karşılaştırması")
    p.add_argument("--exchange", default="okx")
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--profile", default="apex")
    p.add_argument("--balance", type=float, default=1000.0)
    p.add_argument("--costs", type=str, default=None)
    p.add_argument("--data-dir", type=str, default="data/validation")
    p.add_argument("--max-bars", type=int, default=48)
    p.add_argument("--pause", type=float, default=0.25)
    p.add_argument("--target-cost-share", type=float, default=0.15)
    p.add_argument("--out", type=str, default="docs/cikis_geometri.json")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir)
    bars = args.days * 288
    keys = [f"{args.exchange}:{s.strip()}" for s in args.symbols.split(",") if s.strip()]
    candles: dict[str, list[Candle]] = {}
    for key in keys:
        rows = _load_cached_or_fetch(args.exchange, key, bars, data_dir, args.pause)
        if rows:
            candles[key] = rows[-bars:] if len(rows) > bars else rows
    if not candles:
        logger.error("Veri yok")
        return 2

    config = _profile_config(args.profile, None)
    engine = BacktestEngine(config, initial_balance=args.balance)
    engine.gate_probe = []
    costs = CostModel.load(args.costs) if args.costs else CostModel()
    logger.info("%s", costs.summary_text(keys))
    logger.info("Aday toplama: %d sembol, %d gün", len(candles), args.days)
    engine.run(candles, cost_model=costs)
    probe = [c for c in engine.gate_probe if c.get("entry_ref")]
    logger.info("Aday: %d", len(probe))

    index = {
        s: {c.timestamp: i for i, c in enumerate(rows)}
        for s, rows in candles.items()
    }
    results: dict[str, dict[str, list[float]]] = {
        g["ad"]: {"kotumser": [], "iyimser": []} for g in (CURRENT, PROPOSED)
    }
    cost_shares: dict[str, list[float]] = {g["ad"]: [] for g in (CURRENT, PROPOSED)}
    exit_reasons: dict[str, dict[str, int]] = {g["ad"]: {} for g in (CURRENT, PROPOSED)}
    raw_cost_rates: list[float] = []
    base_stops: list[float] = []

    for cand in probe:
        sym = cand["symbol"]
        series = candles.get(sym)
        pos = index.get(sym, {}).get(int(cand["ts_ms"]))
        if series is None or pos is None:
            continue
        forward = series[pos + 1: pos + 1 + args.max_bars]
        if len(forward) < 2:
            continue
        entry = float(cand["entry_ref"])
        base_stop = float(cand["stop_fraction"])
        cost_rate = costs.round_trip_rate(sym)
        raw_cost_rates.append(cost_rate)
        base_stops.append(base_stop)
        for geom in (CURRENT, PROPOSED):
            scale = geom["stop_atr"] / CURRENT["stop_atr"]
            cost_r = cost_rate / (base_stop * scale)
            cost_shares[geom["ad"]].append(cost_r)
            for label, adverse in (("kotumser", True), ("iyimser", False)):
                sim = simulate(
                    cand["side"], entry, base_stop, forward, geom,
                    args.max_bars, adverse,
                )
                if sim is None:
                    continue
                results[geom["ad"]][label].append(sim["r"] - cost_r)
                if label == "kotumser":
                    bucket = exit_reasons[geom["ad"]]
                    bucket[sim["exit"]] = bucket.get(sim["exit"], 0) + 1

    summary = {}
    for geom in (CURRENT, PROPOSED):
        ad = geom["ad"]
        summary[ad] = {
            "geometri": geom,
            "net_kotumser": stat(results[ad]["kotumser"]),
            "net_iyimser": stat(results[ad]["iyimser"]),
            "maliyet_r": stat(cost_shares[ad]),
            "cikis_nedenleri": exit_reasons[ad],
        }

    # Yapsal kaldirac: maliyet payini hedefe indirmek icin stop genisligi
    mean_cost = float(np.mean(raw_cost_rates)) if raw_cost_rates else 0.0
    mean_stop = float(np.mean(base_stops)) if base_stops else 0.0
    needed_stop = mean_cost / args.target_cost_share if args.target_cost_share else 0.0
    structural = {
        "ort_maliyet_orani": round(mean_cost, 8),
        "ort_mevcut_stop_kesri": round(mean_stop, 8),
        "hedef_maliyet_payi": args.target_cost_share,
        "gereken_stop_kesri": round(needed_stop, 8),
        "gereken_genisleme_kati": (
            round(needed_stop / mean_stop, 4) if mean_stop else None
        ),
        "yorum": (
            "Maliyet payı = maliyet_oranı / stop_kesri. Çıkış parametreleri "
            "bunu DEĞİŞTİRMEZ. Payı düşürmenin tek yolu stop mesafesini "
            "genişletmek (daha yüksek zaman dilimi) veya daha likit sembol. "
            "Önerilen 1.5→2.0 ATR değişikliği payı yalnız 1,33x düşürür."
        ),
    }

    cur = summary["MEVCUT"]["net_kotumser"]
    prop = summary["ONERILEN"]["net_kotumser"]
    improved = (prop.get("mean_r") or 0) > (cur.get("mean_r") or 0)
    positive = (prop.get("ci_low") or -1) > 0
    if positive:
        verdict = "ONERILEN_GEOMETRI_POZITIF"
        detail = "Önerilen geometrinin net beklentisi %95 alt sınırıyla pozitif."
    elif improved:
        verdict = "IYILESME_VAR_AMA_NEGATIF"
        detail = (
            f"Önerilen geometri beklentiyi iyileştirdi "
            f"({cur.get('mean_r')} → {prop.get('mean_r')} R) ama hâlâ NEGATİF. "
            "Giriş kenarı olmadan çıkış ayarı zararı ancak azaltır; kâr üretmez. "
            "Yapısal sorun maliyetin stop mesafesine oranı."
        )
    else:
        verdict = "ONERILEN_GEOMETRI_ISE_YARAMADI"
        detail = (
            f"Önerilen geometri beklentiyi iyileştirmedi "
            f"({cur.get('mean_r')} → {prop.get('mean_r')} R). "
            "Giriş kenarı yok; çıkış ayarı bu tabloyu değiştirmez."
        )

    report = {
        "arac": "tools.exit_geometry",
        "days": args.days, "symbols": list(candles),
        "aday": len(probe), "max_bars": args.max_bars,
        "maliyet_kaynagi": "ÖLÇÜLMÜŞ" if args.costs else "VARSAYILAN",
        "yol_cozunurlugu": "5m kaba mum; mum içi sıra İKİ SINIR",
        "tp1_modeli": "TP1'de TAM çıkış (kısmi çıkış modellenmedi)",
        "summary": summary,
        "yapisal_kaldirac": structural,
        "verdict": verdict, "verdict_detail": detail,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False),
        encoding="utf-8",
    )
    logger.info("Rapor: %s", out)
    for ad in ("MEVCUT", "ONERILEN"):
        s = summary[ad]["net_kotumser"]
        logger.info(
            "%s: net %s R [%s, %s] | kazanma %s | maliyet %s R",
            ad, s.get("mean_r"), s.get("ci_low"), s.get("ci_high"),
            s.get("kazanma_orani"), summary[ad]["maliyet_r"].get("mean_r"),
        )
    logger.info(
        "YAPISAL: maliyet payını %%%.0f'e indirmek için stop %.4fx genişlemeli",
        args.target_cost_share * 100, structural["gereken_genisleme_kati"] or 0,
    )
    logger.info("HÜKÜM [%s]: %s", verdict, detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
