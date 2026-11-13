"""GİRİŞ KENARI TESTİ — çıkışa dokunmadan önce sorulacak soru.

Sorulan soru tek: "Bu sinyalin yön bilgisi var mı?"

Önceki analizlerin hatası şuydu: çıkış geometrisi (trailing/TP) ile
giriş kenarı birbirine karıştırıldı. Kazananların +0,44R'de kapanması
"çıkış kötü" diye yorumlandı. Ama aynı veri "fiyat zaten lehimize
gitmiyor" diye de yorumlanabilir. İkisini ayırmanın tek yolu:

  1. Bütün adayları al (kapıların HİÇBİRİNE bakma, drawdown dahil).
  2. Çıkışı SABİT ve SİMETRİK tut: stop -1R, hedef +1R.
     Böylece çıkış asimetrisi denklemden çıkar.
  3. Ayrıca "N bar sonra çık" varyantı: saf yön bilgisi ölçümü.
  4. Aynı sembol / aynı yön / aynı saat dağılımıyla RASTGELE giriş
     baz çizgisi kur (permütasyon testi).
  5. Karar: brüt ileri getiri, maliyet + 2 standart hatanın üstünde
     değilse giriş mantığı kenar TAŞIMIYOR. Çıkışı optimize etmek
     boşuna; sinyali yeniden tasarlamak gerekir.

Mum içi sıra belirsizliği İKİ SINIR olarak raporlanır:
  - kötümser: aynı mumda hem stop hem hedef değdiyse STOP sayılır
  - iyimser : aynı mumda ikisi de değdiyse HEDEF sayılır
Tek bir sayı verilmez; aralık verilir. 5m mumda 1R'lik iki tarafın
hangisinin önce olduğu BİLİNEMEZ.

Kullanım:
    python3 -m tools.entry_edge --days 90 \
        --costs docs/maliyet_olcum_v5.2.json --out docs/giris_kenari.json
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

logger = logging.getLogger("entry_edge")

DEFAULT_SYMBOLS = (
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP",
)


def resample(rows: list[Candle], minutes: int, base_minutes: int = 5) -> list[Candle]:
    """Kaba mumları daha yüksek zaman dilimine TOPLA (uydurma yok).

    5m -> 15m/60m. Her kova: open=ilk.open, close=son.close,
    high=max, low=min, volume=toplam. Eksik kovalar atlanır.
    Amaç: maliyetin stop mesafesine oranını düşüren zaman dilimini
    sınamak. ATR ~ sqrt(zaman) olduğundan stop genişler, maliyet
    sabit kalır → maliyet payı küçülür.
    """
    if minutes <= base_minutes:
        return rows
    factor = minutes // base_minutes
    step = minutes * 60_000
    buckets: dict[int, list[Candle]] = {}
    for c in rows:
        buckets.setdefault(c.timestamp - (c.timestamp % step), []).append(c)
    out: list[Candle] = []
    for key in sorted(buckets):
        group = sorted(buckets[key], key=lambda c: c.timestamp)
        if len(group) < factor:
            continue
        out.append(Candle(
            timestamp=key, open=group[0].open, close=group[-1].close,
            high=max(c.high for c in group), low=min(c.low for c in group),
            volume=sum(c.volume for c in group),
        ))
    return out


# ----------------------------------------------------------------------
# Simetrik çıkış yolu
# ----------------------------------------------------------------------

def symmetric_path(
    side: str,
    entry: float,
    r_price: float,
    forward: list[Candle],
    max_bars: int,
) -> dict | None:
    """Stop -1R / hedef +1R, sabit. Mum içi belirsizlik iki sınır.

    Her iki sınır için de R sonucu ve bar sayısı döner.
    """
    if r_price <= 0 or not forward:
        return None
    sign = 1.0 if side == "LONG" else -1.0
    stop = entry - sign * r_price
    target = entry + sign * r_price
    out: dict = {}
    for label, adverse_first in (("kotumser", True), ("iyimser", False)):
        resolved = False
        for index, candle in enumerate(forward[:max_bars]):
            if sign > 0:
                hit_stop = candle.low <= stop
                hit_target = candle.high >= target
            else:
                hit_stop = candle.high >= stop
                hit_target = candle.low <= target
            if hit_stop and hit_target:
                r = -1.0 if adverse_first else 1.0
                out[label] = {"r": r, "bars": index + 1, "exit": "ambiguous"}
                resolved = True
                break
            if hit_stop:
                out[label] = {"r": -1.0, "bars": index + 1, "exit": "stop"}
                resolved = True
                break
            if hit_target:
                out[label] = {"r": 1.0, "bars": index + 1, "exit": "target"}
                resolved = True
                break
        if not resolved:
            window = forward[:max_bars]
            last = window[-1].close
            out[label] = {
                "r": sign * (last - entry) / r_price,
                "bars": len(window),
                "exit": "horizon",
            }
    # Yol boyunca en iyi / en kötü excursion (R cinsinden)
    window = forward[:max_bars]
    if sign > 0:
        mfe = (max(c.high for c in window) - entry) / r_price
        mae = (min(c.low for c in window) - entry) / r_price
    else:
        mfe = (entry - min(c.low for c in window)) / r_price
        mae = (entry - max(c.high for c in window)) / r_price
    out["mfe_r"] = mfe
    out["mae_r"] = mae
    out["ambiguous"] = out["kotumser"]["r"] != out["iyimser"]["r"]
    return out


def horizon_return(
    side: str, entry: float, r_price: float, forward: list[Candle], bars: int,
) -> float | None:
    """N bar sonraki kapanışa göre brüt R getirisi (yol bağımsız)."""
    if r_price <= 0 or len(forward) < bars:
        return None
    sign = 1.0 if side == "LONG" else -1.0
    return sign * (forward[bars - 1].close - entry) / r_price


def horizon_at(
    closes: np.ndarray, pos: int, sign: float, stop_fraction: float, bars: int,
) -> float:
    """Kopya YOK: kapanış dizisinde doğrudan indeks. Permütasyon için."""
    entry = closes[pos]
    r_price = entry * stop_fraction
    if r_price <= 0:
        return float("nan")
    return float(sign * (closes[pos + bars] - entry) / r_price)


# ----------------------------------------------------------------------
# İstatistik
# ----------------------------------------------------------------------

def mean_se(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "se": None, "ci_low": None, "ci_high": None}
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    se = float(arr.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0
    return {
        "n": n,
        "mean": round(mean, 6),
        "se": round(se, 6),
        "ci_low": round(mean - 1.96 * se, 6),
        "ci_high": round(mean + 1.96 * se, 6),
    }


def permutation_test(
    observed: float, null_means: list[float],
) -> dict:
    """Tek taraflı: rastgele girişlerin kaçı bu kadar iyi?"""
    if not null_means:
        return {"p": None, "n_perm": 0}
    arr = np.asarray(null_means, dtype=float)
    better = int((arr >= observed).sum())
    n = len(null_means)
    return {
        "p": round((better + 1) / (n + 1), 6),
        "n_perm": n,
        "null_mean": round(float(arr.mean()), 6),
        "null_se": round(float(arr.std(ddof=1)), 6) if n > 1 else 0.0,
        "null_p95": round(float(np.percentile(arr, 95)), 6),
    }


# ----------------------------------------------------------------------
# Ana akış
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Giriş kenarı testi (kapısız)")
    p.add_argument("--exchange", default="okx")
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--profile", default="apex")
    p.add_argument("--balance", type=float, default=1000.0)
    p.add_argument("--costs", type=str, default=None)
    p.add_argument("--data-dir", type=str, default="data/validation")
    p.add_argument("--horizon-bars", type=int, default=12,
                   help="Simetrik çıkış ve ufuk için azami bar (12 x 5m = 1 saat)")
    p.add_argument("--horizons", default="3,6,12,24,48",
                   help="Saf yön getirisi ufukları (bar)")
    p.add_argument("--permutations", type=int, default=500)
    p.add_argument("--seed", type=int, default=20261108)
    p.add_argument("--pause", type=float, default=0.25)
    p.add_argument("--resample-minutes", type=int, default=5,
                   help="5m önbelleği bu dakikaya topla (5|15|60|240)")
    p.add_argument("--out", type=str, default="docs/giris_kenari.json")
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
            # Önbellek daha uzunsa İSTENEN gün kadarına dilimle (son N bar).
            # Dilimlenmezse --days etiketi gerçek kapsamı yansıtmaz.
            sliced = rows[-bars:] if len(rows) > bars else rows
            candles[key] = resample(sliced, args.resample_minutes)
    if not candles:
        logger.error("Veri yok")
        return 2

    from dataclasses import replace as _replace

    config = _profile_config(args.profile, None)
    if args.resample_minutes > 5:
        _tf = f"{args.resample_minutes}m" if args.resample_minutes < 60 else (
            f"{args.resample_minutes // 60}h"
        )
        config = _replace(config, data=_replace(
            config.data, timeframe=_tf,
            timeframe_ms=args.resample_minutes * 60_000,
        ))
    engine = BacktestEngine(config, initial_balance=args.balance)
    engine.gate_probe = []

    costs = CostModel.load(args.costs) if args.costs else CostModel()
    logger.info("%s", costs.summary_text(keys))

    logger.info("Aday toplama koşusu: %d sembol, %d gün", len(candles), args.days)
    engine.run(candles, cost_model=costs)
    probe = [c for c in engine.gate_probe if c.get("entry_ref")]
    logger.info("Toplam aday: %d (kapılar uygulanmadan önceki evren)", len(probe))

    # Sembol -> zaman dizini (hızlı ileri pencere)
    index: dict[str, dict[int, int]] = {
        s: {c.timestamp: i for i, c in enumerate(rows)}
        for s, rows in candles.items()
    }
    tf_ms = config.data.timeframe_ms

    # ---- 1) Simetrik çıkış + ufuk getirileri -------------------------
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    rows_out: list[dict] = []
    for cand in probe:
        sym = cand["symbol"]
        series = candles.get(sym)
        pos = index.get(sym, {}).get(int(cand["ts_ms"]))
        if series is None or pos is None:
            continue
        entry = float(cand["entry_ref"])
        r_price = entry * float(cand["stop_fraction"])
        forward = series[pos + 1:]
        if len(forward) < max(horizons):
            continue
        sim = symmetric_path(
            cand["side"], entry, r_price, forward, args.horizon_bars,
        )
        if sim is None:
            continue
        cost_rate = costs.round_trip_rate(sym) if costs is not None else 0.0
        cost_r = cost_rate / float(cand["stop_fraction"])
        rec = {
            "symbol": sym, "ts_ms": int(cand["ts_ms"]), "side": cand["side"],
            "score": float(cand.get("score") or 0.0),
            "stop_fraction": float(cand["stop_fraction"]),
            "cost_r": cost_r,
            "mfe_r": sim["mfe_r"], "mae_r": sim["mae_r"],
            "ambiguous": sim["ambiguous"],
            "sym_kotumser_r": sim["kotumser"]["r"],
            "sym_iyimser_r": sim["iyimser"]["r"],
            "sym_exit_kotumser": sim["kotumser"]["exit"],
        }
        for h in horizons:
            rec[f"fwd_{h}"] = horizon_return(
                cand["side"], entry, r_price, forward, h,
            )
        rows_out.append(rec)

    if not rows_out:
        logger.error("Ölçülebilir aday yok")
        return 2

    # ---- 2) Rastgele giriş baz çizgisi (aynı sembol/yön/saat) ---------
    # Saat eşleşmesi: her adayın saatini koru, günü rastgele kaydır.
    logger.info("Permütasyon testi: %d tekrar (vektörel)", args.permutations)
    usable = [
        r for r in rows_out
        if all(r.get(f"fwd_{h}") is not None for h in horizons)
    ]
    closes_np = {sym: np.asarray([c.close for c in rows], dtype=float)
                 for sym, rows in candles.items()}
    day_bars = max(1, int(86_400_000 / tf_ms))
    max_h = max(horizons)
    # Her kullanilabilir aday icin (sembol, taban konum, yon, stop)
    base = []
    for rec in usable:
        pos = index[rec["symbol"]].get(rec["ts_ms"])
        if pos is None:
            continue
        base.append((
            rec["symbol"], pos,
            1.0 if rec["side"] == "LONG" else -1.0,
            rec["stop_fraction"],
        ))
    perm_means: dict[int, list[float]] = {h: [] for h in horizons}
    nprng = np.random.default_rng(args.seed)
    for _ in range(args.permutations):
        acc: dict[int, list[float]] = {h: [] for h in horizons}
        shifts = nprng.integers(-args.days, args.days, size=len(base)) * day_bars
        for (sym, pos, sign, stop), shift in zip(base, shifts):
            arr = closes_np[sym]
            j = pos + int(shift)
            if j < 0 or j + max_h >= len(arr):
                continue
            for h in horizons:
                val = horizon_at(arr, j, sign, stop, h)
                if math.isfinite(val):
                    acc[h].append(val)
        for h in horizons:
            if acc[h]:
                perm_means[h].append(float(np.mean(acc[h])))

    # ---- 3) Özet -----------------------------------------------------
    cost_r_values = [r["cost_r"] for r in rows_out]
    summary = {
        "aday_toplam": len(probe),
        "olculebilir_aday": len(rows_out),
        "mum_icin_belirsiz_orani": round(
            sum(1 for r in rows_out if r["ambiguous"]) / len(rows_out), 4,
        ),
        "maliyet_r": mean_se(cost_r_values),
        "simetrik_1R": {
            "kotumser": mean_se([r["sym_kotumser_r"] for r in rows_out]),
            "iyimser": mean_se([r["sym_iyimser_r"] for r in rows_out]),
        },
        "mfe_r": mean_se([r["mfe_r"] for r in rows_out]),
        "mae_r": mean_se([r["mae_r"] for r in rows_out]),
        "ufuklar": {},
    }
    for h in horizons:
        vals = [r[f"fwd_{h}"] for r in rows_out if r.get(f"fwd_{h}") is not None]
        st = mean_se(vals)
        perm = permutation_test(st["mean"] or 0.0, perm_means[h])
        cost_mean = summary["maliyet_r"]["mean"] or 0.0
        threshold = cost_mean + 2 * (st["se"] or 0.0)
        st["perm"] = perm
        st["maliyet_artı_2se_esigi"] = round(threshold, 6)
        st["kenar_var_mi"] = bool(
            st["mean"] is not None and st["mean"] > threshold
            and perm["p"] is not None and perm["p"] < 0.05
        )
        summary["ufuklar"][str(h)] = st

    # Skor kalibrasyonu: skor ile ileri getiri ilişkisi
    h_main = horizons[len(horizons) // 2]
    pairs = [
        (r["score"], r[f"fwd_{h_main}"]) for r in rows_out
        if r.get(f"fwd_{h_main}") is not None and r["score"] > 0
    ]
    if len(pairs) > 2:
        xs = np.asarray([p[0] for p in pairs])
        ys = np.asarray([p[1] for p in pairs])
        corr = float(np.corrcoef(xs, ys)[0, 1]) if xs.std() > 0 else 0.0
        summary["skor_kalibrasyonu"] = {
            "ufuk_bar": h_main, "n": len(pairs),
            "pearson_r": round(corr, 6),
            "not": "Skor arttıkça ileri getiri artmıyorsa skor bilgi taşımıyor.",
        }

    any_edge = any(v["kenar_var_mi"] for v in summary["ufuklar"].values())
    sym_pess = summary["simetrik_1R"]["kotumser"]["mean"] or 0.0
    sym_opt = summary["simetrik_1R"]["iyimser"]["mean"] or 0.0
    if any_edge:
        verdict = "GIRIS_KENARI_VAR_ADAY"
        detail = (
            "En az bir ufukta brüt ileri getiri maliyet + 2SE eşiğini geçti ve "
            "permütasyon testinde rastgele girişlerden ayrıştı. Çıkış tasarımı "
            "ANCAK bu noktadan sonra anlam kazanır."
        )
    elif sym_opt > 0 >= sym_pess:
        verdict = "BELIRSIZ_MUM_ICI_SIRA"
        detail = (
            "Simetrik 1R çıkışta kötümser sınır negatif, iyimser sınır pozitif. "
            "5m mumda hangi tarafın önce olduğu BİLİNMİYOR. Karar için 1m/tick "
            "yolu gerekir; bu veriyle kenar iddia edilemez."
        )
    else:
        verdict = "GIRIS_KENARI_YOK"
        detail = (
            "Hiçbir ufukta brüt ileri getiri maliyet + 2SE eşiğini geçmedi. "
            "Simetrik çıkışla da kazanç yok. Sorun ÇIKIŞ DEĞİL GİRİŞ: yön "
            "bilgisi yok. Çıkış parametrelerini optimize etmek bu tabloyu "
            "değiştirmez; sinyal mantığı yeniden tasarlanmalı."
        )

    report = {
        "arac": "tools.entry_edge",
        "exchange": args.exchange,
        "symbols": list(candles),
        "days": args.days,
        "profile": args.profile,
        "timeframe_ms": tf_ms,
        "resample_minutes": args.resample_minutes,
        "horizon_bars": args.horizon_bars,
        "permutations": args.permutations,
        "seed": args.seed,
        "costs_file": args.costs,
        "maliyet_kaynagi": "ÖLÇÜLMÜŞ" if args.costs else "VARSAYILAN",
        "yol_cozunurlugu": f"{tf_ms // 1000}s kaba mum; mum içi sıra İKİ SINIR",
        "summary": summary,
        "verdict": verdict,
        "verdict_detail": detail,
        "kurallar": {
            "kenar_esigi": "brüt ileri getiri > maliyet_R + 2*SE ve perm p<0.05",
            "n_uyarisi": "n<30 ise yön iddiası YASAK",
        },
        "rows": rows_out,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False),
        encoding="utf-8",
    )
    logger.info("Rapor: %s", out)
    logger.info("HÜKÜM [%s]: %s", verdict, detail)
    for h, st in summary["ufuklar"].items():
        logger.info(
            "  ufuk %s bar: brüt %s R (SE %s) | maliyet+2SE %s | perm p=%s | kenar=%s",
            h, st["mean"], st["se"], st["maliyet_artı_2se_esigi"],
            st["perm"]["p"], st["kenar_var_mi"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
