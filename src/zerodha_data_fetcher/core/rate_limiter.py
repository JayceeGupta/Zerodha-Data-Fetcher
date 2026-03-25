"""Rate limiting functionality for API requests."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor


class RequestRateLimiter:
    """Thread-safe execution-time limiter shared across worker threads."""

    def __init__(self, requests_per_second: int):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than 0")

        self.requests_per_second = requests_per_second
        self._min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_allowed_time = 0.0

    def wait_for_slot(self) -> None:
        """Block until the caller is allowed to issue the next request."""
        with self._lock:
            now = time.monotonic()
            scheduled_time = max(now, self._next_allowed_time)
            self._next_allowed_time = scheduled_time + self._min_interval

        sleep_for = scheduled_time - now
        if sleep_for > 0:
            time.sleep(sleep_for)


class RateLimitedThreadPoolExecutor(ThreadPoolExecutor):
    """Backward-compatible executor wrapper used for parallel chunk execution."""

    def __init__(self, max_workers, requests_per_second):
        super().__init__(max_workers=max_workers)
        self.requests_per_second = requests_per_second
