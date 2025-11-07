"""In-memory token bucket rate limiter keyed by API token."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _BucketState:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    """Simple per-key token bucket supporting minute-based refill."""

    def __init__(self, rate_per_minute: int, capacity: float | None = None) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self.rate_per_minute = float(rate_per_minute)
        self.capacity = capacity if capacity is not None else float(rate_per_minute)
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        self._lock = threading.Lock()
        self._buckets: dict[str, _BucketState] = {}

    def _refill(self, state: _BucketState, now: float) -> None:
        elapsed = max(0.0, now - state.last_refill)
        state.last_refill = now
        refill_rate = self.rate_per_minute / 60.0
        state.tokens = min(self.capacity, state.tokens + elapsed * refill_rate)

    def consume(self, key: str, tokens: float = 1.0) -> bool:
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        now = time.monotonic()
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(tokens=self.capacity, last_refill=now)
                self._buckets[key] = state
            else:
                self._refill(state, now)
            if state.tokens < tokens:
                return False
            state.tokens -= tokens
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
