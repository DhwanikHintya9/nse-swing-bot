"""Per-process Kite API pacing and bounded retry behavior."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

ENDPOINT_INTERVAL_SECONDS = {
    "quote": 1.0,
    "historical": 1.0 / 3.0,
    "other": 1.0 / 10.0,
}


class KiteRequestPacer:
    """Serialize requests and enforce conservative per-endpoint minimum spacing.

    This is intentionally process-local. A multi-worker deployment must replace
    it with a shared limiter keyed by API key before running concurrent workers.
    """

    def __init__(
        self,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request: dict[str, float] = {}
        self._lock = Lock()

    def wait(self, endpoint: str) -> None:
        if endpoint not in ENDPOINT_INTERVAL_SECONDS:
            raise ValueError(f"unknown Kite endpoint class: {endpoint}")
        with self._lock:
            now = self._monotonic()
            interval = ENDPOINT_INTERVAL_SECONDS[endpoint]
            previous = self._last_request.get(endpoint)
            delay = 0.0 if previous is None else max(0.0, previous + interval - now)
            if delay:
                self._sleep(delay)
            self._last_request[endpoint] = self._monotonic()


# All adapters in this process share one limiter. Multi-process deployments must
# replace this with a distributed limiter keyed by the Kite API key.
DEFAULT_KITE_REQUEST_PACER = KiteRequestPacer()


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 16.0
    rate_limit_cooldown_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if min(
            self.base_delay_seconds,
            self.max_delay_seconds,
            self.rate_limit_cooldown_seconds,
        ) < 0:
            raise ValueError("retry delays cannot be negative")


def _status_code(error: Exception) -> int | None:
    value: Any = getattr(error, "status_code", None)
    if value is None:
        value = getattr(error, "code", None)
    response = getattr(error, "response", None)
    if value is None and response is not None:
        value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        raw = getattr(error, "retry_after", None)
    try:
        delay = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, delay)


def _is_transient(error: Exception) -> bool:
    status = _status_code(error)
    if status == 429 or (status is not None and 500 <= status <= 599):
        return True
    if status is not None:
        return False
    return isinstance(error, (TimeoutError, ConnectionError, OSError))


class KiteRequestExecutor:
    """Pace and retry only transient failures; authentication/input errors fail fast."""

    def __init__(
        self,
        pacer: KiteRequestPacer | None = None,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.pacer = pacer or DEFAULT_KITE_REQUEST_PACER
        self.policy = policy or RetryPolicy()
        self.sleep = sleep

    def call(self, endpoint: str, operation: Callable[[], Any]) -> Any:
        for attempt in range(1, self.policy.max_attempts + 1):
            self.pacer.wait(endpoint)
            try:
                return operation()
            except Exception as error:
                if not _is_transient(error) or attempt >= self.policy.max_attempts:
                    raise
                status = _status_code(error)
                if status == 429:
                    delay = _retry_after(error)
                    if delay is None:
                        delay = self.policy.rate_limit_cooldown_seconds
                else:
                    delay = min(
                        self.policy.max_delay_seconds,
                        self.policy.base_delay_seconds * (2 ** (attempt - 1)),
                    )
                self.sleep(delay)
        raise RuntimeError("unreachable retry state")
