"""Kritik Güvenlik ve Zırhlama (Security Hardening) Modülü.

Kurallar:
  1) ASLA HASSAS BİLGİ SIZDIRMA (No Secret Leakage):
     Loglarda, hata yakalamalarda, konsol çıktılarında ve Telegram mesajlarında
     API_KEY, API_SECRET, PASSPHRASE veya TOKEN değerleri asla açık yazdırılmaz;
     otomatik olarak `***MASKED***` ile maskelenir.
  2) ÇEVRESEL DEĞİŞKEN GÜVENLİĞİ (Environment Isolation):
     Tüm anahtarlar yalnızca `.env` ve `os.getenv()` üzerinden okunur.
     `config.yaml` içine yanlışlıkla anahtar yazılsa bile reddedilir/temizlenir.
  3) GİRDİ DOĞRULAMA (Input Sanitization):
     RSS ve dış kaynaklardan gelen haber/metin verileri HTML, script, kontrol
     karakteri, SQL/shell/prompt enjeksiyon kalıplarından arındırılır.
  4) YETKİ / KİMLİK DOĞRULAMA HATASI TESPİTİ:
     Borsa API'lerinden dönen 401/403, Invalid API-Key, Signature, Permission
     hatalarını tespit ederek Circuit Breaker'ın 3 hatada Kill-Switch açmasını sağlar.
"""
from __future__ import annotations

import html
import logging
import os
import re
from pathlib import Path

SENSITIVE_ENV_NAMES = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_API_PASSPHRASE",
    "CRYPTOPANIC_KEY",
    "TELEGRAM_BOT_TOKEN",
    "LLM_API_KEY",
)

_EXTRA_SECRETS: set[str] = set()

# Anahtar-değer veya URL içindeki hassas parametre desenleri
_KV_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|api[_-]?secret|secret|passphrase|password|auth[_-]?token|access[_-]?token|bearer)\b"
    r"(\s*[:=]\s*['\"]?)([^'\"\s,&;}{]{4,})(['\"]?)"
)

# Telegram bot URL içindeki token: https://api.telegram.org/bot123456:ABCDEF.../sendMessage
_TG_TOKEN_RE = re.compile(r"bot\d{5,12}:[A-Za-z0-9_-]{15,}")

# Uzun bağımsız yüksek entropili API anahtarı / imza benzeri diziler (32+ karakter)
_LONG_TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|[A-Fa-f0-9]{40,})\b")

# Zararlı HTML / Script / Enjeksiyon desenleri
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|iframe|object|embed)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CTRL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x1b]")
_INJECTION_PATTERNS = re.compile(
    r"(?i)(?:;\s*drop\s+table|union\s+select|insert\s+into|delete\s+from|"
    r"ignore\s+previous\s+instructions|system\s+prompt|<arena-system-message>|"
    r"javascript\s*:|vbscript\s*:|data\s*:\s*text/html|onerror\s*=|onload\s*=|"
    r"\$\([^)]+\)|`[^`]+`)"
)

_AUTH_ERROR_KEYWORDS = (
    "authenticationerror",
    "permissiondenied",
    "invalid api-key",
    "invalid api key",
    "api-key format invalid",
    "signature for this request is not valid",
    "invalid signature",
    "unauthorized",
    "permission denied",
    "insufficient permissions",
    "invalid passphrase",
    "incorrect api key",
    "http 401",
    "http 403",
    "status 401",
    "status 403",
    "-2015",  # Binance: Invalid API-key, IP, or permissions for action
    "-2014",  # Binance: API-key format invalid
    "-1022",  # Binance: Signature for this request is not valid
    "50111",  # OKX: Invalid OK-ACCESS-KEY
    "50113",  # OKX: Invalid signature
)


def register_secret(secret_val: str | None):
    """Çalışma zamanında okunan bir sırrı maskeleme havuzuna ekler."""
    if secret_val and isinstance(secret_val, str):
        s = secret_val.strip()
        if len(s) >= 4:
            _EXTRA_SECRETS.add(s)


def _collect_active_secrets() -> list[str]:
    secrets = set(_EXTRA_SECRETS)
    for env_name in SENSITIVE_ENV_NAMES:
        val = os.getenv(env_name, "").strip()
        if len(val) >= 4:
            secrets.add(val)
    # Uzun olanları önce maskele ki alt-dize çakışması olmasın
    return sorted(secrets, key=len, reverse=True)


