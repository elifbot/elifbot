"""Güvenlik Zırhlaması: Sır Maskeleme, Log Filtresi ve Harici Metin Temizliği."""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlsplit, urlunsplit

SENSITIVE_ENV_NAMES = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_API_PASSPHRASE",
    "CRYPTOPANIC_KEY",
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_WEBHOOK_URL",
    "PAGERDUTY_ROUTING_KEY",
    "DASHBOARD_TOKEN",
    "LLM_API_KEY",
)

_REGISTERED_SECRETS: set[str] = set()
_LOG_FILTER_INSTALLED = False

_TOKEN_PATTERNS = (
    re.compile(r"\b(?:bot)?\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/[^\s\"']+"),
    re.compile(r"(?i)((?:api[_-]?key|api[_-]?secret|passphrase|token|secret)\s*[:=]\s*)[^\s,;\"']+"),
)

_AUTH_ERROR_KEYWORDS = (
    "authenticationerror",
    "permissiondenied",
    "invalid api-key",
    "invalid api key",
    "api-key format invalid",
    "signature for this request is not valid",
    "invalid sign",
    "unauthorized",
    "forbidden",
    "passphrase",
    "-2014",
    "-2015",
    "-1022",
    "50111",
    "50113",
    "50119",
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def register_secret(value: str | None) -> None:
    """Çalışma zamanında bilinen bir sırrı maskeleme havuzuna ekler."""
    if not value:
        return
    cleaned = str(value).strip()
    if len(cleaned) >= 4:
        _REGISTERED_SECRETS.add(cleaned)


def _active_secrets() -> list[str]:
    secrets = set(_REGISTERED_SECRETS)
    for env_name in SENSITIVE_ENV_NAMES:
        val = os.getenv(env_name, "").strip()
        if len(val) >= 4:
            secrets.add(val)
    return sorted(secrets, key=len, reverse=True)


def mask_secrets(text: object) -> str:
    """Metin içindeki kayıtlı sırları ve bilinen token kalıplarını maskeler."""
    out = "" if text is None else str(text)
    if not out:
        return out
    for secret in _active_secrets():
        if secret in out:
            out = out.replace(secret, "***REDACTED***")
    for idx, pattern in enumerate(_TOKEN_PATTERNS):
        if idx == len(_TOKEN_PATTERNS) - 1:
            out = pattern.sub(r"\1***REDACTED***", out)
        else:
            out = pattern.sub("***REDACTED***", out)
    return out


def safe_exception_msg(exc: BaseException, max_len: int = 240) -> str:
    """İstisna mesajını sır sızdırmadan ve makul uzunlukta döndürür."""
    raw = f"{type(exc).__name__}: {exc}"
    masked = mask_secrets(raw)
    masked = _CTRL_CHAR_RE.sub(" ", masked)
    masked = re.sub(r"\s+", " ", masked).strip()
    if len(masked) > max_len:
        return masked[: max_len - 1] + "…"
    return masked


def is_auth_or_permission_error(exc: BaseException) -> bool:
    """Borsa/API kimlik doğrulama veya yetki hatası olup olmadığını tespit eder."""
    cls_name = type(exc).__name__.lower()
    if "authentication" in cls_name or "permission" in cls_name:
        return True
    msg = str(exc).lower()
    return any(keyword in msg for keyword in _AUTH_ERROR_KEYWORDS)


def sanitize_external_text(text: object, max_len: int = 350) -> str:
    """RSS/API/kullanıcı kaynaklı metinlerden HTML ve kontrol karakterlerini temizler."""
    if text is None:
        return ""
    cleaned = str(text)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = _CTRL_CHAR_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = mask_secrets(cleaned)
    if max_len > 0 and len(cleaned) > max_len:
        return cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


def sanitize_url(url: object, max_len: int = 300) -> str:
    """Yalnız güvenli http/https URL'lerini kullanıcı bilgisi olmadan döndürür."""
    if not url:
        return ""
    raw = str(url).strip()
    if len(raw) > max_len:
        raw = raw[:max_len]
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc or "@" in parts.netloc:
        return ""
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    return mask_secrets(clean)


class _SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            try:
                rendered = record.getMessage()
            except Exception:
                rendered = str(record.msg)
            record.msg = mask_secrets(rendered)
            record.args = ()
        else:
            record.msg = mask_secrets(record.msg)
        return True


def install_log_masking() -> None:
    """Root logger üzerine tekrarlanmayan sır maskeleme filtresi kurar."""
    global _LOG_FILTER_INSTALLED
    if _LOG_FILTER_INSTALLED:
        return
    root = logging.getLogger()
    root.addFilter(_SecretMaskingFilter())
    _LOG_FILTER_INSTALLED = True
