"""Rate limiting utilities for UniFi Protect API requests."""

from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimiter:
    """
    Async rate limiter using a sliding window algorithm.

    This rate limiter ensures that no more than `max_requests` are made
    within a rolling `window_seconds` time window. It is designed to
    prevent hitting the UniFi Protect API rate limit of 10 requests/second.

    Usage:
        limiter = RateLimiter(max_requests=10, window_seconds=1.0)
        await limiter.acquire()  # Blocks if rate limit would be exceeded
        # ... make API request ...
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: float = 1.0,
    ) -> None:
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum number of requests allowed in the time window.
                          Default is 10 (matching UniFi Protect's limit).
            window_seconds: Size of the sliding window in seconds.
                            Default is 1.0 second.

        """
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """
        Get or create the lock in the current event loop.

        Note: There's a theoretical race condition here where two coroutines
        could create separate locks. However, this is benign because:
        1. It only happens on first access
        2. Python's GIL ensures the assignment is atomic
        3. After first successful assignment, all coroutines use the same lock
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def max_requests(self) -> int:
        """Maximum number of requests allowed in the time window."""
        return self._max_requests

    @property
    def window_seconds(self) -> float:
        """Size of the sliding window in seconds."""
        return self._window_seconds

    def _cleanup_old_timestamps(self, now: float) -> None:
        """Remove timestamps that are outside the current window."""
        cutoff = now - self._window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    async def acquire(self) -> None:
        """
        Acquire permission to make a request.

        This method will block (sleep) if making a request now would
        exceed the rate limit. Once the method returns, the caller
        is free to make their API request.

        Note: Uses asyncio.sleep() which is non-blocking and yields
        control back to the event loop, making it safe for use with
        Home Assistant and other async frameworks.
        """
        async with self._get_lock():
            now = time.monotonic()
            self._cleanup_old_timestamps(now)

            if len(self._timestamps) >= self._max_requests:
                # Need to wait until the oldest request falls outside the window
                oldest = self._timestamps[0]
                wait_time = self._window_seconds - (now - oldest)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    self._cleanup_old_timestamps(now)

            self._timestamps.append(now)

    async def acquire_with_timeout(self, timeout: float) -> bool:
        """
        Try to acquire permission to make a request with a timeout.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True if permission was acquired, False if timeout was reached.

        """
        try:
            await asyncio.wait_for(self.acquire(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    def get_wait_time(self) -> float:
        """
        Get the estimated wait time before a request can be made.

        Note: This is an estimate and not thread-safe. For accurate
        rate limiting, always use acquire().

        Returns:
            Estimated wait time in seconds. Returns 0.0 if a request
            can be made immediately.

        """
        now = time.monotonic()
        self._cleanup_old_timestamps(now)

        if len(self._timestamps) < self._max_requests:
            return 0.0

        oldest = self._timestamps[0]
        wait_time = self._window_seconds - (now - oldest)
        return max(0.0, wait_time)

    def get_available_requests(self) -> int:
        """
        Get the number of requests that can be made immediately.

        Note: This is an estimate and not thread-safe. For accurate
        rate limiting, always use acquire().

        Returns:
            Number of requests that can be made without waiting.

        """
        now = time.monotonic()
        self._cleanup_old_timestamps(now)
        return max(0, self._max_requests - len(self._timestamps))

    def reset(self) -> None:
        """Reset the rate limiter, clearing all recorded timestamps."""
        self._timestamps.clear()
