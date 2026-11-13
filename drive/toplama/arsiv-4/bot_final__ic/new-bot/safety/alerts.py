"""In-process, secret-redacted alerts; no external notification service is used."""

from __future__ import annotations

import logging

from safety.security import mask_secrets


class AlertManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("paper_bot.alerts")

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
        return sanitized
