"""Sistem saat bütünlüğü ve monotonik saat tutarlılık örnekleyicisi.

Paper supervisor ve çalışma zamanı önsorguları (preflight) tarafından
duvar saati (UTC) ile monotonik saat arasındaki bütünlüğü doğrulamak için kullanılır.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone


def sample() -> dict:
    """Anlık duvar saati ve monotonik saat örneği üretir ve tutarlılığını denetler."""
    t_wall_before = time.time()
    t_mono = time.monotonic()
    t_wall_after = time.time()

    span_sec = t_wall_after - t_wall_before
    finite = (
        math.isfinite(t_wall_before)
        and math.isfinite(t_mono)
        and math.isfinite(t_wall_after)
    )
    # 2020-01-01 UTC öncesi bozuk RTC/sistem saati olarak reddedilir;
    # çağrı esnasında geri sıçrama veya >2s bloklanma da anomali sayılır.
    valid_epoch = t_wall_after >= 1_577_836_800.0
    no_backstep = span_sec >= -0.050
    bounded_jitter = abs(span_sec) <= 2.0
    ok = bool(finite and valid_epoch and no_backstep and bounded_jitter)

    return {
        "ok": ok,
        "wall_ts": float(t_wall_after),
        "wall_utc": datetime.fromtimestamp(t_wall_after, tz=timezone.utc).isoformat(),
        "monotonic_sec": float(t_mono),
        "probe_span_ms": round(span_sec * 1000.0, 4),
        "reason": None if ok else "clock_probe_anomaly",
    }
