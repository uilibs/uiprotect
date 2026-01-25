"""Retry mechanism with exponential backoff for API requests."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from aiohttp import ClientResponse

_LOGGER = logging.getLogger(__name__)

# Minimum delay to prevent tight retry loops
MIN_RETRY_DELAY = 0.1


@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts (0 = no retries).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay in seconds between retries.
        exponential_base: Base for exponential backoff calculation.
        jitter: Whether to add random jitter to delays.
        retry_on_status: HTTP status codes that should trigger a retry.

    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on_status: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 502, 503, 504})
    )

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if self.max_delay <= 0:
            raise ValueError("max_delay must be positive")
        if self.exponential_base <= 1:
            raise ValueError("exponential_base must be greater than 1")

    def calculate_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """
        Calculate delay before next retry attempt.

        Args:
            attempt: Current retry attempt number (0-based).
            retry_after: Optional Retry-After header value in seconds.

        Returns:
            Delay in seconds before next retry.

        """
        if retry_after is not None and retry_after > 0:
            # Respect Retry-After header, but cap at max_delay
            delay = min(retry_after, self.max_delay)
        else:
            # Exponential backoff: base_delay * (exponential_base ^ attempt)
            delay = self.base_delay * (self.exponential_base**attempt)
            delay = min(delay, self.max_delay)

        if self.jitter:
            # Add random jitter (±25% of delay)
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)  # noqa: S311
            delay = max(MIN_RETRY_DELAY, delay)  # Ensure minimum delay

        return delay


def parse_retry_after(response: ClientResponse) -> float | None:
    """
    Parse Retry-After header from response.

    Args:
        response: HTTP response object.

    Returns:
        Retry delay in seconds, or None if header not present/parseable.

    """
    retry_after = response.headers.get("Retry-After")
    if retry_after is None:
        return None

    try:
        # Retry-After can be seconds or HTTP-date, we only handle seconds
        return float(retry_after)
    except ValueError:
        _LOGGER.debug("Could not parse Retry-After header: %s", retry_after)
        return None


# Default configuration for UniFi Protect API (uses dataclass defaults)
DEFAULT_RETRY_CONFIG = RetryConfig()
