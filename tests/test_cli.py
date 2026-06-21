import re
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# The CLI stack (typer + rich) ships with the optional `cli` extra; importing
# uiprotect.cli pulls the whole chain, so skip the module when any part is
# absent (a minimal install without --all-extras) instead of failing collection.
pytest.importorskip("uiprotect.cli")

import typer
from typer.testing import CliRunner

from uiprotect.cli import _is_ssl_error, app
from uiprotect.cli.arm import app as arm_app
from uiprotect.cli.bridges import app as bridges_app
from uiprotect.cli.cameras import app as cameras_app
from uiprotect.cli.chimes import app as chime_app
from uiprotect.cli.chimes import cameras, set_repeat_times, set_volume
from uiprotect.cli.files_public import app as files_public_app
from uiprotect.cli.fobs import app as fob_app
from uiprotect.cli.link_stations import app as link_station_app
from uiprotect.cli.liveviews import app as liveview_app
from uiprotect.cli.relays import app as relay_app
from uiprotect.cli.sirens import app as siren_app
from uiprotect.cli.speakers import app as speaker_app
from uiprotect.cli.ulp_users_public import app as ulp_users_public_app
from uiprotect.cli.users_public import app as users_public_app
from uiprotect.cli.viewers_public import app as viewer_public_app
from uiprotect.data import RingSetting
from uiprotect.exceptions import BadRequest

runner = CliRunner()

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


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
    assert "link-stations" in result.stdout
    assert "liveviews" in result.stdout
    assert "bridges" in result.stdout
    assert "viewers-public" in result.stdout
    assert "users-public" in result.stdout
    assert "ulp-users-public" in result.stdout
    assert "files-public" in result.stdout
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


def test_link_stations_help() -> None:
    """``link-stations --help`` renders without error."""
    result = runner.invoke(link_station_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "show" in result.stdout
    assert "set-name" in result.stdout
    assert "trigger-output" in result.stdout


def test_bridges_help() -> None:
    """``bridges --help`` renders without error."""
    result = runner.invoke(bridges_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "show" in result.stdout
    assert "set-name" in result.stdout


def test_viewers_public_help() -> None:
    """``viewers-public --help`` renders without error."""
    result = runner.invoke(viewer_public_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "show" in result.stdout
    assert "set-name" in result.stdout
    assert "set-liveview" in result.stdout


def test_users_public_help() -> None:
    """``users-public --help`` renders without error."""
    result = runner.invoke(users_public_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "show" in result.stdout


def test_ulp_users_public_help() -> None:
    """``ulp-users-public --help`` renders without error."""
    result = runner.invoke(ulp_users_public_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "show" in result.stdout


def test_files_public_help() -> None:
    """``files-public --help`` renders without error."""
    result = runner.invoke(files_public_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "upload" in result.stdout


def test_public_only_command_constructs_without_credentials() -> None:
    """A public-API subcommand builds the client with only an API key."""
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.return_value = MagicMock(
            get_sirens_public=AsyncMock(return_value=[]),
            close_session=AsyncMock(),
            close_public_api_session=AsyncMock(),
        )
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "sirens", "list"],
        )

    assert result.exit_code == 0
    assert client_cls.call_count == 1
    kwargs = client_cls.call_args.kwargs
    assert kwargs["api_key"] == "k"
    assert kwargs["username"] is None
    assert kwargs["password"] is None


def test_client_construction_bad_request_exits_with_error() -> None:
    """A ``BadRequest`` from client construction prints in red and exits 1."""
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.side_effect = BadRequest("api key cannot be empty")
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "sirens", "list"],
        )

    assert result.exit_code == 1
    output = _ANSI_ESCAPE_RE.sub("", result.stdout + (result.stderr or ""))
    assert "api key cannot be empty" in output


def test_cameras_disable_mic_listed_in_help() -> None:
    """
    ``cameras --help`` advertises the new ``disable-mic-permanently`` subcommand.

    The cameras CLI takes an optional positional ``device_id`` before the
    subcommand, so invoking ``["disable-mic-permanently", "--help"]`` is
    parsed by typer as ``device_id="disable-mic-permanently"`` followed by
    the parent's ``--help``; the parent help is what we assert on instead.
    """
    result = runner.invoke(cameras_app, ["--help"])
    assert result.exit_code == 0
    plain_output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "disable-mic-permanently" in plain_output


def test_link_stations_trigger_output_rejects_negative_delay() -> None:
    """``trigger-output ... --delay -1`` must fail typer's ``min=0`` validator."""
    result = runner.invoke(
        link_station_app,
        ["trigger-output", "hub-id", "0", "--delay", "-1"],
    )
    assert result.exit_code != 0
    plain_output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "Invalid value" in plain_output
    assert "--delay" in plain_output


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


def test_liveviews_create_rejects_non_object_slot_entries() -> None:
    """``--slots`` entries must be JSON objects, not scalars."""
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
            '["bad"]',
        ],
    )
    assert result.exit_code == 1
    assert "--slots entries must be JSON objects" in result.stdout


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


