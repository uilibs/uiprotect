"""Dedicated public device models (PublicCamera/Light/Sensor/Chime) and WS routing."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from uiprotect.api import RTSPSStreams
from uiprotect.data import (
    Fob,
    LinkStation,
    ProtectDeviceIdentity,
    PublicBridge,
    PublicCamera,
    PublicChime,
    PublicDeviceModel,
    PublicLight,
    PublicNVR,
    PublicSensor,
    PublicSensorFeatureFlags,
    PublicViewer,
    Relay,
    SensorFeatureCapability,
    Siren,
    Speaker,
)
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.types import (
    ChannelQuality,
    ModelType,
    SensorScheduleMode,
    SmartDetectObjectType,
)
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
        (PublicCamera, CAMERA_PAYLOAD, 19),
        (PublicLight, LIGHT_PAYLOAD, 15),
        (PublicSensor, SENSOR_PAYLOAD, 30),
        (PublicChime, CHIME_PAYLOAD, 9),
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


@pytest.mark.parametrize(
    ("cls", "payload"),
    [
        (PublicCamera, CAMERA_PAYLOAD),
        (PublicLight, LIGHT_PAYLOAD),
        (PublicSensor, SENSOR_PAYLOAD),
        (PublicChime, CHIME_PAYLOAD),
    ],
)
def test_public_device_model_shared_base(cls: type, payload: dict[str, Any]) -> None:
    """Dedicated public devices share ``PublicDeviceModel`` and type ``mac`` / ``state``."""
    assert issubclass(cls, PublicDeviceModel)
    assert PublicDeviceModel.model_fields.keys() >= {"mac", "state"}
    obj: PublicDeviceModel = cls.from_unifi_dict(api=Mock(), **dict(payload))
    assert obj.mac == payload["mac"]
    assert obj.state.value == payload["state"]


@pytest.mark.parametrize(
    "cls",
    [Siren, Relay, Fob, Speaker, LinkStation, PublicBridge, PublicViewer],
)
def test_mac_state_devices_share_base(cls: type[PublicDeviceModel]) -> None:
    """Every mac/state-carrying public device subclasses ``PublicDeviceModel``."""
    assert issubclass(cls, PublicDeviceModel)
    assert cls.model_fields.keys() >= {"mac", "state"}


def test_reparented_viewer_is_public_device_model() -> None:
    """A constructed viewer satisfies the generic ``isinstance`` dispatch guard."""
    obj = PublicViewer.from_unifi_dict(
        api=Mock(),
        id="viewer-1",
        modelKey="viewer",
        state="CONNECTED",
        name="Viewer 1",
        mac="AABBCCDDEE01",
        liveview="lv-1",
        streamLimit=16,
    )
    assert isinstance(obj, PublicDeviceModel)
    assert obj.mac == "AABBCCDDEE01"
    assert obj.state.value == "CONNECTED"


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


def test_public_camera_unknown_smart_detect_type_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A runtime-generated smart detect type (e.g. ``linecrossing_basic``) is dropped, not fatal."""
    payload = {
        **CAMERA_PAYLOAD,
        "featureFlags": {
            **CAMERA_PAYLOAD["featureFlags"],
            "smartDetectTypes": ["person", "linecrossing_basic"],
            "smartDetectAudioTypes": ["alrmSmoke", "linecrossing_audio"],
            "videoModes": ["default", "linecrossing_video"],
        },
        "smartDetectSettings": {
            "objectTypes": ["person", "linecrossing_basic"],
            "audioTypes": ["alrmSmoke", "linecrossing_audio"],
        },
    }
    obj = PublicCamera.from_unifi_dict(api=Mock(), **payload)
    assert obj.feature_flags.smart_detect_types == [SmartDetectObjectType.PERSON]
    assert obj.smart_detect_settings.object_types == [SmartDetectObjectType.PERSON]
    assert "linecrossing_basic" in caplog.text


