import re
import ssl
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# The CLI stack (typer + rich) ships with the optional `cli` extra; importing
# uiprotect.cli pulls the whole chain, so skip the module when any part is
# absent (a minimal install without --all-extras) instead of failing collection.
pytest.importorskip("uiprotect.cli")

import typer
from typer.testing import CliRunner

from uiprotect.api import ProtectApiClient
from uiprotect.cli import app
from uiprotect.cli import base as base_cli
from uiprotect.cli import cameras as cameras_cli
from uiprotect.cli import chimes as chimes_cli
from uiprotect.cli import lights as lights_cli
from uiprotect.cli import sensors as sensors_cli
from uiprotect.cli.arm import app as arm_app
from uiprotect.cli.base import _is_ssl_error
from uiprotect.cli.bridges import app as bridges_app
from uiprotect.cli.cameras import app as cameras_app
from uiprotect.cli.chimes import app as chime_app
from uiprotect.cli.chimes import cameras, set_repeat_times, set_volume
from uiprotect.cli.files_public import app as files_public_app
from uiprotect.cli.fobs import app as fob_app
from uiprotect.cli.link_stations import app as link_station_app
from uiprotect.cli.liveviews import app as liveview_app
from uiprotect.cli.relays import app as relay_app
from uiprotect.cli.sensors import app as sensor_app
from uiprotect.cli.sensors import (
    set_arm_profiles_public,
    set_custom_sensitivity_public,
    set_glass_break_public,
    set_glass_break_settings_public,
    set_humidity_settings_public,
    set_light_settings_public,
    set_motion_settings_public,
    set_schedule_mode_public,
    set_temperature_settings_public,
)
from uiprotect.cli.sirens import app as siren_app
from uiprotect.cli.speakers import app as speaker_app
from uiprotect.cli.ulp_users_public import app as ulp_users_public_app
from uiprotect.cli.users_public import app as users_public_app
from uiprotect.cli.viewers import app as viewer_app
from uiprotect.cli.viewers import liveview
from uiprotect.data import (
    NVR,
    AiPort,
    Camera,
    Chime,
    Light,
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicSensor,
    PublicViewer,
    RingSetting,
    Sensor,
    Viewer,
)
from uiprotect.data.types import (
    DEFAULT,
    DoorbellMessageType,
    PublicHdrMode,
    RecordingMode,
    SensorScheduleMode,
    SmartDetectAudioType,
    SmartDetectObjectType,
    VideoMode,
)
from uiprotect.exceptions import NvrError

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
    assert "viewers-public" not in result.stdout
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


def _public_only_client() -> MagicMock:
    return MagicMock(
        is_public_only=True,
        get_sirens_public=AsyncMock(return_value=[]),
        close_session=AsyncMock(),
        close_public_api_session=AsyncMock(),
    )


def test_api_key_alone_builds_a_public_only_client() -> None:
    """An API key with no username/password runs the CLI in public-only mode."""
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.public_only.return_value = _public_only_client()
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "sirens", "list"],
        )

    assert result.exit_code == 0
    assert client_cls.call_count == 0
    assert client_cls.public_only.call_count == 1
    args, kwargs = client_cls.public_only.call_args
    assert args == ("192.0.2.10", 443)
    assert kwargs["api_key"] == "k"


def test_api_key_alone_skips_the_private_bootstrap() -> None:
    """Public-only mode never logs in or fetches the private bootstrap."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
    ):
        client_cls.public_only.return_value = _public_only_client()
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "sirens", "list"],
        )

    assert result.exit_code == 0
    connect.assert_not_awaited()


def test_api_key_alone_runs_a_private_first_group_publicly() -> None:
    """A hybrid group no longer prompts for a password when only a key is given."""
    client = _public_only_client()
    client.get_cameras_public = AsyncMock(return_value=[])
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.public_only.return_value = client
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "cameras", "list-ids"],
        )

    assert result.exit_code == 0
    assert "Username" not in result.stdout
    client.get_cameras_public.assert_awaited_once()
    client.update_public.assert_not_called()
    client.get_bootstrap.assert_not_called()


def test_credentials_still_take_the_private_path_with_an_api_key() -> None:
    """Username/password alongside a key keeps the hybrid (private) client."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
    ):
        client = _hybrid_client()
        client.get_sirens_public = AsyncMock(return_value=[])
        client_cls.return_value = client
        result = runner.invoke(
            app,
            [*_BASE_AUTH_ARGS, "--api-key", "k", "sirens", "list"],
        )

    assert result.exit_code == 0
    assert client_cls.public_only.call_count == 0
    kwargs = client_cls.call_args.kwargs
    assert kwargs["username"] == "u"
    assert kwargs["password"] == "p"  # noqa: S105
    assert kwargs["api_key"] == "k"
    # A public-API group needs no private session, so none is opened.
    connect.assert_not_awaited()


def test_private_group_fetches_the_bootstrap_on_first_use() -> None:
    """A private group still logs in, just lazily rather than in the callback."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
    ):
        client = _hybrid_client()
        client.bootstrap.nvr.unifi_dict.return_value = {"id": "nvr-1"}
        client_cls.return_value = client
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "nvr"])

    assert result.exit_code == 0
    connect.assert_awaited_once()


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


def _hybrid_client() -> MagicMock:
    """A client double that has not yet fetched its private bootstrap."""
    return MagicMock(
        is_public_only=False,
        _bootstrap=None,
        _verify_ssl=True,
        _host="192.0.2.10",
        _port=443,
        close_session=AsyncMock(),
        close_public_api_session=AsyncMock(),
    )


def test_ssl_failure_does_not_prompt_or_retry() -> None:
    """SSL failure must exit 1 without offering to disable verification."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
        patch(
            "uiprotect.cli.base._get_cert_fingerprint",
            return_value="AA:BB:CC",
        ),
    ):
        client_cls.return_value = _hybrid_client()
        connect.side_effect = ssl.SSLCertVerificationError("certificate verify failed")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "nvr"])

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
            "uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
        patch(
            "uiprotect.cli.base._get_cert_fingerprint",
            return_value="DE:AD:BE:EF",
        ),
    ):
        client_cls.return_value = _hybrid_client()
        connect.side_effect = ssl.SSLCertVerificationError("certificate verify failed")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "nvr"])

    assert result.exit_code == 1
    output = result.stdout + (result.stderr or "")
    assert "DE:AD:BE:EF" in output
    assert "--no-verify-ssl" in output


def test_ssl_failure_when_fingerprint_unavailable() -> None:
    """Missing fingerprint must still exit 1 with --no-verify-ssl guidance."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
        patch(
            "uiprotect.cli.base._get_cert_fingerprint",
            return_value=None,
        ),
    ):
        client_cls.return_value = _hybrid_client()
        connect.side_effect = ssl.SSLCertVerificationError("certificate verify failed")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "nvr"])

    assert result.exit_code == 1
    output = result.stdout + (result.stderr or "")
    assert "--no-verify-ssl" in output
    assert client_cls.call_count == 1


def test_non_ssl_failure_still_exits_with_message() -> None:
    """Non-SSL connection failures keep their existing exit-1 path."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch(
            "uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock
        ) as connect,
    ):
        client_cls.return_value = _hybrid_client()
        connect.side_effect = RuntimeError("boom")
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "nvr"])

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

    protect = MagicMock(is_public_only=False)
    protect.update_chime_public = AsyncMock()
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()
    protect.bootstrap.cameras = cameras_map if cameras_map is not None else {}

    ctx = MagicMock()
    ctx.obj.device = chime
    ctx.obj.protect = protect
    return ctx, chime, protect


def _doorbell_camera(camera_id: str) -> MagicMock:
    camera = MagicMock(spec=Camera)
    camera.id = camera_id
    camera.feature_flags = MagicMock(is_doorbell=True)
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


def _make_viewer_ctx(liveview_ids: list[str] | None = None):
    """Build a typer context double wired to a mocked viewer + client."""
    viewer = MagicMock()
    viewer.id = "viewer-1"
    viewer.set_liveview = AsyncMock()

    protect = MagicMock(is_public_only=False)
    protect.update_viewer_public = AsyncMock()
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()
    protect.bootstrap.liveviews = dict.fromkeys(liveview_ids or [], MagicMock())

    ctx = MagicMock()
    ctx.obj.device = viewer
    ctx.obj.protect = protect
    return ctx, viewer, protect


