"""v5.2 — CANLI MALİYET ÖLÇÜMÜ (spread / derinlik kayması / gecikme).

v5.2 ÖLÇÜM TABANI GENİŞLETMESİ
------------------------------
v5.1 ölçümü TEK ANDA ve sembol başına 4 örnekle alıyordu. Kullanıcı
tespiti haklıydı: bu taban ince. v5.2:
  * --rounds     : ölçümü zamana yayar (varsayılan 4 tur)
  * --round-gap  : turlar arası bekleme (varsayılan 45 sn)
  * --samples    : tur başına örnek (varsayılan 6) -> 24 örnek/sembol
  * --percentile : planlama değeri medyan değil p75 (muhafazakâr)
  * p50/p75/p90/p95/maks ham istatistikleri de yazılır
  * measurement_quality: tabanın ince/yeterli olduğu AÇIKÇA etiketlenir
  * ölçülmeyen sembol varsayılanı ölçülen p90 x ceza ile türetilir ve
    fallback_basis olarak yazılır (v5.1'de sabit kalıp "ölçülmüş"
    etiketi altında sunuluyordu)

`backtest/costs.py` varsayılanları MUHAFAZAKÂR TAHMİNDİR, ölçüm değildir.
Bu araç emir defterinden gerçek örnek alır ve `CostModel` JSON'u yazar;
backtest o dosyayla koşulduğunda sonuçlar "ÖLÇÜLMÜŞ" etiketi taşır.

Ölçülenler:
  • spread_bps        : (ask1 - bid1) / orta fiyat, baz puan
  • slippage_bps      : hedef nominali defterden süpürmenin VWAP sapması
  • exit_slippage_bps : aynı süpürme, çıkış tarafı (karşı defter)
  • latency_ms        : REST gidiş-dönüş süresi (gerçek ölçüm)

Kullanım:
    python3 -m tools.measure_costs --symbols BTC-USDT-SWAP,ETH-USDT-SWAP \\
        --exchange okx --samples 5 --notional 3000 --out docs/maliyet_olcum.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backtest.costs import CostModel, ExchangeCosts

logger = logging.getLogger("measure_costs")

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


def _get_json(url: str, timeout: float = 15.0) -> tuple[object, int]:
    start = time.perf_counter()
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=_UA), timeout=timeout,
    ) as response:
        payload = json.loads(response.read())
    latency = int((time.perf_counter() - start) * 1000)
    return payload, latency


def fetch_book(exchange: str, symbol: str) -> tuple[list, list]:
    """(bids, asks) — [(fiyat, miktar), ...] en iyi seviye önce."""
    if exchange == "okx":
        url = (
            "https://www.okx.com/api/v5/market/books?"
            + urllib.parse.urlencode({"instId": symbol, "sz": "50"})
        )
        payload, latency = _get_json(url)
        rows = (payload.get("data") or [{}])[0]
        bids = [(float(p), float(q)) for p, q, *_ in rows.get("bids", [])]
        asks = [(float(p), float(q)) for p, q, *_ in rows.get("asks", [])]
    else:
        bare = symbol.replace("-", "").upper()
        url = (
            "https://data-api.binance.vision/api/v3/depth?"
            + urllib.parse.urlencode({"symbol": bare, "limit": "100"})
        )
        payload, latency = _get_json(url)
        bids = [(float(p), float(q)) for p, q in payload.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in payload.get("asks", [])]
    return bids, asks, latency


def sweep_bps(levels: list[tuple[float, float]], mid: float, notional: float,
              side: str) -> float | None:
    """Hedef nominali süpürmenin VWAP sapması (baz puan)."""
    if not levels or mid <= 0 or notional <= 0:
        return None
    remaining = notional
    cost = 0.0
    filled = 0.0
    for price, quantity in levels:
        if price <= 0 or quantity <= 0:
            continue
        level_notional = price * quantity
        take = min(remaining, level_notional)
        cost += take
        filled += take / price
        remaining -= take
        if remaining <= 1e-9:
            break
    if filled <= 0 or remaining > 1e-9:
        return None  # defter yeterince derin değil
    vwap = cost / filled
    drift = (vwap - mid) if side == "buy" else (mid - vwap)
    return max(0.0, drift / mid * 10_000.0)


def _pct(values, pct):
    """Yüzdelik (doğrusal ara değer) — küçük örneklemde kararlı."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def measure_symbol(
    exchange: str, symbol: str, samples: int, notional: float, pause: float,
    percentile: float = 75.0, rounds: int = 1, round_gap: float = 0.0,
) -> dict | None:
    """Sembol maliyetini ölçer. v5.2: çok turlu, zamana yayılmış."""
    spreads: list[float] = []
    entry_slips: list[float] = []
    exit_slips: list[float] = []
    latencies: list[int] = []
    stamps: list[str] = []
    rounds = max(1, rounds)
    samples = max(1, samples)
    total = samples * rounds
    index = -1
    for round_no in range(rounds):
        if round_no > 0 and round_gap > 0:
            time.sleep(round_gap)
        for _ in range(samples):
            index += 1
            stamps.append(
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            try:
                bids, asks, latency = fetch_book(exchange, symbol)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] defter alınamadı: %s", symbol, exc)
                continue
            if not bids or not asks:
                continue
            best_bid, best_ask = bids[0][0], asks[0][0]
            mid = (best_bid + best_ask) / 2.0
            if mid <= 0:
                continue
            spreads.append((best_ask - best_bid) / mid * 10_000.0)
            latencies.append(latency)
            entry = sweep_bps(asks, mid, notional, "buy")
            exit_ = sweep_bps(bids, mid, notional, "sell")
            if entry is not None:
                entry_slips.append(entry)
            if exit_ is not None:
                exit_slips.append(exit_)
            if index < total - 1:
                time.sleep(pause)
    if not spreads:
        return None

    def _pick(values):
        chosen = _pct(values, percentile)
        return round(chosen, 4) if chosen is not None else None

    def _stats(values):
        if not values:
            return {}
        return {
            "p50": round(_pct(values, 50), 4),
            "p75": round(_pct(values, 75), 4),
            "p90": round(_pct(values, 90), 4),
            "p95": round(_pct(values, 95), 4),
            "max": round(max(values), 4),
            "n": len(values),
        }

    window_seconds = 0.0
    if len(stamps) >= 2:
        try:
            first = datetime.fromisoformat(stamps[0])
            last = datetime.fromisoformat(stamps[-1])
            window_seconds = (last - first).total_seconds()
        except ValueError:
            window_seconds = 0.0
    return {
        "spread_bps": _pick(spreads),
        "slippage_bps": _pick(entry_slips),
        "exit_slippage_bps": _pick(exit_slips),
        "latency_ms": (
            int(_pct([float(x) for x in latencies], percentile))
            if latencies else None
        ),
        "samples": len(spreads),
        "rounds": rounds,
        "percentile": percentile,
        "window_seconds": round(window_seconds, 1),
        "first_sample_at": stamps[0] if stamps else None,
        "last_sample_at": stamps[-1] if stamps else None,
        "shallow_book_samples": len(spreads) - len(entry_slips),
        "spread_stats": _stats(spreads),
        "entry_slippage_stats": _stats(entry_slips),
        "exit_slippage_stats": _stats(exit_slips),
    }


