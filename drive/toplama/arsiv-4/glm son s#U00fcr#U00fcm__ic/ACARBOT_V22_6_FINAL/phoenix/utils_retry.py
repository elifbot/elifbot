"""Bounded retry utility + exchange ban detection shared by market-data and execution layers.

V22 changes
-----------
* Bans (HTTP 418 / Binance -1003 "banned until <ms>") are NEVER retried: retrying during
  a ban only extends it. They raise ``ExchangeBanned`` once the ban window is known.
* Request-validity errors (BadRequest, InvalidOrder, BadSymbol, auth errors ...) are not
  retried either; they cannot succeed on a second attempt and only burn rate-limit weight.
"""
from dataclasses import dataclass
from time import sleep
import random
import re
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

_NON_RETRYABLE_NAMES = {
    "BadRequest", "BadSymbol", "InvalidOrder", "InsufficientFunds", "AuthenticationError",
    "PermissionDenied", "AccountSuspended", "ArgumentsRequired", "NotSupported",
    "OrderNotFound", "OrderImmediatelyFillable", "OrderNotFillable", "InvalidNonce",
    "ExchangeBanned",
}
_BAN_RE = re.compile(r"banned until\s+(\d{10,13})", re.I)


class ExchangeBanned(RuntimeError):
    """Raised when an exchange/IP ban is active; carries the ban expiry (epoch seconds)."""

    def __init__(self, message: str, until_ts: float = 0.0):
        super().__init__(message)
        self.until_ts = float(until_ts or 0.0)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base_delay: float = 0.25
    max_delay: float = 4.0
    jitter: float = 0.10

    def __post_init__(self):
        if self.attempts < 1 or self.base_delay < 0 or self.max_delay < 0 or self.jitter < 0:
            raise ValueError("invalid retry policy")


def is_ban(exc: BaseException) -> bool:
    """True for Binance WAF/IP bans (418, -1003 'banned until') and our own ExchangeBanned."""
    if isinstance(exc, ExchangeBanned):
        return True
    text = str(exc)
    low = text.lower()
    if _BAN_RE.search(text):
        return True
    if "-1003" in text and ("banned" in low or "too many requests" in low):
        return True
    return " 418" in text or "http 418" in low or "418 i'm a teapot" in low


def parse_ban_until(exc: BaseException) -> float:
    """Return ban expiry as epoch seconds, or 0.0 when the message has no timestamp."""
    if isinstance(exc, ExchangeBanned):
        return exc.until_ts
    m = _BAN_RE.search(str(exc))
    if not m:
        return 0.0
    raw = int(m.group(1))
    return raw / 1000.0 if raw > 10_000_000_000 else float(raw)


def default_retryable(exc: BaseException) -> bool:
    if is_ban(exc):
        return False
    names = {c.__name__ for c in type(exc).__mro__}
    return not (names & _NON_RETRYABLE_NAMES)


def with_retry(fn: Callable[[], T], policy: RetryPolicy = RetryPolicy(),
               retryable: Optional[Callable[[BaseException], bool]] = None) -> T:
    check = retryable or default_retryable
    last = None
    for attempt in range(policy.attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if not check(exc):
                raise
            if attempt + 1 < policy.attempts:
                delay = min(policy.max_delay, policy.base_delay * (2 ** attempt))
                if policy.jitter:
                    delay += random.random() * policy.jitter
                sleep(delay)
    raise last