def test_viewer_help() -> None:
    """Private viewers CLI exposes its liveview subcommand."""
    result = runner.invoke(viewer_app, ["--help"])
    assert result.exit_code == 0
    assert "liveview" in result.stdout


def test_viewer_liveview_set_uses_update_viewer_public() -> None:
    """Assigning a liveview patches via the public API, not the deprecated setter."""
    ctx, viewer, protect = _make_viewer_ctx(liveview_ids=["lv-1"])

    liveview(ctx, "lv-1")

    protect.update_viewer_public.assert_awaited_once_with("viewer-1", liveview="lv-1")
    viewer.set_liveview.assert_not_called()


def test_viewer_liveview_set_rejects_unknown_id() -> None:
    """An unknown liveview ID exits non-zero without a write."""
    ctx, _viewer, protect = _make_viewer_ctx(liveview_ids=[])

    with pytest.raises(typer.Exit) as exc:
        liveview(ctx, "lv-missing")

    assert exc.value.exit_code == 1
    protect.update_viewer_public.assert_not_awaited()


def _make_sensor_ctx():
    """Build a typer context double wired to a mocked sensor + client."""
    sensor = MagicMock()
    sensor.id = "sensor-1"
    sensor.set_name_public = AsyncMock()
    sensor.set_temperature_settings_public = AsyncMock()
    sensor.set_humidity_settings_public = AsyncMock()
    sensor.set_light_settings_public = AsyncMock()
    sensor.set_motion_settings_public = AsyncMock()
    sensor.set_glass_break_settings_public = AsyncMock()
    sensor.set_alarm_public = AsyncMock()
    sensor.set_motion_status_public = AsyncMock()
    sensor.set_motion_sensitivity_public = AsyncMock()
    sensor.set_temperature_status_public = AsyncMock()
    sensor.set_humidity_status_public = AsyncMock()
    sensor.set_light_status_public = AsyncMock()
    sensor.set_glass_break_status_public = AsyncMock()
    sensor.set_schedule_mode_public = AsyncMock()
    sensor.set_arm_profile_ids_public = AsyncMock()
    sensor.set_custom_sensitivity_when_armed_public = AsyncMock()

    protect = MagicMock(is_public_only=False)
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()

    ctx = MagicMock()
    ctx.obj.device = sensor
    ctx.obj.protect = protect
    return ctx, sensor


def test_sensor_help() -> None:
    """Sensor CLI exposes the public setter subcommands."""
    result = runner.invoke(sensor_app, ["--help"])
    assert result.exit_code == 0
    plain_output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "set-name-public" not in plain_output
    assert "set-glass-break-settings-public" in plain_output
    assert "set-schedule-mode-public" in plain_output


def test_sensor_set_temperature_settings_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_temperature_settings_public(
        ctx, is_enabled=True, low_threshold=5.0, high_threshold=30.0, margin=1.0
    )
    sensor.set_temperature_settings_public.assert_awaited_once_with(
        is_enabled=True, low_threshold=5.0, high_threshold=30.0, margin=1.0
    )


def test_sensor_set_humidity_settings_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_humidity_settings_public(
        ctx, is_enabled=True, low_threshold=10, high_threshold=80, margin=2
    )
    sensor.set_humidity_settings_public.assert_awaited_once_with(
        is_enabled=True, low_threshold=10, high_threshold=80, margin=2
    )


def test_sensor_set_light_settings_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_light_settings_public(
        ctx, is_enabled=False, low_threshold=1, high_threshold=900, margin=5
    )
    sensor.set_light_settings_public.assert_awaited_once_with(
        is_enabled=False, low_threshold=1, high_threshold=900, margin=5
    )


def test_sensor_set_motion_settings_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_motion_settings_public(
        ctx, is_enabled=True, sensitivity=70, sensitivity_when_armed=90
    )
    sensor.set_motion_settings_public.assert_awaited_once_with(
        is_enabled=True, sensitivity=70, sensitivity_when_armed=90
    )


def test_sensor_set_glass_break_settings_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_glass_break_settings_public(
        ctx, is_enabled=True, sensitivity=55, sensitivity_when_armed=65
    )
    sensor.set_glass_break_settings_public.assert_awaited_once_with(
        is_enabled=True, sensitivity=55, sensitivity_when_armed=65
    )


def test_sensor_set_glass_break_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_glass_break_public(ctx, True)
    sensor.set_glass_break_status_public.assert_awaited_once_with(True)


def test_sensor_set_schedule_mode_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_schedule_mode_public(ctx, SensorScheduleMode.WHEN_ARMED)
    sensor.set_schedule_mode_public.assert_awaited_once_with(
        SensorScheduleMode.WHEN_ARMED
    )


def test_sensor_set_arm_profiles_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_arm_profiles_public(ctx, ["p1", "p2"])
    sensor.set_arm_profile_ids_public.assert_awaited_once_with(["p1", "p2"])


def test_sensor_set_custom_sensitivity_public() -> None:
    ctx, sensor = _make_sensor_ctx()
    set_custom_sensitivity_public(ctx, True)
    sensor.set_custom_sensitivity_when_armed_public.assert_awaited_once_with(True)


def _make_device_ctx(*, device_id: str):
    """Build a typer context double wired to a mocked device + client."""
    device = MagicMock()
    device.id = device_id

    protect = MagicMock(is_public_only=False)
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()

    ctx = MagicMock()
    ctx.obj.device = device
    ctx.obj.protect = protect
    return ctx, device


def _make_camera_ctx():
    ctx, camera = _make_device_ctx(device_id="camera-1")
    camera.set_status_light_public = AsyncMock()
    camera.set_hdr_mode_public = AsyncMock()
    camera.set_video_mode_public = AsyncMock()
    camera.set_mic_volume_public = AsyncMock()
    camera.set_osd_name_public = AsyncMock()
    camera.set_osd_date_public = AsyncMock()
    camera.set_osd_logo_public = AsyncMock()
    camera.set_osd_nerd_mode_public = AsyncMock()
    camera.set_lcd_message_public = AsyncMock()
    camera.set_lcd_text = AsyncMock()
    return ctx, camera


def test_camera_set_status_light_uses_public() -> None:
    """Camera set-status-light writes through the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_status_light(ctx, True)
    camera.set_status_light_public.assert_awaited_once_with(True)
    camera.set_status_light.assert_not_called()


@pytest.mark.parametrize("mode", list(PublicHdrMode))
def test_camera_set_hdr_uses_public(mode: PublicHdrMode) -> None:
    """Camera set-hdr passes the requested mode to the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_hdr(ctx, mode)
    camera.set_hdr_mode_public.assert_awaited_once_with(mode)


def test_camera_set_hdr_rejects_unknown_mode() -> None:
    """``set-hdr`` only accepts the public API's three mode values."""
    result = runner.invoke(
        cameras_app,
        ["cam-1", "set-hdr", "always"],
        obj=MagicMock(**{"protect.is_public_only": False}),
    )
    assert result.exit_code == 2
    plain_output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "Invalid value" in plain_output


def test_camera_set_video_mode_uses_public() -> None:
    """Camera set-video-mode writes through the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_video_mode(ctx, VideoMode.HIGH_FPS)
    camera.set_video_mode_public.assert_awaited_once_with(VideoMode.HIGH_FPS)
    camera.set_video_mode.assert_not_called()


def test_camera_set_mic_volume_uses_public() -> None:
    """Camera set-mic-volume writes through the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_mic_volume(ctx, 55)
    camera.set_mic_volume_public.assert_awaited_once_with(55)
    camera.set_mic_volume.assert_not_called()


def test_camera_set_mic_volume_allows_zero() -> None:
    """``set-mic-volume 0`` (mute) passes typer's ``min=0`` validator."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_mic_volume(ctx, 0)
    camera.set_mic_volume_public.assert_awaited_once_with(0)

    result = runner.invoke(
        cameras_app,
        ["cam-1", "set-mic-volume", "0"],
        obj=MagicMock(**{"protect.is_public_only": False}),
    )
    plain_output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "Invalid value" not in plain_output


def test_camera_set_osd_name_uses_public() -> None:
    """Camera set-osd-name writes through the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_osd_name(ctx, True)
    camera.set_osd_name_public.assert_awaited_once_with(True)
    camera.set_osd_name.assert_not_called()


