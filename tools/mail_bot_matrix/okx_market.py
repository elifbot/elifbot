#!/usr/bin/env python3
"""Fetch closed OKX public 1m candles for the mail-bot smoke tests.

This module deliberately has no exchange credentials and never calls an order
endpoint.  The output uses Jesse's one-minute research shape:
[timestamp_ms, open, close, high, low, volume].  OKX volume is retained as
contract volume and is not silently converted to USD.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://www.okx.com/api/v5/market/candles"
PAGE_SIZE = 300
ONE_MINUTE_MS = 60_000


def _get(params: dict[str, str]) -> dict:
    url = f"{BASE_URL}?{urlencode(params)}"
    last: Exception | None = None
    for attempt in range(4):
        try:
            request = Request(url, headers={"User-Agent": "elifbot-mail-bot-matrix/1.0"})
            with urlopen(request, timeout=20) as response:
                payload = json.load(response)
            if payload.get("code") != "0":
                raise RuntimeError(f"OKX API error {payload.get('code')}: {payload.get('msg', '')}")
            return payload
        except Exception as exc:  # noqa: BLE001 - public endpoint diagnostics
            last = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"OKX candles request failed: {last}") from last


def _parse(rows: list[list[str]]) -> dict[int, list[float]]:
    candles: dict[int, list[float]] = {}
    for row in rows:
        if len(row) < 9 or str(row[8]) != "1":
            continue
        ts = int(row[0])
        values = [float(row[i]) for i in (1, 4, 2, 3, 5)]
        if ts < 0 or ts % ONE_MINUTE_MS or not all(math.isfinite(x) for x in values):
            raise ValueError("invalid OKX OHLCV row")
        opening, closing, high, low, volume = values
        if min(opening, closing, high, low) <= 0 or volume < 0:
            raise ValueError("non-positive price or negative volume in OKX row")
        if high < max(opening, closing, low) or low > min(opening, closing, high):
            raise ValueError("inconsistent OHLC relationship in OKX row")
        value = [float(ts), opening, closing, high, low, volume]
        previous = candles.get(ts)
        if previous is not None and previous != value:
            raise ValueError(f"conflicting duplicate candle at {ts}")
        candles[ts] = value
    return candles


def _latest_contiguous(candles: dict[int, list[float]], requested: int) -> list[list[float]]:
    ordered = [candles[k] for k in sorted(candles)]
    if not ordered:
        raise RuntimeError("OKX returned no closed candles")
    end = len(ordered)
    start = end - 1
    while start > 0 and int(ordered[start][0] - ordered[start - 1][0]) == ONE_MINUTE_MS:
        start -= 1
    result = ordered[start:end]
    if len(result) < min(600, requested):
        raise RuntimeError(f"latest contiguous candle run too short: {len(result)}")
    return result[-requested:]


def fetch(inst_id: str, requested: int) -> dict:
    if requested < 600 or requested > 10_000:
        raise ValueError("--bars must be between 600 and 10000")
    rows: list[list[str]] = []
    cursor: int | None = None
    previous_cursor: int | None = None
    while len(rows) < requested + PAGE_SIZE:
        params = {"instId": inst_id, "bar": "1m", "limit": str(PAGE_SIZE)}
        if cursor is not None:
            params["after"] = str(cursor)
        page = _get(params).get("data") or []
        if not page:
            break
        rows.extend(page)
        next_cursor = min(int(item[0]) for item in page)
        if next_cursor == previous_cursor or len(page) < PAGE_SIZE:
            break
        previous_cursor, cursor = cursor, next_cursor
        time.sleep(0.08)
    parsed = _parse(rows)
    candles = _latest_contiguous(parsed, requested)
    first = datetime.fromtimestamp(candles[0][0] / 1000, tz=timezone.utc).isoformat()
    last = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc).isoformat()
    return {
        "kind": "okx_public_closed_candles",
        "source": "OKX public REST /api/v5/market/candles",
        "private_api_used": False,
        "inst_id": inst_id,
        "bar": "1m",
        "volume_unit": "OKX contract volume; not USD",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "first_open_utc": first,
        "last_open_utc": last,
        "closed_candles": len(candles),
        "columns": ["timestamp_ms", "open", "close", "high", "low", "volume"],
        "candles": candles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inst-id", default="BTC-USDT-SWAP")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = fetch(args.inst_id, args.bars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k != "candles"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
