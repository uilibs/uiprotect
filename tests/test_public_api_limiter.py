"""Tests for the proactive, header-driven public-API rate limiter."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from multidict import CIMultiDict

from uiprotect._public_api_limiter import (
    PublicApiRateLimiter,
    _join_headers,
    parse_ratelimit_header,
    parse_ratelimit_policy,
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


def _seed(limiter: PublicApiRateLimiter, q: int, w: int, r: int, t: int) -> None:
    """Drive the limiter with a parseable policy + current-state pair."""
    limiter.update_from_headers(
        {
            "RateLimit-Policy": f'"{q}-in-{w}sec";q={q};w={w};pk=:dXNlcg==:',
            "RateLimit": f'"{q}-in-{w}sec";r={r};t={t}',
        }
    )


# =============================================================================
# parse_ratelimit_header
# =============================================================================


def test_parse_header_full() -> None:
    """Both r and t parse into a (remaining, reset) tuple."""
    assert parse_ratelimit_header('"10-in-1sec";r=7;t=0.5') == (7.0, 0.5)


def test_parse_header_none() -> None:
    """A missing header yields None."""
    assert parse_ratelimit_header(None) is None


def test_parse_header_empty() -> None:
    """An empty header yields None."""
    assert parse_ratelimit_header("") is None


def test_parse_header_missing_remaining() -> None:
    """A header without the r parameter yields None."""
    assert parse_ratelimit_header('"10-in-1sec";t=1') is None


def test_parse_header_missing_reset() -> None:
    """A header without the t parameter yields None."""
    assert parse_ratelimit_header('"10-in-1sec";r=5') is None


def test_parse_header_draft7_raises() -> None:
    """A draft-7 (non-structured-field) value raises ValueError."""
    with pytest.raises(ValueError):
        parse_ratelimit_header("limit=10, remaining=6, reset=1")


def test_parse_header_multi_item_picks_most_restrictive() -> None:
    """A joined multi-item RateLimit list yields the lowest-remaining member."""
    # Two limiter instances doubled the header; the r=3 member binds.
    assert parse_ratelimit_header('"10-in-1sec";r=8;t=1, "10-in-1sec";r=3;t=2') == (
        3.0,
        2.0,
    )


def test_parse_header_multi_item_tie_breaks_on_reset() -> None:
    """Equal remaining ties break to the shortest reset."""
    assert parse_ratelimit_header('"x";r=5;t=4, "x";r=5;t=1') == (5.0, 1.0)


# =============================================================================
# parse_ratelimit_policy
# =============================================================================


def test_parse_policy_full() -> None:
    """A single policy parses into (quota, window)."""
    assert parse_ratelimit_policy('"10-in-1sec";q=10;w=1;pk=:dXNlcg==:') == (
        10.0,
        1.0,
    )


def test_parse_policy_none() -> None:
    """An empty policy header yields None."""
    assert parse_ratelimit_policy(None) is None


def test_parse_policy_missing_params() -> None:
    """A member without q/w yields None."""
    assert parse_ratelimit_policy('"10-in-1sec";pk=:dXNlcg==:') is None


def test_parse_policy_zero_window_skipped() -> None:
    """A non-positive window is skipped, leaving no usable budget."""
    assert parse_ratelimit_policy('"x";q=10;w=0') is None


def test_parse_policy_picks_most_restrictive() -> None:
    """The lowest-throughput policy in the list wins."""
    # 10/1 = 10/s vs 6/3 = 2/s -> the 6-in-3 policy is the binding one.
    assert parse_ratelimit_policy('"10-in-1sec";q=10;w=1, "6-in-3sec";q=6;w=3') == (
        6.0,
        3.0,
    )


def test_parse_policy_bad_value_raises() -> None:
    """A value that is not a structured-field list raises ValueError."""
    with pytest.raises(ValueError):
        parse_ratelimit_policy("not a; valid = list")


# =============================================================================
# _join_headers
# =============================================================================


def test_join_headers_absent() -> None:
    """A header absent from a plain mapping yields None."""
    assert _join_headers({}, "RateLimit") is None


def test_join_headers_plain_get() -> None:
    """A plain mapping falls back to a single get()."""
    assert _join_headers({"RateLimit": '"x";r=1;t=1'}, "RateLimit") == '"x";r=1;t=1'


def test_join_headers_multidict_joins_all_lines() -> None:
    """Repeated multidict lines are joined with ', ' so none are dropped."""
    headers: CIMultiDict[str] = CIMultiDict()
    headers.add("RateLimit-Policy", '"10-in-1sec";q=10;w=1')
    headers.add("RateLimit-Policy", '"6-in-3sec";q=6;w=3')
    joined = _join_headers(headers, "RateLimit-Policy")
    assert joined == '"10-in-1sec";q=10;w=1, "6-in-3sec";q=6;w=3'
    # And the joined value parses to the binding (most restrictive) policy.
    assert parse_ratelimit_policy(joined) == (6.0, 3.0)


def test_join_headers_multidict_absent() -> None:
    """A multidict missing the key yields None."""
    headers: CIMultiDict[str] = CIMultiDict()
    assert _join_headers(headers, "RateLimit") is None


# =============================================================================
# acquire pacing
# =============================================================================


@pytest.mark.asyncio()
async def test_unseeded_limiter_does_not_pace() -> None:
    """With no headers seen yet, acquires pass through without sleeping."""
    limiter, clock = _make_limiter()
    await limiter.acquire()
    await limiter.acquire()
    assert clock.sleeps == []


@pytest.mark.asyncio()
async def test_first_acquire_after_seed_is_immediate() -> None:
    """The freshly-seeded bucket lets the first request through immediately."""
    limiter, clock = _make_limiter()
    _seed(limiter, q=10, w=1, r=10, t=1)
    await limiter.acquire()
    assert clock.sleeps == []


@pytest.mark.asyncio()
async def test_burst_is_paced_at_derived_rate() -> None:
    """Back-to-back acquires are spaced at 1/rate once the bucket drains."""
    limiter, clock = _make_limiter(headroom=4.0)
    _seed(limiter, q=10, w=1, r=10, t=1)  # rate = (10 - 4) / 1 = 6/s
    await limiter.acquire()  # immediate
    await limiter.acquire()  # must wait one slot
    assert clock.sleeps == [pytest.approx(1.0 / 6.0)]


# =============================================================================
# header steering
# =============================================================================


def test_rate_derived_from_policy_quota() -> None:
    """The ceiling is (quota - headroom) / window from the policy."""
    limiter, _ = _make_limiter(headroom=4.0)
    _seed(limiter, q=10, w=2, r=10, t=2)  # (10 - 4) / 2 = 3/s
    assert limiter._rate == pytest.approx(3.0)


def test_rate_respects_min_floor() -> None:
    """A quota at or below the headroom clamps up to the min-rate floor."""
    limiter, _ = _make_limiter(headroom=4.0, min_rate=1.0)
    _seed(limiter, q=4, w=1, r=4, t=1)  # (4 - 4) / 1 = 0, floored to 1.0
    assert limiter._rate == pytest.approx(1.0)


@pytest.mark.asyncio()
async def test_blocks_until_reset_within_headroom() -> None:
    """Once remaining is within the headroom floor, requests wait for reset."""
    limiter, clock = _make_limiter(headroom=4.0)
    # remaining 4 - headroom 4 = 0 -> block until the window resets in 1s.
    _seed(limiter, q=10, w=1, r=4, t=1)
    await limiter.acquire()
    assert clock.sleeps[-1] == pytest.approx(1.0)


@pytest.mark.asyncio()
async def test_block_duration_is_clamped() -> None:
    """A huge server-supplied reset is capped so it can't stall for a day."""
    limiter, clock = _make_limiter(headroom=4.0)
    # remaining within headroom -> block, but t=86400 must clamp to 30s.
    _seed(limiter, q=10, w=1, r=4, t=86400)
    await limiter.acquire()
    assert clock.sleeps[-1] == pytest.approx(30.0)


