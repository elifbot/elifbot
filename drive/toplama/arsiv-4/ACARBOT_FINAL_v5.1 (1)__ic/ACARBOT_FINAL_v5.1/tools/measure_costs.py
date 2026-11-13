"""v5.1 — CANLI MALİYET ÖLÇÜMÜ (spread / derinlik kayması / gecikme).

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


def measure_symbol(
    exchange: str, symbol: str, samples: int, notional: float, pause: float,
) -> dict | None:
    spreads: list[float] = []
    entry_slips: list[float] = []
    exit_slips: list[float] = []
    latencies: list[int] = []
    for index in range(samples):
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
        if index < samples - 1:
            time.sleep(pause)
    if not spreads:
        return None
    return {
        "spread_bps": round(statistics.median(spreads), 4),
        "slippage_bps": (
            round(statistics.median(entry_slips), 4) if entry_slips else None
        ),
        "exit_slippage_bps": (
            round(statistics.median(exit_slips), 4) if exit_slips else None
        ),
        "latency_ms": int(statistics.median(latencies)) if latencies else None,
        "samples": len(spreads),
        "shallow_book_samples": len(spreads) - len(entry_slips),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canlı maliyet ölçümü")
    parser.add_argument("--exchange", choices=("okx", "binance"), default="okx")
    parser.add_argument(
        "--symbols",
        default="BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP",
        help="virgülle ayrılmış enstrüman listesi",
    )
    parser.add_argument("--samples", type=int, default=5)
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
    # Borsa varsayılanlarını ölçülen medyanla güncelle (ölçülmeyen semboller için)
    median_spread = statistics.median(
        d["spread_bps"] for d in details.values()
    )
    base = model.by_exchange.get(args.exchange, ExchangeCosts())
    model.by_exchange[args.exchange] = ExchangeCosts(
        spread_bps=round(median_spread, 4),
        slippage_bps=base.slippage_bps,
        latency_ms=base.latency_ms,
        exit_slippage_bps=base.exit_slippage_bps,
        maker_fee=base.maker_fee,
        taker_fee=base.taker_fee,
    )
    payload = model.as_dict()
    payload["measurement_details"] = details
    payload["target_notional"] = args.notional
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("Ölçüm yazıldı: %s (%d sembol)", out, len(details))
    logger.info("%s", model.summary_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
