"""Tests for retry module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientResponse

from uiprotect import RetryConfig as ExportedRetryConfig
from uiprotect.api import BaseApiClient, ProtectApiClient
from uiprotect.retry import (
    DEFAULT_RETRY_CONFIG,
    MIN_RETRY_DELAY,
    RetryConfig,
    parse_retry_after,
)

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
def default_config() -> RetryConfig:
    """Create default retry config for testing."""
    return RetryConfig(jitter=False)  # Disable jitter for predictable tests


# =============================================================================
# RetryConfig Tests
# =============================================================================


class TestRetryConfigInit:
    """Tests for RetryConfig initialization and validation."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = RetryConfig()

        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0
        assert config.exponential_base == 2.0
        assert config.jitter is True
        assert config.retry_on_status == frozenset({429, 502, 503, 504})

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = RetryConfig(
            max_retries=5,
            base_delay=0.5,
            max_delay=60.0,
            exponential_base=3.0,
            jitter=False,
            retry_on_status=frozenset({429}),
        )

        assert config.max_retries == 5
        assert config.base_delay == 0.5
        assert config.max_delay == 60.0
        assert config.exponential_base == 3.0
        assert config.jitter is False
        assert config.retry_on_status == frozenset({429})

    @pytest.mark.parametrize(
        ("field", "value", "error_msg"),
        [
            ("max_retries", -1, "max_retries must be non-negative"),
            ("base_delay", 0, "base_delay must be positive"),
            ("base_delay", -1, "base_delay must be positive"),
            ("max_delay", 0, "max_delay must be positive"),
            ("max_delay", -1, "max_delay must be positive"),
            ("exponential_base", 1, "exponential_base must be greater than 1"),
            ("exponential_base", 0.5, "exponential_base must be greater than 1"),
        ],
    )
    def test_validation_errors(self, field: str, value: float, error_msg: str) -> None:
        """Test validation raises ValueError for invalid values."""
        with pytest.raises(ValueError, match=error_msg):
            RetryConfig(**{field: value})

    def test_zero_retries_allowed(self) -> None:
        """Test that zero retries is valid (disables retry)."""
        config = RetryConfig(max_retries=0)
        assert config.max_retries == 0


class TestRetryConfigCalculateDelay:
    """Tests for RetryConfig.calculate_delay method."""

    def test_exponential_backoff_without_jitter(self) -> None:
        """Test exponential backoff calculation without jitter."""
        config = RetryConfig(
            base_delay=1.0,
            exponential_base=2.0,
            max_delay=30.0,
            jitter=False,
        )

        assert config.calculate_delay(0) == 1.0  # 1 * 2^0 = 1
        assert config.calculate_delay(1) == 2.0  # 1 * 2^1 = 2
        assert config.calculate_delay(2) == 4.0  # 1 * 2^2 = 4
        assert config.calculate_delay(3) == 8.0  # 1 * 2^3 = 8

    def test_max_delay_cap(self) -> None:
        """Test that delay is capped at max_delay."""
        config = RetryConfig(
            base_delay=1.0,
            exponential_base=2.0,
            max_delay=5.0,
            jitter=False,
        )

        assert config.calculate_delay(0) == 1.0
        assert config.calculate_delay(1) == 2.0
        assert config.calculate_delay(2) == 4.0
        assert config.calculate_delay(3) == 5.0  # Capped at max_delay
        assert config.calculate_delay(10) == 5.0  # Still capped

    def test_retry_after_header_respected(self) -> None:
        """Test that Retry-After header value is used when provided."""
        config = RetryConfig(max_delay=30.0, jitter=False)

        # Retry-After overrides exponential backoff
        assert config.calculate_delay(0, retry_after=5.0) == 5.0
        assert config.calculate_delay(1, retry_after=10.0) == 10.0

    def test_retry_after_capped_at_max_delay(self) -> None:
        """Test that Retry-After is capped at max_delay."""
        config = RetryConfig(max_delay=10.0, jitter=False)

        assert config.calculate_delay(0, retry_after=100.0) == 10.0

    def test_jitter_adds_variation(self) -> None:
        """Test that jitter adds variation to delay."""
        config = RetryConfig(
            base_delay=10.0,
            exponential_base=2.0,
            jitter=True,
        )

        delays = [config.calculate_delay(0) for _ in range(100)]

        # All delays should be around 10.0 (±25%)
        assert all(7.5 <= d <= 12.5 for d in delays)
        # With jitter, we should see variation
        assert len(set(delays)) > 1

    def test_jitter_minimum_delay(self) -> None:
        """Test that jitter maintains minimum delay of MIN_RETRY_DELAY."""
        config = RetryConfig(
            base_delay=0.1,
            jitter=True,
        )

        delays = [config.calculate_delay(0) for _ in range(100)]
        assert all(d >= MIN_RETRY_DELAY for d in delays)


