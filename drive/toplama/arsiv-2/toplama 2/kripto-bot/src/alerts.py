"""Çok Kanallı Acil Durum & Kritik Bildirim Motoru:
Telegram + Discord Webhook + PagerDuty Events API v2 (Sesli Telefon / On-Call Alarmı).

Özellikler:
  • Tüm giden bildirimler `mask_secrets()` ile filtrelenir; API anahtarı, webhook tokenı
    veya PagerDuty routing key asla loglara/mesajlara sızmaz.
  • Kritik sistem olayları (`CIRCUIT BREAKER`, `SİGORTA ATTI`, `KILL-SWITCH`,
    `MULTI-EXCHANGE FAILOVER`, `YETKİ HATASI`, `FLASH CRASH`, `WS KOPMA`) otomatik
    olarak tespit edilir (`is_critical_alert`).
  • Kritik olay anında:
    1. Telegram üzerinden anlık mesaj gönderilir.
    2. Discord Webhook üzerinden `@everyone` etiketli kırmızı acil durum Embed kartı gönderilir.
    3. PagerDuty Events API v2 (`https://events.pagerduty.com/v2/enqueue`) üzerinden
       `severity: "critical"` ve `event_action: "trigger"` ile doğrudan telefona
       sesli arama / push alarmı tetiklenir.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .security import mask_secrets

PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

_CRITICAL_KEYWORDS = (
    "circuit breaker",
    "sigorta attı",
    "sigorta atti",
    "kill-switch",
    "kill switch",
    "acil kapat",
    "acil durum",
    "yetki hatası",
    "yetki hatasi",
    "multi-exchange failover",
    "flash crash",
    "kopma sigortası",
    "kopma sigortasi",
    "sistem kilidi",
    "system locked",
)


def is_critical_alert(text: str) -> bool:
    """Mesajın kritik bir sistem/sigorta hatası olup olmadığını tespit eder."""
    if not text:
        return False
    low = text.lower()
    if "🚨" in text or "🔀" in text:
        return True
    return any(k in low for k in _CRITICAL_KEYWORDS)


def build_discord_payload(
    text: str,
    critical: bool | None = None,
    username: str = "KRIPTO-BOT Zırhlı Alarm",
) -> dict[str, Any]:
    """Discord Webhook için zengin Embed ve acil durumda `@everyone` içeren JSON üretir."""
    clean = mask_secrets(text)
    is_crit = is_critical_alert(clean) if critical is None else bool(critical)

    if is_crit:
        color = 0xEF4444  # Kırmızı (Kritik Alarm)
        title = "🚨 KRİTİK SİSTEM & SİGORTA ALARMI"
        content = "@everyone 🚨 **ACİL DURUM: KRIPTO-BOT KRİTİK UYARI**"
    elif "⚠️" in clean or "⛔" in clean:
        color = 0xF59E0B  # Kehribar (Uyarı)
        title = "⚠️ KRIPTO-BOT Risk / Filtre Uyarısı"
        content = ""
    else:
        color = 0x10B981  # Yeşil (Normal İşlem / Bilgi)
        title = "🤖 KRIPTO-BOT İşlem Bildirimi"
        content = ""

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "username": username,
        "content": content,
        "embeds": [
            {
                "title": title,
                "description": clean,
                "color": color,
                "timestamp": now_iso,
                "footer": {
                    "text": f"KRIPTO-BOT v6 • Seviye: {'CRITICAL' if is_crit else 'INFO'}"
                },
            }
        ],
    }


def build_pagerduty_payload(
    routing_key: str,
    text: str,
    severity: str = "critical",
    event_action: str = "trigger",
    dedup_key: str = "kriptobot-circuit-breaker",
    source: str = "kripto-bot-prod",
    component: str = "circuit_breaker_and_risk_engine",
    custom_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PagerDuty Events API v2 (`v2/enqueue`) standardında telefon/sesli alarm yükü üretir."""
    clean = mask_secrets(text)
    sev = severity if severity in ("critical", "error", "warning", "info") else "critical"
    return {
        "routing_key": routing_key,
        "event_action": event_action,
        "dedup_key": dedup_key,
        "payload": {
            "summary": clean[:1024] if clean else "KRIPTO-BOT Kritik Sistem Alarmı",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "severity": sev,
            "component": component,
            "group": "trading-engine",
            "class": "emergency_circuit_breaker",
            "custom_details": custom_details
            or {
                "message": clean,
                "triggered_at_unix": round(time.time(), 3),
            },
        },
    }


async def send_discord_webhook(
    webhook_url: str,
    text: str,
    critical: bool | None = None,
) -> bool:
    """Discord Webhook URL'sine asenkron POST isteği gönderir."""
    if not webhook_url:
        return False
    payload = build_discord_payload(text, critical=critical)
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, json=payload, timeout=8
            ) as resp:
                return 200 <= resp.status < 300
    except Exception:
        return False


