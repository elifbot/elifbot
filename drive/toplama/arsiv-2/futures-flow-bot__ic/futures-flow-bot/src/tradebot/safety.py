"""Teknik ariza korumasi. KAYIPLA ILGILI DEGILDIR: sadece veri/API/uyumsuzluk sorunlarinda
yeni pozisyon acmayi durdurur. Cikislar (kapatma) her zaman serbesttir."""
from __future__ import annotations

import logging

from .config import SafetyCfg

log = logging.getLogger("safety")


class SafetyMonitor:
    def __init__(self, cfg: SafetyCfg):
        self.cfg = cfg
        self.last_data: dict[str, float] = {}
        self.fresh_since: dict[str, float | None] = {}
        self.halts: dict[tuple[str, str], tuple[str, bool]] = {}   # (kapsam, anahtar) -> (neden, elle_devam)
        self.api_errors: dict[str, int] = {}
        self.pause_until: dict[str, float] = {}

    def touch(self, exchange: str, ts: float) -> None:
        self.last_data[exchange] = ts

    def api_ok(self, exchange: str) -> None:
        self.api_errors[exchange] = 0

    def api_error(self, exchange: str, now: float, msg: str = "") -> list[str]:
        n = self.api_errors.get(exchange, 0) + 1
        self.api_errors[exchange] = n
        if n >= self.cfg.max_consecutive_api_errors and (exchange, "api") not in self.halts:
            self.pause_until[exchange] = now + self.cfg.api_error_pause_sec
            return [self._halt(exchange, "api", f"art arda {n} API hatasi: {msg}", manual=False)]
        return []

    def _halt(self, scope: str, key: str, reason: str, manual: bool) -> str:
        self.halts[(scope, key)] = (reason, manual)
        msg = f"DURDURULDU [{scope}/{key}]: {reason}" + (" (elle devam gerekir)" if manual else "")
        log.warning(msg)
        return msg

    def halt(self, scope: str, key: str, reason: str, manual: bool = True) -> str:
        return self._halt(scope, key, reason, manual)

    def resume(self, scope: str, key: str) -> str | None:
        if self.halts.pop((scope, key), None) is not None:
            msg = f"DEVAM [{scope}/{key}]"
            log.info(msg)
            return msg
        return None

    def check(self, now: float) -> list[str]:
        """Periyodik kontrol. Halt/devam mesajlari doner."""
        out: list[str] = []
        for ex, last in self.last_data.items():
            stale = now - last > self.cfg.halt_on_stale_data_sec
            key = (ex, "stale_data")
            if stale:
                self.fresh_since[ex] = None
                if key not in self.halts:
                    out.append(self._halt(ex, "stale_data", f"{now - last:.0f} sn veri yok", manual=False))
            elif key in self.halts:
                if self.fresh_since.get(ex) is None:
                    self.fresh_since[ex] = now
                elif now - self.fresh_since[ex] >= self.cfg.resume_after_fresh_sec:
                    m = self.resume(ex, "stale_data")
                    if m:
                        out.append(m)
        for ex, until in list(self.pause_until.items()):
            if (ex, "api") in self.halts and now >= until:
                self.api_errors[ex] = 0
                m = self.resume(ex, "api")
                if m:
                    out.append(m)
                del self.pause_until[ex]
        return out

    def can_enter(self, exchange: str) -> bool:
        return not any(scope in ("*", exchange) for scope, _ in self.halts)

    def status(self) -> list[str]:
        return [f"{s}/{k}: {r}" for (s, k), (r, _) in self.halts.items()]