def test_camera_set_osd_date_uses_public() -> None:
    """Camera set-osd-date writes through the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_osd_date(ctx, False)
    camera.set_osd_date_public.assert_awaited_once_with(False)
    camera.set_osd_date.assert_not_called()


def test_camera_set_osd_logo_uses_public() -> None:
    """Camera set-osd-logo writes through the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_osd_logo(ctx, True)
    camera.set_osd_logo_public.assert_awaited_once_with(True)
    camera.set_osd_logo.assert_not_called()


def test_camera_set_osd_bitrate_uses_public_nerd_mode() -> None:
    """Camera set-osd-bitrate writes through the public nerd-mode setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_osd_bitrate(ctx, True)
    camera.set_osd_nerd_mode_public.assert_awaited_once_with(True)
    camera.set_osd_bitrate.assert_not_called()


def _invoke_set_lcd_text(*args: str) -> MagicMock:
    """Drive ``cameras cam-1 set-lcd-text`` through typer, returning the camera."""
    obj = MagicMock()
    obj.protect.is_public_only = False
    camera = obj.protect.bootstrap.cameras.get.return_value
    with patch.object(base_cli, "run"):
        result = runner.invoke(cameras_app, ["cam-1", "set-lcd-text", *args], obj=obj)
    assert result.exit_code == 0, result.output
    return camera


def test_camera_set_lcd_text_uses_public() -> None:
    """Camera set-lcd-text writes through the public setter when given a type."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_lcd_text(
        ctx, DoorbellMessageType.CUSTOM_MESSAGE, "hello", reset_at="2026-01-01T12:00:00"
    )
    text_type, text, awaited_reset_at = camera.set_lcd_message_public.await_args.args
    assert (text_type, text) == (DoorbellMessageType.CUSTOM_MESSAGE, "hello")
    # The CLI localises the naive timestamp to the host timezone first.
    assert awaited_reset_at.tzinfo is not None
    assert awaited_reset_at.replace(tzinfo=None) == datetime(2026, 1, 1, 12, 0)
    camera.set_lcd_text.assert_not_called()


def test_camera_set_lcd_text_omitted_reset_time_uses_nvr_default() -> None:
    """A bare set-lcd-text asks the console for its default reset timeout."""
    camera = _invoke_set_lcd_text("DO_NOT_DISTURB")
    assert camera.set_lcd_message_public.call_args.args == (
        DoorbellMessageType.DO_NOT_DISTURB,
        None,
        DEFAULT,
    )


def test_camera_set_lcd_text_reset_time_never_is_forever() -> None:
    """``--reset-time never`` keeps the message until something replaces it."""
    camera = _invoke_set_lcd_text("DO_NOT_DISTURB", "--reset-time", "never")
    assert camera.set_lcd_message_public.call_args.args == (
        DoorbellMessageType.DO_NOT_DISTURB,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-01", datetime(2026, 1, 1)),
        ("2026-01-01T12:00:00", datetime(2026, 1, 1, 12, 0)),
        ("2026-01-01 12:00:00", datetime(2026, 1, 1, 12, 0)),
    ],
)
def test_camera_set_lcd_text_reset_time_timestamp(
    value: str, expected: datetime
) -> None:
    """A timestamp is parsed and localised to the host timezone."""
    camera = _invoke_set_lcd_text("DO_NOT_DISTURB", "--reset-time", value)
    reset_at = camera.set_lcd_message_public.call_args.args[2]
    assert reset_at.tzinfo is not None
    assert reset_at.replace(tzinfo=None) == expected


def test_camera_set_lcd_text_rejects_unparsable_reset_time() -> None:
    """A ``--reset-time`` that is neither ``never`` nor a timestamp is rejected."""
    result = runner.invoke(
        cameras_app,
        ["cam-1", "set-lcd-text", "DO_NOT_DISTURB", "--reset-time", "tomorrow"],
        obj=MagicMock(**{"protect.is_public_only": False}),
    )
    assert result.exit_code == 2
    plain_output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "Invalid value" in plain_output


def test_camera_set_lcd_text_clear_uses_public() -> None:
    """Clearing the LCD message also writes through the public setter."""
    ctx, camera = _make_camera_ctx()
    cameras_cli.set_lcd_text(ctx, None, None, reset_at=None)
    camera.set_lcd_message_public.assert_awaited_once_with(None)
    camera.set_lcd_text.assert_not_called()


def test_camera_set_lcd_text_clear_rejects_reset_time() -> None:
    """--reset-time is not silently dropped when clearing the message."""
    ctx, camera = _make_camera_ctx()

    with pytest.raises(typer.Exit) as exc:
        cameras_cli.set_lcd_text(ctx, None, None, reset_at="2026-01-01T12:00:00")

    assert exc.value.exit_code == 1
    camera.set_lcd_message_public.assert_not_called()
    camera.set_lcd_text.assert_not_called()


def _make_light_ctx():
    ctx, light = _make_device_ctx(device_id="light-1")
    light.set_status_light_public = AsyncMock()
    light.set_led_level_public = AsyncMock()
    light.set_sensitivity_public = AsyncMock()
    light.set_duration_public = AsyncMock()
    light.set_flood_light_public = AsyncMock()
    return ctx, light


def test_light_set_status_light_uses_public() -> None:
    """Light set-status-light writes through the public setter."""
    ctx, light = _make_light_ctx()
    lights_cli.set_status_light(ctx, True)
    light.set_status_light_public.assert_awaited_once_with(True)
    light.set_status_light.assert_not_called()


def test_light_set_led_level_uses_public() -> None:
    """Light set-led-level writes through the public setter."""
    ctx, light = _make_light_ctx()
    lights_cli.set_led_level(ctx, 4)
    light.set_led_level_public.assert_awaited_once_with(4)
    light.set_led_level.assert_not_called()


def test_light_set_sensitivity_uses_public() -> None:
    """Light set-sensitivity writes through the public setter."""
    ctx, light = _make_light_ctx()
    lights_cli.set_sensitivity(ctx, 80)
    light.set_sensitivity_public.assert_awaited_once_with(80)
    light.set_sensitivity.assert_not_called()


def test_light_set_duration_uses_public() -> None:
    """Light set-duration writes through the public setter."""
    ctx, light = _make_light_ctx()
    lights_cli.set_duration(ctx, 60)
    light.set_duration_public.assert_awaited_once_with(timedelta(seconds=60))
    light.set_duration.assert_not_called()


def test_light_set_flood_light_uses_public() -> None:
    """Light set-flood-light writes through the public setter."""
    ctx, light = _make_light_ctx()
    lights_cli.set_flood_light(ctx, False)
    light.set_flood_light_public.assert_awaited_once_with(False)
    light.set_flood_light.assert_not_called()


def test_sensor_set_motion_uses_public() -> None:
    """Sensor set-motion writes through the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_motion(ctx, True)
    sensor.set_motion_status_public.assert_awaited_once_with(True)
    sensor.set_motion_status.assert_not_called()


def test_sensor_set_temperature_uses_public() -> None:
    """Sensor set-temperature writes through the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_temperature(ctx, False)
    sensor.set_temperature_status_public.assert_awaited_once_with(False)
    sensor.set_temperature_status.assert_not_called()


def test_sensor_set_humidity_uses_public() -> None:
    """Sensor set-humidity writes through the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_humidity(ctx, True)
    sensor.set_humidity_status_public.assert_awaited_once_with(True)
    sensor.set_humidity_status.assert_not_called()


def test_sensor_set_light_uses_public() -> None:
    """Sensor set-light writes through the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_light(ctx, False)
    sensor.set_light_status_public.assert_awaited_once_with(False)
    sensor.set_light_status.assert_not_called()


def test_sensor_set_motion_sensitivity_uses_public() -> None:
    """Sensor set-motion-sensitivity writes through the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_motion_sensitivity(ctx, 30)
    sensor.set_motion_sensitivity_public.assert_awaited_once_with(30)
    sensor.set_motion_sensitivity.assert_not_called()


def test_sensor_set_status_light_stays_private() -> None:
    """The sensor status LED has no public-API field, so it stays on the private setter."""
    ctx, sensor = _make_sensor_ctx()
    sensor.set_status_light = AsyncMock()
    sensors_cli.set_status_light(ctx, True)
    sensor.set_status_light.assert_awaited_once_with(True)


def test_sensor_set_alarm_uses_public() -> None:
    """Sensor set-alarm writes through the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_alarm(ctx, True)
    sensor.set_alarm_public.assert_awaited_once_with(True)
    sensor.set_alarm_status.assert_not_called()


