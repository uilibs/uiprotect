"""Tests for the public-API rate limiter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from uiprotect import _rate_limit as rl
from uiprotect._rate_limit import (
    DEFAULT_RATE,
    SAFETY_MARGIN,
    PublicApiRateLimiter,
    _parse_policy_rate,
    _to_float,
)
from uiprotect.api import BaseApiClient, ProtectApiClient


def _public_client() -> BaseApiClient:
    client = BaseApiClient(
        host="192.168.1.1", port=443, api_key="key", verify_ssl=False
    )
    client.get_public_api_session = AsyncMock(return_value=AsyncMock())
    client.get_session = AsyncMock(return_value=AsyncMock())
    return client


def _mock_response(headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.headers = headers or {}
    response.release = MagicMock()
    response.content_type = "application/json"
    return response


@pytest.fixture
def virtual_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace loop.time/asyncio.sleep with a deterministic virtual clock."""
    clock = [0.0]
    fake_loop = Mock()
    fake_loop.time = lambda: clock[0]

    async def fake_sleep(delay: float) -> None:
        clock[0] += delay

    monkeypatch.setattr(rl, "get_running_loop", lambda: fake_loop)
    monkeypatch.setattr(rl, "sleep", fake_sleep)
    return clock


# ---------------------------------------------------------------------------
# _parse_policy_rate / _to_float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ('"10-in-1sec"; q=10; w=1; pk=abc', 10.0),
        ("q=20; w=2", 10.0),
        ('"5"; q=5; w=1, "100"; q=100; w=60', 5.0),  # only first member used
        (None, None),
        ("", None),
        ("q=10", None),  # missing w
        ("w=1", None),  # missing q
        ("q=oops; w=1", None),  # unparseable quota
        ("q=10; w=bad", None),  # unparseable window
        ("q=0; w=1", None),  # zero quota
        ("q=10; w=0", None),  # zero window
    ],
)
def test_parse_policy_rate(policy: str | None, expected: float | None) -> None:
    assert _parse_policy_rate(policy) == expected


def test_to_float() -> None:
    assert _to_float("3.5") == 3.5
    assert _to_float("nope") is None


# ---------------------------------------------------------------------------
# PublicApiRateLimiter pacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_paces_at_fixed_interval(virtual_clock: list[float]) -> None:
    limiter = PublicApiRateLimiter(rate=10.0)  # 0.1s spacing
    for _ in range(5):
        await limiter.acquire()
    # First acquire returns immediately; the next four are paced 0.1s apart.
    assert virtual_clock[0] == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_concurrent_acquires_do_not_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = PublicApiRateLimiter(rate=8.0)  # 0.125s spacing
    clock = [0.0]
    fake_loop = Mock()
    fake_loop.time = lambda: clock[0]
    inside = 0
    max_inside = 0

    async def fake_sleep(delay: float) -> None:
        # Yield to the loop *while still holding the limiter lock* so any other
        # gathered acquire could run if the lock did not serialize them.
        nonlocal inside, max_inside
        inside += 1
        max_inside = max(max_inside, inside)
        await asyncio.sleep(0)
        clock[0] += delay
        inside -= 1

    monkeypatch.setattr(rl, "get_running_loop", lambda: fake_loop)
    monkeypatch.setattr(rl, "sleep", fake_sleep)

    await asyncio.gather(*(limiter.acquire() for _ in range(20)))

    # Lock serializes: no two acquires ever pace concurrently (no burst).
    assert max_inside == 1
    # 20 requests serialized at 0.125s → 19 gaps.
    assert clock[0] == pytest.approx(19 * (1 / 8))


@pytest.mark.asyncio
async def test_idle_does_not_accumulate_burst_credit(
    virtual_clock: list[float],
) -> None:
    limiter = PublicApiRateLimiter(rate=10.0)
    await limiter.acquire()
    virtual_clock[0] = 100.0  # long idle gap
    await limiter.acquire()  # no backlog credit: returns without sleeping
    assert virtual_clock[0] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Seeding from RateLimit-Policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_changes_pacing(virtual_clock: list[float]) -> None:
    limiter = PublicApiRateLimiter()
    limiter.seed_from_policy('"20-in-1sec"; q=20; w=1')  # 20 * 0.8 = 16/s
    await limiter.acquire()
    await limiter.acquire()
    assert virtual_clock[0] == pytest.approx(1 / (20 * SAFETY_MARGIN))


@pytest.mark.asyncio
async def test_seed_is_one_shot(virtual_clock: list[float]) -> None:
    limiter = PublicApiRateLimiter()
    limiter.seed_from_policy("q=20; w=1")  # 16/s
    limiter.seed_from_policy("q=2; w=1")  # ignored — already seeded
    await limiter.acquire()
    await limiter.acquire()
    assert virtual_clock[0] == pytest.approx(1 / (20 * SAFETY_MARGIN))


@pytest.mark.asyncio
async def test_absent_policy_keeps_default(virtual_clock: list[float]) -> None:
    limiter = PublicApiRateLimiter()
    limiter.seed_from_policy(None)  # unparseable → stays at fallback rate
    await limiter.acquire()
    await limiter.acquire()
    assert virtual_clock[0] == pytest.approx(1 / DEFAULT_RATE)


# ---------------------------------------------------------------------------
# Integration with BaseApiClient.request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_request_is_paced_and_seeded() -> None:
    client = _public_client()
    limiter = Mock()
    limiter.acquire = AsyncMock()
    limiter.seed_from_policy = Mock()
    client._public_rate_limiter = limiter
    response = _mock_response(headers={"RateLimit-Policy": "q=10; w=1"})
    with patch.object(client, "_do_request", AsyncMock(return_value=response)):
        await client.request("get", "/v1/cameras", public_api=True)
    limiter.acquire.assert_awaited_once()
    limiter.seed_from_policy.assert_called_once_with("q=10; w=1")


@pytest.mark.asyncio
async def test_private_request_is_not_paced() -> None:
    client = _public_client()
    limiter = Mock()
    limiter.acquire = AsyncMock()
    limiter.seed_from_policy = Mock()
    client._public_rate_limiter = limiter
    response = _mock_response()
    with patch.object(client, "_do_request", AsyncMock(return_value=response)):
        await client.request("get", "/api/cameras", public_api=False)
    limiter.acquire.assert_not_awaited()
    limiter.seed_from_policy.assert_not_called()


def test_set_api_key_resets_limiter() -> None:
    client = ProtectApiClient("192.168.1.1", 443, api_key="key", verify_ssl=False)
    first = client._public_rate_limiter
    client.set_api_key("rotated-key")
    assert isinstance(client._public_rate_limiter, PublicApiRateLimiter)
    assert client._public_rate_limiter is not first
