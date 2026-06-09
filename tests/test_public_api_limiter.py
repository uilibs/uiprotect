"""Tests for the proactive public-API rate limiter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from uiprotect._public_api_limiter import (
    PUBLIC_API_COLD_START_RATE,
    PublicApiRateLimiter,
    parse_ratelimit_header,
)
from uiprotect.api import ProtectApiClient


class FakeClock:
    """Deterministic monotonic clock whose sleeps advance time instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


def _make_limiter(**kwargs) -> tuple[PublicApiRateLimiter, FakeClock]:
    clock = FakeClock()
    limiter = PublicApiRateLimiter(
        time_func=clock.time, sleep_func=clock.sleep, **kwargs
    )
    return limiter, clock


# =============================================================================
# parse_ratelimit_header
# =============================================================================


def test_parse_header_full() -> None:
    """Both r and t parse into a (remaining, reset) tuple."""
    assert parse_ratelimit_header('"10-in-1sec"; r=7; t=0.5') == (7.0, 0.5)


def test_parse_header_none() -> None:
    """A missing header yields None."""
    assert parse_ratelimit_header(None) is None


def test_parse_header_empty() -> None:
    """An empty header yields None."""
    assert parse_ratelimit_header("") is None


def test_parse_header_missing_remaining() -> None:
    """A header without the r parameter yields None."""
    assert parse_ratelimit_header('"10-in-1sec"; t=1') is None


def test_parse_header_missing_reset() -> None:
    """A header without the t parameter yields None."""
    assert parse_ratelimit_header('"10-in-1sec"; r=5') is None


# =============================================================================
# acquire pacing
# =============================================================================


@pytest.mark.asyncio()
async def test_first_acquire_is_immediate() -> None:
    """The cold-start bucket lets the first request through without sleeping."""
    limiter, clock = _make_limiter()
    await limiter.acquire()
    assert clock.sleeps == []


@pytest.mark.asyncio()
async def test_burst_is_paced_at_cold_start_rate() -> None:
    """Back-to-back acquires are spaced at 1/rate once the bucket drains."""
    limiter, clock = _make_limiter(rate=6.0)
    await limiter.acquire()  # immediate
    await limiter.acquire()  # must wait one slot
    assert clock.sleeps == [pytest.approx(1.0 / 6.0)]


# =============================================================================
# header steering
# =============================================================================


@pytest.mark.asyncio()
async def test_header_slows_pace_when_budget_tightens() -> None:
    """A low remaining budget over a wide reset slows the pace below cold start."""
    limiter, clock = _make_limiter(rate=6.0, headroom=4.0)
    # allowed = 8 - 4 = 4 over 2s -> 2 req/s
    limiter.update_from_headers({"RateLimit": '"10-in-1sec"; r=8; t=2'})
    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == [pytest.approx(0.5)]


@pytest.mark.asyncio()
async def test_header_never_exceeds_cold_start_ceiling() -> None:
    """A full budget cannot push the pace above the cold-start ceiling."""
    limiter, clock = _make_limiter(rate=6.0, headroom=4.0)
    # allowed = 10 - 4 = 6 over 0.5s -> 12 req/s, clamped down to 6
    limiter.update_from_headers({"RateLimit": '"10-in-1sec"; r=10; t=0.5'})
    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == [pytest.approx(1.0 / 6.0)]


@pytest.mark.asyncio()
async def test_header_respects_min_rate_floor() -> None:
    """Pace never drops below the min-rate floor while the budget is non-empty."""
    limiter, clock = _make_limiter(rate=6.0, headroom=4.0, min_rate=1.0)
    # allowed = 5 - 4 = 1 over 10s -> 0.1 req/s, clamped up to the 1.0 floor
    limiter.update_from_headers({"RateLimit": '"10-in-1sec"; r=5; t=10'})
    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == [pytest.approx(1.0)]