def mask_secrets(text: object, extra_secrets: list[str] | None = None) -> str:
    """Metin içindeki tüm API anahtarlarını, şifreleri ve tokenları `***MASKED***` yapar."""
    s = str(text if text is not None else "")
    if not s:
        return s

    all_secrets = _collect_active_secrets()
    if extra_secrets:
        for es in extra_secrets:
            if es and len(str(es).strip()) >= 4:
                all_secrets.append(str(es).strip())

    for sec in all_secrets:
        if sec in s:
            s = s.replace(sec, "***MASKED***")

    s = _TG_TOKEN_RE.sub("bot***MASKED***", s)
    s = _KV_SECRET_RE.sub(r"\1\2***MASKED***\4", s)
    s = _LONG_TOKEN_RE.sub("***MASKED***", s)
    return s


def safe_exception_msg(exc: BaseException, extra_secrets: list[str] | None = None) -> str:
    """İstisna (Exception) nesnesinden yalnızca maskelenmiş güvenli mesaj döner."""
    raw = f"{type(exc).__name__}: {exc}"
    return mask_secrets(raw, extra_secrets=extra_secrets)


def safe_log(msg: object, extra_secrets: list[str] | None = None) -> str:
    """Güvenli konsol yazdırma: hassas verileri maskeler ve ekrana basar."""
    clean = mask_secrets(msg, extra_secrets=extra_secrets)
    print(clean, flush=True)
    return clean


class SecretMaskingFilter(logging.Filter):
    """Python `logging` modülü için otomatik anahtar maskeleme filtresi."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mask_secrets(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def install_log_masking():
    """Root logger üzerine SecretMaskingFilter kurar."""
    root = logging.getLogger()
    if not any(isinstance(f, SecretMaskingFilter) for f in root.filters):
        root.addFilter(SecretMaskingFilter())


def sanitize_external_text(raw: object, max_len: int = 500) -> str:
    """Dışarıdan (RSS, haber API, web) gelen metinleri zararlı kod ve enjeksiyonlardan temizler."""
    if raw is None:
        return ""
    s = str(raw)
    # 1) Script/style bloklarını tamamen sil
    s = _SCRIPT_STYLE_RE.sub(" ", s)
    # 2) Tüm HTML/XML etiketlerini kaldır
    s = _HTML_TAG_RE.sub(" ", s)
    # 3) HTML entity'lerini çöz (&amp; -> &) ve tekrar olası etiketleri temizle
    s = html.unescape(s)
    s = _HTML_TAG_RE.sub(" ", s)
    # 4) Kontrol karakterlerini ve ANSI kaçışlarını sil
    s = _CTRL_CHARS_RE.sub(" ", s)
    # 5) SQL / Shell / Prompt enjeksiyon kalıplarını etkisizleştir
    s = _INJECTION_PATTERNS.sub(" [FİLTRELENDİ] ", s)
    # 6) Fazla boşlukları tek boşluğa indir ve uzunluğu sınırla
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s


def sanitize_url(url: object) -> str:
    """Yalnızca güvenli http/https URL'lerine izin verir (javascript:/data: engellenir)."""
    if not url:
        return ""
    u = str(url).strip()
    if u.lower().startswith(("http://", "https://")):
        return mask_secrets(u[:500])
    return ""


def is_auth_or_permission_error(error: object) -> bool:
    """Hatanın borsa API kimlik doğrulama (401) veya yetki (403) hatası olup olmadığını döner."""
    text = str(error or "").lower()
    cls_name = type(error).__name__.lower()
    combined = f"{cls_name} {text}"
    return any(kw in combined for kw in _AUTH_ERROR_KEYWORDS)


def verify_no_hardcoded_secrets(src_dir: str | Path) -> tuple[bool, list[str]]:
    """Kaynak kodlarda sabit (hardcode) API anahtarı bulunmadığını doğrular."""
    src_path = Path(src_dir)
    violations: list[str] = []
    suspicious_assign = re.compile(
        r"""(?i)\b(binance_api_key|binance_api_secret|okx_api_key|okx_api_secret|telegram_bot_token)\s*=\s*['"][A-Za-z0-9_-]{12,}['"]"""
    )
    for py_file in sorted(src_path.glob("*.py")):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        if suspicious_assign.search(content):
            violations.append(py_file.name)
    return len(violations) == 0, violations


install_log_masking()