def test_sensor_set_temperature_range_uses_public() -> None:
    """Sensor set-temperature-range writes both thresholds via the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_temperature_range(ctx, 5.0, 30.0)
    sensor.set_temperature_settings_public.assert_awaited_once_with(
        low_threshold=5.0, high_threshold=30.0
    )
    sensor.set_temperature_safe_range.assert_not_called()


def test_sensor_set_humidity_range_uses_public() -> None:
    """Sensor set-humidity-range writes both thresholds via the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_humidity_range(ctx, 10.0, 80.0)
    sensor.set_humidity_settings_public.assert_awaited_once_with(
        low_threshold=10.0, high_threshold=80.0
    )
    sensor.set_humidity_safe_range.assert_not_called()


def test_sensor_set_light_range_uses_public() -> None:
    """Sensor set-light-range writes both thresholds via the public setter."""
    ctx, sensor = _make_sensor_ctx()
    sensors_cli.set_light_range(ctx, 2.0, 900.0)
    sensor.set_light_settings_public.assert_awaited_once_with(
        low_threshold=2.0, high_threshold=900.0
    )
    sensor.set_light_safe_range.assert_not_called()


def _make_smart_detect_camera_ctx():
    """Build a camera context double with smart-detect capabilities wired up."""
    ctx, camera = _make_device_ctx(device_id="camera-1")
    camera.feature_flags.has_smart_detect = True
    camera.feature_flags.smart_detect_types = [
        SmartDetectObjectType.PERSON,
        SmartDetectObjectType.VEHICLE,
    ]
    camera.feature_flags.smart_detect_audio_types = [
        SmartDetectAudioType.SMOKE,
        SmartDetectAudioType.CMONX,
    ]
    camera.smart_detect_settings.object_types = [SmartDetectObjectType.PERSON]
    camera.smart_detect_settings.audio_types = [SmartDetectAudioType.SMOKE]
    ctx.obj.protect.update_camera_public = AsyncMock()
    return ctx, camera


def test_camera_smart_detects_uses_public() -> None:
    """Camera smart-detects patches the object types via the public API."""
    ctx, camera = _make_smart_detect_camera_ctx()
    cameras_cli.smart_detects(
        ctx, [SmartDetectObjectType.VEHICLE], add=False, remove=False
    )
    ctx.obj.protect.update_camera_public.assert_awaited_once_with(
        "camera-1", smart_detect_object_types=[SmartDetectObjectType.VEHICLE]
    )
    camera.save_device.assert_not_called()


def test_camera_smart_detects_add_uses_public() -> None:
    """``--add`` unions with the current types before the public write."""
    ctx, _camera = _make_smart_detect_camera_ctx()
    cameras_cli.smart_detects(
        ctx, [SmartDetectObjectType.VEHICLE], add=True, remove=False
    )
    ctx.obj.protect.update_camera_public.assert_awaited_once()
    _args, kwargs = ctx.obj.protect.update_camera_public.call_args
    assert set(kwargs["smart_detect_object_types"]) == {
        SmartDetectObjectType.PERSON,
        SmartDetectObjectType.VEHICLE,
    }


def test_camera_smart_detects_unsupported_type_does_not_write() -> None:
    """An unsupported detection type exits non-zero without a write."""
    ctx, _camera = _make_smart_detect_camera_ctx()
    with pytest.raises(typer.Exit) as exc:
        cameras_cli.smart_detects(
            ctx, [SmartDetectObjectType.ANIMAL], add=False, remove=False
        )
    assert exc.value.exit_code == 1
    ctx.obj.protect.update_camera_public.assert_not_awaited()


def test_camera_smart_audio_detects_uses_public() -> None:
    """Camera smart-audio-detects patches the audio types via the public API."""
    ctx, camera = _make_smart_detect_camera_ctx()
    cameras_cli.smart_audio_detects(
        ctx, [SmartDetectAudioType.CMONX], add=False, remove=False
    )
    ctx.obj.protect.update_camera_public.assert_awaited_once_with(
        "camera-1", smart_detect_audio_types=[SmartDetectAudioType.CMONX]
    )
    camera.save_device.assert_not_called()


def test_camera_smart_audio_detects_remove_uses_public() -> None:
    """``--remove`` subtracts from the current types before the public write."""
    ctx, _camera = _make_smart_detect_camera_ctx()
    cameras_cli.smart_audio_detects(
        ctx, [SmartDetectAudioType.SMOKE], add=False, remove=True
    )
    ctx.obj.protect.update_camera_public.assert_awaited_once_with(
        "camera-1", smart_detect_audio_types=[]
    )


def _make_named_device_ctx(model_class):
    """Build a context double whose device is a spec'd instance of ``model_class``."""
    device = MagicMock(spec=model_class)
    device.id = "device-1"
    device.set_name = AsyncMock()
    if hasattr(model_class, "set_name_public"):
        device.set_name_public = AsyncMock()

    protect = MagicMock(is_public_only=False)
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()

    ctx = MagicMock()
    ctx.obj.device = device
    ctx.obj.protect = protect
    return ctx, device


@pytest.mark.parametrize("model_class", [Camera, Chime, Light, Sensor, Viewer])
def test_set_name_uses_public(model_class) -> None:
    """set-name writes through the public setter for every model that has one."""
    ctx, device = _make_named_device_ctx(model_class)
    base_cli.set_name(ctx, "Kitchen")
    device.set_name_public.assert_awaited_once_with("Kitchen")
    device.set_name.assert_not_called()


def test_set_name_aiport_stays_private() -> None:
    """AiPort has no public-API endpoint of its own, so it keeps the private setter."""
    ctx, device = _make_named_device_ctx(AiPort)
    base_cli.set_name(ctx, "Kitchen")
    device.set_name.assert_awaited_once_with("Kitchen")
    device.set_name_public.assert_not_called()


def test_set_name_nvr_stays_private() -> None:
    """The NVR has no public name setter, so it keeps the private setter."""
    ctx, device = _make_named_device_ctx(NVR)
    base_cli.set_name(ctx, "Console")
    device.set_name.assert_awaited_once_with("Console")


def test_set_name_clear_stays_private() -> None:
    """Clearing a name is not expressible on the public API, so it stays private."""
    ctx, device = _make_named_device_ctx(Camera)
    base_cli.set_name(ctx, None)
    device.set_name.assert_awaited_once_with(None)
    device.set_name_public.assert_not_called()


@pytest.mark.parametrize(
    ("command", "setter"),
    [
        (sensors_cli.set_temperature_range, "set_temperature_settings_public"),
        (sensors_cli.set_humidity_range, "set_humidity_settings_public"),
        (sensors_cli.set_light_range, "set_light_settings_public"),
    ],
)
def test_sensor_set_range_rejects_inverted_bounds(command, setter) -> None:
    """An inverted safe range exits non-zero without a write."""
    ctx, sensor = _make_sensor_ctx()
    with pytest.raises(typer.Exit) as exc:
        command(ctx, 30.0, 5.0)
    assert exc.value.exit_code == 1
    getattr(sensor, setter).assert_not_awaited()


def _make_public_device_ctx(model_class, **attrs):
    """Build a context double whose device is a public-API model."""
    device = MagicMock(spec=model_class)
    device.id = "device-1"
    for name, value in attrs.items():
        setattr(device, name, value)

    protect = MagicMock(is_public_only=True)
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()

    ctx = MagicMock()
    ctx.meta = {}
    ctx.obj.device = device
    ctx.obj.protect = protect
    return ctx, device


def test_public_only_camera_setter_targets_the_public_model() -> None:
    """A camera write lands on the public model's own setter name."""
    ctx, camera = _make_public_device_ctx(PublicCamera, set_status_light=AsyncMock())
    cameras_cli.set_status_light(ctx, True)
    camera.set_status_light.assert_awaited_once_with(True)


def test_public_only_light_setter_targets_the_public_model() -> None:
    """A light write lands on the public model's own setter name."""
    ctx, light = _make_public_device_ctx(PublicLight, set_led_level=AsyncMock())
    lights_cli.set_led_level(ctx, 4)
    light.set_led_level.assert_awaited_once_with(4)