# =============================================================================
# parse_retry_after Tests
# =============================================================================


class TestParseRetryAfter:
    """Tests for parse_retry_after function."""

    def test_valid_integer(self, mock_response: MagicMock) -> None:
        """Test parsing integer Retry-After value."""
        mock_response.headers = {"Retry-After": "5"}
        assert parse_retry_after(mock_response) == 5.0

    def test_valid_float(self, mock_response: MagicMock) -> None:
        """Test parsing float Retry-After value."""
        mock_response.headers = {"Retry-After": "2.5"}
        assert parse_retry_after(mock_response) == 2.5

    def test_missing_header(self, mock_response: MagicMock) -> None:
        """Test handling missing Retry-After header."""
        mock_response.headers = {}
        assert parse_retry_after(mock_response) is None

    def test_invalid_value(self, mock_response: MagicMock) -> None:
        """Test handling invalid Retry-After value."""
        mock_response.headers = {"Retry-After": "not-a-number"}
        assert parse_retry_after(mock_response) is None

    def test_http_date_not_supported(self, mock_response: MagicMock) -> None:
        """Test that HTTP-date format returns None."""
        mock_response.headers = {"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"}
        assert parse_retry_after(mock_response) is None


# =============================================================================
# retry_request Tests
# =============================================================================


# =============================================================================
# DEFAULT_RETRY_CONFIG Tests
# =============================================================================


class TestDefaultRetryConfig:
    """Tests for DEFAULT_RETRY_CONFIG."""

    def test_default_config_values(self) -> None:
        """Test that default config has expected values."""
        assert DEFAULT_RETRY_CONFIG.max_retries == 3
        assert DEFAULT_RETRY_CONFIG.base_delay == 1.0
        assert DEFAULT_RETRY_CONFIG.max_delay == 30.0
        assert DEFAULT_RETRY_CONFIG.exponential_base == 2.0
        assert DEFAULT_RETRY_CONFIG.jitter is True
        assert 429 in DEFAULT_RETRY_CONFIG.retry_on_status
        assert 502 in DEFAULT_RETRY_CONFIG.retry_on_status
        assert 503 in DEFAULT_RETRY_CONFIG.retry_on_status
        assert 504 in DEFAULT_RETRY_CONFIG.retry_on_status


# =============================================================================
# API Client Integration Tests
# =============================================================================


