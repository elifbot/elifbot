"""Monotonic saat, süreklilik dedektörü ve yapısal loglama.

v9.4.5'ten alınan ders: duvar saati (wall) NTP/VM sıçraması yapar; süre ve
boşluk ölçümü YALNIZ monotonic ile yapılır. İkisi ayrı tutulur ve aradaki sapma
başlı başına bir olaydır. Bu modül o ayrımı tek yerde zorunlu kılar.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def now_ms() -> int:
    """Duvar saati — veri zaman damgası ve rapor etiketi için."""
    return int(time.time() * 1000)


def mono() -> float:
    """Monotonic saniye — süre, timeout ve boşluk ölçümü için TEK doğru kaynak."""
    return time.monotonic()


@dataclass(slots=True)
class ContinuityEvent:
    kind: str
    at_ms: int
    gap_sec: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "at_ms": self.at_ms,
            "gap_sec": round(self.gap_sec, 6), "detail": self.detail,
        }


@dataclass
class ContinuityEngine:
    """Poll gecikmesi ve wall/mono sapmasını izler.

    Arşivdeki 5.22s olayı bu sınıf olmadan ancak "sonradan fark edildi"
    seviyesinde yakalanıyordu. Burada boşluk ANINDA olay olarak kaydedilir ve
    run durumunun DISCONTINUOUS sayılmasına yol açar.

    Önemli sınır: bütün süreç/VM durduğunda bu kod da çalışmaz. Dönüşte
    boşluğu tespit eder; kesintisiz uptime garantisi VERMEZ.
    """
    poll_delay_threshold_sec: float = 5.0
    clock_skew_threshold_sec: float = 2.0
    events: list[ContinuityEvent] = field(default_factory=list)
    max_poll_delay_sec: float = 0.0
    max_clock_skew_sec: float = 0.0
    _last_mono: float | None = None
    _last_wall: float | None = None

    def start(self) -> None:
        self._last_mono = mono()
        self._last_wall = time.time()

    def beat(self, expected_interval_sec: float = 1.0) -> ContinuityEvent | None:
        """Her döngü turunda çağrılır. Eşik aşımında olay döndürür."""
        m, w = mono(), time.time()
        if self._last_mono is None or self._last_wall is None:
            self.start()
            return None
        dm = m - self._last_mono
        dw = w - self._last_wall
        self._last_mono, self._last_wall = m, w

        extra = max(0.0, dm - expected_interval_sec)
        self.max_poll_delay_sec = max(self.max_poll_delay_sec, extra)
        skew = abs(dw - dm)
        self.max_clock_skew_sec = max(self.max_clock_skew_sec, skew)

        if dm > self.poll_delay_threshold_sec:
            ev = ContinuityEvent(
                "RUN_DISCONTINUITY_DETECTED", now_ms(), dm,
                f"poll_gap={dm:.3f}s expected={expected_interval_sec:.3f}s",
            )
            self.events.append(ev)
            return ev
        if skew > self.clock_skew_threshold_sec:
            ev = ContinuityEvent(
                "CLOCK_SKEW_DETECTED", now_ms(), skew,
                f"wall_delta={dw:.3f}s mono_delta={dm:.3f}s",
            )
            self.events.append(ev)
            return ev
        return None

    @property
    def gap_count(self) -> int:
        return len(self.events)

    @property
    def is_continuous(self) -> bool:
        return not self.events

    def summary(self) -> dict[str, Any]:
        return {
            "gap_count": self.gap_count,
            "continuous": self.is_continuous,
            "max_poll_delay_sec": round(self.max_poll_delay_sec, 6),
            "max_clock_skew_sec": round(self.max_clock_skew_sec, 6),
            "events": [e.to_dict() for e in self.events[:50]],
        }


class Stopwatch:
    """Kapsayıcı (inclusive) duvar süresi ölçer.

    DİKKAT: iç içe kullanılan stopwatch'ların süreleri TOPLANMAZ; üst ölçüm
    alt ölçümü zaten içerir. Arşiv raporundaki en sık yorum hatası buydu.
    """
    __slots__ = ("name", "total_sec", "calls", "max_sec", "_t0")

    def __init__(self, name: str) -> None:
        self.name = name
        self.total_sec = 0.0
        self.calls = 0
        self.max_sec = 0.0
        self._t0: float | None = None

    def __enter__(self) -> "Stopwatch":
        self._t0 = mono()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._t0 is not None:
            dt = mono() - self._t0
            self.total_sec += dt
            self.max_sec = max(self.max_sec, dt)
            self.calls += 1
            self._t0 = None

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name, "calls": self.calls,
            "total_sec": round(self.total_sec, 6),
            "max_ms": round(self.max_sec * 1000.0, 3),
            "mean_ms": round(self.total_sec / self.calls * 1000.0, 3) if self.calls else 0.0,
            "note": "inclusive_wall_time_not_cpu",
        }


class JsonlLogger:
    """Satır başına bir JSON. Kırık satır üretmemek için tek yazıcı."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8", buffering=1)
        self.count = 0

    def write(self, kind: str, **fields: Any) -> None:
        rec = {"kind": kind, "ts_ms": now_ms(), "mono": round(mono(), 6), **fields}
        self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.count += 1

    def flush(self) -> None:
        try:
            self._fh.flush()
            os.fsync(self._fh.fileno())
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        try:
            self.flush()
            self._fh.close()
        except (OSError, ValueError):
            pass


def setup_logging(level: str = "INFO", log_file: Path | str | None = None) -> logging.Logger:
    logger = logging.getLogger("omnistudio")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    if log_file:
        p = Path(log_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(p, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        logger.addHandler(fh)
    return logger


def get_logger(suffix: str = "") -> logging.Logger:
    return logging.getLogger("omnistudio" + (f".{suffix}" if suffix else ""))