@pytest.mark.asyncio()
async def test_reset_zero_clears_block() -> None:
    """A zero reset clears any standing block."""
    limiter, clock = _make_limiter(headroom=4.0)
    _seed(limiter, q=10, w=1, r=4, t=1)  # block
    _seed(limiter, q=10, w=1, r=10, t=0)  # reset 0 -> unblock
    await limiter.acquire()
    assert clock.sleeps == []


def test_no_headers_is_a_noop() -> None:
    """An update with neither RateLimit header leaves pacing disengaged."""
    limiter, _ = _make_limiter()
    limiter.update_from_headers({})
    assert limiter._rate is None
    assert limiter._disabled is False


# =============================================================================
# unparsable headers disable pacing
# =============================================================================


@pytest.mark.asyncio()
async def test_unparsable_headers_disable_pacing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Present-but-unparsable headers log one WARNING and disable pacing."""
    limiter, clock = _make_limiter()
    with caplog.at_level(logging.WARNING):
        limiter.update_from_headers(
            {"RateLimit": "limit=10, remaining=6, reset=1"}  # draft-7 shape
        )
    assert limiter._disabled is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)

    # Once disabled, both paths are inert: no pacing, no further steering.
    await limiter.acquire()
    assert clock.sleeps == []
    _seed(limiter, q=10, w=1, r=10, t=1)
    assert limiter._rate is None


def test_missing_param_disables_pacing() -> None:
    """A valid policy but a RateLimit missing t disables pacing."""
    limiter, _ = _make_limiter()
    limiter.update_from_headers(
        {
            "RateLimit-Policy": '"10-in-1sec";q=10;w=1',
            "RateLimit": '"10-in-1sec";r=5',  # no t
        }
    )
    assert limiter._disabled is True


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
        headroom=4.0, time_func=clock.time, sleep_func=clock.sleep
    )
    resp = _resp(
        headers={
            "RateLimit-Policy": '"10-in-1sec";q=10;w=2;pk=:dXNlcg==:',
            "RateLimit": '"10-in-1sec";r=8;t=2',
        }
    )

    with patch.object(client, "_do_request", AsyncMock(return_value=resp)):
        await client.request("get", "/test", public_api=True, auto_close=False)

    # rate = (10 - 4) / 2 = 3/s
    assert client._public_api_limiter._rate == pytest.approx(3.0)


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
        headroom=4.0, time_func=clock.time, sleep_func=clock.sleep
    )
    first = _resp(status=429, headers={"Retry-After": "0"})
    second = _resp(
        headers={
            "RateLimit-Policy": '"10-in-1sec";q=10;w=2;pk=:dXNlcg==:',
            "RateLimit": '"10-in-1sec";r=8;t=2',
        }
    )
    responses = [first, second]

    async def fake_do_request(*args, **kwargs):
        return responses.pop(0)

    with patch.object(client, "_do_request", side_effect=fake_do_request):
        await client.request("get", "/test", public_api=True, auto_close=False)

    # The retried 200's header steered the bucket: (10 - 4) / 2 = 3/s.
    assert client._public_api_limiter._rate == pytest.approx(3.0)
    assert responses == []