def test_public_only_sensor_setter_targets_the_public_model() -> None:
    """A sensor write lands on the public model's own setter name."""
    ctx, sensor = _make_public_device_ctx(PublicSensor, set_alarm=AsyncMock())
    sensors_cli.set_alarm(ctx, True)
    sensor.set_alarm.assert_awaited_once_with(True)


@pytest.mark.parametrize(
    "model_class", [PublicCamera, PublicChime, PublicLight, PublicSensor, PublicViewer]
)
def test_public_only_set_name(model_class) -> None:
    """set-name works for every public device model."""
    ctx, device = _make_public_device_ctx(model_class, set_name=AsyncMock())
    base_cli.set_name(ctx, "Kitchen")
    device.set_name.assert_awaited_once_with("Kitchen")


@pytest.mark.parametrize(
    "command",
    [
        lambda ctx: base_cli.set_name(ctx, None),
        lambda ctx: base_cli.set_ssh(ctx, True),
        lambda ctx: base_cli.reboot(ctx, force=True),
        lambda ctx: base_cli.adopt(ctx, None),
        base_cli.is_wired,
        lambda ctx: cameras_cli.set_recording_mode(ctx, RecordingMode.ALWAYS),
        lambda ctx: cameras_cli.set_camera_zoom(ctx, 10),
    ],
)
def test_public_only_rejects_commands_without_a_public_equivalent(command) -> None:
    """Gap commands exit 1 instead of failing on a missing private attribute."""
    ctx, _device = _make_public_device_ctx(PublicCamera)
    with pytest.raises(typer.Exit) as exc:
        command(ctx)
    assert exc.value.exit_code == 1


def test_list_ids_flags_an_unreachable_public_device() -> None:
    """``list-ids`` annotates public devices from their single state field."""
    online = MagicMock(spec=PublicCamera, id="cam-1")
    online.display_name = "Front"
    online.is_reachable = True
    offline = MagicMock(spec=PublicCamera, id="cam-2")
    offline.display_name = "Back"
    offline.is_reachable = False

    ctx = MagicMock()
    ctx.obj.device = None
    ctx.obj.devices = {"cam-1": online, "cam-2": offline}
    ctx.obj.output_format = base_cli.OutputFormatEnum.JSON

    with patch.object(base_cli, "json_output") as out:
        base_cli.list_ids(ctx)

    assert out.call_args.args[0] == [
        ("cam-1", "Front"),
        ("cam-2", "Back [Disconnected]"),
    ]


def test_device_map_uses_the_private_bootstrap_in_hybrid_mode() -> None:
    """A hybrid client keeps resolving devices from the private bootstrap."""
    protect = MagicMock(is_public_only=False)
    protect.bootstrap.cameras = {"cam-1": MagicMock()}
    ctx = MagicMock()
    ctx.obj.protect = protect

    assert base_cli.device_map(ctx, "cameras") is protect.bootstrap.cameras
    protect.update_public.assert_not_called()


@pytest.mark.parametrize("args", [["nvr"], ["events"], ["aiports"]])
def test_public_only_rejects_private_groups(args) -> None:
    """Groups with no public equivalent exit 1 rather than prompting for a password."""
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.public_only.return_value = _public_only_client()
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", *args],
        )

    assert result.exit_code == 1
    output = _ANSI_ESCAPE_RE.sub("", result.stdout + (result.stderr or ""))
    assert "public-only mode" in output


@pytest.mark.parametrize(
    "args",
    [["generate-sample-data"], ["profile-ws"], ["create-api-key", "n"]],
)
def test_public_only_rejects_private_top_level_commands(args) -> None:
    """Top-level commands that need a private session are rejected."""
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.public_only.return_value = _public_only_client()
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", *args],
        )

    assert result.exit_code == 1
    output = _ANSI_ESCAPE_RE.sub("", result.stdout + (result.stderr or ""))
    assert "public-only mode" in output


def test_run_reports_an_ssl_failure_from_a_public_request(capsys) -> None:
    """A public-API request that fails verification gets the same guidance."""
    protect = MagicMock(_verify_ssl=True, _host="192.0.2.10", _port=443)
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()
    ctx = MagicMock()
    ctx.obj.protect = protect

    err = NvrError("Error requesting data")
    err.__cause__ = ssl.SSLCertVerificationError("certificate verify failed")

    async def _fail() -> None:
        raise err

    with (
        patch("uiprotect.cli.base._get_cert_fingerprint", return_value="DE:AD"),
        pytest.raises(typer.Exit) as exc,
    ):
        base_cli.run(ctx, _fail())

    assert exc.value.exit_code == 1
    captured = capsys.readouterr()
    output = _ANSI_ESCAPE_RE.sub("", captured.out + captured.err)
    assert "SSL certificate verification failed" in output
    assert "DE:AD" in output


def test_get_meta_info_reports_a_failure_without_a_traceback() -> None:
    """A failed meta-info request exits 1 with the error, not a stack trace."""
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client = _public_only_client()
        client.get_meta_info = AsyncMock(side_effect=NvrError("boom"))
        client_cls.public_only.return_value = client
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "get-meta-info"],
        )

    assert result.exit_code == 1
    output = _ANSI_ESCAPE_RE.sub("", result.stdout + (result.stderr or ""))
    assert "boom" in output


def test_get_meta_info_prints_the_metadata() -> None:
    """The happy path still prints the meta info as JSON."""
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client = _public_only_client()
        meta = MagicMock()
        meta.model_dump_json.return_value = '{"applicationVersion": "6.0.0"}'
        client.get_meta_info = AsyncMock(return_value=meta)
        client_cls.public_only.return_value = client
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "get-meta-info"],
        )

    assert result.exit_code == 0
    assert "6.0.0" in result.stdout


