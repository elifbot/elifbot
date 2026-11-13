"""Görev denetimi — v9.4.5'in doğrulanmış supervisor deseni.

DAVRANIŞ SÖZLEŞMESİ
  * Ana arka plan görevlerinden biri beklenmedik dönerse/iptal olursa/istisna
    atarsa: yeni girişler KESİLİR, run FAILED kapanır.
  * Açık pozisyonlar ZORLA KAPATILMAZ.
  * Otomatik restart YAPILMAZ.
  * Sinyal olmaması görev ölümü DEĞİLDİR: ilerleme (evaluation_calls) ve
    heartbeat ayrı ölçülür.

Bu, arşivde 158 testle doğrulanmış davranışın temiz uygulamasıdır.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..core.clock import get_logger, mono, now_ms

log = get_logger("supervisor")


@dataclass
class TaskRecord:
    name: str
    task: asyncio.Task | None = None
    started_ms: int = 0
    finished_ms: int = 0
    failure: str = ""
    outcome: str = "running"   # running | returned | cancelled | exception

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "started_ms": self.started_ms,
                "finished_ms": self.finished_ms, "outcome": self.outcome,
                "failure": self.failure,
                "done": bool(self.task and self.task.done())}


@dataclass
class Heartbeat:
    name: str
    last_beat_mono: float = field(default_factory=mono)
    beats: int = 0
    stale_after_sec: float = 30.0
    #: Aynı bayatlık epizodu için tekrar alarm yazmayı engeller.
    alarm_open: bool = False

    def beat(self) -> None:
        self.last_beat_mono = mono()
        self.beats += 1
        self.alarm_open = False

    @property
    def age_sec(self) -> float:
        return mono() - self.last_beat_mono

    @property
    def is_stale(self) -> bool:
        return self.age_sec > self.stale_after_sec


class TaskSupervisor:
    """Ana görevleri izler; ilk ölçekte fail-closed kapanış üretir."""

    def __init__(self) -> None:
        self.records: dict[str, TaskRecord] = {}
        self.heartbeats: dict[str, Heartbeat] = {}
        self.failures: dict[str, str] = {}
        self.fatal = asyncio.Event()
        self.fatal_reason: str = ""
        self.alarms: list[dict[str, Any]] = []
        self.entries_halted = False
        #: Planlı kapanış başladıktan sonra iptal, görev ölümü DEĞİLDİR.
        self.shutting_down = False

    def begin_shutdown(self) -> None:
        """Planlı kapanışı işaretler. Bundan sonra iptal normal kabul edilir."""
        self.shutting_down = True
        self.entries_halted = True

    def register_heartbeat(self, name: str, stale_after_sec: float = 30.0) -> None:
        self.heartbeats[name] = Heartbeat(name, stale_after_sec=stale_after_sec)

    def beat(self, name: str) -> None:
        hb = self.heartbeats.get(name)
        if hb:
            hb.beat()

    def spawn(self, name: str, coro: Awaitable[Any]) -> asyncio.Task:
        rec = TaskRecord(name=name, started_ms=now_ms())
        task = asyncio.create_task(self._wrap(name, coro), name=f"os::{name}")
        rec.task = task
        self.records[name] = rec
        return task

    async def _wrap(self, name: str, coro: Awaitable[Any]) -> Any:
        rec = self.records[name]
        try:
            result = await coro
            # Normal dönüş: ana görev için bu da ÖLÜMDÜR (v9.4.5 sözleşmesi).
            rec.outcome = "returned"
            rec.finished_ms = now_ms()
            if not self.shutting_down:
                self._fail(name, "TASK_RETURNED_UNEXPECTEDLY",
                           f"{name} beklenmedik şekilde normal döndü")
            return result
        except asyncio.CancelledError:
            rec.outcome = "cancelled"
            rec.finished_ms = now_ms()
            if self.shutting_down:
                rec.outcome = "cancelled_planned"
            elif not self.fatal.is_set():
                self._fail(name, "TASK_CANCELLED", f"{name} beklenmedik iptal")
            raise
        except Exception as e:
            rec.outcome = "exception"
            rec.finished_ms = now_ms()
            rec.failure = f"{type(e).__name__}: {e}"
            self._fail(name, "TASK_EXCEPTION", rec.failure)
            raise

    def _fail(self, name: str, code: str, detail: str) -> None:
        if name in self.failures:
            return
        self.failures[name] = f"{code}: {detail}"
        self.entries_halted = True
        if not self.fatal_reason:
            self.fatal_reason = f"{name} — {code}: {detail}"
        self.alarms.append({"ts_ms": now_ms(), "kind": code,
                            "task": name, "detail": detail})
        log.error("GÖREV ÖLÜMÜ %s: %s — yeni girişler kesildi", name, detail)
        self.fatal.set()

    def raise_alarm(self, kind: str, detail: str) -> None:
        """Görev ölümü olmayan sağlık alarmı (HTTP503 karşılığı)."""
        self.alarms.append({"ts_ms": now_ms(), "kind": kind, "detail": detail})
        log.warning("SAĞLIK ALARMI %s: %s", kind, detail)

    def check_heartbeats(self) -> list[str]:
        stale: list[str] = []
        for name, hb in self.heartbeats.items():
            if hb.is_stale:
                stale.append(name)
                # Epizod başına tek alarm; tekrar beat gelince sıfırlanır.
                if not hb.alarm_open:
                    hb.alarm_open = True
                    self.raise_alarm("HEARTBEAT_STALE",
                                     f"{name} {hb.age_sec:.1f}s bayat "
                                     f"(eşik {hb.stale_after_sec:.0f}s)")
            elif hb.alarm_open:
                hb.alarm_open = False
        return stale

    async def cancel_all(self, timeout: float = 8.0) -> None:
        tasks = [r.task for r in self.records.values() if r.task and not r.task.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)

    def summary(self) -> dict[str, Any]:
        return {
            "entries_halted": self.entries_halted,
            "fatal_reason": self.fatal_reason,
            "task_failures": dict(self.failures),
            "tasks": {n: r.to_dict() for n, r in self.records.items()},
            "heartbeats": {n: {"beats": h.beats,
                               "age_sec": round(h.age_sec, 3),
                               "stale": h.is_stale}
                           for n, h in self.heartbeats.items()},
            "alarm_count": len(self.alarms),
            "alarms": self.alarms[-40:],
        }