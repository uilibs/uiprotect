"""
Lightweight event-loop-safe pacer for the Public Integration API.

The public API enforces a per-API-key request budget (observed as ~10 req/1s,
advertised via draft-8 ``RateLimit``/``RateLimit-Policy`` headers). The public
WebSocket draws from the *same* budget. Pacing the request path proactively
keeps the bootstrap fan-out from tripping a 429 storm or a WS ``1008``
disconnect.
"""

from __future__ import annotations

from asyncio import Lock, get_running_loop, sleep

# Requests/second used until a ``RateLimit-Policy`` header seeds the real rate.
# The observed budget is 10/1s; default conservatively to leave WS headroom.
DEFAULT_RATE: float = 8.0

# Fraction of the server-advertised budget we actually consume, leaving room
# for the shared-budget public WebSocket.
SAFETY_MARGIN: float = 0.8


class PublicApiRateLimiter:
    """
    Fixed-interval async gate for one client's public path.

    ``acquire()`` spaces successive requests at least ``1 / rate`` seconds apart
    on the running loop — no threads, no background tasks. All state lives on the
    instance so several clients in one process never share a budget.
    """

    def __init__(self, rate: float = DEFAULT_RATE) -> None:
        self._lock = Lock()
        self._interval = 1.0 / rate
        self._next_allowed = 0.0
        self._seeded = False

    async def acquire(self) -> None:
        """Block until the next request is permitted under the current rate."""
        async with self._lock:
            now = get_running_loop().time()
            if now < self._next_allowed:
                await sleep(self._next_allowed - now)
                self._next_allowed += self._interval
            else:
                self._next_allowed = now + self._interval

    def seed_from_policy(self, policy: str | None) -> None:
        """Seed the rate once from a draft-8 ``RateLimit-Policy`` header value."""
        if self._seeded:
            return
        rate = _parse_policy_rate(policy)
        if rate is None:
            return
        self._interval = 1.0 / (rate * SAFETY_MARGIN)
        self._seeded = True


def _parse_policy_rate(policy: str | None) -> float | None:
    """Return requests/second from ``q`` / ``w`` of a RateLimit-Policy header."""
    if not policy:
        return None
    quota: float | None = None
    window: float | None = None
    # Only the first policy member matters; its params are ``;``-separated.
    for part in policy.split(",", 1)[0].split(";"):
        key, _, value = part.strip().partition("=")
        if key == "q":
            quota = _to_float(value)
        elif key == "w":
            window = _to_float(value)
    if quota is None or window is None or quota <= 0 or window <= 0:
        return None
    return quota / window


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