def test_create_api_key_prints_the_new_key() -> None:
    """``create-api-key`` echoes the key the console minted."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch("uiprotect.cli.base._connect_and_bootstrap", new_callable=AsyncMock),
    ):
        client = _hybrid_client()
        client.create_api_key = AsyncMock(return_value="new-key")
        client_cls.return_value = client
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, "create-api-key", "n"])

    assert result.exit_code == 0
    assert "new-key" in result.stdout


def test_public_only_rejects_shell() -> None:
    """The shell hands over a client whose private bootstrap cannot be loaded."""
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch("uiprotect.cli.embed", MagicMock()),
        # ``colored`` is only bound when the shell extra is installed.
        patch("uiprotect.cli.colored", MagicMock(), create=True),
    ):
        client_cls.public_only.return_value = _public_only_client()
        result = runner.invoke(
            app,
            ["--api-key", "k", "--address", "192.0.2.10", "shell"],
        )

    assert result.exit_code == 1
    output = _ANSI_ESCAPE_RE.sub("", result.stdout + (result.stderr or ""))
    assert "public-only mode" in output


def test_public_only_viewer_liveview_reads_from_the_public_api() -> None:
    """The current liveview is resolved by id against the public liveviews."""
    ctx, viewer = _make_public_device_ctx(PublicViewer)
    viewer.liveview_id = "lv-1"
    current = MagicMock(id="lv-1")
    current.unifi_dict.return_value = {"id": "lv-1"}
    ctx.obj.protect.get_liveviews_public = AsyncMock(return_value=[current])

    with patch.object(base_cli, "json_output") as out:
        liveview(ctx, None)

    out.assert_called_once_with({"id": "lv-1"})


_DEVICE_GROUPS = [
    ("cameras", Camera, PublicCamera),
    ("chimes", Chime, PublicChime),
    ("lights", Light, PublicLight),
    ("sensors", Sensor, PublicSensor),
    ("viewers", Viewer, PublicViewer),
]
_KEY_ONLY_ARGS = ["--api-key", "k", "--address", "192.0.2.10"]


def _private_device(model_class) -> MagicMock:
    return MagicMock(
        spec=model_class,
        id="dev-1",
        display_name="Dev",
        is_adopted_by_other=False,
        is_adopting=False,
        can_adopt=False,
        is_rebooting=False,
        is_updating=False,
        is_connected=True,
    )


def _private_bootstrap_with(attr: str, device: MagicMock) -> MagicMock:
    bootstrap = MagicMock()
    setattr(bootstrap, attr, {device.id: device})
    return bootstrap


@pytest.mark.parametrize(
    ("group", "model_class"),
    [(group, private) for group, private, _public in _DEVICE_GROUPS]
    + [("aiports", AiPort)],
)
def test_hybrid_group_lists_devices_from_the_private_bootstrap(
    group, model_class
) -> None:
    """Each device group logs in and reads its devices from the private bootstrap."""
    bootstrap = _private_bootstrap_with(group, _private_device(model_class))
    with patch.object(
        ProtectApiClient, "get_bootstrap", AsyncMock(return_value=bootstrap)
    ) as get_bootstrap:
        result = runner.invoke(app, [*_BASE_AUTH_ARGS, group, "list-ids"])

    assert result.exit_code == 0, result.output
    assert "dev-1\tDev" in result.stdout
    get_bootstrap.assert_awaited_once()


@pytest.mark.parametrize(("group", "private_class", "public_class"), _DEVICE_GROUPS)
def test_key_only_group_lists_devices_from_the_public_api(
    group, private_class, public_class
) -> None:
    """Each device group resolves its devices from its own public endpoint."""
    device = MagicMock(spec=public_class, id="dev-1", display_name="Dev")
    device.is_reachable = True
    client = _public_only_client()
    setattr(client, f"get_{group}_public", AsyncMock(return_value=[device]))
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.public_only.return_value = client
        result = runner.invoke(app, [*_KEY_ONLY_ARGS, group, "list-ids"])

    assert result.exit_code == 0, result.output
    assert "dev-1\tDev" in result.stdout
    getattr(client, f"get_{group}_public").assert_awaited_once()
    client.update_public.assert_not_called()


@pytest.mark.parametrize("group", [group for group, _p, _q in _DEVICE_GROUPS])
def test_key_only_group_exits_on_a_failed_device_fetch(group) -> None:
    """A failed public fetch exits 1 with its error instead of an empty list."""
    client = _public_only_client()
    setattr(
        client,
        f"get_{group}_public",
        AsyncMock(side_effect=NvrError("Error requesting data from 192.0.2.10")),
    )
    with patch("uiprotect.cli.ProtectApiClient") as client_cls:
        client_cls.public_only.return_value = client
        result = runner.invoke(app, [*_KEY_ONLY_ARGS, group, "list-ids"])

    assert result.exit_code == 1
    assert "Error requesting data from 192.0.2.10" in result.output


def test_key_only_device_fetch_reports_an_untrusted_certificate() -> None:
    """A certificate failure on the device fetch gets the SSL guidance."""
    err = NvrError("Error requesting data")
    err.__cause__ = ssl.SSLCertVerificationError("certificate verify failed")
    client = _public_only_client()
    client._verify_ssl = True
    client._host = "192.0.2.10"
    client._port = 443
    client.get_cameras_public = AsyncMock(side_effect=err)
    with (
        patch("uiprotect.cli.ProtectApiClient") as client_cls,
        patch("uiprotect.cli.base._get_cert_fingerprint", return_value="DE:AD"),
    ):
        client_cls.public_only.return_value = client
        result = runner.invoke(app, [*_KEY_ONLY_ARGS, "cameras", "list-ids"])

    assert result.exit_code == 1
    output = _ANSI_ESCAPE_RE.sub("", result.stdout + (result.stderr or ""))
    assert "SSL certificate verification failed" in output
    assert "DE:AD" in output


def test_device_map_fetches_each_kind_once() -> None:
    """Public-only lookups fetch only the requested kind, and only once."""
    camera = MagicMock(id="cam-1")
    protect = MagicMock(is_public_only=True)
    protect.get_cameras_public = AsyncMock(return_value=[camera])
    protect.close_session = AsyncMock()
    protect.close_public_api_session = AsyncMock()
    ctx = MagicMock()
    ctx.meta = {}
    ctx.obj.protect = protect

    assert base_cli.device_map(ctx, "cameras") == {"cam-1": camera}
    assert base_cli.device_map(ctx, "cameras") == {"cam-1": camera}

    protect.get_cameras_public.assert_awaited_once()
    protect.get_lights_public.assert_not_called()
    protect.update_public.assert_not_called()


def _public_camera_payload() -> dict:
    return {
        "id": "cam-1",
        "modelKey": "camera",
        "state": "CONNECTED",
        "name": "Front",
        "mac": "AABBCCDDEEFF",
        "isMicEnabled": True,
        "osdSettings": {
            "isNameEnabled": True,
            "isDateEnabled": True,
            "isLogoEnabled": False,
            "isDebugEnabled": False,
            "overlayLocation": "topLeft",
        },
        "ledSettings": {"isEnabled": True, "welcomeLed": None, "floodLed": None},
        "lcdMessage": {},
        "micVolume": 100,
        "activePatrolSlot": None,
        "videoMode": "default",
        "hdrType": "auto",
        "featureFlags": {
            "supportFullHdSnapshot": False,
            "hasHdr": True,
            "hasMic": True,
            "hasLedStatus": True,
            "hasSpeaker": False,
            "videoModes": ["default"],
            "smartDetectTypes": ["person"],
            "smartDetectAudioTypes": [],
        },
        "smartDetectSettings": {"objectTypes": ["person"], "audioTypes": []},
        "hasPackageCamera": False,
    }


def test_key_only_end_to_end_with_real_public_models() -> None:
    """A real public-only client lists and renames a camera it parsed itself."""
    payload = _public_camera_payload()
    renamed = {**payload, "name": "Porch"}
    with (
        patch.object(
            ProtectApiClient, "api_request_list", AsyncMock(return_value=[payload])
        ),
        patch.object(
            ProtectApiClient, "api_request_obj", AsyncMock(return_value=renamed)
        ) as request_obj,
        patch.object(ProtectApiClient, "get_bootstrap") as get_bootstrap,
    ):
        listed = runner.invoke(app, [*_KEY_ONLY_ARGS, "cameras", "list-ids"])
        renamed_result = runner.invoke(
            app, [*_KEY_ONLY_ARGS, "cameras", "cam-1", "set-name", "Porch"]
        )

    assert listed.exit_code == 0, listed.output
    assert "cam-1\tFront" in listed.stdout
    assert renamed_result.exit_code == 0, renamed_result.output
    kwargs = request_obj.call_args.kwargs
    assert kwargs["url"] == "/v1/cameras/cam-1"
    assert kwargs["json"] == {"name": "Porch"}
    assert kwargs["public_api"] is True
    get_bootstrap.assert_not_called()


def test_key_only_end_to_end_gap_command_exits() -> None:
    """A real public-only client rejects a command with no public equivalent."""
    with patch.object(
        ProtectApiClient,
        "api_request_list",
        AsyncMock(return_value=[_public_camera_payload()]),
    ):
        result = runner.invoke(app, [*_KEY_ONLY_ARGS, "cameras", "cam-1", "reboot"])

    assert result.exit_code == 1
    assert "public-only mode" in _ANSI_ESCAPE_RE.sub("", result.output)


def test_no_credentials_public_command_needs_an_api_key() -> None:
    """Without a key or a login, a public command fails instead of prompting."""
    with patch.object(base_cli, "_is_interactive", return_value=True):
        result = runner.invoke(app, ["--address", "192.0.2.10", "sirens", "list"])

    assert result.exit_code == 1
    assert "API key is required" in result.output
    assert "Username" not in result.output


def test_missing_credentials_exit_without_a_terminal() -> None:
    """A private command with no login exits 1 rather than hanging on a prompt."""
    with (
        patch.object(base_cli, "_is_interactive", return_value=False),
        patch.object(ProtectApiClient, "get_bootstrap") as get_bootstrap,
    ):
        result = runner.invoke(app, ["--address", "192.0.2.10", "nvr"])

    assert result.exit_code == 1
    output = _ANSI_ESCAPE_RE.sub("", result.stdout + (result.stderr or ""))
    assert base_cli.MISSING_CREDENTIALS_ERROR in output
    assert "Username" not in output
    get_bootstrap.assert_not_called()


def test_missing_credentials_prompt_on_a_terminal() -> None:
    """With no login, a private command prompts for both halves on a terminal."""
    bootstrap = _private_bootstrap_with("cameras", _private_device(Camera))
    with (
        patch.object(base_cli, "_is_interactive", return_value=True),
        patch.object(
            ProtectApiClient,
            "get_bootstrap",
            autospec=True,
            return_value=bootstrap,
        ) as get_bootstrap,
    ):
        result = runner.invoke(
            app,
            ["--address", "192.0.2.10", "cameras", "list-ids"],
            input="u\np\n",
        )

    assert result.exit_code == 0, result.output
    client = get_bootstrap.call_args.args[0]
    assert client._username == "u"
    assert client._password == "p"  # noqa: S105
    assert not client.is_public_only


def test_username_and_key_prompt_only_for_the_password() -> None:
    """An exported username plus a key stays hybrid and asks only for the password."""
    bootstrap = _private_bootstrap_with("cameras", _private_device(Camera))
    with (
        patch.object(base_cli, "_is_interactive", return_value=True),
        patch.object(
            ProtectApiClient,
            "get_bootstrap",
            autospec=True,
            return_value=bootstrap,
        ) as get_bootstrap,
    ):
        result = runner.invoke(
            app,
            [*_KEY_ONLY_ARGS, "cameras", "list-ids"],
            input="p\n",
            env={"UFP_USERNAME": "u"},
        )

    assert result.exit_code == 0, result.output
    assert "Username" not in result.output
    assert "Password" in result.output
    client = get_bootstrap.call_args.args[0]
    assert client._username == "u"
    assert client._password == "p"  # noqa: S105
    assert client._api_key == "k"


def test_half_a_credential_does_not_prompt_for_a_public_command() -> None:
    """A public command never asks for the missing half of a login."""
    with (
        patch.object(base_cli, "_is_interactive", return_value=True),
        patch.object(
            ProtectApiClient, "api_request_list", AsyncMock(return_value=[])
        ) as request_list,
    ):
        result = runner.invoke(
            app, ["--username", "u", *_KEY_ONLY_ARGS, "sirens", "list"]
        )

    assert result.exit_code == 0, result.output
    assert "Password" not in result.output
    request_list.assert_awaited_once()


def _public_ctx(model_class, **attrs):
    ctx, device = _make_public_device_ctx(model_class, **attrs)
    ctx.obj.output_format = base_cli.OutputFormatEnum.JSON
    return ctx, device, ctx.obj.protect


@pytest.mark.parametrize(
    ("model_class", "command", "setter", "args", "kwargs"),
    [
        (PublicCamera, cameras_cli.set_status_light, "set_status_light", (True,), {}),
        (
            PublicCamera,
            cameras_cli.set_hdr,
            "set_hdr_mode",
            (PublicHdrMode.AUTO,),
            {},
        ),
        (
            PublicCamera,
            cameras_cli.set_video_mode,
            "set_video_mode",
            (VideoMode.DEFAULT,),
            {},
        ),
        (PublicCamera, cameras_cli.set_mic_volume, "set_mic_volume", (40,), {}),
        (PublicCamera, cameras_cli.set_osd_name, "set_osd_name", (True,), {}),
        (PublicCamera, cameras_cli.set_osd_date, "set_osd_date", (True,), {}),
        (PublicCamera, cameras_cli.set_osd_logo, "set_osd_logo", (True,), {}),
        (PublicCamera, cameras_cli.set_osd_bitrate, "set_osd_nerd_mode", (True,), {}),
        (PublicLight, lights_cli.set_status_light, "set_status_light", (True,), {}),
        (PublicLight, lights_cli.set_led_level, "set_led_level", (3,), {}),
        (PublicLight, lights_cli.set_sensitivity, "set_sensitivity", (50,), {}),
        (PublicLight, lights_cli.set_flood_light, "set_flood_light", (True,), {}),
        (PublicSensor, sensors_cli.set_motion, "set_motion_status", (True,), {}),
        (
            PublicSensor,
            sensors_cli.set_temperature,
            "set_temperature_status",
            (True,),
            {},
        ),
        (PublicSensor, sensors_cli.set_humidity, "set_humidity_status", (True,), {}),
        (PublicSensor, sensors_cli.set_light, "set_light_status", (True,), {}),
        (PublicSensor, sensors_cli.set_alarm, "set_alarm", (True,), {}),
        (
            PublicSensor,
            sensors_cli.set_motion_sensitivity,
            "set_motion_sensitivity",
            (30,),
            {},
        ),
        (
            PublicSensor,
            set_glass_break_public,
            "set_glass_break_status",
            (True,),
            {},
        ),
        (
            PublicSensor,
            set_schedule_mode_public,
            "set_schedule_mode",
            (SensorScheduleMode.ALWAYS,),
            {},
        ),
        (
            PublicSensor,
            set_arm_profiles_public,
            "set_arm_profile_ids",
            (["p1"],),
            {},
        ),
        (
            PublicSensor,
            set_custom_sensitivity_public,
            "set_custom_sensitivity_when_armed",
            (True,),
            {},
        ),
    ],
)
def test_key_only_setter_commands(model_class, command, setter, args, kwargs) -> None:
    """Every public-capable setter command writes through the public model."""
    ctx, device, _protect = _public_ctx(model_class, **{setter: AsyncMock()})
    command(ctx, *args, **kwargs)
    getattr(device, setter).assert_awaited_once_with(*args, **kwargs)


def test_key_only_light_set_duration() -> None:
    """set-duration converts seconds before calling the public setter."""
    ctx, light, _protect = _public_ctx(PublicLight, set_duration=AsyncMock())
    lights_cli.set_duration(ctx, 60)
    light.set_duration.assert_awaited_once_with(timedelta(seconds=60))


def test_key_only_camera_set_lcd_text() -> None:
    """set-lcd-text sets and clears the message through the public model."""
    ctx, camera, _protect = _public_ctx(PublicCamera, set_lcd_message=AsyncMock())
    cameras_cli.set_lcd_text(ctx, DoorbellMessageType.CUSTOM_MESSAGE, "Hi", "never")
    camera.set_lcd_message.assert_awaited_once_with(
        DoorbellMessageType.CUSTOM_MESSAGE, "Hi", None
    )

    camera.set_lcd_message.reset_mock()
    cameras_cli.set_lcd_text(ctx, None, None, None)
    camera.set_lcd_message.assert_awaited_once_with(None)


@pytest.mark.parametrize(
    ("command", "setter"),
    [
        (sensors_cli.set_temperature_range, "set_temperature_settings"),
        (sensors_cli.set_humidity_range, "set_humidity_settings"),
        (sensors_cli.set_light_range, "set_light_settings"),
    ],
)
def test_key_only_sensor_ranges(command, setter) -> None:
    """The safe-range commands write thresholds through the public model."""
    ctx, sensor, _protect = _public_ctx(PublicSensor, **{setter: AsyncMock()})
    command(ctx, 5.0, 30.0)
    getattr(sensor, setter).assert_awaited_once_with(
        low_threshold=5.0, high_threshold=30.0
    )


@pytest.mark.parametrize(
    ("command", "setter", "kwargs"),
    [
        (
            set_temperature_settings_public,
            "set_temperature_settings",
            {
                "is_enabled": True,
                "low_threshold": 1.0,
                "high_threshold": 2.0,
                "margin": 0.5,
            },
        ),
        (
            set_humidity_settings_public,
            "set_humidity_settings",
            {"is_enabled": True, "low_threshold": 1, "high_threshold": 2, "margin": 1},
        ),
        (
            set_light_settings_public,
            "set_light_settings",
            {"is_enabled": True, "low_threshold": 1, "high_threshold": 2, "margin": 1},
        ),
        (
            set_motion_settings_public,
            "set_motion_settings",
            {"is_enabled": True, "sensitivity": 50, "sensitivity_when_armed": 60},
        ),
        (
            set_glass_break_settings_public,
            "set_glass_break_settings",
            {"is_enabled": True, "sensitivity": 50, "sensitivity_when_armed": 60},
        ),
    ],
)
def test_key_only_sensor_settings(command, setter, kwargs) -> None:
    """The sensor settings commands write through the public model."""
    ctx, sensor, _protect = _public_ctx(PublicSensor, **{setter: AsyncMock()})
    command(ctx, **kwargs)
    getattr(sensor, setter).assert_awaited_once_with(**kwargs)


@pytest.mark.parametrize(
    ("command", "attr"),
    [
        (sensors_cli.is_tampering_detected, "is_tampering_detected"),
        (sensors_cli.is_contact_enabled, "is_contact_sensor_enabled"),
        (sensors_cli.is_motion_enabled, "is_motion_sensor_enabled"),
        (sensors_cli.is_alarm_enabled, "is_alarm_sensor_enabled"),
        (sensors_cli.is_light_enabled, "is_light_sensor_enabled"),
        (sensors_cli.is_temperature_enabled, "is_temperature_sensor_enabled"),
        (sensors_cli.is_humidity_enabled, "is_humidity_sensor_enabled"),
    ],
)
def test_key_only_sensor_reads(command, attr) -> None:
    """The sensor state reads answer from the public payload."""
    ctx, _sensor, _protect = _public_ctx(PublicSensor, **{attr: True})
    with patch.object(base_cli, "json_output") as out:
        command(ctx)
    out.assert_called_once_with(True)


@pytest.mark.parametrize(
    "command",
    [
        sensors_cli.is_alarm_detected,
        sensors_cli.remove_temperature_range,
        lambda ctx: sensors_cli.set_mount_type(ctx, MagicMock()),
        lambda ctx: sensors_cli.set_status_light(ctx, True),
        lambda ctx: sensors_cli.camera(ctx, None),
    ],
)
def test_key_only_sensor_gap_commands_exit(command) -> None:
    """Sensor commands without a public equivalent exit 1."""
    ctx, _sensor, _protect = _public_ctx(PublicSensor)
    with pytest.raises(typer.Exit) as exc:
        command(ctx)
    assert exc.value.exit_code == 1


@pytest.mark.parametrize(
    ("command", "method", "result"),
    [
        (
            lambda ctx: cameras_cli.create_rtsps_streams(ctx, ["high"]),
            "create_camera_rtsps_streams",
            MagicMock(),
        ),
        (cameras_cli.get_rtsps_streams, "get_camera_rtsps_streams", None),
        (
            lambda ctx: cameras_cli.delete_rtsps_streams(ctx, ["high"]),
            "delete_camera_rtsps_streams",
            True,
        ),
    ],
)
def test_key_only_rtsps_stream_commands(command, method, result) -> None:
    """The RTSPS stream commands call the public endpoints by camera id."""
    ctx, _camera, protect = _public_ctx(PublicCamera)
    setattr(protect, method, AsyncMock(return_value=result))
    with patch.object(base_cli, "json_output"):
        command(ctx)
    assert getattr(protect, method).await_args.args[0] == "device-1"


def test_key_only_rtsps_streams_print_urls() -> None:
    """get-rtsps-streams prints the stream URLs the public endpoint returned."""
    ctx, _camera, protect = _public_ctx(PublicCamera)
    streams = MagicMock()
    streams.get_available_stream_qualities.return_value = ["high"]
    streams.get_stream_url.return_value = "rtsps://192.0.2.10/high"
    protect.get_camera_rtsps_streams = AsyncMock(return_value=streams)
    with patch.object(base_cli, "json_output") as out:
        cameras_cli.get_rtsps_streams(ctx)
    out.assert_called_once_with({"high": "rtsps://192.0.2.10/high"})


def test_key_only_disable_mic_permanently() -> None:
    """disable-mic-permanently works on a public camera."""
    ctx, _camera, protect = _public_ctx(PublicCamera)
    protect.disable_camera_mic_permanently_public = AsyncMock()
    cameras_cli.disable_mic_permanently(ctx, yes=True)
    protect.disable_camera_mic_permanently_public.assert_awaited_once_with("device-1")


def test_key_only_chime_cameras_lists_paired_cameras() -> None:
    """Listing a public chime's cameras resolves them from the public cameras."""
    paired = MagicMock(id="cam-1")
    paired.unifi_dict.return_value = {"id": "cam-1"}
    ctx, _chime, protect = _public_ctx(PublicChime, camera_ids=["cam-1", "gone"])
    protect.get_cameras_public = AsyncMock(return_value=[paired, MagicMock(id="cam-2")])
    with patch.object(base_cli, "json_output") as out:
        chimes_cli.cameras(ctx, camera_ids=[], add=False, remove=False)
    out.assert_called_once_with([{"id": "cam-1"}])