@pytest.mark.parametrize(
    ("object_types", "audio_types", "prop", "expected"),
    [
        (["person"], [], "is_person_detection_on", True),
        ([], [], "is_person_detection_on", False),
        (["vehicle"], [], "is_vehicle_detection_on", True),
        (["face"], [], "is_face_detection_on", True),
        (["licensePlate"], [], "is_license_plate_detection_on", True),
        (["package"], [], "is_package_detection_on", True),
        ([], [], "is_package_detection_on", False),
        (["animal"], [], "is_animal_detection_on", True),
        ([], ["alrmSmoke"], "is_smoke_detection_on", True),
        ([], [], "is_smoke_detection_on", False),
        ([], ["alrmCmonx"], "is_co_detection_on", True),
        ([], ["alrmSiren"], "is_siren_detection_on", True),
        ([], ["alrmBabyCry"], "is_baby_cry_detection_on", True),
        ([], ["alrmSpeak"], "is_speaking_detection_on", True),
        ([], ["alrmBark"], "is_bark_detection_on", True),
        ([], ["alrmBurglar"], "is_car_alarm_detection_on", True),
        ([], ["alrmCarHorn"], "is_car_horn_detection_on", True),
        ([], ["alrmGlassBreak"], "is_glass_break_detection_on", True),
        ([], ["alrmSmoke"], "is_siren_detection_on", False),
    ],
)
def test_public_camera_detection_on_properties(
    object_types: list[str],
    audio_types: list[str],
    prop: str,
    expected: bool,
) -> None:
    """``is_*_detection_on`` are membership tests over the smart-detect settings."""
    obj = PublicCamera.from_unifi_dict(
        api=Mock(),
        **{
            **CAMERA_PAYLOAD,
            "smartDetectSettings": {
                "objectTypes": object_types,
                "audioTypes": audio_types,
            },
        },
    )
    assert getattr(obj, prop) is expected


@pytest.mark.parametrize(
    ("video_mode", "expected"),
    [("default", False), ("highFps", True)],
)
def test_public_camera_is_high_fps_enabled(video_mode: str, expected: bool) -> None:
    """``is_high_fps_enabled`` tracks the ``highFps`` video mode."""
    obj = PublicCamera.from_unifi_dict(
        api=Mock(), **{**CAMERA_PAYLOAD, "videoMode": video_mode}
    )
    assert obj.is_high_fps_enabled is expected


@pytest.mark.parametrize(
    ("hdr_type", "expected"),
    [("auto", "auto"), ("on", "always"), ("off", "off")],
)
def test_public_camera_hdr_mode_display(hdr_type: str, expected: str) -> None:
    """``hdr_mode_display`` inverts the public HDR enum to the interface labels."""
    obj = PublicCamera.from_unifi_dict(
        api=Mock(), **{**CAMERA_PAYLOAD, "hdrType": hdr_type}
    )
    assert obj.hdr_mode_display == expected


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


def test_public_device_identity_optional_and_round_trips() -> None:
    """``type`` / ``guid`` map to ``device_type`` / ``device_guid`` and round-trip."""
    data = dict(SENSOR_PAYLOAD)
    data["type"] = "Example-Model"
    data["guid"] = "00000000-0000-0000-0000-000000000000"
    sensor = PublicSensor.from_unifi_dict(api=Mock(), **data)
    assert sensor.device_type == "Example-Model"
    assert sensor.device_guid == "00000000-0000-0000-0000-000000000000"
    # ``model`` (the modelKey enum) is untouched by the new fields.
    assert sensor.model is ModelType.SENSOR
    dumped = sensor.unifi_dict()
    assert dumped["type"] == "Example-Model"
    assert dumped["guid"] == "00000000-0000-0000-0000-000000000000"


def test_sensor_feature_capability_enum_matches_flag_fields() -> None:
    """``supports`` does ``getattr`` by enum value, so the names must stay in lockstep."""
    assert {c.value for c in SensorFeatureCapability} == set(
        PublicSensorFeatureFlags.model_fields
    )


