import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from typer.testing import CliRunner

from uiprotect.cli import _is_ssl_error, app
from uiprotect.cli.arm import app as arm_app
from uiprotect.cli.relays import app as relay_app
from uiprotect.cli.sirens import app as siren_app

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


# ---------------------------------------------------------------------------
# New Public-API sub-app smoke tests (no server needed)
# ---------------------------------------------------------------------------


def test_root_help_shows_public_subcommands() -> None:
    """Top-level --help must list the new public-API sub-apps."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sirens" in result.stdout
    assert "relays" in result.stdout
    assert "arm" in result.stdout


def test_sirens_help() -> None:
    """``sirens --help`` renders without error."""
    result = runner.invoke(siren_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout


def test_relays_help() -> None:
    """``relays --help`` renders without error."""
    result = runner.invoke(relay_app, ["--help"])
    assert result.exit_code == 0
    assert "activate" in result.stdout


def test_arm_help() -> None:
    """``arm --help`` renders without error."""
    result = runner.invoke(arm_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout


def test_relays_activate_rejects_invalid_state() -> None:
    """``activate --state bad`` must exit with code 1 before any API call."""
    result = runner.invoke(relay_app, ["activate", "relay-id", "0", "--state", "bad"])
    assert result.exit_code == 1
    assert "--state must be" in result.stdout


def test_relays_activate_rejects_pulse_without_on_state() -> None:
    """``--pulse-duration-ms`` with ``--state off`` must exit with code 1."""
    result = runner.invoke(
        relay_app,
        ["activate", "relay-id", "0", "--state", "off", "--pulse-duration-ms", "500"],
    )
    assert result.exit_code == 1
    assert "--pulse-duration-ms requires" in result.stdout


def test_relays_activate_rejects_pulse_without_any_state() -> None:
    """``--pulse-duration-ms`` without a state must exit with code 1."""
    result = runner.invoke(
        relay_app,
        ["activate", "relay-id", "0", "--pulse-duration-ms", "500"],
    )
    assert result.exit_code == 1
    assert "--pulse-duration-ms requires" in result.stdout


# ---------------------------------------------------------------------------
# SSL verification failure behaviour
# ---------------------------------------------------------------------------


_BASE_AUTH_ARGS = [
    "--username",
    "u",
    "--password",
    "p",
    "--address",
    "192.0.2.10",
]


def test_ssl_failure_does_not_prompt_or_retry() -> None:
    """SSL failure must exit 1 without offering to disable verification."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
        patch(
            "uiprotect.cli._get_cert_fingerprint",
            return_value="AA:BB:CC",
        ),
    ):
        client_cls.return_value = MagicMock(
            close_session=AsyncMock(),
            close_public_api_session=AsyncMock(),
        )
        connect.side_effect = ssl.SSLCertVerificationError("certificate verify failed")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "get-meta-info"])

    assert result.exit_code == 1
    output = result.stdout + (result.stderr or "")
    assert "Would you like to disable" not in output
    assert "Tip:" not in output
    assert client_cls.call_count == 1
    kwargs = client_cls.call_args.kwargs
    assert kwargs.get("verify_ssl") is True


def test_ssl_failure_prints_fingerprint_and_instructions() -> None:
    """Operator-visible output must show fingerprint and --no-verify-ssl."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
        patch(
            "uiprotect.cli._get_cert_fingerprint",
            return_value="DE:AD:BE:EF",
        ),
    ):
        client_cls.return_value = MagicMock(
            close_session=AsyncMock(),
            close_public_api_session=AsyncMock(),
        )
        connect.side_effect = ssl.SSLCertVerificationError("certificate verify failed")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "get-meta-info"])

    assert result.exit_code == 1
    output = result.stdout + (result.stderr or "")
    assert "DE:AD:BE:EF" in output
    assert "--no-verify-ssl" in output


def test_ssl_failure_when_fingerprint_unavailable() -> None:
    """Missing fingerprint must still exit 1 with --no-verify-ssl guidance."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
        patch(
            "uiprotect.cli._get_cert_fingerprint",
            return_value=None,
        ),
    ):
        client_cls.return_value = MagicMock(
            close_session=AsyncMock(),
            close_public_api_session=AsyncMock(),
        )
        connect.side_effect = ssl.SSLCertVerificationError("certificate verify failed")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "get-meta-info"])

    assert result.exit_code == 1
    output = result.stdout + (result.stderr or "")
    assert "--no-verify-ssl" in output
    assert client_cls.call_count == 1


def test_non_ssl_failure_still_exits_with_message() -> None:
    """Non-SSL connection failures keep their existing exit-1 path."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
    ):
        client_cls.return_value = MagicMock(
            close_session=AsyncMock(),
            close_public_api_session=AsyncMock(),
        )
        connect.side_effect = RuntimeError("boom")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "get-meta-info"])

    assert result.exit_code == 1
    output = result.stdout + (result.stderr or "")
    assert "Connection failed" in output
    assert client_cls.call_count == 1