def test_key_only_chime_cameras_sets_pairing() -> None:
    """Pairing a public chime patches its camera ids over the public API."""
    ctx, _chime, protect = _public_ctx(PublicChime, camera_ids=["cam-1"])
    protect.get_cameras_public = AsyncMock(
        return_value=[MagicMock(spec=PublicCamera, id="cam-2")]
    )
    protect.update_chime_public = AsyncMock()
    chimes_cli.cameras(ctx, camera_ids=["cam-2"], add=True, remove=False)
    sent = protect.update_chime_public.await_args
    assert sent.args == ("device-1",)
    assert set(sent.kwargs["camera_ids"]) == {"cam-1", "cam-2"}


@pytest.mark.parametrize(
    ("command", "setter", "value"),
    [
        (set_volume, "set_volume_for_camera", 55),
        (set_repeat_times, "set_repeat_times_for_camera", 3),
    ],
)
def test_key_only_chime_per_camera_settings(command, setter, value) -> None:
    """Per-camera chime settings use the public model's own setters."""
    ctx, chime, protect = _public_ctx(PublicChime, **{setter: AsyncMock()})
    protect.get_cameras_public = AsyncMock(return_value=[MagicMock(id="cam-1")])
    command(ctx, value=value, camera_id="cam-1")
    getattr(chime, setter).assert_awaited_once_with("cam-1", value)