def test_public_sensor_feature_flags_capabilities() -> None:
    """``featureFlags`` parses into the capability map and the presence helpers."""
    data = dict(SENSOR_PAYLOAD)
    data["featureFlags"] = {
        "temperature": {"channelCount": 1},
        "humidity": {"channelCount": 1},
        "light": {"channelCount": 1},
        "waterLeak": {"channelCount": 2},
        # A present capability that omits ``channelCount`` must not raise.
        "motion": {},
    }
    sensor = PublicSensor.from_unifi_dict(api=Mock(), **data)
    assert sensor.has_feature_flags is True
    assert sensor.feature_flags.water_leak.channel_count == 2
    assert sensor.feature_flags.motion.channel_count == 0
    assert sensor.supports(SensorFeatureCapability.TEMPERATURE) is True
    assert sensor.supports(SensorFeatureCapability.WATER_LEAK) is True
    assert sensor.supports(SensorFeatureCapability.MOTION) is True
    # An absent capability key means "not supported".
    assert sensor.supports(SensorFeatureCapability.SMOKE) is False


@pytest.mark.parametrize(
    ("internal", "external", "expected"),
    [(None, None, False), (1, None, True), (None, 1, True), (1, 1, True)],
)
def test_public_sensor_is_leak_detected_aggregates_channels(
    internal: int | None, external: int | None, expected: bool
) -> None:
    """``is_leak_detected`` is the OR of the internal and external leak channels."""
    data = dict(SENSOR_PAYLOAD)
    data["leakDetectedAt"] = internal
    data["externalLeakDetectedAt"] = external
    sensor = PublicSensor.from_unifi_dict(api=Mock(), **data)
    assert sensor.is_leak_detected is expected


@pytest.mark.parametrize(("at", "expected"), [(None, False), (123, True)])
def test_public_sensor_is_tampering_detected(at: int | None, expected: bool) -> None:
    sensor = PublicSensor.from_unifi_dict(
        api=Mock(), **{**SENSOR_PAYLOAD, "tamperingDetectedAt": at}
    )
    assert sensor.is_tampering_detected is expected


@pytest.mark.parametrize(
    ("mount_type", "temp_en", "leak_en", "contact_en"),
    [
        ("door", True, False, True),
        ("leak", False, True, False),
        ("none", True, False, False),
    ],
)
def test_public_sensor_enabled_properties_respect_mount_type(
    mount_type: str, temp_en: bool, leak_en: bool, contact_en: bool
) -> None:
    """Environmental metrics are suppressed on leak mounts; leak only on leak mounts."""
    data = dict(SENSOR_PAYLOAD)
    data["mountType"] = mount_type
    for key in (
        "temperatureSettings",
        "humiditySettings",
        "lightSettings",
        "motionSettings",
        "alarmSettings",
    ):
        data[key] = {"isEnabled": True}
    sensor = PublicSensor.from_unifi_dict(api=Mock(), **data)
    # The five environmental/alarm metrics share the same gate (enabled unless
    # leak-mounted), so they all track ``temp_en``.
    assert sensor.is_temperature_sensor_enabled is temp_en
    assert sensor.is_humidity_sensor_enabled is temp_en
    assert sensor.is_light_sensor_enabled is temp_en
    assert sensor.is_motion_sensor_enabled is temp_en
    assert sensor.is_alarm_sensor_enabled is temp_en
    assert sensor.is_leak_sensor_enabled is leak_en
    assert sensor.is_contact_sensor_enabled is contact_en


def test_public_sensor_old_shape_has_no_capabilities() -> None:
    """Older firmware omits the new fields; they default and the capability helpers degrade safely."""
    sensor = PublicSensor.from_unifi_dict(api=Mock(), **dict(SENSOR_PAYLOAD))
    assert sensor.device_type is None
    assert sensor.device_guid is None
    assert sensor.feature_flags is None
    assert sensor.has_feature_flags is False
    assert sensor.supports(SensorFeatureCapability.TEMPERATURE) is False


