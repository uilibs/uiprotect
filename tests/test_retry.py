"""Tests for retry functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import aiohttp
import pytest
from aiohttp import ClientResponse, client_exceptions
from yarl import URL

from uiprotect.api import (
    RETRY_BASE_DELAY,
    RETRY_DEFAULT_ATTEMPTS,
    RETRY_EXPONENTIAL_BASE,
    RETRY_MAX_DELAY,
    RETRY_STATUS_CODES,
    BaseApiClient,
    ProtectApiClient,
    calculate_retry_delay,
    parse_retry_after,
)
from uiprotect.exceptions import NvrError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_response() -> MagicMock:
    """Create a mock aiohttp ClientResponse."""
    response = MagicMock(spec=ClientResponse)
    response.status = 200
    response.headers = {}
    response.release = MagicMock()
    return response


@pytest.fixture
def base_client() -> BaseApiClient:
    """Create a BaseApiClient for testing."""
    return BaseApiClient(
        host="192.168.1.1",
        port=443,
        username="test",
        password="test",  # noqa: S106
    )


@pytest.fixture
def protect_client_factory():
    """Factory to create ProtectApiClient with custom max_retries."""

    def _create(max_retries: int = RETRY_DEFAULT_ATTEMPTS) -> ProtectApiClient:
        client = ProtectApiClient(
            "127.0.0.1",
            0,
            "user",
            "pass",
            verify_ssl=False,
            max_retries=max_retries,
        )
        client.get_session = AsyncMock(return_value=AsyncMock())
        return client

    return _create


def _mock_response(status: int = 200, headers: dict | None = None) -> MagicMock:
    """Create a mock response with given status and headers."""
    response = MagicMock()
    response.status = status
    response.headers = headers or {}
    response.release = MagicMock()
    response.content_type = "application/json"
    return response


def _create_mock_request_context(
    side_effect: Exception | None = None,
    return_value: AsyncMock | None = None,
    fail_count: int = 0,
):
    """
    Create a mock request context for testing _do_request.

    Args:
        side_effect: Exception to raise on every call.
        return_value: Value to return after fail_count failures.
        fail_count: Number of times to raise side_effect before returning.

    """
    call_count = 0

    class MockRequestContext:
        async def __aenter__(self_inner):
            nonlocal call_count
            call_count += 1
            if side_effect and (fail_count == 0 or call_count <= fail_count):
                raise side_effect
            return return_value

        async def __aexit__(self_inner, *args):
            pass

        @property
        def calls(self_inner) -> int:
            return call_count

    return MockRequestContext()


# =============================================================================
# Retry Constants Tests
# =============================================================================


def test_default_attempts() -> None:
    """Test default retry attempts value."""
    assert RETRY_DEFAULT_ATTEMPTS == 3


def test_base_delay() -> None:
    """Test base delay value."""
    assert RETRY_BASE_DELAY == 1.0


def test_max_delay() -> None:
    """Test max delay value."""
    assert RETRY_MAX_DELAY == 30.0


def test_exponential_base() -> None:
    """Test exponential base value."""
    assert RETRY_EXPONENTIAL_BASE == 2.0


def test_status_codes() -> None:
    """Test retry status codes include 408, 429, 500, 502, 503, 504."""
    assert frozenset({408, 429, 500, 502, 503, 504}) == RETRY_STATUS_CODES


# =============================================================================
# calculate_retry_delay Tests
# =============================================================================


def test_exponential_backoff() -> None:
    """Test that delays follow exponential backoff pattern."""
    # With jitter, values will vary, but should be around expected values
    delays = [calculate_retry_delay(i) for i in range(4)]

    # Check rough ranges (accounting for ±25% jitter)
    assert 0.75 <= delays[0] <= 1.25  # ~1.0
    assert 1.5 <= delays[1] <= 2.5  # ~2.0
    assert 3.0 <= delays[2] <= 5.0  # ~4.0
    assert 6.0 <= delays[3] <= 10.0  # ~8.0


def test_max_delay_cap() -> None:
    """Test that delay is capped at max_delay."""
    # Very high attempt number should still cap at RETRY_MAX_DELAY
    delay = calculate_retry_delay(100)
    assert delay <= RETRY_MAX_DELAY


def test_retry_after_header_respected() -> None:
    """Test that Retry-After header value is used when provided."""
    delay = calculate_retry_delay(0, retry_after=5.0)
    # With only positive jitter (0-25%), should be between 5.0 and 6.25
    assert 5.0 <= delay <= 6.25


def test_retry_after_only_adds_positive_jitter() -> None:
    """Test that Retry-After only adds positive jitter (never subtracts)."""
    retry_after = 5.0
    delays = [calculate_retry_delay(0, retry_after=retry_after) for _ in range(100)]
    # All delays should be >= retry_after (only positive jitter)
    assert all(d >= retry_after for d in delays)
    # But at least some should be > retry_after (jitter is being added)
    assert any(d > retry_after for d in delays)


def test_retry_after_capped_at_max_delay() -> None:
    """Test that Retry-After is capped at max_delay."""
    delay = calculate_retry_delay(0, retry_after=100.0)
    # Final delay is capped at RETRY_MAX_DELAY regardless of jitter
    assert delay <= RETRY_MAX_DELAY


def test_jitter_adds_variation() -> None:
    """Test that jitter adds variation to delay."""
    delays = [calculate_retry_delay(0) for _ in range(100)]

    # With jitter, we should see variation
    assert len(set(delays)) > 1


def test_minimum_delay() -> None:
    """Test that delay never goes below 0.1s."""
    delays = [calculate_retry_delay(0) for _ in range(100)]
    assert all(d >= 0.1 for d in delays)


def test_calculated_delay_can_subtract_jitter() -> None:
    """Test that calculated delays (without retry_after) can subtract jitter."""
    # For calculated delays, jitter should be ±25%
    base_delay = RETRY_BASE_DELAY  # 1.0
    delays = [calculate_retry_delay(0) for _ in range(100)]
    # Some delays should be below base_delay (negative jitter)
    assert any(d < base_delay for d in delays)
    # Some delays should be above base_delay (positive jitter)
    assert any(d > base_delay for d in delays)


# =============================================================================
# parse_retry_after Tests
# =============================================================================


def test_parse_valid_integer(mock_response: MagicMock) -> None:
    """Test parsing integer Retry-After value."""
    mock_response.headers = {"Retry-After": "5"}
    assert parse_retry_after(mock_response) == 5.0


def test_parse_valid_float(mock_response: MagicMock) -> None:
    """Test parsing float Retry-After value."""
    mock_response.headers = {"Retry-After": "2.5"}
    assert parse_retry_after(mock_response) == 2.5


def test_parse_missing_header(mock_response: MagicMock) -> None:
    """Test handling missing Retry-After header."""
    mock_response.headers = {}
    assert parse_retry_after(mock_response) is None


def test_parse_invalid_value(mock_response: MagicMock) -> None:
    """Test handling invalid Retry-After value."""
    mock_response.headers = {"Retry-After": "not-a-number"}
    assert parse_retry_after(mock_response) is None


def test_parse_http_date_not_supported(mock_response: MagicMock) -> None:
    """Test that HTTP-date format returns None."""
    mock_response.headers = {"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"}
    assert parse_retry_after(mock_response) is None


# =============================================================================
# API Client Integration Tests
# =============================================================================


def test_default_max_retries_applied(base_client: BaseApiClient) -> None:
    """Test that default max_retries is applied to new clients."""
    assert base_client._max_retries == RETRY_DEFAULT_ATTEMPTS


def test_custom_max_retries() -> None:
    """Test that custom max_retries can be provided."""
    client = BaseApiClient(
        host="192.168.1.1",
        port=443,
        username="test",
        password="test",  # noqa: S106
        max_retries=5,
    )
    assert client._max_retries == 5


def test_disable_retry() -> None:
    """Test that retry can be disabled by passing 0."""
    client = BaseApiClient(
        host="192.168.1.1",
        port=443,
        username="test",
        password="test",  # noqa: S106
        max_retries=0,
    )
    assert client._max_retries == 0


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("status_code", "headers"),
    [
        (408, None),
        (429, {"Retry-After": "0.01"}),
        (500, None),
        (502, None),
        (503, None),
        (504, None),
    ],
    ids=[
        "408-timeout",
        "429-rate-limit",
        "500-server-error",
        "502-bad-gateway",
        "503-unavailable",
        "504-gateway-timeout",
    ],
)
async def test_retry_loop_on_retryable_status(
    protect_client_factory, status_code: int, headers: dict[str, str] | None
) -> None:
    """Test that request retries on retryable status codes."""
    client = protect_client_factory(max_retries=1)
    response_error = _mock_response(status_code, headers)
    response_200 = _mock_response(200)
    call_count = 0

    async def mock_do_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return response_error if call_count == 1 else response_200

    with patch.object(client, "_do_request", side_effect=mock_do_request):
        result = await client.request("get", "/test", auto_close=False)

    assert result is response_200
    assert call_count == 2


@pytest.mark.asyncio()
async def test_retry_loop_exhausted_returns_last_response(
    protect_client_factory,
) -> None:
    """Test that request returns last response when retries exhausted."""
    client = protect_client_factory(max_retries=2)
    response_502 = _mock_response(502)

    with patch.object(client, "_do_request", return_value=response_502) as mock_request:
        result = await client.request("get", "/test", auto_close=False)

    assert result is response_502
    assert mock_request.await_count == 3  # 1 initial + 2 retries


@pytest.mark.asyncio()
async def test_no_retry_on_success_status(protect_client_factory) -> None:
    """Test that request does not retry on success status codes."""
    client = protect_client_factory(max_retries=3)
    response_200 = _mock_response(200)

    with patch.object(client, "_do_request", return_value=response_200) as mock_request:
        result = await client.request("get", "/test", auto_close=False)

    assert result is response_200
    assert mock_request.await_count == 1  # No retries


@pytest.mark.asyncio()
async def test_auto_close_releases_response(protect_client_factory) -> None:
    """Test that auto_close=True releases response."""
    client = protect_client_factory(max_retries=0)
    response_200 = _mock_response(200)
    response_200.content_type = "application/json"

    with patch.object(client, "_do_request", return_value=response_200):
        result = await client.request("get", "/test", auto_close=True)

    assert result is response_200
    response_200.release.assert_called()


@pytest.mark.asyncio()
async def test_auto_close_releases_on_exception(protect_client_factory) -> None:
    """Test that auto_close=True releases response even on exception."""
    client = protect_client_factory(max_retries=0)
    response_200 = _mock_response(200)
    type(response_200).content_type = PropertyMock(side_effect=ValueError("test error"))

    with (
        patch.object(client, "_do_request", return_value=response_200),
        pytest.raises(ValueError, match="test error"),
    ):
        await client.request("get", "/test", auto_close=True)

    response_200.release.assert_called()


@pytest.mark.asyncio()
async def test_no_retry_when_max_retries_zero(protect_client_factory) -> None:
    """Test that request does not retry when max_retries is 0."""
    client = protect_client_factory(max_retries=0)
    response_503 = _mock_response(503)

    with patch.object(client, "_do_request", return_value=response_503) as mock_request:
        result = await client.request("get", "/test", auto_close=False)

    assert result is response_503
    assert mock_request.await_count == 1  # No retries


# =============================================================================
# _do_request Exception Handling Tests
# =============================================================================


@pytest.fixture
def do_request_client() -> ProtectApiClient:
    """Create a ProtectApiClient for _do_request testing."""
    return ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        verify_ssl=False,
    )


@pytest.mark.asyncio()
async def test_server_disconnected_error_retries_once(
    do_request_client: ProtectApiClient,
) -> None:
    """Test that ServerDisconnectedError triggers one retry."""
    mock_session = AsyncMock()
    response_200 = AsyncMock()
    response_200.status = 200
    response_200.headers = {}

    mock_ctx = _create_mock_request_context(
        side_effect=aiohttp.ServerDisconnectedError(),
        return_value=response_200,
        fail_count=1,
    )
    mock_session.request = MagicMock(return_value=mock_ctx)
    do_request_client._update_last_token_cookie = AsyncMock()

    result = await do_request_client._do_request(
        mock_session, "GET", URL("http://test/api"), {}
    )

    assert result is response_200
    assert mock_ctx.calls == 2  # 1 retry after disconnect


@pytest.mark.asyncio()
async def test_server_disconnected_error_raises_after_retry(
    do_request_client: ProtectApiClient,
) -> None:
    """Test that ServerDisconnectedError raises NvrError after retry fails."""
    mock_session = AsyncMock()
    mock_ctx = _create_mock_request_context(
        side_effect=aiohttp.ServerDisconnectedError()
    )
    mock_session.request = MagicMock(return_value=mock_ctx)

    with pytest.raises(NvrError, match="Error requesting data"):
        await do_request_client._do_request(
            mock_session, "GET", URL("http://test/api"), {}
        )


@pytest.mark.asyncio()
async def test_client_error_raises_nvr_error(
    do_request_client: ProtectApiClient,
) -> None:
    """Test that ClientError raises NvrError immediately."""
    mock_session = AsyncMock()
    mock_ctx = _create_mock_request_context(
        side_effect=client_exceptions.ClientConnectionError("Connection failed")
    )
    mock_session.request = MagicMock(return_value=mock_ctx)

    with pytest.raises(NvrError, match="Error requesting data"):
        await do_request_client._do_request(
            mock_session, "GET", URL("http://test/api"), {}
        )


@pytest.mark.asyncio()
async def test_update_token_cookie_failure_releases_response(
    do_request_client: ProtectApiClient,
) -> None:
    """Test that response is released if _update_last_token_cookie fails."""
    mock_session = AsyncMock()
    response = MagicMock()
    response.status = 200
    response.headers = {}
    response.release = MagicMock()

    class MockRequestContext:
        async def __aenter__(self_inner):
            return response

        async def __aexit__(self_inner, *args):
            pass

    mock_session.request = MagicMock(return_value=MockRequestContext())
    do_request_client._update_last_token_cookie = AsyncMock(
        side_effect=ValueError("Cookie parsing failed")
    )

    with pytest.raises(ValueError, match="Cookie parsing failed"):
        await do_request_client._do_request(
            mock_session, "GET", URL("http://test/api"), {}
        )

    response.release.assert_called_once()