@pytest.mark.parametrize("command", [set_volume, set_repeat_times])
def test_key_only_chime_whole_device_settings_exit(command) -> None:
    """Without --camera the chime settings need the private model and exit 1."""
    ctx, _chime, protect = _public_ctx(PublicChime)
    protect.update_chime_public = AsyncMock()
    with pytest.raises(typer.Exit) as exc:
        command(ctx, value=3, camera_id=None)
    assert exc.value.exit_code == 1
    protect.update_chime_public.assert_not_called()


@pytest.mark.parametrize("command", [chimes_cli.play, chimes_cli.play_buzzer])
def test_key_only_chime_gap_commands_exit(command) -> None:
    """Chime playback has no public equivalent and exits 1."""
    ctx, _chime, _protect = _public_ctx(PublicChime)
    with pytest.raises(typer.Exit) as exc:
        command(ctx)
    assert exc.value.exit_code == 1


def test_key_only_viewer_liveview_set_and_clear() -> None:
    """A public viewer's liveview is set by id, or cleared with ``null``."""
    ctx, _viewer, protect = _public_ctx(PublicViewer)
    protect.get_liveviews_public = AsyncMock(return_value=[MagicMock(id="lv-1")])
    protect.update_viewer_public = AsyncMock()

    liveview(ctx, "lv-1")
    protect.update_viewer_public.assert_awaited_once_with("device-1", liveview="lv-1")

    protect.update_viewer_public.reset_mock()
    liveview(ctx, "null")
    protect.update_viewer_public.assert_awaited_once_with("device-1", liveview=None)


def test_hybrid_viewer_liveview_clear() -> None:
    """``null`` clears the liveview in hybrid mode too."""
    ctx, _viewer, protect = _make_viewer_ctx(liveview_ids=[])
    liveview(ctx, "NULL")
    protect.update_viewer_public.assert_awaited_once_with("viewer-1", liveview=None)


def _public_call_names(module_path: str) -> set[str]:
    source = Path(module_path).read_text()
    return set(re.findall(r'public_call\(\s*\w+,\s*"(\w+)"', source))


@pytest.mark.parametrize(
    ("module_path", "pairs"),
    [
        ("src/uiprotect/cli/cameras.py", [(Camera, PublicCamera)]),
        ("src/uiprotect/cli/lights.py", [(Light, PublicLight)]),
        ("src/uiprotect/cli/sensors.py", [(Sensor, PublicSensor)]),
        (
            "src/uiprotect/cli/base.py",
            [
                (Camera, PublicCamera),
                (Chime, PublicChime),
                (Light, PublicLight),
                (Sensor, PublicSensor),
                (Viewer, PublicViewer),
            ],
        ),
    ],
)
def test_public_call_names_exist_on_both_models(module_path, pairs) -> None:
    """Every ``public_call`` name resolves on the public and the private model."""
    root = Path(__file__).resolve().parent.parent
    names = _public_call_names(str(root / module_path))
    assert names
    for private_class, public_class in pairs:
        for name in names:
            assert callable(getattr(public_class, name, None)), (public_class, name)
            assert callable(getattr(private_class, f"{name}_public", None)), (
                private_class,
                name,
            )
