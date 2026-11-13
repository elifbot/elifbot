"""Asenkron Telegram bildirimleri (Y2 operasyonel düzeltme).

Eski sürümde `urlopen` senkrondu ve `notify("critical")` event loop'u
bloklayabiliyordu. Yeni sürüm:
  - Gönderimler bir asyncio kuyruğuna atılır, arka plan görevi tüketir.
  - Dakika başına mesaj limiti (drop + log).
  - asyncio yoksa / test ortamındaysa senkron yola düşer (log asla engellenmez).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from safety.security import mask_secrets

logger = logging.getLogger("paper_bot.alerts")


def _load_dotenv(path: str = ".env") -> None:
    p = path if isinstance(path, str) else str(path)
    if not os.path.isfile(p):
        return
    try:
        for line in open(p, encoding="utf-8"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError as exc:
        logger.error("Telegram yapılandırma dosyası okunamadı: %s", exc)


class TelegramNotifier:
    """Senkron HTTP gönderimi (yalnız arka plan görevinden çağrılır)."""

    def __init__(self, token: str, chat_id: str, timeout: float = 5.0) -> None:
        if not token or not chat_id:
            raise ValueError("Telegram token ve chat ID zorunlu")
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout

    @classmethod
    def from_environment(cls) -> TelegramNotifier | None:
        _load_dotenv()
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token and not chat_id:
            return None
        if not token or not chat_id:
            logger.error(
                "Telegram için TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID birlikte gerekli"
            )
            return None
        return cls(token, chat_id)

    def send(self, message: str) -> bool:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        body = json.dumps({
            "chat_id": self._chat_id,
            "text": mask_secrets(message),
        }).encode("utf-8")
        request = Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                if response.status != 200:
                    logger.error("Telegram HTTP %s ile başarısız", response.status)
                    return False
                result = json.loads(response.read().decode("utf-8"))
                return isinstance(result, dict) and result.get("ok") is True
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError):
            logger.error("Telegram gönderimi başarısız")
            return False


class AlertManager:
    """Log + kuyruklu asenkron Telegram. Hiçbir çağrı engellemez."""

    LEVELS = {"debug", "info", "warning", "error", "critical"}

    def __init__(
        self,
        telegram: TelegramNotifier | None = None,
        rate_limit_per_min: int = 20,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.telegram = telegram
        self.rate_limit = max(1, rate_limit_per_min)
        self._queue: asyncio.Queue[str] | None = None
        self._worker_task: asyncio.Task | None = None
        self._loop = loop
        self._sent_timestamps: list[float] = []
        self._dropped = 0
        self._queue_full_count = 0

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Canlı döngü başlarken çağrılır; kuyruk + worker başlatır."""
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=200)
        self._worker_task = loop.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                if self.telegram is not None:
                    await asyncio.to_thread(self.telegram.send, message)
            except Exception:  # noqa: BLE001 — bildirim hataları akışı durdurmaz
                logger.exception("Telegram worker hatası")
            finally:
                self._queue.task_done()
                await asyncio.sleep(0.05)

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            self._queue = None

    def _rate_allowed(self) -> bool:
        now = time.monotonic()
        self._sent_timestamps = [
            ts for ts in self._sent_timestamps if now - ts < 60.0
        ]
        if len(self._sent_timestamps) >= self.rate_limit:
            self._dropped += 1
            return False
        self._sent_timestamps.append(now)
        return True

    def _enqueue(self, message: str) -> None:
        if not self._rate_allowed():
            if self._dropped % 10 == 1:
                logger.warning("Telegram hız limiti: mesaj düşürüldü")
            return
        if self._queue is None or self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, message
            )
        except RuntimeError:
            pass  # döngü kapandı

    def notify(self, message: str, level: str = "info") -> str:
        """Asla engellemeyen bildirim. Kritik mesajlar kuyruğa girer."""
        level_lower = level.lower()
        if level_lower not in self.LEVELS:
            raise ValueError(f"desteklenmeyen seviye: {level}")
        sanitized = mask_secrets(message)
        log_method = {
            "debug": logger.debug, "info": logger.info,
            "warning": logger.warning, "error": logger.error,
            "critical": logger.critical,
        }[level_lower]
        log_method("%s", sanitized)
        if level_lower in {"critical", "error"} or self.telegram is not None:
            self._enqueue(f"[{level_upper(level_lower)}] {sanitized}")
        return sanitized

    def notify_event(self, message: str) -> str:
        """İşlem olayları (emir açıldı/kapandı) — bilgi + Telegram."""
        sanitized = mask_secrets(message)
        logger.info("%s", sanitized)
        self._enqueue(sanitized)
        return sanitized

    def stats(self) -> dict[str, int]:
        return {
            "dropped": self._dropped,
            "queue_full": self._queue_full_count,
            "sent_last_minute": len(self._sent_timestamps),
        }


def level_upper(level: str) -> str:
    return level.upper()
