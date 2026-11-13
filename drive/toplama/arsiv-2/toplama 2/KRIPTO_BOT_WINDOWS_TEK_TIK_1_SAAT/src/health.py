"""Gerçek zamanlı `/health`, `/healthz` ve Prometheus `/metrics` HTTP sunucusu."""
from __future__ import annotations

import time
from typing import Any

from .state_store import StateStore

_PROCESS_START_TS = time.time()


def build_health_payload(
    state_store: StateStore, max_heartbeat_age_sec: float = 90.0
) -> tuple[int, dict[str, Any]]:
    """Sağlık durumunu (http_status_code, json_payload) olarak döndürür."""
    now = time.time()
    meta = state_store.get_meta("bot_status", {}) or {}
    cb = meta.get("circuit_breaker", {}) or {}
    ex_health = meta.get("exchange_health", {}) or {}
    wal_info = state_store.get_wal_status()

    cb_tripped = bool(cb.get("tripped", False))
    sys_locked = bool(cb.get("system_locked", False))
    active_ex = ex_health.get("active_primary") or meta.get("primary_exchange", "binance")
    failover_active = bool(ex_health.get("failover_active", False))

    try:
        last_hb = float(meta["ts"])
        heartbeat_present = True
    except (KeyError, TypeError, ValueError):
        last_hb = 0.0
        heartbeat_present = False
    hb_age = max(0.0, now - last_hb) if heartbeat_present else -1.0
    heartbeat_fresh = (
        heartbeat_present
        and 0.0 <= now - last_hb <= max_heartbeat_age_sec
    )

    # Eksik/bayat heartbeat, bot artık durum yazmıyor demektir. Bunu sağlıklı
    # saymak dış izleme sistemlerinin ölü bir botu canlı sanmasına yol açar.
    is_healthy = heartbeat_fresh and (not sys_locked) and (not cb_tripped)
    if not heartbeat_fresh:
        status_str = "not_ready" if not heartbeat_present else "stale_heartbeat"
        http_code = 503
    elif sys_locked or cb_tripped:
        status_str = "unhealthy"
        http_code = 503
    elif failover_active:
        status_str = "degraded_failover"
        http_code = 200
    else:
        status_str = "ok"
        http_code = 200

    payload = {
        "healthy": is_healthy,
        "status": status_str,
        "timestamp": round(now, 3),
        "uptime_sec": round(now - _PROCESS_START_TS, 2),
        "last_heartbeat_age_sec": round(hb_age, 2),
        "heartbeat_fresh": heartbeat_fresh,
        "mode": meta.get("mode", "PAPER"),
        "active_exchange": active_ex,
        "failover_active": failover_active,
        "balance_usdt": float(meta.get("balance_usdt", 0.0) or 0.0),
        "equity_usdt": float(meta.get("equity_usdt", 0.0) or 0.0),
        "open_positions": int(meta.get("open_positions", 0) or 0),
        "circuit_breaker": {
            "tripped": cb_tripped,
            "system_locked": sys_locked,
            "reason": cb.get("trip_reason") or cb.get("reason", ""),
        },
        "sqlite": {
            "journal_mode": wal_info["journal_mode"],
            "wal_enabled": wal_info["wal_enabled"],
            "db_size_bytes": wal_info["db_size_bytes"],
        },
    }
    return http_code, payload


