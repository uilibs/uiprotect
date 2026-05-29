import ssl
from unittest.mock import MagicMock

import aiohttp
from typer.testing import CliRunner

from uiprotect.cli import _is_ssl_error, app
from uiprotect.cli.arm import app as arm_app
from uiprotect.cli.fobs import app as fob_app
from uiprotect.cli.liveviews import app as liveview_app
from uiprotect.cli.relays import app as relay_app
from uiprotect.cli.sirens import app as siren_app
from uiprotect.cli.speakers import app as speaker_app

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
    assert "fobs" in result.stdout
    assert "speakers" in result.stdout
    assert "liveviews" in result.stdout
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


def test_fobs_help() -> None:
    """``fobs --help`` renders without error."""
    result = runner.invoke(fob_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "set-name" in result.stdout


def test_speakers_help() -> None:
    """``speakers --help`` renders without error."""
    result = runner.invoke(speaker_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "show" in result.stdout
    assert "set-name" in result.stdout
    assert "set-volume" in result.stdout
    assert "set-mic-volume" in result.stdout
    assert "set-mic-enabled" in result.stdout
    assert "test-sound" in result.stdout


def test_arm_help() -> None:
    """``arm --help`` renders without error."""
    result = runner.invoke(arm_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout


def test_liveviews_help() -> None:
    """``liveviews --help`` renders without error."""
    result = runner.invoke(liveview_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "show" in result.stdout
    assert "create" in result.stdout
    assert "update" in result.stdout


def test_liveviews_create_rejects_invalid_slots_json() -> None:
    """``create --slots <bad-json>`` must exit with code 1 before any API call."""
    result = runner.invoke(
        liveview_app,
        [
            "create",
            "--name",
            "X",
            "--owner",
            "u1",
            "--layout",
            "1",
            "--slots",
            "not-json",
        ],
    )
    assert result.exit_code == 1
    assert "--slots must be valid JSON" in result.stdout


def test_liveviews_create_rejects_non_array_slots() -> None:
    """``--slots`` must be a JSON array, not an object."""
    result = runner.invoke(
        liveview_app,
        [
            "create",
            "--name",
            "X",
            "--owner",
            "u1",
            "--layout",
            "1",
            "--slots",
            '{"foo": 1}',
        ],
    )
    assert result.exit_code == 1
    assert "--slots must be a JSON array" in result.stdout


def test_liveviews_update_rejects_empty_args() -> None:
    """``update <id>`` without any field must exit with code 1."""
    result = runner.invoke(liveview_app, ["update", "lv-1"])
    assert result.exit_code == 1
    assert "At least one field must be provided" in result.stdout


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
