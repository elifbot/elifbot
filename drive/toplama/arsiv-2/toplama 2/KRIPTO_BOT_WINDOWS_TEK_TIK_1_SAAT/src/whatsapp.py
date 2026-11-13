"""WhatsApp Bildirim Modülü (TextMeBot + CallMeBot + Resmi Meta Cloud API + Özel Webhook).

Desteklenen 4 Yöntem (otomatik algılanır):
  1. TextMeBot (Harf+rakam APIKey — örn. 12 haneli alfanümerik):
       WHATSAPP_PHONE (örn. +905XXXXXXXXX) + WHATSAPP_API_KEY
  2. CallMeBot (Sayısal APIKey — örn. 6-7 haneli rakam):
       WHATSAPP_PHONE (örn. +905XXXXXXXXX) + WHATSAPP_API_KEY
  3. Meta WhatsApp Cloud API (Resmi):
       WHATSAPP_PHONE + WHATSAPP_CLOUD_TOKEN + WHATSAPP_PHONE_NUMBER_ID
  4. Kendi Sunucun (WAHA / Evolution API Webhook):
       WHATSAPP_WEBHOOK_URL (+ isteğe bağlı WHATSAPP_PHONE)

Güvenlik:
  • Telefon numarası, API anahtarı ve token'lar `register_secret` ile kaydedilir;
    loglarda veya hata mesajlarında asla açık görünmez.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus

from .security import mask_secrets, register_secret


def normalize_callmebot_apikey(api_key: str) -> str:
    """TextMeBot/CallMeBot mesajı veya URL yapıştırılmışsa içindeki APIKey değerini ayıklar."""
    raw = str(api_key or "").strip().strip("\"'").strip()
    if raw:
        register_secret(raw)
    m_url = re.search(
        r"(?i)apikey(?:\s+is|\s+for\s+you:|\s*[=:])\s*\*?\*?([A-Za-z0-9]{4,24})",
        raw,
    )
    if m_url:
        register_secret(m_url.group(1))
        return m_url.group(1)
    if raw.isdigit() or re.fullmatch(r"[A-Za-z0-9_-]{4,32}", raw):
        return raw
    nums = [n for n in re.findall(r"\d{5,9}", raw) if not n.startswith("905")]
    if len(nums) == 1:
        register_secret(nums[0])
        return nums[0]
    return raw


def normalize_whatsapp_phone(phone: str) -> str:
    """Telefon numarasını uluslararası rakam biçimine (+905... -> 905...) temizler."""
    raw = str(phone or "").strip().strip("\"'").strip()
    digits = re.sub(r"[^\d]", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        # Türkiye yerel 05XX... yazılırsa otomatik 905XX... yap
        digits = "90" + digits[1:]
    elif len(digits) == 10 and digits.startswith("5"):
        digits = "90" + digits
    if digits:
        register_secret(digits)
        if raw:
            register_secret(raw)
    return digits


def whatsapp_message_chunks(text: str, max_len: int = 1500) -> list[str]:
    """WhatsApp servis sınırları için satır bazlı güvenli parçalama."""
    clean = mask_secrets(text)
    chunks: list[str] = []
    current = ""
    limit = max(300, int(max_len))
    for line in clean.splitlines(keepends=True):
        if len(line) > limit:
            line = line[: limit - 40] + "\n… [satır kısaltıldı]\n"
        if current and len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or ([clean[:limit]] if clean else [])


def is_whatsapp_configured(
    phone: str = "",
    api_key: str = "",
    cloud_token: str = "",
    phone_number_id: str = "",
    webhook_url: str = "",
) -> bool:
    norm_phone = normalize_whatsapp_phone(phone)
    if cloud_token.strip() and phone_number_id.strip() and norm_phone:
        return True
    if api_key.strip() and norm_phone:
        return True
    if webhook_url.strip():
        return True
    return False


async def send_whatsapp(
    text: str,
    *,
    phone: str = "",
    api_key: str = "",
    cloud_token: str = "",
    phone_number_id: str = "",
    webhook_url: str = "",
) -> bool:
    """Yapılandırılan WhatsApp sağlayıcısı üzerinden tek mesaj gönderir."""
    norm_phone = normalize_whatsapp_phone(phone)
    key_clean = normalize_callmebot_apikey(api_key)
    token_clean = str(cloud_token or "").strip().strip("\"'")
    pid_clean = str(phone_number_id or "").strip().strip("\"'")
    hook_clean = str(webhook_url or "").strip().strip("\"'")

    for sec in (key_clean, token_clean, hook_clean):
        if sec:
            register_secret(sec)

    if not is_whatsapp_configured(
        norm_phone, key_clean, token_clean, pid_clean, hook_clean
    ):
        return False

    clean_text = mask_secrets(text)
    if len(clean_text) > 1500:
        clean_text = clean_text[:1450] + "\n… [rapor kısaltıldı]"

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            # 1) Resmi Meta WhatsApp Cloud API
            if token_clean and pid_clean and norm_phone:
                url = f"https://graph.facebook.com/v20.0/{pid_clean}/messages"
                headers = {
                    "Authorization": f"Bearer {token_clean}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "messaging_product": "whatsapp",
                    "to": norm_phone,
                    "type": "text",
                    "text": {"preview_url": False, "body": clean_text},
                }
                async with session.post(
                    url, json=payload, headers=headers, timeout=12
                ) as resp:
                    return 200 <= resp.status < 300

            # 2) TextMeBot (Alfanümerik APIKey) veya CallMeBot (Sayısal APIKey)
            if key_clean and norm_phone:
                encoded = quote_plus(clean_text)
                if key_clean.isdigit():
                    url = (
                        f"https://api.callmebot.com/whatsapp.php?"
                        f"phone={norm_phone}&text={encoded}&apikey={quote_plus(key_clean)}"
                    )
                else:
                    url = (
                        f"https://api.textmebot.com/send.php?"
                        f"recipient=%2B{norm_phone}&apikey={quote_plus(key_clean)}&text={encoded}"
                    )
                async with session.get(url, timeout=20) as resp:
                    body = await resp.text()
                    low = body.lower()
                    has_err = (
                        any(t in low for t in ("error:", "apikey is invalid", "not connected"))
                        and "success" not in low
                    )
                    return (200 <= resp.status < 300) and not has_err

            # 3) Özel Webhook (WAHA / Evolution API)
            if hook_clean:
                payload = {"phone": norm_phone, "text": clean_text}
                async with session.post(hook_clean, json=payload, timeout=12) as resp:
                    return 200 <= resp.status < 300
    except Exception as exc:
        print(
            f"⚠️ WhatsApp gönderim hatası ({type(exc).__name__}); "
            "WhatsApp ayarlarını kontrol edin.",
            flush=True,
        )
        return False
    return False


async def send_whatsapp_long(
    text: str,
    *,
    phone: str = "",
    api_key: str = "",
    cloud_token: str = "",
    phone_number_id: str = "",
    webhook_url: str = "",
) -> bool:
    """Uzun saatlik/günlük raporları parçalara bölerek WhatsApp'a iletir."""
    if not is_whatsapp_configured(
        phone, api_key, cloud_token, phone_number_id, webhook_url
    ):
        return False
    key_clean = normalize_callmebot_apikey(api_key)
    pause_sec = 1.0 if (not key_clean or key_clean.isdigit()) else 5.2
    chunks = whatsapp_message_chunks(text, max_len=1450)
    ok = True
    for idx, chunk in enumerate(chunks, 1):
        prefix = f"({idx}/{len(chunks)})\n" if len(chunks) > 1 else ""
        sent = await send_whatsapp(
            prefix + chunk,
            phone=phone,
            api_key=api_key,
            cloud_token=cloud_token,
            phone_number_id=phone_number_id,
            webhook_url=webhook_url,
        )
        ok = sent and ok
        if idx < len(chunks):
            await asyncio.sleep(pause_sec)
    return ok