async def send_pagerduty_event(
    routing_key: str,
    text: str,
    severity: str = "critical",
    event_action: str = "trigger",
    dedup_key: str = "kriptobot-circuit-breaker",
    custom_details: dict[str, Any] | None = None,
) -> bool:
    """PagerDuty Events API v2 üzerinden acil durum incident (telefon/sesli alarm) tetikler."""
    if not routing_key:
        return False
    payload = build_pagerduty_payload(
        routing_key=routing_key,
        text=text,
        severity=severity,
        event_action=event_action,
        dedup_key=dedup_key,
        custom_details=custom_details,
    )
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                PAGERDUTY_EVENTS_URL, json=payload, timeout=8
            ) as resp:
                return 200 <= resp.status < 300
    except Exception:
        return False


class MultiChannelAlerter:
    """Telegram + Discord Webhook + PagerDuty Events API v2 birleşik bildirim dağıtıcısı."""

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        discord_webhook_url: str = "",
        pagerduty_routing_key: str = "",
        discord_only_critical: bool = False,
        pagerduty_only_critical: bool = True,
    ):
        self.telegram_token = (telegram_token or "").strip()
        self.telegram_chat_id = str(telegram_chat_id or "").strip()
        self.discord_webhook_url = (discord_webhook_url or "").strip()
        self.pagerduty_routing_key = (pagerduty_routing_key or "").strip()
        self.discord_only_critical = discord_only_critical
        self.pagerduty_only_critical = pagerduty_only_critical

        self.stats = {
            "total_alerts": 0,
            "critical_alerts": 0,
            "telegram_dispatched": 0,
            "discord_dispatched": 0,
            "pagerduty_triggered": 0,
            "pagerduty_resolved": 0,
        }
        self.history: deque[dict[str, Any]] = deque(maxlen=50)

    async def __call__(self, msg: str) -> dict[str, Any]:
        return await self.send(msg)

    async def send(
        self,
        msg: str,
        force_critical: bool | None = None,
        custom_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mesajı analiz eder; kritikse Telegram + Discord + PagerDuty kanallarını paralel tetikler."""
        from .telegram import send_telegram

        clean = mask_secrets(msg)
        crit = is_critical_alert(clean) if force_critical is None else bool(force_critical)
        self.stats["total_alerts"] += 1
        if crit:
            self.stats["critical_alerts"] += 1

        channels_used: list[str] = []
        tasks = []

        # 1) Telegram
        if self.telegram_token and self.telegram_chat_id:
            tasks.append(
                send_telegram(self.telegram_token, self.telegram_chat_id, clean)
            )
            channels_used.append("telegram")
            self.stats["telegram_dispatched"] += 1

        # 2) Discord Webhook
        should_discord = crit or (not self.discord_only_critical)
        discord_preview = None
        if should_discord:
            discord_preview = build_discord_payload(clean, critical=crit)
            self.stats["discord_dispatched"] += 1
            channels_used.append("discord")
            if self.discord_webhook_url:
                tasks.append(
                    send_discord_webhook(
                        self.discord_webhook_url, clean, critical=crit
                    )
                )

        # 3) PagerDuty Events API v2 (Kritik olaylarda telefon/sesli alarm)
        should_pd = crit or (not self.pagerduty_only_critical)
        pd_preview = None
        if should_pd:
            pd_preview = build_pagerduty_payload(
                routing_key="***MASKED_ROUTING_KEY***",
                text=clean,
                severity="critical" if crit else "warning",
                event_action="trigger",
                custom_details=custom_details,
            )
            self.stats["pagerduty_triggered"] += 1
            channels_used.append("pagerduty")
            if self.pagerduty_routing_key:
                tasks.append(
                    send_pagerduty_event(
                        self.pagerduty_routing_key,
                        clean,
                        severity="critical" if crit else "warning",
                        event_action="trigger",
                        custom_details=custom_details,
                    )
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        rec = {
            "ts": time.strftime("%H:%M:%S"),
            "critical": crit,
            "message": clean,
            "channels": channels_used,
            "discord_embed_title": (
                discord_preview["embeds"][0]["title"] if discord_preview else None
            ),
            "pagerduty_severity": (
                pd_preview["payload"]["severity"] if pd_preview else None
            ),
        }
        self.history.appendleft(rec)
        return rec

    async def resolve_pagerduty(self, reason: str = "Circuit Breaker sıfırlandı, sistem normale döndü") -> dict[str, Any]:
        """Sigorta sıfırlandığında PagerDuty üzerindeki aktif incident'ı `resolve` eder."""
        clean = mask_secrets(reason)
        self.stats["pagerduty_resolved"] += 1
        if self.pagerduty_routing_key:
            await send_pagerduty_event(
                self.pagerduty_routing_key,
                clean,
                severity="info",
                event_action="resolve",
            )
        rec = {
            "ts": time.strftime("%H:%M:%S"),
            "critical": False,
            "message": f"✅ [PagerDuty RESOLVED] {clean}",
            "channels": ["pagerduty"],
        }
        self.history.appendleft(rec)
        return rec

    def snapshot(self) -> dict[str, Any]:
        return {
            "channels_configured": {
                "telegram": bool(self.telegram_token and self.telegram_chat_id),
                "discord": bool(self.discord_webhook_url),
                "pagerduty": bool(self.pagerduty_routing_key),
            },
            "stats": dict(self.stats),
            "recent_alerts": list(self.history)[:10],
        }
