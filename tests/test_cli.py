import ssl
from unittest.mock import MagicMock

import aiohttp
from typer.testing import CliRunner

from uiprotect.cli import _is_ssl_error, app

runner = CliRunner()


def test_help():
    """The help message includes the CLI name."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "UniFi Protect CLI" in result.stdout


def test_is_ssl_error_with_ssl_exceptions():
    """SSL-related exceptions should be detected."""
    # Direct SSL errors
    assert (
        _is_ssl_error(ssl.SSLCertVerificationError("certificate verify failed")) is True
    )

    # Mock aiohttp SSL errors (they require complex OSError arguments)
    ssl_error = MagicMock(spec=aiohttp.ClientConnectorSSLError)
    ssl_error.__class__ = aiohttp.ClientConnectorSSLError
    assert _is_ssl_error(ssl_error) is True

    cert_error = MagicMock(spec=aiohttp.ClientConnectorCertificateError)
    cert_error.__class__ = aiohttp.ClientConnectorCertificateError
    assert _is_ssl_error(cert_error) is True


def test_is_ssl_error_with_wrapped_ssl_exceptions():
    """SSL exceptions wrapped in other exceptions should be detected."""
    ssl_error = ssl.SSLCertVerificationError()
    wrapped = RuntimeError("Connection failed")
    wrapped.__cause__ = ssl_error
    assert _is_ssl_error(wrapped) is True

    # Deeply nested
    outer = ValueError("Outer error")
    outer.__cause__ = wrapped
    assert _is_ssl_error(outer) is True


def test_is_ssl_error_with_non_ssl_exceptions():
    """Non-SSL exceptions should not be detected as SSL errors."""
    assert _is_ssl_error(ValueError("some error")) is False
    assert _is_ssl_error(RuntimeError("connection refused")) is False
    assert _is_ssl_error(aiohttp.ClientError("generic error")) is False
    assert _is_ssl_error(ConnectionError("network error")) is False