def grade_measurement(details: dict, rounds: int, samples: int) -> dict:
    """Ölçüm tabanının kalitesi — raporda DÜRÜST etiket için."""
    if not details:
        return {"grade": "none", "reasons": ["hiç ölçüm yok"]}
    counts = [d.get("samples", 0) for d in details.values()]
    windows = [d.get("window_seconds", 0.0) for d in details.values()]
    min_samples = min(counts)
    max_window = max(windows) if windows else 0.0
    reasons: list[str] = []
    if min_samples < 12:
        reasons.append(f"sembol başına en az örnek {min_samples} (<12)")
    if rounds < 3:
        reasons.append(f"tur sayısı {rounds} (<3)")
    if max_window < 120:
        reasons.append(f"ölçüm penceresi {max_window:.0f} sn (<120)")
    if len(details) < 8:
        reasons.append(f"sembol sayısı {len(details)} (<8)")
    if not reasons:
        grade = "adequate"
    elif len(reasons) >= 3:
        grade = "thin"
    else:
        grade = "limited"
    return {
        "grade": grade,
        "reasons": reasons or ["taban yeterli"],
        "symbols": len(details),
        "rounds": rounds,
        "samples_per_symbol": samples * rounds,
        "min_samples_observed": min_samples,
        "window_seconds": round(max_window, 1),
        "caveat": (
            "Ölçüm yalnızca bu sembollerde ve bu zaman penceresinde alındı. "
            "Tam pazardaki küçük coinlerde kayma DAHA KÖTÜ olabilir."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canlı maliyet ölçümü")
    parser.add_argument("--exchange", choices=("okx", "binance"), default="okx")
    parser.add_argument(
        "--symbols",
        default="BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP",
        help="virgülle ayrılmış enstrüman listesi",
    )
    parser.add_argument("--samples", type=int, default=6,
                        help="tur başına örnek (v5.2: 5 -> 6)")
    parser.add_argument("--rounds", type=int, default=4,
                        help="ölçümü zamana yaymak için tur sayısı (v5.2)")
    parser.add_argument("--round-gap", type=float, default=45.0,
                        help="turlar arası bekleme (sn)")
    parser.add_argument("--percentile", type=float, default=75.0,
                        help="planlama yüzdeliği (v5.2: medyan -> p75)")
    parser.add_argument("--unmeasured-penalty", type=float, default=1.5,
                        help="ölçülmeyen sembol varsayılanı = ölçülen p90 x bu")
    parser.add_argument("--notional", type=float, default=3_000.0)
    parser.add_argument("--pause", type=float, default=0.4)
    parser.add_argument("--out", default="docs/maliyet_olcum.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    model = CostModel(source="measured")
    details: dict[str, dict] = {}
    for raw in args.symbols.split(","):
        raw = raw.strip()
        if not raw:
            continue
        key = f"{args.exchange}:{raw}"
        result = measure_symbol(
            args.exchange, raw, args.samples, args.notional, args.pause,
            percentile=args.percentile, rounds=args.rounds,
            round_gap=args.round_gap,
        )
        if result is None:
            logger.warning("[%s] ölçüm başarısız — atlandı", key)
            continue
        details[key] = result
        model.measured_spread_bps[key] = result["spread_bps"]
        if result["slippage_bps"] is not None:
            model.measured_slippage_bps[key] = result["slippage_bps"]
        if result["exit_slippage_bps"] is not None:
            model.measured_exit_slippage_bps[key] = result["exit_slippage_bps"]
        if result["latency_ms"] is not None:
            model.measured_latency_ms[key] = result["latency_ms"]
        logger.info(
            "[%s] spread %.2f bps | giriş kayması %s | çıkış kayması %s | "
            "gecikme %s ms (%d örnek)",
            key, result["spread_bps"], result["slippage_bps"],
            result["exit_slippage_bps"], result["latency_ms"], result["samples"],
        )
    model.measured_symbols = len(details)
    model.measured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not details:
        logger.error("Hiç ölçüm alınamadı — dosya yazılmadı")
        return 1
    # v5.2: ölçülmeyen semboller için varsayılan, ÖLÇÜLEN p90 x ceza'dan
    # türetilir. v5.1'de bu değerler sabit kalıyor ve "ölçülmüş" etiketi
    # altında sunuluyordu.
    base = model.by_exchange.get(args.exchange, ExchangeCosts())
    spread_p50 = statistics.median(d["spread_bps"] for d in details.values())
    entry_p90 = _pct(
        [d["slippage_bps"] for d in details.values()
         if d.get("slippage_bps") is not None], 90.0,
    )
    exit_p90 = _pct(
        [d["exit_slippage_bps"] for d in details.values()
         if d.get("exit_slippage_bps") is not None], 90.0,
    )
    penalty = max(1.0, args.unmeasured_penalty)
    fallback_entry = (
        round(entry_p90 * penalty, 4) if entry_p90 is not None
        else base.slippage_bps
    )
    fallback_exit = (
        round(exit_p90 * penalty, 4) if exit_p90 is not None
        else base.exit_slippage_bps
    )
    model.by_exchange[args.exchange] = ExchangeCosts(
        spread_bps=round(spread_p50, 4),
        slippage_bps=fallback_entry,
        latency_ms=base.latency_ms,
        exit_slippage_bps=fallback_exit,
        maker_fee=base.maker_fee,
        taker_fee=base.taker_fee,
    )
    quality = grade_measurement(details, args.rounds, args.samples)
    payload = model.as_dict()
    payload["measurement_details"] = details
    payload["measurement_quality"] = quality
    payload["target_notional"] = args.notional
    payload["fallback_basis"] = {
        args.exchange: (
            f"ölçülen p90 x {penalty:.2f} (ölçülmeyen semboller için varsayım)"
        ),
        "note": (
            "Bu değer ÖLÇÜM DEĞİLDİR; ölçülen sembollerden türetilmiş "
            "muhafazakâr varsayımdır. Diğer borsalar hiç ölçülmedi."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("Ölçüm yazıldı: %s (%d sembol)", out, len(details))
    logger.info("ÖLÇÜM KALİTESİ: %s — %s",
                quality["grade"], "; ".join(quality["reasons"]))
    logger.info("%s", model.summary_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
