"""Dedicated public device models (PublicCamera/Light/Sensor/Chime) and WS routing."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from uiprotect.api import RTSPSStreams
from uiprotect.data import (
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicSensor,
)
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.types import ChannelQuality, ModelType, SensorScheduleMode
from uiprotect.exceptions import BadRequest

CAMERA_PAYLOAD: dict[str, Any] = {
    "id": "cam1",
    "modelKey": "camera",
    "state": "CONNECTED",
    "name": "Front Door",
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
        "smartDetectAudioTypes": ["alrmSmoke"],
    },
    "smartDetectSettings": {"objectTypes": ["person"], "audioTypes": ["alrmSmoke"]},
    "hasPackageCamera": False,
}

LIGHT_PAYLOAD: dict[str, Any] = {
    "id": "light1",
    "modelKey": "light",
    "state": "CONNECTED",
    "name": "Garage Light",
    "mac": "AABBCCDDEE01",
    "lightModeSettings": {"mode": "motion", "enableAt": "dark"},
    "lightDeviceSettings": {
        "isIndicatorEnabled": True,
        "pirDuration": 15000,
        "pirSensitivity": 80,
        "ledLevel": 3,
    },
    "isDark": True,
    "isLightOn": False,
    "isLightForceEnabled": False,
    "lastMotion": None,
    "isPirMotionDetected": False,
    "camera": "cam1",
}

SENSOR_PAYLOAD: dict[str, Any] = {
    "id": "sensor1",
    "modelKey": "sensor",
    "state": "CONNECTED",
    "name": "Kitchen Sensor",
    "mac": "AABBCCDDEE02",
    "mountType": "door",
    "batteryStatus": {"percentage": 90, "isLow": False},
    "stats": {
        "light": {"value": 12.0, "status": "neutral"},
        "humidity": {"value": None, "status": "unknown"},
        "temperature": {"value": 22.5, "status": "neutral"},
    },
    "lightSettings": {
        "isEnabled": True,
        "margin": 1,
        "lowThreshold": 1.0,
        "highThreshold": 100.0,
    },
    "humiditySettings": {
        "isEnabled": False,
        "margin": 1,
        "lowThreshold": None,
        "highThreshold": None,
    },
    "temperatureSettings": {
        "isEnabled": False,
        "margin": 1,
        "lowThreshold": None,
        "highThreshold": None,
    },
    "isOpened": False,
    "openStatusChangedAt": None,
    "isMotionDetected": False,
    "motionDetectedAt": None,
    "motionSettings": {
        "isEnabled": True,
        "sensitivity": 50,
        "sensitivityWhenArmed": 80,
    },
    "alarmTriggeredAt": None,
    "alarmSettings": {"isEnabled": False},
    "leakDetectedAt": None,
    "externalLeakDetectedAt": None,
    "leakSettings": {"isInternalEnabled": False, "isExternalEnabled": False},
    "tamperingDetectedAt": None,
    "wirelessConnectionState": {
        "signalState": {"signalQuality": 80, "signalStrength": -50},
        "batteryStatus": {"percentage": 90, "isLow": False},
        "bridge": "bridge1",
    },
    "scheduleMode": "when_armed",
    "glassBreakSettings": {
        "isEnabled": True,
        "sensitivity": 60,
        "sensitivityWhenArmed": 90,
    },
    "armProfileIds": ["profile1"],
    "hasCustomSensitivityWhenArmed": True,
}

CHIME_PAYLOAD: dict[str, Any] = {
    "id": "chime1",
    "modelKey": "chime",
    "state": "CONNECTED",
    "name": "Hallway Chime",
    "mac": "AABBCCDDEE03",
    "cameraIds": ["cam1", "cam2"],
    "ringSettings": [
        {
            "cameraId": "cam1",
            "repeatTimes": 2,
            "ringtoneId": "rt1",
            "volume": 75,
        }
    ],
}


@pytest.mark.parametrize(
    ("cls", "payload", "field_count"),
    [
        (PublicCamera, CAMERA_PAYLOAD, 17),
        (PublicLight, LIGHT_PAYLOAD, 13),
        (PublicSensor, SENSOR_PAYLOAD, 27),
        (PublicChime, CHIME_PAYLOAD, 7),
    ],
)
def test_public_model_field_set(
    cls: type, payload: dict[str, Any], field_count: int
) -> None:
    """Each public model exposes exactly its spec field count and parses its payload."""
    assert len(cls.model_fields) == field_count
    obj = cls.from_unifi_dict(api=Mock(), **dict(payload))
    assert obj.name == payload["name"]


@pytest.mark.parametrize(
    ("cls", "payload"),
    [
        (PublicCamera, CAMERA_PAYLOAD),
        (PublicLight, LIGHT_PAYLOAD),
        (PublicSensor, SENSOR_PAYLOAD),
        (PublicChime, CHIME_PAYLOAD),
    ],
)
def test_public_model_name_nullable(cls: type, payload: dict[str, Any]) -> None:
    """``name`` is present-but-nullable: a ``null`` wire value parses to ``None``."""
    data = dict(payload)
    data["name"] = None
    obj = cls.from_unifi_dict(api=Mock(), **data)
    assert obj.name is None


def test_public_camera_drops_private_only_fields() -> None:
    """A private-only key on the payload is not modeled and not stored."""
    assert "recording_settings" not in PublicCamera.model_fields
    obj = PublicCamera.from_unifi_dict(
        api=Mock(), **{**CAMERA_PAYLOAD, "recordingSettings": {"mode": "always"}}
    )
    assert not hasattr(obj, "recording_settings")


@pytest.mark.parametrize(
    ("has_package_camera", "expected"),
    [
        (False, [ChannelQuality.HIGH, ChannelQuality.MEDIUM, ChannelQuality.LOW]),
        (
            True,
            [
                ChannelQuality.HIGH,
                ChannelQuality.MEDIUM,
                ChannelQuality.LOW,
                ChannelQuality.PACKAGE,
            ],
        ),
    ],
)
def test_public_camera_hardware_stream_qualities(
    has_package_camera: bool, expected: list[ChannelQuality]
) -> None:
    """Hardware qualities are high/medium/low plus package only when supported."""
    obj = PublicCamera.from_unifi_dict(
        api=Mock(), **{**CAMERA_PAYLOAD, "hasPackageCamera": has_package_camera}
    )
    assert obj.hardware_stream_qualities() == expected


def test_public_sensor_sub_models_typed() -> None:
    """Sensor leaf payloads parse into the dedicated read-shape sub-models."""
    sensor = PublicSensor.from_unifi_dict(api=Mock(), **dict(SENSOR_PAYLOAD))
    assert sensor.battery_status.percentage == 90
    assert sensor.stats.temperature.value == 22.5
    assert sensor.stats.humidity.value is None
    assert sensor.leak_settings.is_internal_enabled is False
    assert sensor.schedule_mode is SensorScheduleMode.WHEN_ARMED
    assert sensor.glass_break_settings.is_enabled is True
    assert sensor.glass_break_settings.sensitivity_when_armed == 90
    assert sensor.motion_settings.sensitivity_when_armed == 80
    assert sensor.arm_profile_ids == ["profile1"]
    assert sensor.has_custom_sensitivity_when_armed is True


@pytest.mark.parametrize(
    ("model_type", "payload", "cls", "store_attr"),
    [
        (ModelType.CAMERA, CAMERA_PAYLOAD, PublicCamera, "cameras"),
        (ModelType.LIGHT, LIGHT_PAYLOAD, PublicLight, "lights"),
        (ModelType.SENSOR, SENSOR_PAYLOAD, PublicSensor, "sensors"),
        (ModelType.CHIME, CHIME_PAYLOAD, PublicChime, "chimes"),
    ],
)
def test_ws_add_update_remove_routes_to_public_model(
    model_type: ModelType,
    payload: dict[str, Any],
    cls: type,
    store_attr: str,
) -> None:
    """WS add/update/remove caches the dedicated public model, not the private one."""
    pb = PublicBootstrap()
    api = Mock()

    mt, new, _old = pb.process_devices_ws_message(
        api, {"type": "add", "item": dict(payload)}
    )
    assert mt is model_type
    assert isinstance(new, cls)
    store = getattr(pb, store_attr)
    assert isinstance(store[payload["id"]], cls)

    # update diff that omits ``name`` must preserve it.
    mt, merged, _old = pb.process_devices_ws_message(
        api,
        {
            "type": "update",
            "item": {"id": payload["id"], "modelKey": payload["modelKey"], "mac": "X"},
        },
    )
    assert isinstance(merged, cls)
    assert merged.name == payload["name"]
    assert merged.mac == "X"

    pb.process_devices_ws_message(
        api,
        {
            "type": "remove",
            "item": {"id": payload["id"], "modelKey": payload["modelKey"]},
        },
    )
    assert payload["id"] not in getattr(pb, store_attr)


def test_get_device_mac_resolves_public_devices() -> None:
    """Routing the four types via factory slots keeps them mac-resolvable."""
    pb = PublicBootstrap()
    pb.process_devices_ws_message(Mock(), {"type": "add", "item": dict(SENSOR_PAYLOAD)})
    assert pb.get_device_mac("sensor1") == "AABBCCDDEE02"


@pytest.mark.parametrize("cls", [PublicCamera, PublicLight, PublicSensor, PublicChime])
@pytest.mark.asyncio()
async def test_public_model_api_update_blocked(cls: type) -> None:
    """The generic mutation path is blocked in favor of the public helpers."""
    obj = cls.model_construct()
    with pytest.raises(BadRequest):
        await obj._api_update({})


def _seed_camera(pb: PublicBootstrap, state: str) -> None:
    pb.process_devices_ws_message(
        Mock(), {"type": "add", "item": {**CAMERA_PAYLOAD, "state": state}}
    )


def test_camera_connect_schedules_rtsps_refresh_keeping_cache() -> None:
    """A camera transitioning to CONNECTED schedules a refresh, keeping its streams."""
    pb = PublicBootstrap()
    api = Mock()
    _seed_camera(pb, "CONNECTING")
    streams = RTSPSStreams(high="rtsps://example.com/high")
    pb.cameras["cam1"].rtsps_streams = streams

    pb.process_devices_ws_message(
        api,
        {
            "type": "update",
            "item": {"id": "cam1", "modelKey": "camera", "state": "CONNECTED"},
        },
    )

    # The field is never emptied — the old URLs stay until the background
    # refresh overwrites them in place.
    assert pb.cameras["cam1"].rtsps_streams is streams
    api._schedule_rtsps_refresh.assert_called_once_with("cam1")


def test_camera_steady_connected_update_keeps_cached_rtsps_streams() -> None:
    """An update on an already-connected camera leaves the RTSPS field intact."""
    pb = PublicBootstrap()
    api = Mock()
    _seed_camera(pb, "CONNECTED")
    streams = RTSPSStreams(high="rtsps://example.com/high")
    pb.cameras["cam1"].rtsps_streams = streams

    pb.process_devices_ws_message(
        api,
        {
            "type": "update",
            "item": {"id": "cam1", "modelKey": "camera", "name": "Renamed"},
        },
    )

    assert pb.cameras["cam1"].rtsps_streams is streams
    api._schedule_rtsps_refresh.assert_not_called()


def test_camera_remove_cancels_pending_rtsps_refresh() -> None:
    """A camera-remove WS frame drops the camera and cancels any pending refresh."""
    pb = PublicBootstrap()
    api = Mock()
    _seed_camera(pb, "CONNECTED")
    pb.cameras["cam1"].rtsps_streams = RTSPSStreams(high="rtsps://example.com/high")

    pb.process_devices_ws_message(
        api,
        {"type": "remove", "item": {"id": "cam1", "modelKey": "camera"}},
    )

    # The streams ride with the removed camera object.
    assert "cam1" not in pb.cameras
    api._cancel_rtsps_refresh.assert_called_once_with("cam1")


def test_non_camera_remove_leaves_camera_rtsps_untouched() -> None:
    """A non-camera remove frame does not cancel a camera's refresh or streams."""
    pb = PublicBootstrap()
    api = Mock()
    _seed_camera(pb, "CONNECTED")
    streams = RTSPSStreams(high="rtsps://example.com/high")
    pb.cameras["cam1"].rtsps_streams = streams
    pb.process_devices_ws_message(
        api, {"type": "add", "item": {**LIGHT_PAYLOAD, "state": "CONNECTED"}}
    )

    pb.process_devices_ws_message(
        api,
        {"type": "remove", "item": {"id": "light1", "modelKey": "light"}},
    )

    assert pb.cameras["cam1"].rtsps_streams is streams
    api._cancel_rtsps_refresh.assert_not_called()


