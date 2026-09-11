"""Small in-process limiter for login failures."""

import math
from collections import deque
from datetime import timedelta
from threading import Lock


class LoginRateLimiter:
    """Allow a bounded burst of login attempts per direct client address."""

    def __init__(self, maximum_attempts: int = 5, window: timedelta = timedelta(minutes=1)) -> None:
        self._maximum_attempts = maximum_attempts
        self._window_seconds = window.total_seconds()
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def begin_attempt(self, client_key: str, now: float) -> int | None:
        """Record an allowed attempt or return the retry delay in seconds."""

        with self._lock:
            attempts = self._attempts.setdefault(client_key, deque())
            threshold = now - self._window_seconds
            while attempts and attempts[0] <= threshold:
                attempts.popleft()
            if len(attempts) >= self._maximum_attempts:
                return max(1, math.ceil(attempts[0] + self._window_seconds - now))
            attempts.append(now)
            return None

    def clear(self, client_key: str) -> None:
        """Forget failures after a successful authentication."""

        with self._lock:
            self._attempts.pop(client_key, None)
