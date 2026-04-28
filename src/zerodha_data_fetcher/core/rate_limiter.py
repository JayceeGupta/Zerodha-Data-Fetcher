"""Rate limiting functionality for API requests."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor


class RequestRateLimiter:
    """Thread-safe request pacer shared across worker threads.

    Uses a monotonic clock to space outgoing requests by a fixed minimum
    interval.  The algorithm resembles a single-token bucket: each caller
    claims the next available time-slot under a lock, then sleeps
    *outside* the lock until that slot arrives.  This means scheduling is
    serialised (fair, FIFO-ish ordering) while the actual waiting is
    concurrent — threads don't block each other while sleeping.
    """

    def __init__(self, requests_per_second: int):
        """
        Args:
            requests_per_second: Maximum number of requests allowed per
                second.  Must be a positive integer.

        Raises:
            ValueError: If *requests_per_second* is zero or negative.
        """
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than 0")

        self.requests_per_second = requests_per_second
        # Convert "N requests/sec" into the minimum gap between two
        # consecutive requests (in seconds).
        self._min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_allowed_time = 0.0

    def wait_for_slot(self) -> None:
        """Block until the caller is allowed to issue the next request."""
        with self._lock:
            now = time.monotonic()
            # Schedule this request at whichever is later: now, or the
            # earliest slot that hasn't been claimed yet.
            scheduled_time = max(now, self._next_allowed_time)
            # Advance the gate so the next caller waits behind us.
            self._next_allowed_time = scheduled_time + self._min_interval

        # Sleep OUTSIDE the lock so other threads can claim their slots
        # while we wait — this is what makes the limiter non-blocking
        # for scheduling while still serialising actual execution.
        sleep_for = scheduled_time - now
        if sleep_for > 0:
            time.sleep(sleep_for)


class RateLimitedThreadPoolExecutor(ThreadPoolExecutor):
    """Thread-pool executor that enforces request pacing across workers.

    Wraps the standard :class:`~concurrent.futures.ThreadPoolExecutor`
    and injects a :class:`RequestRateLimiter` call before every submitted
    callable, ensuring the Zerodha API is never hit faster than the
    configured rate.

    This class is also used as a backward-compatible drop-in for code
    that previously used a plain ``ThreadPoolExecutor``.
    """

    def __init__(self, max_workers=None, requests_per_second=1, **kwargs):
        """
        Args:
            max_workers: Maximum number of concurrent threads (passed
                through to :class:`ThreadPoolExecutor`).
            requests_per_second: Target pacing — the shared rate limiter
                allows at most this many requests per second across *all*
                worker threads.
            **kwargs: Additional keyword arguments forwarded to
                :class:`ThreadPoolExecutor`.

        Raises:
            ValueError: If *requests_per_second* is zero or negative.
        """
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than 0")

        super().__init__(max_workers=max_workers, **kwargs)
        self.requests_per_second = requests_per_second
        self._rate_limiter = RequestRateLimiter(requests_per_second)

    def submit(self, fn, /, *args, **kwargs):
        """Submit work while enforcing shared request pacing across workers.

        Wraps *fn* so that each invocation waits for a rate-limiter slot
        before executing, then delegates to the parent ``submit()``.
        """

        def rate_limited_fn(*wrapped_args, **wrapped_kwargs):
            self._rate_limiter.wait_for_slot()
            return fn(*wrapped_args, **wrapped_kwargs)

        return super().submit(rate_limited_fn, *args, **kwargs)
