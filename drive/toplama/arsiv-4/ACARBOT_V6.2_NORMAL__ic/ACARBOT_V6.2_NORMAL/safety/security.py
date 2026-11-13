"""Log redaction: common credential patterns and registered secret values.

Defense in depth, not an encryption system and not a guarantee for handlers
outside the application's logging configuration. Avoid logging secrets at all.
"""
from __future__ import annotations

import logging
import os
import re

_ASSIGNMENT = re.compile(
    r'(?i)\b(api[_-]?key|api[_-]?secret|secret|password|token|authorization|'
    r'passphrase|signature|x-mbx-apikey|ok-access-key|ok-access-sign|ok-access-passphrase)\b'
    r'(\s*[:=]\s*)([\'\"]?)([^,\s;\'\"&]+)\3'
)
_BEARER = re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+')
_TELEGRAM = re.compile(r'(?i)(api\.telegram\.org/bot)[^/\s]+')
_registered: set[str] = set()


def register_secret(secret: str) -> None:
    """Register values read from secret files as well as environment variables."""
    if isinstance(secret, str) and len(secret) >= 4:
        _registered.add(secret)


def mask_secrets(value: object) -> str:
    text = str(value)
    secrets = set(_registered)
    for key, val in os.environ.items():
        k = key.upper()
        if (k.endswith(('_API_KEY', '_API_SECRET', '_PASSPHRASE', '_BOT_TOKEN'))
                or k in {'TELEGRAM_BOT_TOKEN', 'ACARBOT_LLM_API_KEY'}):
            if len(val) >= 4:
                secrets.add(val)
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    text = _TELEGRAM.sub(r'\1[REDACTED]', text)
    text = _BEARER.sub('Bearer [REDACTED]', text)
    return _ASSIGNMENT.sub(lambda m: f'{m.group(1)}{m.group(2)}[REDACTED]', text)


class SecretSafeFormatter(logging.Formatter):
    """Redact fully formatted records, including formatted exception text."""

    def format(self, record):
        return mask_secrets(super().format(record))
