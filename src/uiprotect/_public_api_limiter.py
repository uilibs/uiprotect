"""
Proactive, header-driven rate limiter for the Public Integration API.

The public API runs ``express-rate-limit`` middleware ahead of every
``/integration/v1`` route (including the ``/subscribe`` websocket upgrades),
keyed per user principal, and advertises the budget through the IETF draft-8
``RateLimit`` structured-field headers::

    RateLimit:        "10-in-1sec";r=<remaining>;t=<reset-seconds>
    RateLimit-Policy: "10-in-1sec";q=<quota>;w=<window-seconds>;pk=:<key>:

This limiter paces ``public_api=True`` traffic to stay *under* that budget
instead of leaning solely on the reactive 429 retry loop in
:meth:`uiprotect.api.BaseApiClient.request`. It is **fully header-driven**:
the ceiling is derived from the server's own ``RateLimit-Policy`` quota
(``rate = (q - headroom) / w``) rather than a hardcoded pace, so it self-adapts
if Ubiquiti changes the server values. Until the first headers are seen there
is no pacing, and on firmware old enough to lack the limiter middleware (no
``RateLimit`` headers at all) pacing never engages — the 429 retry stays the
universal backstop.

The public websocket auth/keepalive draws from the same per-key pool, so the
limiter reserves a :data:`PUBLIC_API_RATE_HEADROOM` slice the bursts never
spend.

One limiter is owned per :class:`~uiprotect.api.ProtectApiClient` — never a
module global — because a single process can drive several consoles, each with
its own per-key budget.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from http_sfv import Item, List

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

_LOGGER = logging.getLogger(__name__)

# Requests held back out of the server's reported budget so the public
# websocket auth/keepalive keeps a slice when request bursts drain the per-key
# pool. The keepalive shares the same per-principal budget (the limiter is
# mounted ahead of the /subscribe upgrades), verified against Protect 7.1.77.
PUBLIC_API_RATE_HEADROOM = 4.0

# Floor pace (req/s) while the budget is still non-empty; the reactive 429
# retry stays the backstop for genuine overshoot.
PUBLIC_API_MIN_RATE = 1.0


def parse_ratelimit_header(value: str | None) -> tuple[float, float] | None:
    """
    Parse a draft-8 ``RateLimit`` sf-item into ``(remaining, reset_seconds)``.

    Returns ``None`` if the value is empty or lacks the ``r``/``t`` params.
    Raises ``ValueError`` on a value that is not a valid structured-field item
    (e.g. a draft-7 ``limit=…, remaining=…`` line) so the caller can treat it
    as an unparsable header.
    """
    if not value:
        return None
    item = Item()
    item.parse(value.encode())
    params = item.params
    if "r" in params and "t" in params:
        return float(params["r"]), float(params["t"])
    return None


def parse_ratelimit_policy(value: str | None) -> tuple[float, float] | None:
    """
    Parse a draft-8 ``RateLimit-Policy`` sf-list into ``(quota, window)``.

    The list may carry several policies (each an item with ``q``/``w`` params,
    plus a byte-sequence ``pk``); the most restrictive — the one with the
    lowest ``q/w`` throughput — wins. Returns ``None`` if the value is empty or
    no member carries a usable ``q``/``w`` pair. Raises ``ValueError`` on a
    value that is not a valid structured-field list.
    """
    if not value:
        return None
    policies = List()
    policies.parse(value.encode())
    best: tuple[float, float] | None = None
    for member in policies:
        params = member.params
        if "q" not in params or "w" not in params:
            continue
        quota = float(params["q"])
        window = float(params["w"])
        if window <= 0:
            continue
        if best is None or quota / window < best[0] / best[1]:
            best = (quota, window)
    return best


def _join_headers(headers: Mapping[str, str], name: str) -> str | None:
    """
    Return all values of ``name`` joined with ``", "``, or ``None`` if absent.

    The server emits these headers with ``response.append()``, so a second
    policy arrives as a *separate* header line; ``get()`` would silently drop
    it. ``getall()`` (aiohttp multidicts) collects every line; plain mappings
    fall back to a single ``get()``.
    """
    getall = getattr(headers, "getall", None)
    if getall is not None:
        values = getall(name, ())
    else:
        single = headers.get(name)
        values = (single,) if single is not None else ()
    if not values:
        return None
    return ", ".join(values)


class PublicApiRateLimiter:
    """Per-client token bucket that paces ``public_api=True`` requests."""

    def __init__(
        self,
        *,
        headroom: float = PUBLIC_API_RATE_HEADROOM,
        min_rate: float = PUBLIC_API_MIN_RATE,
        time_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._headroom = headroom
        self._min_rate = min_rate
        self._time = time_func
        self._sleep = sleep_func
        # ``None`` until the first parseable headers seed the budget: no pacing
        # before then, and none ever on firmware without the limiter middleware.
        self._rate: float | None = None
        # Set once if headers are present but unparsable — pacing disables for
        # the life of the client and the 429 retry carries on as the backstop.
        self._disabled = False
        self._capacity = 1.0
        self._tokens = 1.0
        self._updated = time_func()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until one request may proceed under the current pace."""
        if self._disabled or self._rate is None:
            return
        async with self._lock:
            while True:
                now = self._time()
                if now < self._blocked_until:
                    await self._sleep(self._blocked_until - now)
                    continue
                rate = self._rate
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._updated) * rate,
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await self._sleep((1.0 - self._tokens) / rate)

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Steer the bucket from the server's own ``RateLimit`` accounting."""
        if self._disabled:
            return
        policy_raw = _join_headers(headers, "RateLimit-Policy")
        current_raw = _join_headers(headers, "RateLimit")
        if policy_raw is None and current_raw is None:
            # No limiter middleware (older firmware): pacing is pure overhead.
            return
        try:
            budget = parse_ratelimit_policy(policy_raw)
            current = parse_ratelimit_header(current_raw)
        except ValueError:
            budget = current = None
        if budget is None or current is None:
            self._disabled = True
            _LOGGER.warning(
                "Public API RateLimit headers present but unparsable "
                "(policy=%r, ratelimit=%r); disabling proactive pacing and "
                "falling back to the 429 retry",
                policy_raw,
                current_raw,
            )
            return
        quota, window = budget
        remaining, reset = current
        self._rate = max(self._min_rate, (quota - self._headroom) / window)
        if reset > 0 and remaining - self._headroom <= 0:
            # Budget within the headroom floor (a 429's ``r=0`` lands here):
            # pause new requests until the window resets so the websocket
            # keepalive keeps its slice.
            self._blocked_until = self._time() + reset
        else:
            self._blocked_until = 0.0