def build_prometheus_metrics(state_store: StateStore) -> str:
    """Prometheus text exposition format (0.0.4) metriklerini üretir."""
    code, health = build_health_payload(state_store)
    meta = state_store.get_meta("bot_status", {}) or {}
    cb = meta.get("circuit_breaker", {}) or {}
    ex_health = meta.get("exchange_health", {}) or {}
    stats = meta.get("stats", {}) or {}
    wal_info = state_store.get_wal_status()

    lines = [
        "# HELP kriptobot_up Bot saglikli ve canli mi (1=evet, 0=hayir)",
        "# TYPE kriptobot_up gauge",
        f"kriptobot_up {1 if code == 200 and health['healthy'] else 0}",
        "# HELP kriptobot_uptime_seconds surec calisma suresi",
        "# TYPE kriptobot_uptime_seconds gauge",
        f"kriptobot_uptime_seconds {health['uptime_sec']}",
        "# HELP kriptobot_balance_usdt Hesap bakiyesi USDT",
        "# TYPE kriptobot_balance_usdt gauge",
        f"kriptobot_balance_usdt {float(meta.get('balance_usdt', 0.0) or 0.0)}",
        "# HELP kriptobot_equity_usdt Toplam ozsermaye USDT",
        "# TYPE kriptobot_equity_usdt gauge",
        f"kriptobot_equity_usdt {float(meta.get('equity_usdt', 0.0) or 0.0)}",
        "# HELP kriptobot_open_positions Acik pozisyon sayisi",
        "# TYPE kriptobot_open_positions gauge",
        f"kriptobot_open_positions {int(meta.get('open_positions', 0) or 0)}",
        "# HELP kriptobot_trades_total Kapanan toplam islem sayisi",
        "# TYPE kriptobot_trades_total counter",
        f"kriptobot_trades_total {int(stats.get('trades', 0) or 0)}",
        "# HELP kriptobot_circuit_breaker_tripped Sigorta atik mi",
        "# TYPE kriptobot_circuit_breaker_tripped gauge",
        f"kriptobot_circuit_breaker_tripped {1 if cb.get('tripped') else 0}",
        "# HELP kriptobot_system_locked Acil kill-switch kilidi",
        "# TYPE kriptobot_system_locked gauge",
        f"kriptobot_system_locked {1 if cb.get('system_locked') else 0}",
        "# HELP kriptobot_failover_active Yedek borsaya gecis aktif mi",
        "# TYPE kriptobot_failover_active gauge",
        f"kriptobot_failover_active {1 if ex_health.get('failover_active') else 0}",
        "# HELP kriptobot_sqlite_db_size_bytes SQLite veritabani dosya boyutu",
        "# TYPE kriptobot_sqlite_db_size_bytes gauge",
        f"kriptobot_sqlite_db_size_bytes {int(wal_info.get('db_size_bytes', 0))}",
    ]

    ex_map = ex_health.get("exchanges", {}) or {}
    if isinstance(ex_map, dict) and ex_map:
        lines.append("# HELP kriptobot_exchange_degraded Borsa kesinti/timeout nedeniyle devre disi mi")
        lines.append("# TYPE kriptobot_exchange_degraded gauge")
        for ex_name, info in ex_map.items():
            deg = 1 if info.get("degraded", not info.get("healthy", True)) else 0
            lines.append(f'kriptobot_exchange_degraded{{exchange="{ex_name}"}} {deg}')

        lines.append("# HELP kriptobot_exchange_consecutive_timeouts Borsa ardisik timeout sayisi")
        lines.append("# TYPE kriptobot_exchange_consecutive_timeouts gauge")
        for ex_name, info in ex_map.items():
            to_cnt = int(info.get("consecutive_timeouts", 0) or 0)
            lines.append(f'kriptobot_exchange_consecutive_timeouts{{exchange="{ex_name}"}} {to_cnt}')

    return "\n".join(lines) + "\n"


class HealthCheckServer:
    """Bağımsız hafif aiohttp `/health`, `/healthz` ve `/metrics` sunucusu."""

    def __init__(self, state_store: StateStore, host: str = "0.0.0.0", port: int = 8502):
        self.state_store = state_store
        self.host = host
        self.port = int(port)
        self._runner = None
        self._site = None

    async def start(self) -> None:
        from aiohttp import web

        async def handle_health(_request: web.Request) -> web.Response:
            code, payload = build_health_payload(self.state_store)
            return web.json_response(payload, status=code)

        async def handle_metrics(_request: web.Request) -> web.Response:
            return web.Response(
                text=build_prometheus_metrics(self.state_store),
                content_type="text/plain; version=0.0.4",
                charset="utf-8",
            )

        app = web.Application()
        app.router.add_get("/health", handle_health)
        app.router.add_get("/healthz", handle_health)
        app.router.add_get("/metrics", handle_metrics)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
