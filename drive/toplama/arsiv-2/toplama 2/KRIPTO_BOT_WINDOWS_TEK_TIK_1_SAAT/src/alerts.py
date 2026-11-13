"""Çok kanallı bildirim dağıtıcısı (Telegram + Discord Webhook + PagerDuty Events API v2)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .security import mask_secrets, register_secret

_CRITICAL_HINTS = (
    "🚨",
    "KILL-SWITCH",
    "SİGORTA ATTI",
    "CIRCUIT BREAKER",
    "FAILOVER",
    "ACİL",
)


async def send_discord_webhook(webhook_url: str, text: str, *, critical: bool = False) -> bool:
    if not webhook_url:
        return False
    register_secret(webhook_url)
    clean_text = mask_secrets(text)
    color = 0xE74C3C if critical else 0x2ECC71
    content = "@everyone 🚨 **ACİL SİSTEM UYARISI**" if critical else ""
    payload = {
        "content": content,
        "embeds": [
            {
                "title": "KRIPTO-BOT Bildirimi",
                "description": clean_text[:4000],
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as resp:
                return 200 <= resp.status < 300
    except Exception:
        return False


async def send_pagerduty_event(
    routing_key: str,
    summary: str,
    *,
    severity: str = "critical",
    dedup_key: str = "kriptobot-critical",
) -> bool:
    if not routing_key:
        return False
    register_secret(routing_key)
    clean_summary = mask_secrets(summary)[:1000]
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": dedup_key,
        "payload": {
            "summary": clean_summary,
            "source": "kripto-bot",
            "severity": severity,
        },
    }
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
                timeout=10,
            ) as resp:
                return 200 <= resp.status < 300
    except Exception:
        return False


class MultiChannelAlerter:
    """Telegram, Discord ve PagerDuty kanallarını tek çağrıda birleştirir."""

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        discord_webhook_url: str = "",
        pagerduty_routing_key: str = "",
        pagerduty_critical_only: bool = True,
        whatsapp_phone: str = "",
        whatsapp_api_key: str = "",
        whatsapp_cloud_token: str = "",
        whatsapp_phone_number_id: str = "",
        whatsapp_webhook_url: str = "",
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.discord_webhook_url = discord_webhook_url
        self.pagerduty_routing_key = pagerduty_routing_key
        self.pagerduty_critical_only = bool(pagerduty_critical_only)
        self.whatsapp_phone = whatsapp_phone
        self.whatsapp_api_key = whatsapp_api_key
        self.whatsapp_cloud_token = whatsapp_cloud_token
        self.whatsapp_phone_number_id = whatsapp_phone_number_id
        self.whatsapp_webhook_url = whatsapp_webhook_url
        for secret in (
            telegram_token,
            discord_webhook_url,
            pagerduty_routing_key,
            whatsapp_phone,
            whatsapp_api_key,
            whatsapp_cloud_token,
            whatsapp_webhook_url,
        ):
            if secret:
                register_secret(secret)

    @staticmethod
    def is_critical_message(text: str) -> bool:
        upper = (text or "").upper()
        return any(hint.upper() in upper for hint in _CRITICAL_HINTS)

    async def send(self, text: str, *, critical: bool | None = None) -> dict[str, bool]:
        from .telegram import send_telegram
        from .whatsapp import is_whatsapp_configured, send_whatsapp

        clean_text = mask_secrets(text)
        is_crit = self.is_critical_message(clean_text) if critical is None else bool(critical)
        tasks: dict[str, asyncio.Task] = {}
        if self.telegram_token and self.telegram_chat_id:
            tasks["telegram"] = asyncio.create_task(
                send_telegram(self.telegram_token, self.telegram_chat_id, clean_text)
            )
        if is_whatsapp_configured(
            self.whatsapp_phone,
            self.whatsapp_api_key,
            self.whatsapp_cloud_token,
            self.whatsapp_phone_number_id,
            self.whatsapp_webhook_url,
        ):
            tasks["whatsapp"] = asyncio.create_task(
                send_whatsapp(
                    clean_text,
                    phone=self.whatsapp_phone,
                    api_key=self.whatsapp_api_key,
                    cloud_token=self.whatsapp_cloud_token,
                    phone_number_id=self.whatsapp_phone_number_id,
                    webhook_url=self.whatsapp_webhook_url,
                )
            )
        if self.discord_webhook_url:
            tasks["discord"] = asyncio.create_task(
                send_discord_webhook(self.discord_webhook_url, clean_text, critical=is_crit)
            )
        if self.pagerduty_routing_key and (is_crit or not self.pagerduty_critical_only):
            tasks["pagerduty"] = asyncio.create_task(
                send_pagerduty_event(
                    self.pagerduty_routing_key,
                    clean_text,
                    severity="critical" if is_crit else "warning",
                )
            )
        results: dict[str, bool] = {}
        for channel, task in tasks.items():
            try:
                results[channel] = bool(await task)
            except Exception:
                results[channel] = False
        return results

    def status(self) -> dict[str, bool]:
        from .whatsapp import is_whatsapp_configured

        return {
            "telegram": bool(self.telegram_token and self.telegram_chat_id),
            "whatsapp": is_whatsapp_configured(
                self.whatsapp_phone,
                self.whatsapp_api_key,
                self.whatsapp_cloud_token,
                self.whatsapp_phone_number_id,
                self.whatsapp_webhook_url,
            ),
            "discord": bool(self.discord_webhook_url),
            "pagerduty": bool(self.pagerduty_routing_key),
        }

    async def __call__(self, text: str, *, critical: bool | None = None) -> dict[str, bool]:
        return await self.send(text, critical=critical)