# ---------------------------------------------------------------------------
# Chime CLI — public-API migration
# ---------------------------------------------------------------------------


def _make_chime_ctx(
    *,
    ring_settings: list[RingSetting] | None = None,
    camera_ids: list[str] | None = None,
    cameras_map: dict[str, MagicMock] | None = None,
):
    """Build a typer context double wired to mocked chime + client."""
    chime = MagicMock()
    chime.id = "chime-1"
    chime.ring_settings = ring_settings if ring_settings is not None else []
    chime.camera_ids = camera_ids if camera_ids is not None else []
    chime.cameras = []
    chime.set_volume_for_camera_public = AsyncMock()
    chime.set_ring_settings_public = AsyncMock()
    chime.set_repeat_times_for_camera_public = AsyncMock()

    protect = MagicMock()
    protect.update_chime_public = AsyncMock()
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()
    protect.bootstrap.cameras = cameras_map if cameras_map is not None else {}

    ctx = MagicMock()
    ctx.obj.device = chime
    ctx.obj.protect = protect
    return ctx, chime, protect


def _doorbell_camera(camera_id: str) -> MagicMock:
    camera = MagicMock()
    camera.id = camera_id
    camera.feature_flags.is_doorbell = True
    return camera


def test_chime_help() -> None:
    """Chime CLI exposes its subcommands."""
    result = runner.invoke(chime_app, ["--help"])
    assert result.exit_code == 0
    assert "cameras" in result.stdout
    assert "set-volume" in result.stdout
    assert "set-repeat-times" in result.stdout


def test_chime_cameras_set_uses_update_chime_public() -> None:
    """Setting cameras patches via the public API, not save_device."""
    camera = _doorbell_camera("cam-1")
    ctx, _chime, protect = _make_chime_ctx(cameras_map={"cam-1": camera})

    cameras(ctx, camera_ids=["cam-1"], add=False, remove=False)

    protect.update_chime_public.assert_awaited_once_with(
        "chime-1", camera_ids=["cam-1"]
    )


def test_chime_cameras_empty_clears_list() -> None:
    """`[]` sentinel clears paired cameras via the public API."""
    ctx, _chime, protect = _make_chime_ctx(camera_ids=["cam-1"])

    cameras(ctx, camera_ids=["[]"], add=False, remove=False)

    protect.update_chime_public.assert_awaited_once_with("chime-1", camera_ids=[])


def test_chime_cameras_add_merges_existing() -> None:
    """--add unions with current cameras."""
    camera = _doorbell_camera("cam-2")
    ctx, _chime, protect = _make_chime_ctx(
        camera_ids=["cam-1"], cameras_map={"cam-2": camera}
    )

    cameras(ctx, camera_ids=["cam-2"], add=True, remove=False)

    protect.update_chime_public.assert_awaited_once()
    sent = protect.update_chime_public.await_args.kwargs["camera_ids"]
    assert set(sent) == {"cam-1", "cam-2"}


def test_chime_cameras_remove_subtracts() -> None:
    """--remove drops the named cameras."""
    camera = _doorbell_camera("cam-1")
    ctx, _chime, protect = _make_chime_ctx(
        camera_ids=["cam-1", "cam-2"], cameras_map={"cam-1": camera}
    )

    cameras(ctx, camera_ids=["cam-1"], add=False, remove=True)

    protect.update_chime_public.assert_awaited_once()
    sent = protect.update_chime_public.await_args.kwargs["camera_ids"]
    assert set(sent) == {"cam-2"}


def test_chime_cameras_add_and_remove_rejected() -> None:
    """--add and --remove are mutually exclusive."""
    ctx, _chime, protect = _make_chime_ctx()

    with pytest.raises(typer.Exit) as exc:
        cameras(ctx, camera_ids=["cam-1"], add=True, remove=True)

    assert exc.value.exit_code == 1
    protect.update_chime_public.assert_not_called()


