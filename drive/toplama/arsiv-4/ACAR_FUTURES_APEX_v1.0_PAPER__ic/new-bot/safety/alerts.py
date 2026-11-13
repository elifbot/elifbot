"""Secret-redacted local logs and optional Telegram notifications."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from safety.security import mask_secrets


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError as exc:
        logging.getLogger("paper_bot.alerts").error(
            "Could not read Telegram configuration file: %s", exc
        )


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        if not token or not chat_id:
            raise ValueError("Telegram token and chat ID are required")
        self._token = token
        self._chat_id = chat_id
        self.logger = logging.getLogger("paper_bot.telegram")

    @classmethod
    def from_environment(cls) -> TelegramNotifier | None:
        _load_dotenv()
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token and not chat_id:
            return None
        if not token or not chat_id:
            logging.getLogger("paper_bot.telegram").error(
                "Telegram alerts require both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
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
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                if response.status != 200:
                    self.logger.error(
                        "Telegram notification failed with HTTP %s",
                        response.status,
                    )
                    return False
                result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict) or result.get("ok") is not True:
                    self.logger.error("Telegram rejected a notification")
                    return False
                return True
        except (
            HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError
        ) as exc:
            self.logger.error(
                "Telegram notification failed (%s)",
                type(exc).__name__,
            )
            return False


class AlertManager:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        telegram: TelegramNotifier | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("paper_bot.alerts")
        self.telegram = telegram if telegram is not None else TelegramNotifier.from_environment()

    def notify(self, message: str, level: str = "info") -> str:
        sanitized = mask_secrets(message)
        log_method = {
            "debug": self.logger.debug,
            "info": self.logger.info,
            "warning": self.logger.warning,
            "error": self.logger.error,
            "critical": self.logger.critical,
        }.get(level.lower())
        if log_method is None:
            raise ValueError(f"unsupported alert level: {level}")
        log_method("%s", sanitized)
        if level.lower() == "critical" and self.telegram is not None:
            self.telegram.send(sanitized)
        return sanitized

    def notify_event(self, message: str) -> str:
        sanitized = mask_secrets(message)
        self.logger.info("%s", sanitized)
        if self.telegram is not None:
            self.telegram.send(sanitized)
        return sanitized
