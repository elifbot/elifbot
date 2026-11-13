"""Small bounded retry utility shared by market-data and execution layers."""
from dataclasses import dataclass
from time import sleep
import random
from typing import Callable, TypeVar

T = TypeVar("T")

@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base_delay: float = 0.25
    max_delay: float = 4.0
    jitter: float = 0.10

    def __post_init__(self):
        if self.attempts < 1 or self.base_delay < 0 or self.max_delay < 0 or self.jitter < 0:
            raise ValueError("invalid retry policy")


def with_retry(fn: Callable[[], T], policy: RetryPolicy = RetryPolicy()) -> T:
    last = None
    for attempt in range(policy.attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if attempt + 1 < policy.attempts:
                delay = min(policy.max_delay, policy.base_delay * (2 ** attempt))
                if policy.jitter:
                    delay += random.random() * policy.jitter
                sleep(delay)
    raise last