def test_chime_cameras_no_args_lists_cameras() -> None:
    """No camera ids prints the current pairing."""
    ctx, _chime, protect = _make_chime_ctx()

    cameras(ctx, camera_ids=[], add=False, remove=False)

    protect.update_chime_public.assert_not_called()


def test_chime_cameras_invalid_id_rejected() -> None:
    """Unknown camera id exits 1."""
    ctx, _chime, protect = _make_chime_ctx(cameras_map={})

    with pytest.raises(typer.Exit) as exc:
        cameras(ctx, camera_ids=["nope"], add=False, remove=False)

    assert exc.value.exit_code == 1
    protect.update_chime_public.assert_not_called()


def test_chime_cameras_non_doorbell_rejected() -> None:
    """Non-doorbell camera exits 1."""
    camera = _doorbell_camera("cam-1")
    camera.feature_flags.is_doorbell = False
    ctx, _chime, protect = _make_chime_ctx(cameras_map={"cam-1": camera})

    with pytest.raises(typer.Exit) as exc:
        cameras(ctx, camera_ids=["cam-1"], add=False, remove=False)

    assert exc.value.exit_code == 1
    protect.update_chime_public.assert_not_called()


def test_chime_set_volume_whole_device_uses_ring_settings() -> None:
    """Whole-device volume routes through update_chime_public(ring_settings=...)."""
    ring = RingSetting(
        camera_id="cam-1",
        repeat_times=2,  # type: ignore[arg-type]
        ringtone_id="rt-1",
        volume=20,
    )
    ctx, _chime, protect = _make_chime_ctx(ring_settings=[ring])

    set_volume(ctx, value=80, camera_id=None)

    protect.update_chime_public.assert_awaited_once_with(
        "chime-1",
        ring_settings=[
            {
                "cameraId": "cam-1",
                "volume": 80,
                "repeatTimes": 2,
                "ringtoneId": "rt-1",
            }
        ],
    )


def test_chime_set_volume_per_camera_uses_public_wrapper() -> None:
    """Per-camera volume uses set_volume_for_camera_public."""
    camera = _doorbell_camera("cam-1")
    ctx, chime, protect = _make_chime_ctx(cameras_map={"cam-1": camera})

    set_volume(ctx, value=55, camera_id="cam-1")

    chime.set_volume_for_camera_public.assert_awaited_once_with(camera, 55)
    protect.update_chime_public.assert_not_called()


def test_chime_set_volume_per_camera_invalid_id_rejected() -> None:
    """Per-camera volume with unknown camera exits 1."""
    ctx, chime, _protect = _make_chime_ctx(cameras_map={})

    with pytest.raises(typer.Exit) as exc:
        set_volume(ctx, value=55, camera_id="nope")

    assert exc.value.exit_code == 1
    chime.set_volume_for_camera_public.assert_not_called()


def test_chime_set_repeat_times_whole_device_uses_ring_settings() -> None:
    """Whole-device repeat routes through update_chime_public(ring_settings=...)."""
    ring = RingSetting(
        camera_id="cam-1",
        repeat_times=1,  # type: ignore[arg-type]
        ringtone_id="rt-1",
        volume=20,
    )
    ctx, _chime, protect = _make_chime_ctx(ring_settings=[ring])

    set_repeat_times(ctx, value=4, camera_id=None)

    protect.update_chime_public.assert_awaited_once_with(
        "chime-1",
        ring_settings=[
            {
                "cameraId": "cam-1",
                "volume": 20,
                "repeatTimes": 4,
                "ringtoneId": "rt-1",
            }
        ],
    )


def test_chime_set_repeat_times_per_camera_uses_public_wrapper() -> None:
    """Per-camera repeat delegates to set_repeat_times_for_camera_public."""
    camera = _doorbell_camera("cam-1")
    ctx, chime, protect = _make_chime_ctx(cameras_map={"cam-1": camera})

    set_repeat_times(ctx, value=5, camera_id="cam-1")

    chime.set_repeat_times_for_camera_public.assert_awaited_once_with(camera, 5)
    protect.update_chime_public.assert_not_called()


def test_chime_set_repeat_times_per_camera_invalid_id_rejected() -> None:
    """Per-camera repeat with unknown camera exits 1."""
    ctx, chime, _protect = _make_chime_ctx(cameras_map={})

    with pytest.raises(typer.Exit) as exc:
        set_repeat_times(ctx, value=5, camera_id="nope")

    assert exc.value.exit_code == 1
    chime.set_repeat_times_for_camera_public.assert_not_called()