def test_non_camera_connect_leaves_camera_rtsps_untouched() -> None:
    """A non-camera device reaching CONNECTED does not schedule a camera refresh."""
    pb = PublicBootstrap()
    api = Mock()
    _seed_camera(pb, "CONNECTED")
    streams = RTSPSStreams(high="rtsps://example.com/high")
    pb.cameras["cam1"].rtsps_streams = streams
    pb.process_devices_ws_message(
        api, {"type": "add", "item": {**LIGHT_PAYLOAD, "state": "CONNECTING"}}
    )

    pb.process_devices_ws_message(
        api,
        {
            "type": "update",
            "item": {"id": "light1", "modelKey": "light", "state": "CONNECTED"},
        },
    )

    assert pb.cameras["cam1"].rtsps_streams is streams
    api._schedule_rtsps_refresh.assert_not_called()


@pytest.mark.asyncio()
async def test_public_camera_get_rtsps_streams_returns_primed_field() -> None:
    """``PublicCamera.get_rtsps_streams`` returns the primed field without a fetch."""
    streams = RTSPSStreams(high="rtsps://example.com/high")
    api = Mock()
    api.get_camera_rtsps_streams = AsyncMock()
    camera = PublicCamera.from_unifi_dict(api=api, **dict(CAMERA_PAYLOAD))
    camera.rtsps_streams = streams

    result = await camera.get_rtsps_streams()

    api.get_camera_rtsps_streams.assert_not_awaited()
    assert result is streams


@pytest.mark.asyncio()
async def test_public_camera_get_rtsps_streams_fetches_when_unprimed() -> None:
    """``PublicCamera.get_rtsps_streams`` fetches once and stores when not primed."""
    streams = RTSPSStreams(high="rtsps://example.com/high")
    api = Mock()
    api.get_camera_rtsps_streams = AsyncMock(return_value=streams)
    camera = PublicCamera.from_unifi_dict(api=api, **dict(CAMERA_PAYLOAD))

    result = await camera.get_rtsps_streams()

    api.get_camera_rtsps_streams.assert_awaited_once_with("cam1")
    assert result is streams
    assert camera.rtsps_streams is streams
