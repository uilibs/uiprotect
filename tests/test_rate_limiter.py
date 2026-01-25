"""Tests for uiprotect.rate_limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from uiprotect.rate_limiter import RateLimiter

# --- Fixtures ---


@pytest.fixture
def limiter() -> RateLimiter:
    """Create a rate limiter with default settings (10 req/sec)."""
    return RateLimiter()


@pytest.fixture
def fast_limiter() -> RateLimiter:
    """Create a rate limiter with small window for fast tests."""
    return RateLimiter(max_requests=3, window_seconds=0.1)


# --- Test Initialization and Properties ---


class TestRateLimiterInit:
    """Tests for RateLimiter initialization and properties."""

    def test_default_values(self, limiter: RateLimiter) -> None:
        """Test default initialization values."""
        assert limiter.max_requests == 10
        assert limiter.window_seconds == 1.0

    @pytest.mark.parametrize(
        ("max_requests", "window_seconds"),
        [
            (5, 2.0),
            (100, 0.5),
            (1, 10.0),
        ],
    )
    def test_custom_values(self, max_requests: int, window_seconds: float) -> None:
        """Test custom initialization values."""
        limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
        assert limiter.max_requests == max_requests
        assert limiter.window_seconds == window_seconds


# --- Test Core Acquire Functionality ---


class TestAcquire:
    """Tests for the acquire() method."""

    @pytest.mark.asyncio
    async def test_acquire_under_limit(self, fast_limiter: RateLimiter) -> None:
        """Test acquiring when under the rate limit."""
        for _ in range(fast_limiter.max_requests):
            await fast_limiter.acquire()
        # Should complete without blocking significantly
        assert fast_limiter.get_available_requests() == 0

    @pytest.mark.asyncio
    async def test_acquire_at_limit_waits(self) -> None:
        """Test that acquire() waits when at rate limit."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.05)

        # Fill up the limit
        await limiter.acquire()
        await limiter.acquire()

        # Next acquire should wait
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        # Should have waited approximately window_seconds
        assert elapsed >= 0.04  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_acquire_creates_lock_lazily(self, limiter: RateLimiter) -> None:
        """Test that lock is created on first acquire."""
        assert limiter._lock is None
        await limiter.acquire()
        assert limiter._lock is not None


# --- Test acquire_with_timeout ---


class TestAcquireWithTimeout:
    """Tests for the acquire_with_timeout() method."""

    @pytest.mark.asyncio
    async def test_acquire_with_timeout_success(
        self, fast_limiter: RateLimiter
    ) -> None:
        """Test successful acquisition within timeout."""
        result = await fast_limiter.acquire_with_timeout(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_with_timeout_failure(self) -> None:
        """Test timeout when rate limit is exceeded."""
        limiter = RateLimiter(max_requests=1, window_seconds=1.0)

        # Use up the limit
        await limiter.acquire()

        # Try to acquire with very short timeout - should fail
        result = await limiter.acquire_with_timeout(timeout=0.01)
        assert result is False


# --- Test get_wait_time ---


class TestGetWaitTime:
    """Tests for the get_wait_time() method."""

    def test_get_wait_time_empty(self, limiter: RateLimiter) -> None:
        """Test wait time when no requests have been made."""
        assert limiter.get_wait_time() == 0.0

    @pytest.mark.asyncio
    async def test_get_wait_time_under_limit(self, fast_limiter: RateLimiter) -> None:
        """Test wait time when under the limit."""
        await fast_limiter.acquire()
        assert fast_limiter.get_wait_time() == 0.0

    @pytest.mark.asyncio
    async def test_get_wait_time_at_limit(self) -> None:
        """Test wait time when at the rate limit."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.5)

        await limiter.acquire()
        await limiter.acquire()

        wait_time = limiter.get_wait_time()
        # Should be close to window_seconds since requests just happened
        assert 0.0 < wait_time <= 0.5


# --- Test get_available_requests ---


class TestGetAvailableRequests:
    """Tests for the get_available_requests() method."""

    def test_get_available_requests_empty(self, limiter: RateLimiter) -> None:
        """Test available requests when limiter is empty."""
        assert limiter.get_available_requests() == limiter.max_requests

    @pytest.mark.asyncio
    async def test_get_available_requests_partial(
        self, fast_limiter: RateLimiter
    ) -> None:
        """Test available requests after some requests."""
        await fast_limiter.acquire()
        await fast_limiter.acquire()
        assert fast_limiter.get_available_requests() == 1

    @pytest.mark.asyncio
    async def test_get_available_requests_full(self, fast_limiter: RateLimiter) -> None:
        """Test available requests when at limit."""
        for _ in range(fast_limiter.max_requests):
            await fast_limiter.acquire()
        assert fast_limiter.get_available_requests() == 0

    @pytest.mark.asyncio
    async def test_get_available_requests_after_window(self) -> None:
        """Test that requests become available after window expires."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.05)

        await limiter.acquire()
        await limiter.acquire()
        assert limiter.get_available_requests() == 0

        # Wait for window to expire
        await asyncio.sleep(0.06)
        assert limiter.get_available_requests() == 2


# --- Test reset ---


class TestReset:
    """Tests for the reset() method."""

    @pytest.mark.asyncio
    async def test_reset_clears_timestamps(self, fast_limiter: RateLimiter) -> None:
        """Test that reset clears all recorded timestamps."""
        # Fill up the limiter
        for _ in range(fast_limiter.max_requests):
            await fast_limiter.acquire()

        assert fast_limiter.get_available_requests() == 0

        # Reset and verify
        fast_limiter.reset()
        assert fast_limiter.get_available_requests() == fast_limiter.max_requests


# --- Test timestamp cleanup ---


class TestTimestampCleanup:
    """Tests for the _cleanup_old_timestamps() method."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_timestamps(self) -> None:
        """Test that old timestamps are cleaned up."""
        limiter = RateLimiter(max_requests=5, window_seconds=0.05)

        # Make some requests
        await limiter.acquire()
        await limiter.acquire()
        assert len(limiter._timestamps) == 2

        # Wait for window to expire
        await asyncio.sleep(0.06)

        # Trigger cleanup via get_available_requests
        available = limiter.get_available_requests()
        assert available == 5
        assert len(limiter._timestamps) == 0
