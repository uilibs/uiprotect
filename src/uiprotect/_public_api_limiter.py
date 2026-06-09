"""
Proactive, header-aware rate limiter for the Public Integration API.

The public API enforces a per-API-key request budget (observed ~10 req/s on
UniFi Protect 7.1.77) and advertises it through draft-8 ``RateLimit`` response
headers::

    RateLimit:        "10-in-1sec"; r=<remaining>; t=<reset-seconds>
    RateLimit-Policy: "10-in-1sec"; q=10; w=1; pk=<key>

This limiter paces ``public_api=True`` traffic to stay *under* that budget
instead of leaning solely on the reactive 429 retry loop in
:meth:`uiprotect.api.BaseApiClient.request`. The public websocket
auth/keepalive draws from the same per-key pool, so request bursts and the
live connection compete for one budget; the limiter reserves a headroom floor
so the keepalive is never starved.

One limiter is owned per :class:`~uiprotect.api.ProtectApiClient` — never a
module global — because a single process can drive several consoles, each with
its own per-key budget.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

# Cold-start pace (req/s) used until the first ``RateLimit`` header is seen.
# 6/s leaves headroom under the observed 10/s ceiling for the public websocket
# keepalive, which draws from the same per-key budget; 8/s does not.
PUBLIC_API_COLD_START_RATE = 6.0

# Requests held back out of the server's reported remaining budget so the
# websocket auth/keepalive keeps a slice when request bursts drain the pool.
PUBLIC_API_RATE_HEADROOM = 4.0

# Floor pace (req/s) while the budget is still above the headroom; the reactive
# 429 retry stays the backstop for genuine overshoot.
PUBLIC_API_MIN_RATE = 1.0


_RATELIMIT_PARAM_RE = re.compile(r"\b([rt])\s*=\s*(\d+(?:\.\d+)?)")


def parse_ratelimit_header(value: str | None) -> tuple[float, float] | None:
    """
    Parse a draft-8 ``RateLimit`` header into ``(remaining, reset_seconds)``.

    Returns ``None`` unless both the ``r`` (remaining) and ``t`` (reset)
    parameters are present and parseable.
    """
    if not value:
        return None
    params = {key: float(num) for key, num in _RATELIMIT_PARAM_RE.findall(value)}
    if "r" in params and "t" in params:
        return params["r"], params["t"]
    return None


class PublicApiRateLimiter:
    """Per-client token bucket that paces ``public_api=True`` requests."""

    def __init__(
        self,
        *,
        rate: float = PUBLIC_API_COLD_START_RATE,
        headroom: float = PUBLIC_API_RATE_HEADROOM,
        min_rate: float = PUBLIC_API_MIN_RATE,
        time_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        # ``rate`` doubles as the ceiling: header steering only ever slows the
        # pace below the proven-safe cold-start value, never above it.
        self._max_rate = rate
        self._rate = rate
        self._headroom = headroom
        self._min_rate = min_rate
        self._time = time_func
        self._sleep = sleep_func
        self._capacity = 1.0
        self._tokens = 1.0
        self._updated = time_func()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until one request may proceed under the current pace."""
        async with self._lock:
            while True:
                now = self._time()
                if now < self._blocked_until:
                    await self._sleep(self._blocked_until - now)
                    continue
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._updated) * self._rate,
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await self._sleep((1.0 - self._tokens) / self._rate)

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Steer the bucket from the server's own ``RateLimit`` accounting."""
        parsed = parse_ratelimit_header(headers.get("RateLimit"))
        if parsed is None:
            return
        remaining, reset = parsed
        if reset <= 0:
            self._blocked_until = 0.0
            self._rate = self._max_rate
            return
        allowed = remaining - self._headroom
        if allowed <= 0:
            # Budget within the headroom floor: pause new requests until the
            # window resets so the websocket keepalive keeps its slice.
            self._blocked_until = self._time() + reset
            return
        self._blocked_until = 0.0
        self._rate = max(self._min_rate, min(self._max_rate, allowed / reset))