class TestApiClientRetryIntegration:
    """Tests for retry integration in BaseApiClient."""

    @pytest.fixture
    def base_client(self) -> BaseApiClient:
        """Create a BaseApiClient for testing."""
        return BaseApiClient(
            host="192.168.1.1",
            port=443,
            username="test",
            password="test",  # noqa: S106
        )

    @pytest.fixture
    def protect_client_factory(self):
        """Factory to create ProtectApiClient with custom retry config."""

        def _create(retry_config: RetryConfig | None = None) -> ProtectApiClient:
            return ProtectApiClient(
                "127.0.0.1",
                0,
                "user",
                "pass",
                verify_ssl=False,
                retry_config=retry_config,
            )

        return _create

    @staticmethod
    def _mock_response(status: int, headers: dict[str, str] | None = None) -> AsyncMock:
        """Create a mock response with given status."""
        response = AsyncMock()
        response.status = status
        response.headers = headers or {}
        response.release = AsyncMock()
        response.content_type = "application/json" if status == 200 else "text/plain"
        return response

    def test_default_retry_config_applied(self, base_client: BaseApiClient) -> None:
        """Test that default retry config is applied to new clients."""
        assert base_client._retry_config is not None
        assert base_client._retry_config.max_retries == 3

    def test_custom_retry_config(self, base_client: BaseApiClient) -> None:
        """Test that custom retry config can be provided."""
        custom_config = RetryConfig(max_retries=5, base_delay=2.0)
        client = BaseApiClient(
            host="192.168.1.1",
            port=443,
            username="test",
            password="test",  # noqa: S106
            retry_config=custom_config,
        )

        assert client._retry_config is custom_config
        assert client._retry_config.max_retries == 5

    def test_disable_retry(self) -> None:
        """Test that retry can be disabled by passing None."""
        client = BaseApiClient(
            host="192.168.1.1",
            port=443,
            username="test",
            password="test",  # noqa: S106
            retry_config=None,
        )

        assert client._retry_config is None

    def test_retry_config_exported(self) -> None:
        """Test that RetryConfig is exported from uiprotect package."""
        assert ExportedRetryConfig is RetryConfig
        assert 503 in DEFAULT_RETRY_CONFIG.retry_on_status
        assert 504 in DEFAULT_RETRY_CONFIG.retry_on_status

    @pytest.mark.asyncio
    async def test_retry_loop_on_503_status(self, protect_client_factory) -> None:
        """Test that request retries on 503 status code."""
        client = protect_client_factory(
            RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        )
        response_503 = self._mock_response(503)
        response_200 = self._mock_response(200)
        call_count = 0

        async def mock_do_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return response_503 if call_count < 3 else response_200

        client.get_session = AsyncMock(return_value=AsyncMock())
        with patch.object(client, "_do_request", side_effect=mock_do_request):
            result = await client.request("get", "/test", auto_close=False)

        assert result is response_200
        assert call_count == 3  # 2 retries + 1 initial

    @pytest.mark.asyncio
    async def test_retry_loop_on_429_with_retry_after(
        self, protect_client_factory
    ) -> None:
        """Test that request respects Retry-After header on 429."""
        client = protect_client_factory(
            RetryConfig(max_retries=1, base_delay=0.01, jitter=False)
        )
        response_429 = self._mock_response(429, {"Retry-After": "0.01"})
        response_200 = self._mock_response(200)
        call_count = 0

        async def mock_do_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return response_429 if call_count == 1 else response_200

        client.get_session = AsyncMock(return_value=AsyncMock())
        with patch.object(client, "_do_request", side_effect=mock_do_request):
            result = await client.request("get", "/test", auto_close=False)

        assert result is response_200
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_loop_exhausted_returns_last_response(
        self, protect_client_factory
    ) -> None:
        """Test that request returns last response when retries exhausted."""
        client = protect_client_factory(
            RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        )
        response_502 = self._mock_response(502)

        client.get_session = AsyncMock(return_value=AsyncMock())
        with patch.object(
            client, "_do_request", return_value=response_502
        ) as mock_request:
            result = await client.request("get", "/test", auto_close=False)

        assert result is response_502
        assert mock_request.await_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_no_retry_on_success_status(self, protect_client_factory) -> None:
        """Test that request does not retry on success status codes."""
        client = protect_client_factory(RetryConfig(max_retries=3, base_delay=0.01))
        response_200 = self._mock_response(200)

        client.get_session = AsyncMock(return_value=AsyncMock())
        with patch.object(
            client, "_do_request", return_value=response_200
        ) as mock_request:
            result = await client.request("get", "/test", auto_close=False)

        assert result is response_200
        assert mock_request.await_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_no_retry_when_config_is_none(self, protect_client_factory) -> None:
        """Test that request does not retry when retry_config is None."""
        client = protect_client_factory(retry_config=None)
        response_503 = self._mock_response(503)

        client.get_session = AsyncMock(return_value=AsyncMock())
        with patch.object(
            client, "_do_request", return_value=response_503
        ) as mock_request:
            result = await client.request("get", "/test", auto_close=False)

        assert result is response_503
        assert mock_request.await_count == 1  # No retries
