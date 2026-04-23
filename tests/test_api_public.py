# mypy: disable-error-code="attr-defined, method-assign"
"""Tests for the Public Integration API extensions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import orjson
import pytest

from uiprotect.data import ArmProfile, PublicBootstrap, Relay, Siren
from uiprotect.data.types import ModelType
from uiprotect.exceptions import BadRequest
from uiprotect.websocket import WebsocketState

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient


SENSOR_ID = "66d025b301ebc903e80003ea"
SIREN_ID = "672094f900e26303e800062a"
RELAY_ID = "66d025b301ebc903e80003eb"
PROFILE_ID = "6878d82800155803e45928e0"


def _mock_update_public_endpoints(client: ProtectApiClient, **overrides: Any) -> None:
    """Stub every endpoint ``update_public`` calls. Overrides win over defaults."""
    defaults: dict[str, Any] = {
        "get_nvr_public": AsyncMock(return_value=Mock(id="nvr-1")),
        "get_cameras_public": AsyncMock(return_value=[]),
        "get_lights_public": AsyncMock(return_value=[]),
        "get_chimes_public": AsyncMock(return_value=[]),
        "get_sensors_public": AsyncMock(return_value=[]),
        "get_sirens_public": AsyncMock(return_value=[]),
        "get_relays_public": AsyncMock(return_value=[]),
        "get_arm_profiles_public": AsyncMock(return_value=[]),
        "get_arm_manager_settings_public": AsyncMock(return_value=Mock()),
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
    # Materialise the cache first so state tracking is observable.
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    await protect_client.set_current_arm_profile_public(PROFILE_ID)
    assert pb.current_arm_profile_id == PROFILE_ID


@pytest.mark.asyncio()
async def test_enable_disable_arm_alarm_tracks_state(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    await protect_client.enable_arm_alarm_public()
    assert pb.arm_alarm_enabled is True
    await protect_client.disable_arm_alarm_public()
    assert pb.arm_alarm_enabled is False


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
        get_arm_manager_settings_public=AsyncMock(side_effect=BadRequest("404")),
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
        get_arm_manager_settings_public=AsyncMock(side_effect=BadRequest("X")),
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
    assert relay.get_output(1) is not None
    with pytest.raises(KeyError):
        relay[99]


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
# Arm-manager settings endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_get_arm_manager_settings_populates_cache(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_obj = AsyncMock(
        return_value={"armProfileId": PROFILE_ID, "isEnabled": True}
    )
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    settings = await protect_client.get_arm_manager_settings_public()
    assert settings.arm_profile_id == PROFILE_ID
    assert settings.is_enabled is True
    assert pb.current_arm_profile_id == PROFILE_ID
    assert pb.arm_alarm_enabled is True


@pytest.mark.asyncio()
async def test_update_public_fetches_arm_manager_settings(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(protect_client)
    await protect_client.update_public()
    protect_client.get_arm_manager_settings_public.assert_awaited_once()


@pytest.mark.asyncio()
async def test_update_public_skips_arm_when_disabled(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(protect_client)
    await protect_client.update_public(include_arm_profiles=False)
    protect_client.get_arm_profiles_public.assert_not_called()
    protect_client.get_arm_manager_settings_public.assert_not_called()


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
async def test_arm_manager_settings_overwrites_both_fields(
    protect_client: ProtectApiClient,
) -> None:
    """Response is truth: both fields always overwrite the cache."""
    protect_client._public_bootstrap = PublicBootstrap()
    pb = protect_client.public_bootstrap
    pb.current_arm_profile_id = "old"
    pb.arm_alarm_enabled = True
    protect_client.api_request_obj = AsyncMock(
        return_value={"armProfileId": None, "isEnabled": None}
    )
    await protect_client.get_arm_manager_settings_public()
    assert pb.current_arm_profile_id is None
    assert pb.arm_alarm_enabled is None


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
    protect_client.get_arm_manager_settings_public = AsyncMock(return_value=Mock())
    await protect_client.update_public()
    assert peak >= 7


@pytest.mark.asyncio()
async def test_ws_reconnect_schedules_resync(
    protect_client: ProtectApiClient,
) -> None:
    """When the devices WS reconnects, update_public is scheduled if cache exists."""
    protect_client._public_bootstrap = PublicBootstrap()
    update_called = asyncio.Event()

    async def _fake_update() -> PublicBootstrap:
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

    assert old is camera  # caller can diff pre/post
    assert new is not None and new.is_motion_detected is True  # type: ignore[attr-defined]
    # Cache now holds the merged copy.
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

    async def _fake_update() -> PublicBootstrap:
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
