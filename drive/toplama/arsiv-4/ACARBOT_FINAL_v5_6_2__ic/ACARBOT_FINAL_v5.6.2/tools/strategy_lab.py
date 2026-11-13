"""Yeni giriş stratejileri laboratuvarı — v5.6 (D bölümü).

AMAÇ
-----
Altı yeni giriş stratejisini BAĞIMSIZ olarak, maliyetler dahil,
look-ahead olmadan taramak. Bu bir ELEME aracıdır; production
motorun yerine geçmez.

SİMÜLATÖRÜN SINIRLARI (açıkça belirtilir)
-----------------------------------------
* Bu, üretim motoru (BacktestEngine) DEĞİL; basit bir tarama
  simülatörüdür. Kısmi kâr alma, trailing, portföy limitleri,
  drawdown kilidi YOKTUR. Amaç: giriş sinyalinin HAM kenarını
  ölçmek, çıkış yönetiminin etkisini dışarıda bırakmak.
* Çıkış: stop veya +1R hedef. Aynı mumda ikisi de varsa
  ÖNCE STOP (kötümser, look-ahead'e karşı).
* Giriş: sinyalden SONRAKİ mumun AÇILIŞI (sinyal mumunun
  kapanışıyla işlem açmak look-ahead olurdu).
* Maker/taker ayrımı YOK; taker komisyonu uygulanır (kötümser).

Bu yüzden sonuçlar üretim performans tahmini DEĞİL, giriş kenarı
göstergesidir. Pozitif çıkan strateji ayrıca üretim motoruyla
doğrulanmadan canlıya alınamaz.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.entry_strategies import STRATEGIES  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("strategy_lab")

MIN_TRADES = 30
TARGET_R = 1.0


def simulate(cs, fn, fee_rate: float, slip_bps: float, higher_tf=None,
             ht_factor: int = 12):
    """Tek strateji, tek sembol. Look-ahead yok.

    MTF için üst zaman dilimi yalnız KAPANMIŞ mumlarla verilir:
    i. alt-TF mumunun zamanından önce kapanan üst-TF mumları.
    """
    trades = []
    i = 30
    # Üst TF mumunun kapanış zamanı = timestamp + factor * bar_süresi
    bar_ms = (cs[1].timestamp - cs[0].timestamp) if len(cs) > 1 else 300_000
    ht_close_ms = ht_factor * bar_ms
    while i < len(cs) - 1:
        if fn.__code__.co_argcount >= 3:
            ht = None
            if higher_tf:
                now_ms = cs[i].timestamp + bar_ms   # i. mumun kapanışı
                ht = [c for c in higher_tf
                      if c.timestamp + ht_close_ms <= now_ms]
                if len(ht) < 55:
                    i += 1
                    continue
            sig = fn(cs, i, ht)
        else:
            sig = fn(cs, i)
        if sig is None:
            i += 1
            continue
        nxt = cs[i + 1]
        entry = float(nxt.open)
        if entry <= 0:
            i += 1
            continue
        # Stop mesafesini sinyal mumundan taşı, giriş fiyatına göre yeniden kur
        frac = sig.stop_fraction
        if frac <= 0:
            i += 1
            continue
        long = sig.side == "LONG"
        stop = entry * (1 - frac) if long else entry * (1 + frac)
        target = entry * (1 + frac * TARGET_R) if long else entry * (1 - frac * TARGET_R)
        exit_px, reason, exit_idx = None, "", None
        for j in range(i + 1, min(i + 200, len(cs))):
            b = cs[j]
            hi, lo = float(b.high), float(b.low)
            hit_stop = lo <= stop if long else hi >= stop
            hit_tgt = hi >= target if long else lo <= target
            if hit_stop:                      # kötümser: önce stop
                exit_px, reason, exit_idx = stop, "stop", j
                break
            if hit_tgt:
                exit_px, reason, exit_idx = target, "target", j
                break
        if exit_px is None:
            exit_idx = min(i + 199, len(cs) - 1)
            exit_px, reason = float(cs[exit_idx].close), "timeout"
        direction = 1.0 if long else -1.0
        gross_r = direction * (exit_px - entry) / (entry * frac)
        cost_usdt_frac = 2 * fee_rate + 2 * slip_bps / 1e4
        net_r = gross_r - cost_usdt_frac / frac
        trades.append({
            "side": sig.side, "gross_r": gross_r, "net_r": net_r,
            "reason": reason, "stop_fraction": frac,
            "bars_held": exit_idx - i,
            "approximation": sig.approximation,
        })
        i = exit_idx + 1                       # örtüşen işlem yok
    return trades


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"islem": 0, "hukum": "SINYAL_YOK"}
    net = [t["net_r"] for t in trades]
    gross = [t["gross_r"] for t in trades]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None
    eq, peak, mdd = 0.0, 0.0, 0.0
    for x in net:
        eq += x
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    mean_net = statistics.mean(net)
    se = statistics.stdev(net) / (n ** 0.5) if n > 2 else None
    ci = (mean_net - 1.96 * se, mean_net + 1.96 * se) if se else None
    if n < MIN_TRADES:
        hukum = "YETERSIZ_ORNEKLEM"
    elif ci and ci[0] > 0:
        hukum = "POZITIF_NET_BEKLENTI"
    elif ci and ci[1] < 0:
        hukum = "NEGATIF_NET_BEKLENTI"
    else:
        hukum = "ANLAMSIZ"
    return {
        "islem": n,
        "brüt_beklenti_R": statistics.mean(gross),
        "net_beklenti_R": mean_net,
        "net_ga95": ci,
        "profit_factor": pf,
        "kazanma_orani": len(wins) / n,
        "max_dd_R": mdd,
        "maliyet_R": statistics.mean(gross) - mean_net,
        "ort_stop_yuzde": statistics.mean(t["stop_fraction"] for t in trades) * 100,
        "ort_tutma_mum": statistics.mean(t["bars_held"] for t in trades),
        "cikis_nedenleri": {
            r: sum(1 for t in trades if t["reason"] == r)
            for r in ("stop", "target", "timeout")
        },
        "yaklasikliklar": sorted({a for t in trades for a in t["approximation"]}),
        "hukum": hukum,
    }


def resample(cs, factor: int):
    """5m mumları üst zaman dilimine birleştirir (gerçek OHLCV toplamı).

    Bu yeniden örnekleme UYDURMA veri değildir: açık ilk mumun
    açılışı, kapanış son mumun kapanışı, high/low ekstremum,
    hacim toplamı. Eksik gruplar (tam dolmayan) ATILIR.
    """
    out = []
    for k in range(0, len(cs) - factor + 1, factor):
        grp = cs[k:k + factor]
        out.append(type(grp[0])(
            timestamp=grp[0].timestamp,
            open=float(grp[0].open),
            high=max(float(c.high) for c in grp),
            low=min(float(c.low) for c in grp),
            close=float(grp[-1].close),
            volume=sum(float(c.volume) for c in grp),
        ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Yeni giriş stratejileri taraması (v5.6)")
    ap.add_argument("--data-dir", default="data/validation")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--bars", type=int, default=25920)
    ap.add_argument("--out", default="docs/strateji_lab_v56.json")
    ap.add_argument("--mtf-factor", type=int, default=12,
                    help="MTF üst zaman dilimi katsayısı (12 = 5m→1h)")
    ap.add_argument("--resample", type=int, default=1,
                    help="5m veriyi N katına birleştir (12=1h, 48=4h)")
    args = ap.parse_args()

    from tools.validate_strategy import _read_csv  # noqa: PLC0415

    data_dir = Path(args.data_dir)
    files = sorted(data_dir.glob(f"*_{args.interval}_{args.bars}.csv"))
    if not files:
        logger.error("Veri yok: %s", data_dir)
        return 1
    fee = 0.0005          # taker (kötümser)
    slip = 2.0
    logger.info(
        "TARAMA SİMÜLATÖRÜ — üretim motoru değil; taker %.4f, kayma %.1f bps",
        fee, slip,
    )
    report = {
        "olcum_zamani": datetime.now(UTC).isoformat(),
        "arac": "strategy_lab (ELEME taraması, üretim motoru DEĞİL)",
        "sinirlar": [
            "Kısmi kâr alma / trailing / portföy limiti / DD kilidi YOK",
            "Giriş sinyal sonrası mumun açılışı (look-ahead yok)",
            "Aynı mumda stop+hedef varsa ÖNCE stop (kötümser)",
            "Taker komisyonu + 2 bps kayma, her iki bacak",
            "Sonuç üretim performans tahmini DEĞİLDİR",
        ],
        "komisyon_orani": fee, "kayma_bps": slip,
        "zaman_dilimi": args.interval,
        "yeniden_ornekleme_kati": args.resample,
        "mtf_ust_tf_kati": args.mtf_factor,
        "semboller": [], "stratejiler": {},
    }
    all_by_strategy: dict[str, list[dict]] = {k: [] for k in STRATEGIES}
    for path in files:
        symbol = path.stem.split(f"_{args.interval}_")[0]
        cs = _read_csv(path)
        if args.resample > 1:
            cs = resample(cs, args.resample)
        if len(cs) < 100:
            continue
        report["semboller"].append(symbol)
        logger.info("%s: %d bar", symbol, len(cs))
        ht_series = resample(cs, args.mtf_factor) if args.mtf_factor > 1 else None
        for key, fn in STRATEGIES.items():
            tr = simulate(cs, fn, fee, slip, higher_tf=ht_series,
                          ht_factor=args.mtf_factor)
            all_by_strategy[key].extend(tr)
            logger.info("  %-28s %d işlem", key, len(tr))
    for key, tr in all_by_strategy.items():
        report["stratejiler"][key] = summarize(tr)
    eligible = [
        k for k, v in report["stratejiler"].items()
        if v.get("hukum") == "POZITIF_NET_BEKLENTI"
    ]
    report["canliya_aday"] = eligible
    report["sonuc"] = (
        f"{len(eligible)} strateji pozitif net beklenti gösterdi: {eligible}"
        if eligible else
        "HİÇBİR strateji pozitif net beklenti göstermedi. Canlıya aday YOK."
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    logger.info("Rapor: %s", out)
    logger.info("SONUÇ: %s", report["sonuc"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())