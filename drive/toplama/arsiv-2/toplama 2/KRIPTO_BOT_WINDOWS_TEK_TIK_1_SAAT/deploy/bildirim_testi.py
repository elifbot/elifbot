#!/usr/bin/env python3
"""Telegram/WhatsApp hazırlığını ve gerçek teslimatı stratejiyi başlatmadan test eder."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.telegram import make_alerter  # noqa: E402
from src.whatsapp import is_whatsapp_configured  # noqa: E402


async def main() -> int:
    cfg = load_config()
    api = cfg["api"]
    notification_cfg = cfg.get("bildirimler", {})
    telegram_enabled = bool(notification_cfg.get("telegram_aktif", True))
    whatsapp_enabled = bool(notification_cfg.get("whatsapp_aktif", True))

    telegram_ready = bool(
        str(api.get("telegram_token", "")).strip()
        and str(api.get("telegram_chat", "")).strip()
    )
    wa_cfg = {
        "phone": api.get("whatsapp_phone", ""),
        "api_key": api.get("whatsapp_api_key", ""),
        "cloud_token": api.get("whatsapp_cloud_token", ""),
        "phone_number_id": api.get("whatsapp_phone_id", ""),
        "webhook_url": api.get("whatsapp_webhook", ""),
    }
    whatsapp_ready = is_whatsapp_configured(
        phone=str(wa_cfg["phone"]),
        api_key=str(wa_cfg["api_key"]),
        cloud_token=str(wa_cfg["cloud_token"]),
        phone_number_id=str(wa_cfg["phone_number_id"]),
        webhook_url=str(wa_cfg["webhook_url"]),
    )

    print(
        "Hazırlık: "
        f"Telegram={'HAZIR' if telegram_ready else ('EKSİK' if telegram_enabled else 'KAPALI')} | "
        f"WhatsApp={'HAZIR' if whatsapp_ready else ('EKSİK' if whatsapp_enabled else 'KAPALI')}"
    )
    missing: list[str] = []
    if telegram_enabled and not telegram_ready:
        missing.append("Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
    if whatsapp_enabled and not whatsapp_ready:
        missing.append("WhatsApp: desteklenen sağlayıcı kimlik bilgileri")
    if missing:
        print("Kimlik bilgisi eksik: " + "; ".join(missing))
        return 2

    alerter = make_alerter(
        api["telegram_token"] if telegram_enabled else "",
        api["telegram_chat"] if telegram_enabled else "",
        discord_webhook="",
        pagerduty_routing_key="",
        whatsapp_phone=wa_cfg["phone"] if whatsapp_enabled else "",
        whatsapp_api_key=wa_cfg["api_key"] if whatsapp_enabled else "",
        whatsapp_cloud_token=wa_cfg["cloud_token"] if whatsapp_enabled else "",
        whatsapp_phone_number_id=wa_cfg["phone_number_id"] if whatsapp_enabled else "",
        whatsapp_webhook_url=wa_cfg["webhook_url"] if whatsapp_enabled else "",
    )
    result = await alerter(
        "🧪 KRIPTO-BOT bağımsız bildirim testi başarılıysa bu mesajı görmelisiniz."
    )
    failures: list[str] = []
    if telegram_enabled and result.get("telegram") is not True:
        failures.append("Telegram")
    if whatsapp_enabled and result.get("whatsapp") is not True:
        failures.append("WhatsApp")
    print(
        "Teslimat: "
        + " | ".join(
            f"{name}={'BAŞARILI' if ok else 'BAŞARISIZ'}"
            for name, ok in (
                ("Telegram", not telegram_enabled or result.get("telegram") is True),
                ("WhatsApp", not whatsapp_enabled or result.get("whatsapp") is True),
            )
        )
    )
    if failures:
        print("Test başarısız: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
