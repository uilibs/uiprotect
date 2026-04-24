# mypy: disable-error-code="attr-defined, method-assign"
"""Tests for the Public Integration API extensions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import orjson
import pytest

from uiprotect.data import (
    ArmProfile,
    NvrArmModeStatus,
    PublicBootstrap,
    PublicNVR,
    Relay,
    RelayOutputState,
    Siren,
)
from uiprotect.data.types import EventType, ModelType
from uiprotect.exceptions import BadRequest
from uiprotect.websocket import WebsocketState

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient


SENSOR_ID = "66d025b301ebc903e80003ea"
SIREN_ID = "672094f900e26303e800062a"
RELAY_ID = "66d025b301ebc903e80003eb"
PROFILE_ID = "6878d82800155803e45928e0"
NVR_ID = "66d025b301ebc903e80003ec"

# Minimal raw payload matching the Public API NVR schema (v7.0 — no armMode).
_NVR_RAW_BASE: dict[str, Any] = {
    "id": NVR_ID,
    "modelKey": "nvr",
    "name": "Test NVR",
    "doorbellSettings": {
        "defaultMessageText": "WELCOME",
        "defaultMessageResetTimeoutMs": 60000,
        "customMessages": [],
        "customImages": [],
    },
}


def _make_public_nvr(
    client: ProtectApiClient,
    arm_mode: dict[str, Any] | None = None,
) -> PublicNVR:
    """Build a minimal :class:`PublicNVR` instance for use in tests."""
    raw = dict(_NVR_RAW_BASE)
    if arm_mode is not None:
        raw["armMode"] = arm_mode
    return PublicNVR.from_unifi_dict(**raw, api=client)


def _arm_mode_raw(
    status: str = "disabled", profile_id: str | None = None
) -> dict[str, Any]:
    return {
        "status": status,
        "armProfileId": profile_id,
        "armedAt": None,
        "willBeArmedAt": None,
        "breachDetectedAt": None,
        "breachEventCount": 0,
        "breachTriggerEventId": None,
        "breachEventId": None,
    }


def _mock_update_public_endpoints(client: ProtectApiClient, **overrides: Any) -> None:
    """Stub every endpoint ``update_public`` calls. Overrides win over defaults."""
    defaults: dict[str, Any] = {
        "get_nvr_public": AsyncMock(return_value=_make_public_nvr(client)),
        "get_cameras_public": AsyncMock(return_value=[]),
        "get_lights_public": AsyncMock(return_value=[]),
        "get_chimes_public": AsyncMock(return_value=[]),
        "get_sensors_public": AsyncMock(return_value=[]),
        "get_sirens_public": AsyncMock(return_value=[]),
        "get_relays_public": AsyncMock(return_value=[]),
        "get_arm_profiles_public": AsyncMock(return_value=[]),
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        setattr(client, name, value)


# ---------------------------------------------------------------------------
# Camera snapshot: package channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_get_public_api_camera_snapshot_package(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=b"snap")
    result = await protect_client.get_public_api_camera_snapshot("cam-1", package=True)
    assert result == b"snap"
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == "/v1/cameras/cam-1/snapshot"
    assert kwargs["params"]["channel"] == "package"


@pytest.mark.asyncio()
async def test_get_public_api_camera_snapshot_no_package(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=b"snap")
    await protect_client.get_public_api_camera_snapshot("cam-1")
    _, kwargs = protect_client.api_request_raw.call_args
    assert "channel" not in kwargs["params"]


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
@patch("uiprotect.api.Sensor.from_unifi_dict")
async def test_get_sensors_public(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.side_effect = [Mock(id=SENSOR_ID), Mock(id="other")]
    protect_client.api_request_list = AsyncMock(
        return_value=[{"id": SENSOR_ID}, {"id": "other"}]
    )
    result = await protect_client.get_sensors_public()
    assert len(result) == 2
    protect_client.api_request_list.assert_called_with(
        url="/v1/sensors", public_api=True
    )


@pytest.mark.asyncio()
@patch("uiprotect.api.Sensor.from_unifi_dict")
async def test_get_sensor_public(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.return_value = Mock(id=SENSOR_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": SENSOR_ID})
    await protect_client.get_sensor_public(SENSOR_ID)
    protect_client.api_request_obj.assert_called_with(
        url=f"/v1/sensors/{SENSOR_ID}", public_api=True
    )


@pytest.mark.asyncio()
async def test_update_sensor_public_requires_args(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest):
        await protect_client.update_sensor_public(SENSOR_ID)


@pytest.mark.asyncio()
@patch("uiprotect.api.Sensor.from_unifi_dict")
async def test_update_sensor_public_body(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.return_value = Mock(id=SENSOR_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": SENSOR_ID})
    await protect_client.update_sensor_public(
        SENSOR_ID,
        name="kitchen",
        motion_settings={"isEnabled": True, "sensitivity": 80},
    )
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["method"] == "patch"
    assert kwargs["json"] == {
        "name": "kitchen",
        "motionSettings": {"isEnabled": True, "sensitivity": 80},
    }


# ---------------------------------------------------------------------------
# Sirens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
@patch("uiprotect.api.Siren.from_unifi_dict")
async def test_get_sirens_public(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.side_effect = [Mock(id=SIREN_ID)]
    protect_client.api_request_list = AsyncMock(return_value=[{"id": SIREN_ID}])
    await protect_client.get_sirens_public()
    protect_client.api_request_list.assert_called_with(
        url="/v1/sirens", public_api=True
    )


@pytest.mark.asyncio()
async def test_play_siren_public(protect_client: ProtectApiClient) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.play_siren_public(SIREN_ID, duration=10)
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == f"/v1/sirens/{SIREN_ID}/play"
    assert kwargs["method"] == "post"
    assert kwargs["json"] == {"duration": 10}


@pytest.mark.asyncio()
async def test_play_siren_public_no_body(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.play_siren_public(SIREN_ID)
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["json"] is None


@pytest.mark.asyncio()
async def test_stop_siren_public(protect_client: ProtectApiClient) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.stop_siren_public(SIREN_ID)
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == f"/v1/sirens/{SIREN_ID}/stop"
    assert kwargs["method"] == "post"


@pytest.mark.asyncio()
async def test_test_siren_sound_public(protect_client: ProtectApiClient) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.test_siren_sound_public(SIREN_ID, volume=70)
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == f"/v1/sirens/{SIREN_ID}/test-sound"
    assert kwargs["json"] == {"volume": 70}


@pytest.mark.asyncio()
@patch("uiprotect.api.Siren.from_unifi_dict")
async def test_update_siren_public_led(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.return_value = Mock(id=SIREN_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": SIREN_ID})
    await protect_client.update_siren_public(SIREN_ID, volume=80, led_is_enabled=True)
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {"volume": 80, "ledSettings": {"isEnabled": True}}


@pytest.mark.asyncio()
async def test_update_siren_public_empty(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest):
        await protect_client.update_siren_public(SIREN_ID)


# ---------------------------------------------------------------------------
# Relays
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_activate_relay_output_toggle(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.activate_relay_output_public(RELAY_ID, 0)
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == f"/v1/relays/{RELAY_ID}/outputs/0/activate"
    assert kwargs["json"] is None


@pytest.mark.asyncio()
async def test_activate_relay_output_on_with_pulse(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.activate_relay_output_public(
        RELAY_ID, 1, state="on", pulse_duration_ms=500
    )
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["json"] == {"state": "on", "pulseDuration": 500}


@pytest.mark.asyncio()
@patch("uiprotect.api.Relay.from_unifi_dict")
async def test_update_relay_public(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.return_value = Mock(id=RELAY_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": RELAY_ID})
    await protect_client.update_relay_public(
        RELAY_ID, name="garage", led_is_enabled=False
    )
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {
        "name": "garage",
        "ledSettings": {"isEnabled": False},
    }


# ---------------------------------------------------------------------------
# Alarm webhook + arm profiles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_send_alarm_webhook(protect_client: ProtectApiClient) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.send_alarm_webhook_public("my-trigger")
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == "/v1/alarm-manager/webhook/my-trigger"
    assert kwargs["method"] == "post"


@pytest.mark.asyncio()
async def test_send_alarm_webhook_empty(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest):
        await protect_client.send_alarm_webhook_public("")


@pytest.mark.asyncio()
async def test_set_current_arm_profile_updates_cache(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    # Without an arm_mode in the cache the profile_id update is a no-op.
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    await protect_client.set_current_arm_profile_public(PROFILE_ID)
    # arm_mode is None (global alarm manager) — no crash, no state change.
    assert pb.arm_mode is None


@pytest.mark.asyncio()
async def test_enable_disable_arm_alarm_tracks_state(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    pb.nvr = _make_public_nvr(protect_client, arm_mode=_arm_mode_raw("disabled"))
    await protect_client.enable_arm_alarm_public()
    assert pb.arm_mode.status == NvrArmModeStatus.ARMING
    await protect_client.disable_arm_alarm_public()
    assert pb.arm_mode.status == NvrArmModeStatus.DISABLED


@pytest.mark.asyncio()
@patch("uiprotect.api.ArmProfile.from_unifi_dict")
async def test_get_arm_profiles_populates_cache(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.side_effect = [Mock(id=PROFILE_ID)]
    protect_client.api_request_list = AsyncMock(return_value=[{"id": PROFILE_ID}])
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    await protect_client.get_arm_profiles_public()
    assert PROFILE_ID in pb.arm_profiles


@pytest.mark.asyncio()
async def test_update_arm_profile_empty(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest):
        await protect_client.update_arm_profile_public(PROFILE_ID)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_siren_model_from_unifi_dict() -> None:
    siren = Siren.from_unifi_dict(
        id=SIREN_ID,
        modelKey="siren",
        state="CONNECTED",
        name="Front Siren",
        mac="AA:BB:CC:DD:EE:FF",
        volume=80,
        ledSettings={"isEnabled": True},
        sirenStatus={"isActive": True, "activatedAt": 1, "duration": 5000},
        connectionType="lora",
        wirelessConnectionState={
            "signalState": {"signalQuality": 85, "signalStrength": -45},
            "batteryStatus": {"percentage": 90, "isLow": False},
            "bridge": None,
        },
    )
    assert siren.id == SIREN_ID
    assert siren.model is ModelType.SIREN
    assert siren.volume == 80
    assert siren.is_active is True


def test_relay_model_from_unifi_dict() -> None:
    relay = Relay.from_unifi_dict(
        id=RELAY_ID,
        modelKey="relay",
        state="CONNECTED",
        name="Garage Relay",
        mac="AA:BB:CC:DD:EE:FF",
        ledSettings={"isEnabled": True},
        outputs=[
            {
                "id": 0,
                "name": "Garage Door",
                "type": "garageDoor",
                "delay": 0,
                "pulseDuration": 500,
                "state": "off",
                "rebootState": "off",
            }
        ],
        inputs=[],
        wirelessConnectionState={
            "signalState": {"signalQuality": 85, "signalStrength": -45},
            "batteryStatus": {"percentage": 90, "isLow": False},
            "bridge": None,
        },
    )
    assert relay.id == RELAY_ID
    assert relay.model is ModelType.RELAY
    out = relay.get_output(0)
    assert out is not None
    assert out.name == "Garage Door"
    assert out.state is RelayOutputState.OFF
    assert out.reboot_state is RelayOutputState.OFF
    assert relay.get_output(5) is None


def test_arm_profile_model_from_unifi_dict() -> None:
    profile = ArmProfile.from_unifi_dict(
        id=PROFILE_ID,
        name="Night",
        automations=["a1", "a2"],
        creator="user-1",
        schedules=[{"start": "0 22 * * *", "end": "0 6 * * *"}],
        recordEverything=True,
        activationDelay=60000,
        createdAt=1600000000000,
        updatedAt=1600000100000,
    )
    assert profile.id == PROFILE_ID
    assert profile.name == "Night"
    assert profile.record_everything is True
    assert profile.activation_delay == 60000
    assert len(profile.schedules) == 1


# ---------------------------------------------------------------------------
# PublicBootstrap WS apply
# ---------------------------------------------------------------------------


def test_public_bootstrap_applies_add_and_update(
    protect_client: ProtectApiClient,
) -> None:
    pb = PublicBootstrap()
    add_payload = {
        "type": "add",
        "item": {
            "id": SIREN_ID,
            "modelKey": "siren",
            "state": "CONNECTED",
            "name": "Siren",
            "mac": "AA",
            "volume": 50,
            "ledSettings": {"isEnabled": True},
            "sirenStatus": {"isActive": False, "activatedAt": None, "duration": None},
            "connectionType": "lora",
            "wirelessConnectionState": {
                "signalState": {"signalQuality": 80, "signalStrength": -50},
                "batteryStatus": {"percentage": 100, "isLow": False},
                "bridge": None,
            },
        },
    }
    mt, new, old = pb.process_devices_ws_message(protect_client, add_payload)
    assert mt is ModelType.SIREN
    assert new is not None and new.id == SIREN_ID
    assert old is None
    assert SIREN_ID in pb.sirens

    # Partial update — only changed fields on the wire (realistic).
    update_payload: dict[str, Any] = {
        "type": "update",
        "item": {"id": SIREN_ID, "modelKey": "siren", "volume": 10},
    }
    mt, new, old = pb.process_devices_ws_message(protect_client, update_payload)
    assert old is not None
    assert new is not None and new.volume == 10  # type: ignore[attr-defined]
    # Other fields must be preserved from the cached object.
    assert new.name == "Siren"  # type: ignore[attr-defined]

    # Partial update of a nested model (``sirenStatus.isActive``).
    status_payload: dict[str, Any] = {
        "type": "update",
        "item": {
            "id": SIREN_ID,
            "modelKey": "siren",
            "sirenStatus": {"isActive": True, "activatedAt": 1234, "duration": 30},
        },
    }
    mt, new, old = pb.process_devices_ws_message(protect_client, status_payload)
    assert new is not None and new.is_active is True  # type: ignore[attr-defined]
    assert new.siren_status.is_active is True  # type: ignore[attr-defined]

    # Update for an id that isn't in the cache → dropped.
    stranger: dict[str, Any] = {
        "type": "update",
        "item": {"id": "unknown", "modelKey": "siren", "volume": 1},
    }
    mt, new, old = pb.process_devices_ws_message(protect_client, stranger)
    assert new is None and old is None

    # remove
    remove_payload = {
        "type": "remove",
        "item": {"id": SIREN_ID, "modelKey": "siren"},
    }
    mt, new, old = pb.process_devices_ws_message(protect_client, remove_payload)
    assert new is None
    assert old is not None
    assert SIREN_ID not in pb.sirens


def test_public_bootstrap_ignores_unknown_model(
    protect_client: ProtectApiClient,
) -> None:
    pb = PublicBootstrap()
    _mt, new, old = pb.process_devices_ws_message(
        protect_client,
        {"type": "add", "item": {"id": "x", "modelKey": "nope"}},
    )
    # ModelType.from_string returns UNKNOWN for unknown values, which is not
    # in the store map, so no object is created.
    assert new is None
    assert old is None


def test_public_bootstrap_warning_state_is_per_instance() -> None:
    """Warning dedupe keys must not leak across multiple client instances."""
    first = PublicBootstrap()
    second = PublicBootstrap()

    key = ("add", "siren")
    first._warned_merge_failures.add(key)

    assert key in first._warned_merge_failures
    assert key not in second._warned_merge_failures


# ---------------------------------------------------------------------------
# update_public wires everything together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_update_public_populates_cache(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(
        protect_client,
        get_cameras_public=AsyncMock(return_value=[Mock(id="c1")]),
        get_lights_public=AsyncMock(return_value=[Mock(id="l1")]),
        get_sensors_public=AsyncMock(return_value=[Mock(id="s1")]),
        get_sirens_public=AsyncMock(return_value=[Mock(id="si1")]),
        get_relays_public=AsyncMock(return_value=[Mock(id="r1")]),
    )

    pb = await protect_client.update_public()
    assert "c1" in pb.cameras
    assert "l1" in pb.lights
    assert "s1" in pb.sensors
    assert "si1" in pb.sirens
    assert "r1" in pb.relays
    protect_client.get_arm_profiles_public.assert_awaited_once()
    assert pb.nvr is not None


@pytest.mark.asyncio()
async def test_update_public_tolerates_missing_endpoints(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(
        protect_client,
        get_sensors_public=AsyncMock(side_effect=BadRequest("404")),
        get_sirens_public=AsyncMock(side_effect=BadRequest("404")),
        get_relays_public=AsyncMock(side_effect=BadRequest("404")),
        get_arm_profiles_public=AsyncMock(side_effect=BadRequest("404")),
    )

    pb = await protect_client.update_public()
    assert pb.sensors == {}
    assert pb.sirens == {}
    assert pb.relays == {}


@pytest.mark.asyncio()
async def test_update_public_tolerates_every_endpoint_failing(
    protect_client: ProtectApiClient,
) -> None:
    """Even core endpoints (cameras/lights/chimes/nvr) are best-effort."""
    _mock_update_public_endpoints(
        protect_client,
        get_nvr_public=AsyncMock(side_effect=BadRequest("X")),
        get_cameras_public=AsyncMock(side_effect=BadRequest("X")),
        get_lights_public=AsyncMock(side_effect=BadRequest("X")),
        get_chimes_public=AsyncMock(side_effect=BadRequest("X")),
        get_sensors_public=AsyncMock(side_effect=BadRequest("X")),
        get_sirens_public=AsyncMock(side_effect=BadRequest("X")),
        get_relays_public=AsyncMock(side_effect=BadRequest("X")),
        get_arm_profiles_public=AsyncMock(side_effect=BadRequest("X")),
    )

    pb = await protect_client.update_public()
    assert pb.cameras == {}
    assert pb.lights == {}
    assert pb.chimes == {}
    assert pb.nvr is None


# ---------------------------------------------------------------------------
# Relay pulse guard & dict access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_activate_relay_output_pulse_without_on_raises(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest):
        await protect_client.activate_relay_output_public(
            RELAY_ID, 0, pulse_duration_ms=500
        )


@pytest.mark.asyncio()
async def test_activate_relay_output_pulse_with_off_raises(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest):
        await protect_client.activate_relay_output_public(
            RELAY_ID, 0, state="off", pulse_duration_ms=500
        )


def test_relay_getitem_and_get_output() -> None:
    relay = Relay.from_unifi_dict(
        id=RELAY_ID,
        modelKey="relay",
        state="CONNECTED",
        name="R",
        mac="AA",
        ledSettings={"isEnabled": True},
        outputs=[
            {
                "id": 0,
                "name": "Out A",
                "type": "generic",
                "delay": 0,
                "pulseDuration": 200,
                "state": "off",
                "rebootState": "off",
            },
            {
                "id": 1,
                "name": "Out B",
                "type": "generic",
                "delay": 10,
                "pulseDuration": 100,
                "state": "on",
                "rebootState": "off",
            },
        ],
        inputs=[],
    )
    assert relay[1].name == "Out B"
    assert relay[1].state is RelayOutputState.ON
    assert relay[0].state is RelayOutputState.OFF
    assert relay.get_output(1) is not None
    with pytest.raises(KeyError):
        relay[99]


def test_relay_output_unknown_state_does_not_raise() -> None:
    """Forward-compat: an unknown output state from newer firmware coerces to UNKNOWN."""
    relay = Relay.from_unifi_dict(
        id=RELAY_ID,
        modelKey="relay",
        state="CONNECTED",
        name="R",
        mac="AA",
        ledSettings={"isEnabled": True},
        outputs=[
            {
                "id": 0,
                "name": None,
                "type": None,
                "delay": None,
                "pulseDuration": None,
                "state": "totally_new_state_from_future_firmware",
                "rebootState": None,
            }
        ],
        inputs=[],
    )
    assert relay.outputs[0].state is RelayOutputState.UNKNOWN


# ---------------------------------------------------------------------------
# URL-quoting of trigger ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_send_alarm_webhook_quotes_id(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.send_alarm_webhook_public("my trigger/with+special")
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == ("/v1/alarm-manager/webhook/my%20trigger%2Fwith%2Bspecial")


# ---------------------------------------------------------------------------
# Arm-manager settings (from NVR armMode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_get_arm_manager_settings_returns_from_cache(
    protect_client: ProtectApiClient,
) -> None:
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    pb.nvr = _make_public_nvr(
        protect_client, arm_mode=_arm_mode_raw("armed", PROFILE_ID)
    )
    result = await protect_client.get_arm_manager_settings_public()
    assert result is pb.nvr.arm_mode
    assert result is not None
    assert result.arm_profile_id == PROFILE_ID


@pytest.mark.asyncio()
async def test_get_arm_manager_settings_fetches_nvr_when_no_cache(
    protect_client: ProtectApiClient,
) -> None:
    protect_client._public_bootstrap = None
    arm_mode = _arm_mode_raw("disabled", PROFILE_ID)
    protect_client.get_nvr_public = AsyncMock(
        return_value=_make_public_nvr(protect_client, arm_mode=arm_mode)
    )
    result = await protect_client.get_arm_manager_settings_public()
    assert result is not None
    assert result.arm_profile_id == PROFILE_ID
    protect_client.get_nvr_public.assert_called_once()


@pytest.mark.asyncio()
async def test_get_arm_manager_settings_returns_none_when_nvr_has_no_arm_mode(
    protect_client: ProtectApiClient,
) -> None:
    protect_client._public_bootstrap = None
    protect_client.get_nvr_public = AsyncMock(
        return_value=_make_public_nvr(protect_client, arm_mode=None)
    )

    result = await protect_client.get_arm_manager_settings_public()

    assert result is None
    protect_client.get_nvr_public.assert_called_once()


@pytest.mark.asyncio()
async def test_set_current_arm_profile_updates_arm_mode_profile_id(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    pb.nvr = _make_public_nvr(protect_client, arm_mode=_arm_mode_raw("disabled"))

    await protect_client.set_current_arm_profile_public(PROFILE_ID)

    assert pb.arm_mode.arm_profile_id == PROFILE_ID


# ---------------------------------------------------------------------------
# Typed settings are forwarded as plain dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
@patch("uiprotect.api.Sensor.from_unifi_dict")
async def test_update_sensor_public_all_settings(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.return_value = Mock(id=SENSOR_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": SENSOR_ID})
    await protect_client.update_sensor_public(
        SENSOR_ID,
        light_settings={"isEnabled": True, "lowThreshold": 10},
        humidity_settings={"highThreshold": 80},
        temperature_settings={"lowThreshold": 15.5},
        motion_settings={"sensitivity": 60},
        alarm_settings={"isEnabled": False},
    )
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {
        "lightSettings": {"isEnabled": True, "lowThreshold": 10},
        "humiditySettings": {"highThreshold": 80},
        "temperatureSettings": {"lowThreshold": 15.5},
        "motionSettings": {"sensitivity": 60},
        "alarmSettings": {"isEnabled": False},
    }


# ---------------------------------------------------------------------------
# Arm profile create/update forward typed schedules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
@patch("uiprotect.api.ArmProfile.from_unifi_dict")
async def test_create_arm_profile(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.return_value = Mock(id=PROFILE_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": PROFILE_ID})
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    await protect_client.create_arm_profile_public(
        name="Night",
        automations=["a"],
        schedules=[{"start": "0 22 * * *", "end": "0 6 * * *"}],
        record_everything=True,
        activation_delay=60000,
    )
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {
        "name": "Night",
        "automations": ["a"],
        "schedules": [{"start": "0 22 * * *", "end": "0 6 * * *"}],
        "recordEverything": True,
        "activationDelay": 60000,
    }
    assert PROFILE_ID in pb.arm_profiles


@pytest.mark.asyncio()
@patch("uiprotect.api.ArmProfile.from_unifi_dict")
async def test_update_arm_profile(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_ctor.return_value = Mock(id=PROFILE_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": PROFILE_ID})
    await protect_client.update_arm_profile_public(
        PROFILE_ID, name="Day", schedules=[{"start": "0 8 * * *", "end": "0 18 * * *"}]
    )
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {
        "name": "Day",
        "schedules": [{"start": "0 8 * * *", "end": "0 18 * * *"}],
    }


@pytest.mark.asyncio()
async def test_delete_arm_profile(protect_client: ProtectApiClient) -> None:
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    pb.arm_profiles[PROFILE_ID] = Mock()
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.delete_arm_profile_public(PROFILE_ID)
    _, kwargs = protect_client.api_request_raw.call_args
    assert kwargs["url"] == f"/v1/arm-profiles/{PROFILE_ID}"
    assert kwargs["method"] == "delete"
    assert PROFILE_ID not in pb.arm_profiles


# ---------------------------------------------------------------------------
# Review fixes: strict property, arm-settings consistency, WS fallback,
# concurrent update_public, resync on reconnect
# ---------------------------------------------------------------------------


def test_public_bootstrap_property_raises_before_update(
    protect_client: ProtectApiClient,
) -> None:
    assert protect_client.has_public_bootstrap is False
    with pytest.raises(BadRequest):
        _ = protect_client.public_bootstrap


@pytest.mark.asyncio()
async def test_update_public_creates_cache(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(protect_client)
    pb = await protect_client.update_public()
    assert pb is protect_client.public_bootstrap
    assert protect_client.has_public_bootstrap is True


@pytest.mark.asyncio()
async def test_arm_manager_settings_from_nvr_arm_mode(
    protect_client: ProtectApiClient,
) -> None:
    """get_nvr_public with no armMode in payload → returned PublicNVR.arm_mode is None."""
    protect_client.api_request_obj = AsyncMock(return_value=dict(_NVR_RAW_BASE))
    result = await protect_client.get_nvr_public()

    assert isinstance(result, PublicNVR)
    assert result.arm_mode is None


@pytest.mark.asyncio()
async def test_get_nvr_public_sets_arm_mode_when_present(
    protect_client: ProtectApiClient,
) -> None:
    """get_nvr_public with armMode in payload → returned PublicNVR.arm_mode is populated."""
    raw = dict(_NVR_RAW_BASE)
    raw["armMode"] = _arm_mode_raw("armed", PROFILE_ID)
    protect_client.api_request_obj = AsyncMock(return_value=raw)

    result = await protect_client.get_nvr_public()

    assert isinstance(result, PublicNVR)
    assert result.arm_mode is not None
    assert result.arm_mode.arm_profile_id == PROFILE_ID


def test_ws_handler_without_cache_emits_none_obj(
    protect_client: ProtectApiClient,
) -> None:
    """With the cache unmaterialised the WS handler no longer fabricates objects."""
    captured: list[Any] = []
    protect_client._devices_ws_subscriptions.append(captured.append)
    msg = aiohttp.WSMessage(
        aiohttp.WSMsgType.TEXT,
        orjson.dumps(
            {
                "type": "add",
                "item": {"id": SIREN_ID, "modelKey": "siren", "state": "CONNECTED"},
            }
        ).decode(),
        None,
    )
    protect_client._process_devices_ws_message(msg)
    assert len(captured) == 1
    assert captured[0].new_obj is None
    assert captured[0].changed_data["id"] == SIREN_ID


@pytest.mark.asyncio()
async def test_update_public_runs_concurrently(
    protect_client: ProtectApiClient,
) -> None:
    """All endpoint fetches are dispatched via asyncio.gather, not awaited serially."""
    active = 0
    peak = 0

    async def _slow_empty() -> list[Any]:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return []

    for name in (
        "get_nvr_public",
        "get_cameras_public",
        "get_lights_public",
        "get_chimes_public",
        "get_sensors_public",
        "get_sirens_public",
        "get_relays_public",
        "get_arm_profiles_public",
    ):
        setattr(protect_client, name, _slow_empty)
    await protect_client.update_public()
    assert peak >= 7


@pytest.mark.asyncio()
async def test_ws_reconnect_schedules_resync(
    protect_client: ProtectApiClient,
) -> None:
    """When the devices WS reconnects, update_public is scheduled if cache exists."""
    protect_client._public_bootstrap = PublicBootstrap()
    update_called = asyncio.Event()

    async def _fake_update(*, include_arm_profiles: bool = True) -> PublicBootstrap:
        update_called.set()
        return protect_client.public_bootstrap

    protect_client.update_public = _fake_update  # type: ignore[assignment]
    # Initial connect is not a reconnect and must NOT schedule a resync.
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert protect_client._public_resync_task is None
    # Drop and reconnect.
    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    await asyncio.wait_for(update_called.wait(), timeout=1.0)


def test_ws_initial_connect_does_not_resync(
    protect_client: ProtectApiClient,
) -> None:
    """First CONNECTED transition is the initial connect, not a reconnect."""
    protect_client._public_bootstrap = PublicBootstrap()
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert protect_client._public_resync_task is None


def test_ws_reconnect_skips_resync_without_cache(
    protect_client: ProtectApiClient,
) -> None:
    """Without a materialised cache, reconnect does not schedule anything."""
    assert protect_client._public_bootstrap is None
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert protect_client._public_resync_task is None


# ---------------------------------------------------------------------------
# HA-realistic roundtrip: partial WS diffs applied to full cached objects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_camera_motion_start_partial_ws_update(
    protect_client: ProtectApiClient,
) -> None:
    """
    A minimal ``isMotionDetected=true`` diff flips the cached camera.

    This is the exact shape HA's motion entity relies on.
    """
    # Seed the public cache with the private-bootstrap cameras (same model
    # class, same ids — realistic because the Public API returns Camera
    # instances identical in shape to the private one).
    pb = PublicBootstrap()
    camera = next(iter(protect_client.bootstrap.cameras.values()))
    pb.cameras[camera.id] = camera
    protect_client._public_bootstrap = pb

    assert camera.is_motion_detected is False

    _, new, old = pb.process_devices_ws_message(
        protect_client,
        {
            "type": "update",
            "item": {
                "id": camera.id,
                "modelKey": "camera",
                "isMotionDetected": True,
                "lastMotion": 1643055781132,
            },
        },
    )

    assert old is camera
    assert new is camera
    assert new is not None and new.is_motion_detected is True  # type: ignore[attr-defined]
    # Cache now holds the same object, updated in place.
    assert pb.cameras[camera.id].is_motion_detected is True


@pytest.mark.asyncio()
async def test_doorbell_ring_partial_ws_update(
    protect_client: ProtectApiClient,
) -> None:
    """Doorbell ring arrives as a ``lastRing`` partial diff; HA reads it."""
    pb = PublicBootstrap()
    camera = next(iter(protect_client.bootstrap.cameras.values()))
    pb.cameras[camera.id] = camera
    protect_client._public_bootstrap = pb

    before = camera.last_ring

    _, new, _ = pb.process_devices_ws_message(
        protect_client,
        {
            "type": "update",
            "item": {
                "id": camera.id,
                "modelKey": "camera",
                "lastRing": 1700000000000,
            },
        },
    )

    assert new is not None
    assert new.last_ring != before  # type: ignore[attr-defined]


def test_events_ws_motion_minimal_add_and_end_update(
    protect_client: ProtectApiClient,
) -> None:
    """Public API motion event: minimal ``add`` then ``end`` partial diff."""
    pb = PublicBootstrap()
    protect_client._public_bootstrap = pb

    # Minimal payload — the public integration websocket sends only
    # these fields on motion-start (no ``score`` / ``smartDetect*``).
    new_event, old_event = pb.process_events_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {
                "id": "evt-motion-1",
                "modelKey": "event",
                "type": "motion",
                "start": 1700000000000,
            },
        },
    )
    assert old_event is None
    assert new_event is not None
    assert new_event.id == "evt-motion-1"
    assert new_event.type.value == "motion"
    assert new_event.end is None
    assert new_event.score == 0  # default applied
    assert new_event.smart_detect_types == []  # default applied
    assert "evt-motion-1" in pb.events

    # Partial update closing the event — only ``end`` on the wire.
    new2, old2 = pb.process_events_ws_message(
        protect_client,
        {
            "type": "update",
            "item": {
                "id": "evt-motion-1",
                "modelKey": "event",
                "end": 1700000005000,
            },
        },
    )
    assert old2 is new_event  # merged from cache
    assert new2 is not None and new2.end is not None
    # And the cache-stored copy reflects the merge.
    assert pb.events["evt-motion-1"].end is not None


def test_events_ws_sensor_button_pressed_add(
    protect_client: ProtectApiClient,
) -> None:
    """Public API events WS accepts ``sensorButtonPressed`` payloads."""
    pb = PublicBootstrap()
    protect_client._public_bootstrap = pb

    new_event, old_event = pb.process_events_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {
                "id": "evt-sensor-button-1",
                "modelKey": "event",
                "type": "sensorButtonPressed",
                "start": 1700000000000,
                "device": SENSOR_ID,
                "metadata": {
                    "button": {
                        "text": "alarmHubButton",
                    }
                },
            },
        },
    )

    assert old_event is None
    assert new_event is not None
    assert new_event.type is EventType.SENSOR_BUTTON_PRESSED
    assert new_event.id == "evt-sensor-button-1"
    assert pb.events["evt-sensor-button-1"].type is EventType.SENSOR_BUTTON_PRESSED


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("sensorSmokeTest", EventType.SENSOR_SMOKE_TEST),
        ("sensorTamper", EventType.SENSOR_TAMPER),
        ("relayInputChanged", EventType.RELAY_INPUT_CHANGED),
        ("alarmHubMotion", EventType.ALARM_HUB_MOTION),
        ("alarmHubEntryOpened", EventType.ALARM_HUB_ENTRY_OPENED),
        ("alarmHubEntryClosed", EventType.ALARM_HUB_ENTRY_CLOSED),
        ("alarmHubRelaySwitched", EventType.ALARM_HUB_RELAY_SWITCHED),
        ("alarmHubButtonPress", EventType.ALARM_HUB_BUTTON_PRESS),
        ("alarmHubSmoke", EventType.ALARM_HUB_SMOKE),
        ("alarmHubGlassBreak", EventType.ALARM_HUB_GLASS_BREAK),
        ("alarmHubTamper", EventType.ALARM_HUB_TAMPER),
        ("alarmHubBatteryConnected", EventType.ALARM_HUB_BATTERY_CONNECTED),
        ("alarmHubBatteryLow", EventType.ALARM_HUB_BATTERY_LOW),
        ("smartDetectLoiterZone", EventType.SMART_DETECT_LOITER),
    ],
)
def test_events_ws_add_supports_additional_public_event_types(
    protect_client: ProtectApiClient,
    event_type: str,
    expected: EventType,
) -> None:
    """Public API events WS can parse additional event types from the spec."""
    pb = PublicBootstrap()
    protect_client._public_bootstrap = pb

    event_id = f"evt-{event_type}"
    new_event, old_event = pb.process_events_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {
                "id": event_id,
                "modelKey": "event",
                "type": event_type,
                "start": 1700000000000,
            },
        },
    )

    assert old_event is None
    assert new_event is not None
    assert new_event.type is expected
    assert pb.events[event_id].type is expected


def test_events_ws_add_evicts_oldest(
    protect_client: ProtectApiClient,
) -> None:
    """Event cache is bounded; oldest entry is evicted on overflow."""
    pb = PublicBootstrap(max_event_cache_size=2)
    protect_client._public_bootstrap = pb

    for i in range(3):
        pb.process_events_ws_message(
            protect_client,
            {
                "type": "add",
                "item": {
                    "id": f"evt-{i}",
                    "modelKey": "event",
                    "type": "motion",
                    "start": 1700000000000 + i,
                },
            },
        )

    assert list(pb.events) == ["evt-1", "evt-2"]


def test_public_bootstrap_rejects_negative_event_cache_size() -> None:
    with pytest.raises(ValueError, match="max_event_cache_size must be >= 0"):
        PublicBootstrap(max_event_cache_size=-1)


def test_events_ws_add_zero_cache_size_keeps_cache_empty(
    protect_client: ProtectApiClient,
) -> None:
    pb = PublicBootstrap(max_event_cache_size=0)
    protect_client._public_bootstrap = pb

    pb.process_events_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {
                "id": "evt-0",
                "modelKey": "event",
                "type": "motion",
                "start": 1700000000000,
            },
        },
    )

    assert pb.events == {}


def test_nvr_ws_partial_update_merges_in_place(
    protect_client: ProtectApiClient,
) -> None:
    """``modelKey: nvr`` WS messages update :attr:`PublicBootstrap.nvr`."""
    pb = PublicBootstrap()
    pb.nvr = protect_client.bootstrap.nvr  # seed with a valid NVR object
    protect_client._public_bootstrap = pb

    before_version = pb.nvr.version

    mt, new, old = pb.process_devices_ws_message(
        protect_client,
        {
            "type": "update",
            "item": {
                "id": pb.nvr.id,
                "modelKey": "nvr",
                "isAway": True,
            },
        },
    )

    assert mt is ModelType.NVR
    assert old is not None and new is not None
    assert pb.nvr.is_away is True
    # Unchanged fields preserved.
    assert pb.nvr.version == before_version


@pytest.mark.asyncio()
async def test_reconnect_resync_is_debounced(
    protect_client: ProtectApiClient,
) -> None:
    """Rapid reconnects collapse into a single ``update_public`` call."""
    protect_client._public_bootstrap = PublicBootstrap()
    call_count = 0

    async def _fake_update(*, include_arm_profiles: bool = True) -> PublicBootstrap:
        nonlocal call_count
        call_count += 1
        return protect_client.public_bootstrap

    protect_client.update_public = _fake_update  # type: ignore[assignment]
    # Initial connect — no resync.
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    # First real reconnect fires.
    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    # Let the task run.
    await asyncio.sleep(0)
    if protect_client._public_resync_task is not None:
        await protect_client._public_resync_task
    # Immediate second reconnect — debounced away.
    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    await asyncio.sleep(0)
    assert call_count == 1


@pytest.mark.asyncio()
async def test_reconnect_queues_follow_up_resync_while_running(
    protect_client: ProtectApiClient,
) -> None:
    """Reconnect during active resync queues exactly one follow-up refresh."""
    protect_client._public_bootstrap = PublicBootstrap()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    call_count = 0

    async def _fake_update(*, include_arm_profiles: bool = True) -> PublicBootstrap:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            first_started.set()
            await release_first.wait()
        return protect_client.public_bootstrap

    protect_client.update_public = _fake_update  # type: ignore[assignment]

    # Initial connect — no resync.
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    # First reconnect starts first resync run.
    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    await asyncio.wait_for(first_started.wait(), timeout=1.0)

    # Another reconnect during the active task should queue one follow-up.
    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert protect_client._public_resync_pending is True

    # Complete first run; queued second run should happen once.
    release_first.set()
    if protect_client._public_resync_task is not None:
        await protect_client._public_resync_task
    await asyncio.sleep(0)
    if protect_client._public_resync_task is not None:
        await protect_client._public_resync_task

    assert call_count == 2
    assert protect_client._public_resync_pending is False


@pytest.mark.asyncio()
async def test_subscribed_models_filters_devices_ws(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """``subscribed_models`` is respected by the public devices WS handler."""
    from uiprotect.data.websocket import WSSubscriptionMessage  # noqa: PLC0415

    protect_client_no_debug._subscribed_models = {ModelType.CAMERA}
    got: list[WSSubscriptionMessage] = []
    unsub = protect_client_no_debug.subscribe_devices_websocket(got.append)
    try:
        # A ``light`` message must be filtered out entirely.
        msg = aiohttp.WSMessage(
            aiohttp.WSMsgType.TEXT,
            orjson.dumps(
                {
                    "type": "update",
                    "item": {"id": "x", "modelKey": "light", "isLightOn": True},
                }
            ).decode(),
            None,
        )
        protect_client_no_debug._process_devices_ws_message(msg)
        assert got == []
    finally:
        unsub()


# ---------------------------------------------------------------------------
# Device action helpers (public_devices.py)
# ---------------------------------------------------------------------------


def _build_siren(protect_client: ProtectApiClient, siren_id: str = SIREN_ID) -> Siren:
    pb = PublicBootstrap()
    protect_client._public_bootstrap = pb
    pb.process_devices_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {
                "id": siren_id,
                "modelKey": "siren",
                "state": "CONNECTED",
                "name": "Siren",
                "mac": "AA",
                "volume": 50,
                "ledSettings": {"isEnabled": True},
                "sirenStatus": {
                    "isActive": False,
                    "activatedAt": None,
                    "duration": None,
                },
                "connectionType": "lora",
                "wirelessConnectionState": {
                    "signalState": {"signalQuality": 80, "signalStrength": -50},
                    "batteryStatus": {"percentage": 100, "isLow": False},
                    "bridge": None,
                },
            },
        },
    )
    return pb.sirens[siren_id]


def _build_relay(protect_client: ProtectApiClient, relay_id: str = RELAY_ID) -> Relay:
    pb = protect_client._public_bootstrap or PublicBootstrap()
    protect_client._public_bootstrap = pb
    pb.process_devices_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {
                "id": relay_id,
                "modelKey": "relay",
                "state": "CONNECTED",
                "name": "Relay",
                "mac": "BB",
                "ledSettings": {"isEnabled": True},
                "outputs": [
                    {
                        "id": 0,
                        "name": "Out0",
                        "type": "relay",
                        "delay": 0,
                        "pulseDuration": 500,
                        "state": "off",
                        "rebootState": "off",
                    }
                ],
                "inputs": [],
            },
        },
    )
    return pb.relays[relay_id]


@pytest.mark.asyncio()
async def test_siren_device_action_helpers(
    protect_client: ProtectApiClient,
) -> None:
    siren = _build_siren(protect_client)
    protect_client.play_siren_public = AsyncMock()
    protect_client.stop_siren_public = AsyncMock()
    protect_client.test_siren_sound_public = AsyncMock()
    protect_client.update_siren_public = AsyncMock(return_value=siren)

    await siren.play(duration=5)
    protect_client.play_siren_public.assert_awaited_once_with(SIREN_ID, duration=5)

    await siren.stop()
    protect_client.stop_siren_public.assert_awaited_once_with(SIREN_ID)

    await siren.test_sound(volume=70)
    protect_client.test_siren_sound_public.assert_awaited_once_with(SIREN_ID, volume=70)

    assert await siren.set_name("New") is siren
    protect_client.update_siren_public.assert_awaited_with(SIREN_ID, name="New")
    assert await siren.set_volume(33) is siren
    protect_client.update_siren_public.assert_awaited_with(SIREN_ID, volume=33)
    assert await siren.set_status_light(False) is siren
    protect_client.update_siren_public.assert_awaited_with(
        SIREN_ID, led_is_enabled=False
    )


@pytest.mark.asyncio()
async def test_relay_device_action_helpers(
    protect_client: ProtectApiClient,
) -> None:
    relay = _build_relay(protect_client)
    protect_client.activate_relay_output_public = AsyncMock()
    protect_client.update_relay_public = AsyncMock(return_value=relay)

    await relay.activate_output(0, state="on", pulse_duration_ms=200)
    protect_client.activate_relay_output_public.assert_awaited_once_with(
        RELAY_ID, 0, state="on", pulse_duration_ms=200
    )

    assert await relay.set_name("R1") is relay
    protect_client.update_relay_public.assert_awaited_with(RELAY_ID, name="R1")
    assert await relay.set_status_light(True) is relay
    protect_client.update_relay_public.assert_awaited_with(
        RELAY_ID, led_is_enabled=True
    )


# ---------------------------------------------------------------------------
# PublicBootstrap edge cases
# ---------------------------------------------------------------------------


def test_public_bootstrap_get_and_unknown_model(
    protect_client: ProtectApiClient,
) -> None:
    """``PublicBootstrap.get`` returns cached obj for known type, ``None`` otherwise."""
    siren = _build_siren(protect_client)
    pb = protect_client.public_bootstrap
    assert pb.get(ModelType.SIREN, SIREN_ID) is siren
    assert pb.get(ModelType.SIREN, "missing") is None
    # ModelType.UNKNOWN (or any type not in _DEVICE_STORES) → None.
    assert pb.get(ModelType.UNKNOWN, SIREN_ID) is None


def test_apply_fetch_result_removes_stale_entries(
    protect_client: ProtectApiClient,
) -> None:
    siren = _build_siren(protect_client)
    pb = protect_client.public_bootstrap
    # Pretend the HTTP fetch returned an empty list → the cached siren is stale.
    pb.apply_fetch_result("sirens", [])
    assert SIREN_ID not in pb.sirens
    # Reinsert via fetch.
    pb.apply_fetch_result("sirens", [siren])
    assert pb.sirens[SIREN_ID] is siren


def test_process_devices_ws_message_invalid_envelope(
    protect_client: ProtectApiClient,
) -> None:
    """Missing ``type`` / ``modelKey`` / ``id`` short-circuits to ``(None, None, None)``."""
    pb = PublicBootstrap()
    # Missing type.
    assert pb.process_devices_ws_message(
        protect_client, {"item": {"id": "x", "modelKey": "siren"}}
    ) == (None, None, None)
    # Missing modelKey.
    assert pb.process_devices_ws_message(
        protect_client, {"type": "add", "item": {"id": "x"}}
    ) == (None, None, None)
    # Missing id.
    assert pb.process_devices_ws_message(
        protect_client, {"type": "add", "item": {"modelKey": "siren"}}
    ) == (None, None, None)
    # Completely missing item.
    assert pb.process_devices_ws_message(protect_client, {"type": "add"}) == (
        None,
        None,
        None,
    )


def test_process_events_ws_message_invalid_or_non_event(
    protect_client: ProtectApiClient,
) -> None:
    pb = PublicBootstrap()
    # Invalid envelope.
    assert pb.process_events_ws_message(protect_client, {}) == (None, None)
    # Non-event modelKey routed to the events handler.
    assert pb.process_events_ws_message(
        protect_client,
        {"type": "add", "item": {"id": "x", "modelKey": "siren"}},
    ) == (None, None)


def test_apply_action_add_creation_failure(
    protect_client: ProtectApiClient,
) -> None:
    """``create_from_unifi_dict`` raising → cache untouched, ``_warn_once`` fires."""
    pb = PublicBootstrap()
    protect_client._public_bootstrap = pb
    # A ``siren`` payload missing required fields triggers a validation error.
    mt, new, old = pb.process_devices_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {"id": "bad-siren", "modelKey": "siren"},
        },
    )
    assert mt is ModelType.SIREN
    assert new is None and old is None
    assert "bad-siren" not in pb.sirens


def test_nvr_ws_remove_clears_slot(
    protect_client: ProtectApiClient,
) -> None:
    pb = PublicBootstrap()
    protect_client._public_bootstrap = pb
    # First an NVR update to populate (reuse existing merge-in-place logic).
    # Simplest: set the slot directly, then issue a remove envelope.
    pb.nvr = Mock(id="nvr-1")
    mt, new, old = pb.process_devices_ws_message(
        protect_client,
        {"type": "remove", "item": {"id": "nvr-1", "modelKey": "nvr"}},
    )
    assert mt is ModelType.NVR
    assert new is None and old is not None
    assert pb.nvr is None


def test_events_ws_remove_clears_cache(
    protect_client: ProtectApiClient,
) -> None:
    pb = PublicBootstrap()
    protect_client._public_bootstrap = pb
    pb.process_events_ws_message(
        protect_client,
        {
            "type": "add",
            "item": {
                "id": "evt-rm",
                "modelKey": "event",
                "type": "motion",
                "start": 1700000000000,
            },
        },
    )
    new, old = pb.process_events_ws_message(
        protect_client,
        {"type": "remove", "item": {"id": "evt-rm", "modelKey": "event"}},
    )
    assert new is None
    assert old is not None
    assert "evt-rm" not in pb.events


def test_apply_action_unknown_action_falls_through(
    protect_client: ProtectApiClient,
) -> None:
    """An unrecognized action returns ``(None, old)`` without touching the cache."""
    siren = _build_siren(protect_client)
    pb = protect_client.public_bootstrap
    mt, new, old = pb.process_devices_ws_message(
        protect_client,
        {"type": "weird", "item": {"id": SIREN_ID, "modelKey": "siren"}},
    )
    assert mt is ModelType.SIREN
    assert new is None
    assert old is siren
    assert pb.sirens[SIREN_ID] is siren


def test_merge_empty_and_no_op_payloads(
    protect_client: ProtectApiClient,
) -> None:
    siren = _build_siren(protect_client)
    pb = protect_client.public_bootstrap
    # Empty payload (only identity fields) → merge returns original.
    _, new, old = pb.process_devices_ws_message(
        protect_client,
        {"type": "update", "item": {"id": SIREN_ID, "modelKey": "siren"}},
    )
    assert new is siren
    assert old is siren
    # Payload with a camelCase key that ``unifi_dict_to_dict`` drops (unknown)
    # → cleaned is empty → returns original.
    _, new, old = pb.process_devices_ws_message(
        protect_client,
        {
            "type": "update",
            "item": {
                "id": SIREN_ID,
                "modelKey": "siren",
                "totallyUnknownField": 123,
            },
        },
    )
    assert new is siren


def test_merge_exception_and_warn_once(
    protect_client: ProtectApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A merge that raises triggers WARNING once, then DEBUG."""
    siren = _build_siren(protect_client)
    pb = protect_client.public_bootstrap
    # Reset the per-instance WARNING tracker so we can reliably see the
    # first-occurrence path.
    pb._warned_merge_failures.clear()

    def _boom(self: Any, cleaned: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(type(siren), "update_from_dict", _boom)

    update = {
        "type": "update",
        "item": {"id": SIREN_ID, "modelKey": "siren", "volume": 10},
    }
    # First call → WARNING path in _warn_once.
    _, new, old = pb.process_devices_ws_message(protect_client, update)
    assert new is None
    assert old is siren  # cache still contains the old value.
    assert pb.sirens[SIREN_ID] is siren
    # Second call → DEBUG path (already warned for this key).
    _, new2, _ = pb.process_devices_ws_message(protect_client, update)
    assert new2 is None


def test_parse_ws_envelope_none_item() -> None:
    """Direct test of ``_parse_ws_envelope`` for the ``data['item'] is None`` path."""
    from uiprotect.data.public_bootstrap import _parse_ws_envelope  # noqa: PLC0415

    assert _parse_ws_envelope({"type": "add", "item": None}) == (None, {}, None)
    assert _parse_ws_envelope({}) == (None, {}, None)


# ---------------------------------------------------------------------------
# Additional api.py Public API coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
@patch("uiprotect.api.Siren.from_unifi_dict")
async def test_get_siren_public(
    mock_ctor: Mock, protect_client: ProtectApiClient
) -> None:
    mock_ctor.return_value = Mock(id=SIREN_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": SIREN_ID})
    result = await protect_client.get_siren_public(SIREN_ID)
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["url"] == f"/v1/sirens/{SIREN_ID}"
    assert result.id == SIREN_ID


@pytest.mark.asyncio()
@patch("uiprotect.api.Siren.from_unifi_dict")
async def test_update_siren_public_name_only(
    mock_ctor: Mock, protect_client: ProtectApiClient
) -> None:
    mock_ctor.return_value = Mock(id=SIREN_ID)
    protect_client.api_request_obj = AsyncMock(return_value={"id": SIREN_ID})
    await protect_client.update_siren_public(SIREN_ID, name="Front")
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {"name": "Front"}


@pytest.mark.asyncio()
@patch("uiprotect.api.Relay.from_unifi_dict")
async def test_get_relays_and_relay_public(
    mock_ctor: Mock, protect_client: ProtectApiClient
) -> None:
    mock_ctor.side_effect = [Mock(id=RELAY_ID), Mock(id=RELAY_ID)]
    protect_client.api_request_list = AsyncMock(return_value=[{"id": RELAY_ID}])
    protect_client.api_request_obj = AsyncMock(return_value={"id": RELAY_ID})

    relays = await protect_client.get_relays_public()
    assert len(relays) == 1
    assert relays[0].id == RELAY_ID
    _, kwargs = protect_client.api_request_list.call_args
    assert kwargs["url"] == "/v1/relays"

    relay = await protect_client.get_relay_public(RELAY_ID)
    assert relay.id == RELAY_ID
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["url"] == f"/v1/relays/{RELAY_ID}"


@pytest.mark.asyncio()
async def test_update_relay_public_empty(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest):
        await protect_client.update_relay_public(RELAY_ID)


@pytest.mark.asyncio()
@patch("uiprotect.api.ArmProfile.from_unifi_dict")
async def test_update_arm_profile_all_params_updates_cache(
    mock_ctor: Mock, protect_client: ProtectApiClient
) -> None:
    """Exercises ``automations`` / ``recordEverything`` / ``activationDelay`` + cache upsert."""
    profile = Mock(id=PROFILE_ID)
    mock_ctor.return_value = profile
    protect_client.api_request_obj = AsyncMock(return_value={"id": PROFILE_ID})
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap

    await protect_client.update_arm_profile_public(
        PROFILE_ID,
        automations=["a1"],
        record_everything=True,
        activation_delay=30,
    )
    _, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {
        "automations": ["a1"],
        "recordEverything": True,
        "activationDelay": 30,
    }
    assert pb.arm_profiles[PROFILE_ID] is profile


def test_process_devices_ws_message_uses_cache_when_materialised(
    protect_client: ProtectApiClient,
) -> None:
    """When ``_public_bootstrap`` exists, ``new_obj`` comes from the cache."""
    captured: list[Any] = []
    protect_client._devices_ws_subscriptions.append(captured.append)
    _build_siren(protect_client)  # populates the cache with SIREN_ID
    msg = aiohttp.WSMessage(
        aiohttp.WSMsgType.TEXT,
        orjson.dumps(
            {
                "type": "update",
                "item": {"id": SIREN_ID, "modelKey": "siren", "volume": 11},
            }
        ).decode(),
        None,
    )
    protect_client._process_devices_ws_message(msg)
    assert len(captured) == 1
    assert captured[0].new_obj is not None
    assert captured[0].new_obj.volume == 11
    assert captured[0].old_obj is not None


@pytest.mark.asyncio()
async def test_process_events_ws_message_uses_cache_when_materialised(
    protect_client: ProtectApiClient,
) -> None:
    """Events WS pipes cached ``new_obj`` / ``old_obj`` from ``PublicBootstrap``."""
    protect_client._public_bootstrap = PublicBootstrap()
    captured: list[Any] = []
    protect_client._events_ws_subscriptions.append(captured.append)
    msg = aiohttp.WSMessage(
        aiohttp.WSMsgType.TEXT,
        orjson.dumps(
            {
                "type": "add",
                "item": {
                    "id": "evt-cache",
                    "modelKey": "event",
                    "type": "motion",
                    "start": 1700000000000,
                },
            }
        ).decode(),
        None,
    )
    protect_client._process_events_ws_message(msg)
    assert len(captured) == 1
    assert captured[0].new_obj is not None
    assert captured[0].new_obj.id == "evt-cache"


@pytest.mark.asyncio()
async def test_resync_public_bootstrap_logs_on_failure(
    protect_client: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``_resync_public_bootstrap`` swallows and logs any ``update_public`` exception."""
    protect_client.update_public = AsyncMock(side_effect=RuntimeError("offline"))  # type: ignore[method-assign]
    with caplog.at_level("ERROR"):
        await protect_client._resync_public_bootstrap()
    assert "Failed to resync public bootstrap after reconnect" in caplog.text


@pytest.mark.asyncio()
async def test_update_public_reraises_unexpected_exception(
    protect_client: ProtectApiClient,
) -> None:
    """Unexpected (non-``BadRequest``/``NvrError``) endpoint failures propagate."""
    _mock_update_public_endpoints(
        protect_client,
        get_cameras_public=AsyncMock(side_effect=RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        await protect_client.update_public()


def test_process_events_ws_message_invalid_envelope_early_return(
    protect_client: ProtectApiClient,
) -> None:
    """Events WS short-circuits on missing ``type`` / ``modelKey``."""
    captured: list[Any] = []
    protect_client._events_ws_subscriptions.append(captured.append)
    for payload in (
        {"item": {"id": "x", "modelKey": "event"}},  # missing type
        {"type": "add", "item": {"id": "x"}},  # missing modelKey
        {"type": "add", "item": {"id": "x", "modelKey": "totally_unknown"}},
    ):
        msg = aiohttp.WSMessage(
            aiohttp.WSMsgType.TEXT,
            orjson.dumps(payload).decode(),
            None,
        )
        protect_client._process_events_ws_message(msg)

    # Covers the ``_subscribed_models`` filter branch (early return).
    protect_client._subscribed_models = {ModelType.CAMERA}
    try:
        msg = aiohttp.WSMessage(
            aiohttp.WSMsgType.TEXT,
            orjson.dumps(
                {"type": "add", "item": {"id": "x", "modelKey": "event"}}
            ).decode(),
            None,
        )
        protect_client._process_events_ws_message(msg)
    finally:
        protect_client._subscribed_models = set()

    assert captured == []


@pytest.mark.asyncio()
@patch("uiprotect.api.ArmProfile.from_unifi_dict")
async def test_get_arm_profiles_preserves_dict_identity(
    mock_ctor: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Refreshing arm profiles must update the dict in place, not replace it."""
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    original_dict = pb.arm_profiles
    # Seed with a stale entry that must be evicted after refresh.
    pb.arm_profiles["stale"] = Mock(id="stale")

    mock_ctor.side_effect = [Mock(id=PROFILE_ID)]
    protect_client.api_request_list = AsyncMock(return_value=[{"id": PROFILE_ID}])

    await protect_client.get_arm_profiles_public()

    assert pb.arm_profiles is original_dict  # identity preserved
    assert "stale" not in pb.arm_profiles
    assert PROFILE_ID in pb.arm_profiles


@pytest.mark.asyncio()
async def test_update_public_records_include_arm_profiles(
    protect_client: ProtectApiClient,
) -> None:
    """``update_public`` persists the ``include_arm_profiles`` flag for resyncs."""
    _mock_update_public_endpoints(protect_client)
    await protect_client.update_public(include_arm_profiles=False)
    assert protect_client._last_update_public_include_arm_profiles is False
    # Arm-profile endpoint must NOT be called when opted out.
    protect_client.get_arm_profiles_public.assert_not_called()

    await protect_client.update_public(include_arm_profiles=True)
    assert protect_client._last_update_public_include_arm_profiles is True


@pytest.mark.asyncio()
async def test_resync_public_bootstrap_honours_last_include_arm_profiles(
    protect_client: ProtectApiClient,
) -> None:
    """Reconnect resync must use the last caller-specified ``include_arm_profiles``."""
    protect_client._last_update_public_include_arm_profiles = False
    protect_client.update_public = AsyncMock(return_value=PublicBootstrap())  # type: ignore[method-assign]
    await protect_client._resync_public_bootstrap()
    protect_client.update_public.assert_awaited_once_with(include_arm_profiles=False)


@pytest.mark.asyncio()
async def test_siren_api_update_rejects_generic_mutations(
    protect_client: ProtectApiClient,
) -> None:
    """Generic mutation path must fail loudly for Public API sirens."""
    siren = _build_siren(protect_client)
    with pytest.raises(BadRequest, match="Siren mutations"):
        await siren._api_update({"name": "new"})


@pytest.mark.asyncio()
async def test_relay_api_update_rejects_generic_mutations(
    protect_client: ProtectApiClient,
) -> None:
    """Generic mutation path must fail loudly for Public API relays."""
    relay = _build_relay(protect_client)
    with pytest.raises(BadRequest, match="Relay mutations"):
        await relay._api_update({"name": "new"})
