"""Alarm: konsol logu + (varsa) Telegram. Token asla loglanmaz."""
from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger("alert")


class Alerter:
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat = os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.token and self.chat)

    def _post(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": self.chat, "text": text[:4000]}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10).read()
        except Exception as e:  # noqa: BLE001 - alarm hatasi botu durdurmamali
            log.warning("Telegram gonderilemedi: %s", type(e).__name__)

    async def send(self, text: str) -> None:
        log.info(text)
        if self.telegram_enabled:
            await asyncio.to_thread(self._post, text)