def test_public_nvr_device_identity_round_trips() -> None:
    """``type`` / ``guid`` map onto the NVR and round-trip; absent → ``None``."""
    nvr = PublicNVR.from_unifi_dict(
        api=Mock(),
        id="nvr1",
        modelKey="nvr",
        type="Example-Model",
        guid="00000000-0000-0000-0000-000000000000",
    )
    assert nvr.device_type == "Example-Model"
    assert nvr.device_guid == "00000000-0000-0000-0000-000000000000"
    dumped = nvr.unifi_dict()
    assert dumped["type"] == "Example-Model"
    assert dumped["guid"] == "00000000-0000-0000-0000-000000000000"

    bare = PublicNVR.from_unifi_dict(api=Mock(), id="nvr1", modelKey="nvr")
    assert bare.device_type is None
    assert bare.device_guid is None


@pytest.mark.parametrize(
    ("cls", "payload"),
    [
        (PublicCamera, CAMERA_PAYLOAD),
        (PublicLight, LIGHT_PAYLOAD),
        (PublicSensor, SENSOR_PAYLOAD),
        (PublicChime, CHIME_PAYLOAD),
    ],
)
def test_public_type_aliases_device_type(cls: type, payload: dict[str, Any]) -> None:
    """``type`` mirrors ``device_type`` (the private tree's ``type`` field)."""
    data = dict(payload)
    data["type"] = "Example-Model"
    obj = cls.from_unifi_dict(api=Mock(), **data)
    assert obj.type == "Example-Model"
    assert obj.type == obj.device_type

    bare = cls.from_unifi_dict(api=Mock(), **dict(payload))
    assert bare.type is None


@pytest.mark.parametrize(
    ("name", "device_type", "expected"),
    [
        ("Front Door", "Example-Model", "Front Door"),
        (None, "Example-Model", "Example-Model"),
        (None, None, ""),
    ],
)
def test_public_display_name_fallback(
    name: str | None, device_type: str | None, expected: str
) -> None:
    """``display_name`` falls back ``name -> type -> ""`` like the private tree."""
    nvr = PublicNVR.from_unifi_dict(
        api=Mock(), id="nvr1", modelKey="nvr", name=name, type=device_type
    )
    assert nvr.display_name == expected


@pytest.mark.asyncio
async def test_shared_identity_protocol_spans_both_trees(
    nvr_obj: Any, camera_obj: Any
) -> None:
    """One ``ProtectDeviceIdentity`` variable accepts either tree without ``cast()``."""
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    public_nvr = PublicNVR.from_unifi_dict(
        api=Mock(), id="nvr1", modelKey="nvr", name="Console", type="UNVR"
    )
    public_camera = PublicCamera.from_unifi_dict(api=Mock(), **dict(CAMERA_PAYLOAD))

    def identity_line(device: ProtectDeviceIdentity) -> str:
        return f"{device.display_name} ({device.type}) [{device.mac}] {device.id}"

    for device in (nvr_obj, camera_obj, public_nvr, public_camera):
        assert isinstance(device, ProtectDeviceIdentity)
        assert identity_line(device)

    assert public_nvr.display_name == "Console"
    assert public_nvr.type == "UNVR"


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


def test_camera_connect_schedules_rtsps_prime_when_streamless() -> None:
    """A streamless camera coming online schedules a prime, not just a refresh."""
    pb = PublicBootstrap()
    api = Mock()
    _seed_camera(pb, "DISCONNECTED")
    assert pb.cameras["cam1"].rtsps_streams is None

    pb.process_devices_ws_message(
        api,
        {
            "type": "update",
            "item": {"id": "cam1", "modelKey": "camera", "state": "CONNECTED"},
        },
    )

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
