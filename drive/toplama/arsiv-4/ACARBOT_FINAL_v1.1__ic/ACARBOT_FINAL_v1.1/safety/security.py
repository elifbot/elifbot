"""Redact common credential formats from log and CLI text."""

from __future__ import annotations

import re


_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|token|authorization)\b"
    r"(\s*[:=]\s*)(['\"]?)([^,\s;'\"]+)\3"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def mask_secrets(value: object) -> str:
    """Return a display-safe string with common key/value and bearer secrets redacted."""
    text = str(value)
    text = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    return _BEARER.sub("Bearer [REDACTED]", text)
