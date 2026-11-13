"""Gerçek Zamanlı Sağlık & Prometheus Metrik Endpoint'i (`/health`, `/healthz`, `/metrics`).

Bulut sunucularda (VPS / Docker / Kubernetes / UptimeRobot / Prometheus) dışarıdan
bir izleme aracının her saniye botun hayatta, sağlıklı ve hangi borsada aktif olduğunu
milisaniyeler içinde kontrol etmesini sağlar.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .state_store import StateStore

_PROCESS_START_TS = time.time()


def build_health_payload(
    store: StateStore,
    runtime_override: dict[str, Any] | None = None,
    max_heartbeat_age_sec: float = 30.0,
) -> tuple[int, dict[str, Any]]:
    """`/health` endpoint'i için HTTP durum kodu (200 veya 503) ve JSON sözlüğü üretir."""
    now = time.time()
    meta = runtime_override if runtime_override is not None else (store.get_meta("bot_status", {}) or {})
    positions = store.load_positions()
    wal_info = store.get_wal_status()

    cb = meta.get("circuit_breaker", {}) or {}
    cb_tripped = bool(cb.get("tripped", False))
    sys_locked = bool(cb.get("system_locked", False))

    ex_health = meta.get("exchange_health", {}) or {}
    active_ex = ex_health.get("active_primary") or meta.get("primary_exchange", "binance")
    failover_active = bool(ex_health.get("failover_active", False))

    last_hb = float(meta.get("ts", now))
    hb_age = max(0.0, now - last_hb)

    is_healthy = (not sys_locked) and (not cb_tripped)
    if sys_locked or cb_tripped:
        status_str = "unhealthy"
        http_code = 503
    elif failover_active:
        status_str = "degraded_failover"
        http_code = 200
    else:
        status_str = "healthy"
        http_code = 200

    payload = {
        "status": status_str,
        "alive": True,
        "healthy": is_healthy,
        "timestamp": round(now, 3),
        "uptime_sec": round(now - _PROCESS_START_TS, 2),
        "last_heartbeat_age_sec": round(hb_age, 2),
        "heartbeat_fresh": hb_age <= max_heartbeat_age_sec,
        "mode": meta.get("mode", "PAPER"),
        "active_exchange": active_ex,
        "failover_active": failover_active,
        "exchange_health": ex_health,
        "open_positions_count": len(positions),
        "balance_usdt": float(meta.get("balance_usdt", 1000.0)),
        "equity_usdt": float(meta.get("equity_usdt", 1000.0)),
        "circuit_breaker": {
            "tripped": cb_tripped,
            "system_locked": sys_locked,
            "reason": cb.get("reason", ""),
        },
        "sqlite": {
            "journal_mode": wal_info["journal_mode"],
            "wal_active": wal_info["wal_active"],
            "db_size_bytes": wal_info["db_size_bytes"],
            "vacuum_runs": wal_info["vacuum_runs"],
        },
    }
    return http_code, payload