@pytest.mark.asyncio()
async def test_header_blocks_until_reset_within_headroom() -> None:
    """Once remaining is within the headroom floor, new requests wait for reset."""
    limiter, clock = _make_limiter(rate=6.0, headroom=4.0)
    await limiter.acquire()  # consume the initial token
    # allowed = 4 - 4 = 0 -> block until the window resets in 1s
    limiter.update_from_headers({"RateLimit": '"10-in-1sec"; r=4; t=1'})
    await limiter.acquire()
    assert clock.sleeps[-1] == pytest.approx(1.0)


@pytest.mark.asyncio()
async def test_header_reset_zero_restores_max_rate() -> None:
    """A zero reset clears any block and restores the cold-start ceiling."""
    limiter, clock = _make_limiter(rate=6.0, headroom=4.0)
    limiter.update_from_headers({"RateLimit": '"10-in-1sec"; r=4; t=1'})  # block
    limiter.update_from_headers({"RateLimit": '"10-in-1sec"; r=10; t=0'})  # unblock
    await limiter.acquire()
    assert clock.sleeps == []


def test_missing_header_is_a_noop() -> None:
    """An update with no RateLimit header leaves the pace untouched."""
    limiter, _ = _make_limiter(rate=6.0)
    limiter.update_from_headers({})
    assert limiter._rate == 6.0


# =============================================================================
# request() integration
# =============================================================================


def _public_client() -> ProtectApiClient:
    client = ProtectApiClient(
        "127.0.0.1", 0, "user", "pass", verify_ssl=False, max_retries=1
    )
    client.get_public_api_session = AsyncMock(return_value=AsyncMock())
    return client


def _resp(status: int = 200, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.headers = headers or {}
    resp.release = MagicMock()
    resp.content_type = "application/json"
    return resp


@pytest.mark.asyncio()
async def test_public_request_acquires_and_steers() -> None:
    """A public_api request paces through the limiter and steers from headers."""
    client = _public_client()
    clock = FakeClock()
    client._public_api_limiter = PublicApiRateLimiter(
        rate=6.0, headroom=4.0, time_func=clock.time, sleep_func=clock.sleep
    )
    resp = _resp(headers={"RateLimit": '"10-in-1sec"; r=8; t=2'})

    with patch.object(client, "_do_request", AsyncMock(return_value=resp)):
        await client.request("get", "/test", public_api=True, auto_close=False)

    # allowed = 8 - 4 = 4 over 2s -> 2 req/s
    assert client._public_api_limiter._rate == pytest.approx(2.0)


@pytest.mark.asyncio()
async def test_private_request_skips_limiter() -> None:
    """Private-API traffic never touches the public limiter."""
    client = _public_client()
    client.get_session = AsyncMock(return_value=AsyncMock())
    client._public_api_limiter = MagicMock()
    client._public_api_limiter.acquire = AsyncMock()

    with patch.object(client, "_do_request", AsyncMock(return_value=_resp())):
        await client.request("get", "/test", auto_close=False)

    client._public_api_limiter.acquire.assert_not_awaited()
    client._public_api_limiter.update_from_headers.assert_not_called()


@pytest.mark.asyncio()
async def test_public_request_paces_on_retry() -> None:
    """The retry path also paces through the limiter and re-reads headers."""
    client = _public_client()
    clock = FakeClock()
    client._public_api_limiter = PublicApiRateLimiter(
        rate=6.0, headroom=4.0, time_func=clock.time, sleep_func=clock.sleep
    )
    first = _resp(status=429, headers={"Retry-After": "0"})
    second = _resp(headers={"RateLimit": '"10-in-1sec"; r=8; t=2'})
    responses = [first, second]

    async def fake_do_request(*args, **kwargs):
        return responses.pop(0)

    with patch.object(client, "_do_request", side_effect=fake_do_request):
        await client.request("get", "/test", public_api=True, auto_close=False)

    # The retried 200's header steered the bucket: allowed = 4 over 2s = 2/s.
    assert client._public_api_limiter._rate == pytest.approx(2.0)
    assert responses == []


def test_cold_start_rate_constant() -> None:
    """The cold-start pace stays at the documented 6 req/s."""
    assert PUBLIC_API_COLD_START_RATE == 6.0