def build_prometheus_metrics(
    store: StateStore,
    runtime_override: dict[str, Any] | None = None,
) -> str:
    """Prometheus `/metrics` text/plain (0.0.4) formatında gerçek zamanlı metrik üretir."""
    _, h = build_health_payload(store, runtime_override=runtime_override)
    cb = h["circuit_breaker"]
    sq = h["sqlite"]
    ex_map = (h.get("exchange_health") or {}).get("exchanges") or {}

    lines = [
        "# HELP kriptobot_up Bot sureci ayakta mi (1=evet, 0=hayir)",
        "# TYPE kriptobot_up gauge",
        f"kriptobot_up {1 if h['alive'] else 0}",
        "# HELP kriptobot_healthy Bot saglikli ve isleme hazir mi (1=saglikli, 0=devre_kesici_veya_kilitli)",
        "# TYPE kriptobot_healthy gauge",
        f"kriptobot_healthy {1 if h['healthy'] else 0}",
        "# HELP kriptobot_uptime_seconds Bot calisma suresi (saniye)",
        "# TYPE kriptobot_uptime_seconds counter",
        f"kriptobot_uptime_seconds {h['uptime_sec']}",
        "# HELP kriptobot_balance_usdt Cuzdan nakit bakiyesi (USDT)",
        "# TYPE kriptobot_balance_usdt gauge",
        f"kriptobot_balance_usdt {h['balance_usdt']:.4f}",
        "# HELP kriptobot_equity_usdt Anlik toplam varlik / equity (USDT)",
        "# TYPE kriptobot_equity_usdt gauge",
        f"kriptobot_equity_usdt {h['equity_usdt']:.4f}",
        "# HELP kriptobot_open_positions_total Acik pozisyon sayisi",
        "# TYPE kriptobot_open_positions_total gauge",
        f"kriptobot_open_positions_total {h['open_positions_count']}",
        "# HELP kriptobot_circuit_breaker_tripped Devre kesici tetiklendi mi (1=evet, 0=hayir)",
        "# TYPE kriptobot_circuit_breaker_tripped gauge",
        f"kriptobot_circuit_breaker_tripped {1 if cb['tripped'] else 0}",
        "# HELP kriptobot_system_locked Acil kill-switch sistem kilidi aktif mi (1=evet, 0=hayir)",
        "# TYPE kriptobot_system_locked gauge",
        f"kriptobot_system_locked {1 if cb['system_locked'] else 0}",
        "# HELP kriptobot_failover_active Multi-Exchange yedek borsa (OKX) failover aktif mi",
        "# TYPE kriptobot_failover_active gauge",
        f"kriptobot_failover_active {1 if h['failover_active'] else 0}",
        "# HELP kriptobot_sqlite_wal_active SQLite WAL modu aktif mi (1=wal, 0=diger)",
        "# TYPE kriptobot_sqlite_wal_active gauge",
        f"kriptobot_sqlite_wal_active {1 if sq['wal_active'] else 0}",
        "# HELP kriptobot_sqlite_db_size_bytes SQLite bot_state.db dosya boyutu (byte)",
        "# TYPE kriptobot_sqlite_db_size_bytes gauge",
        f"kriptobot_sqlite_db_size_bytes {sq['db_size_bytes']}",
        "# HELP kriptobot_sqlite_vacuum_runs_total Tamamlanan VACUUM cop toplama sayisi",
        "# TYPE kriptobot_sqlite_vacuum_runs_total counter",
        f"kriptobot_sqlite_vacuum_runs_total {sq['vacuum_runs']}",
    ]

    if ex_map:
        lines.append("# HELP kriptobot_exchange_degraded Borsa kesinti/timeout nedeniyle devre disi mi")
        lines.append("# TYPE kriptobot_exchange_degraded gauge")
        for ex_name, info in ex_map.items():
            deg = 1 if info.get("degraded") else 0
            lines.append(f'kriptobot_exchange_degraded{{exchange="{ex_name}"}} {deg}')

        lines.append("# HELP kriptobot_exchange_consecutive_timeouts Borsa ardisik timeout sayisi")
        lines.append("# TYPE kriptobot_exchange_consecutive_timeouts gauge")
        for ex_name, info in ex_map.items():
            cnt = int(info.get("consecutive_timeouts", 0))
            lines.append(f'kriptobot_exchange_consecutive_timeouts{{exchange="{ex_name}"}} {cnt}')

    return "\n".join(lines) + "\n"


class HealthCheckServer:
    """Bağımsız, ultra-hafif asyncio HTTP `/health` ve `/metrics` sunucusu."""

    def __init__(self, store: StateStore, host: str = "0.0.0.0", port: int = 8502):
        self.store = store
        self.host = host
        self.port = port
        self._server: asyncio.AbstractServer | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            raw = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            if not raw:
                writer.close()
                return
            line = raw.decode("utf-8", errors="ignore").split("\r\n", 1)[0]
            parts = line.split(" ")
            path = (parts[1] if len(parts) > 1 else "/health").split("?", 1)[0]

            if path in ("/health", "/healthz", "/api/health"):
                code, payload = build_health_payload(self.store)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                status_txt = "OK" if code == 200 else "Service Unavailable"
                hdr = (
                    f"HTTP/1.1 {code} {status_txt}\r\n"
                    f"Content-Type: application/json; charset=utf-8\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"Cache-Control: no-store\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("utf-8")
                writer.write(hdr + body)
            elif path == "/metrics":
                body = build_prometheus_metrics(self.store).encode("utf-8")
                hdr = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"Cache-Control: no-store\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("utf-8")
                writer.write(hdr + body)
            else:
                body = b'{"error":"not_found"}'
                writer.write(
                    b"HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8")
                    + body
                )
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def start(self):
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        return self._server

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
