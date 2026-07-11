"""Convenience setters on the public device model tree (public-only writes)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.public_devices import (
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicSensor,
    RTSPSStreams,
    Siren,
)
from uiprotect.data.types import (
    DoorbellMessageType,
    LightModeEnableType,
    LightModeType,
    OsdOverlayLocation,
    PublicHdrMode,
    SensorScheduleMode,
    SmartDetectAudioType,
    SmartDetectObjectType,
    VideoMode,
)
from uiprotect.exceptions import BadRequest


def _camera(api: Any) -> PublicCamera:
    return PublicCamera.from_unifi_dict(
        api=api,
        id="cam-1",
        modelKey="camera",
        state="CONNECTED",
        name="Cam",
        mac="AABBCCDDEEFF",
        isMicEnabled=True,
        osdSettings={
            "isNameEnabled": False,
            "isDateEnabled": False,
            "isLogoEnabled": False,
            "isDebugEnabled": False,
            "overlayLocation": "topLeft",
        },
        ledSettings={"isEnabled": False, "welcomeLed": None, "floodLed": None},
        lcdMessage={},
        micVolume=50,
        activePatrolSlot=None,
        videoMode="default",
        hdrType="auto",
        featureFlags={
            "supportFullHdSnapshot": True,
            "hasHdr": True,
            "hasMic": True,
            "hasLedStatus": True,
            "hasSpeaker": False,
            "videoModes": ["default", "highFps"],
            "smartDetectTypes": ["person", "vehicle", "animal", "package", "face"],
            "smartDetectAudioTypes": ["alrmSmoke", "alrmCmonx", "alrmSiren"],
        },
        smartDetectSettings={"objectTypes": ["person"], "audioTypes": []},
        hasPackageCamera=False,
    )


def _light(api: Any) -> PublicLight:
    return PublicLight.from_unifi_dict(
        api=api,
        id="light-1",
        modelKey="light",
        state="CONNECTED",
        mac="AABBCCDDEE01",
        name="Light",
        lightModeSettings={"mode": "motion", "enableAt": "fulltime"},
        lightDeviceSettings={
            "isIndicatorEnabled": True,
            "pirDuration": 30000,
            "pirSensitivity": 50,
            "ledLevel": 3,
        },
        isDark=True,
        isLightOn=False,
        isLightForceEnabled=False,
        isPirMotionDetected=False,
        camera=None,
    )


def _sensor(api: Any) -> PublicSensor:
    return PublicSensor.from_unifi_dict(
        api=api,
        id="sensor-1",
        modelKey="sensor",
        state="CONNECTED",
        mac="AABBCCDDEE02",
        name="Sensor",
        mountType="door",
        batteryStatus={},
        stats={},
        lightSettings={},
        humiditySettings={},
        temperatureSettings={},
        isMotionDetected=False,
        motionSettings={"isEnabled": True, "sensitivity": 40},
        alarmSettings={},
        leakSettings={},
        wirelessConnectionState={},
    )


def _chime(api: Any) -> PublicChime:
    return PublicChime.from_unifi_dict(
        api=api,
        id="chime-1",
        modelKey="chime",
        state="CONNECTED",
        mac="AABBCCDDEE03",
        name="Chime",
        cameraIds=["cam-a", "cam-b"],
        ringSettings=[
            {"cameraId": "cam-a", "volume": 50, "repeatTimes": 1},
            {"cameraId": "cam-b", "volume": 60, "repeatTimes": 2},
        ],
    )


# ---------------------------------------------------------------------------
# Write-through helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_from_response_merges_and_skips_rtsps() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.rtsps_streams = RTSPSStreams(high="rtsps://sentinel")
    fresh = _camera(api)
    fresh.mic_volume = 42
    fresh.rtsps_streams = None  # a real PATCH response never carries this

    cam._apply_from_response(fresh)

    assert cam.mic_volume == 42
    assert cam.rtsps_streams is not None
    assert cam.rtsps_streams.get_stream_url("high") == "rtsps://sentinel"


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_camera_set_mic_volume_writes_through() -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(update={"mic_volume": 55})
    )

    result = await cam.set_mic_volume(55)

    assert result is cam
    assert cam.mic_volume == 55
    api.update_camera_public.assert_awaited_once_with(cam.id, mic_volume=55)


@pytest.mark.asyncio
async def test_public_camera_set_mic_volume_no_mic() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.has_mic = False
    with pytest.raises(BadRequest, match="does not have mic"):
        await cam.set_mic_volume(55)


@pytest.mark.asyncio
async def test_public_camera_setters_preserve_rtsps() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.rtsps_streams = RTSPSStreams(high="rtsps://keepme")
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(update={"led_settings": cam.led_settings})
    )

    await cam.set_status_light(True)

    assert cam.rtsps_streams is not None
    assert cam.rtsps_streams.get_stream_url("high") == "rtsps://keepme"


@pytest.mark.asyncio
async def test_public_camera_led_setters() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.led_settings.welcome_led = False
    cam.led_settings.flood_led = False
    api.update_camera_public = AsyncMock(return_value=cam)

    assert await cam.set_status_light(True) is cam
    assert await cam.set_welcome_led(True) is cam
    assert await cam.set_flood_led(True) is cam


@pytest.mark.parametrize(
    "method",
    ["set_status_light", "set_welcome_led", "set_flood_led"],
)
@pytest.mark.asyncio
async def test_public_camera_led_no_status(method: str) -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.has_led_status = False
    with pytest.raises(BadRequest, match="does not have status light"):
        await getattr(cam, method)(True)


@pytest.mark.asyncio
async def test_public_camera_welcome_led_absent() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.led_settings.welcome_led = None
    with pytest.raises(BadRequest, match="welcome LED"):
        await cam.set_welcome_led(True)


@pytest.mark.asyncio
async def test_public_camera_flood_led_absent() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.led_settings.flood_led = None
    with pytest.raises(BadRequest, match="flood LED"):
        await cam.set_flood_led(True)


@pytest.mark.asyncio
async def test_public_camera_set_hdr_mode() -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(update={"hdr_type": PublicHdrMode.ON})
    )

    result = await cam.set_hdr_mode(PublicHdrMode.ON)

    assert result is cam
    assert cam.hdr_type is PublicHdrMode.ON


@pytest.mark.asyncio
async def test_public_camera_set_hdr_mode_no_hdr() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.has_hdr = False
    with pytest.raises(BadRequest, match="does not have HDR"):
        await cam.set_hdr_mode(PublicHdrMode.ON)


@pytest.mark.asyncio
async def test_public_camera_set_video_mode() -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(update={"video_mode": VideoMode.HIGH_FPS})
    )

    result = await cam.set_video_mode(VideoMode.HIGH_FPS)

    assert result is cam
    assert cam.video_mode is VideoMode.HIGH_FPS


@pytest.mark.asyncio
async def test_public_camera_set_video_mode_unsupported() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.video_modes = [VideoMode.DEFAULT]
    with pytest.raises(BadRequest):
        await cam.set_video_mode(VideoMode.HIGH_FPS)


@pytest.mark.asyncio
async def test_public_camera_lcd_message_custom() -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(return_value=cam)

    await cam.set_lcd_message(
        DoorbellMessageType.CUSTOM_MESSAGE,
        "hello",
        reset_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    sent = api.update_camera_public.call_args.kwargs["lcd_message"]
    assert sent["type"] is DoorbellMessageType.CUSTOM_MESSAGE
    assert sent["text"] == "hello"
    assert isinstance(sent["resetAt"], int)


@pytest.mark.asyncio
async def test_public_camera_lcd_message_forever() -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(return_value=cam)

    await cam.set_lcd_message(DoorbellMessageType.DO_NOT_DISTURB, reset_at=None)

    sent = api.update_camera_public.call_args.kwargs["lcd_message"]
    assert sent["resetAt"] is None


@pytest.mark.asyncio
async def test_public_camera_lcd_message_requires_text() -> None:
    api = MagicMock()
    cam = _camera(api)
    with pytest.raises(BadRequest, match="requires text"):
        await cam.set_lcd_message(DoorbellMessageType.CUSTOM_MESSAGE)


@pytest.mark.asyncio
async def test_public_camera_lcd_message_rejects_text() -> None:
    api = MagicMock()
    cam = _camera(api)
    with pytest.raises(BadRequest, match="does not accept text"):
        await cam.set_lcd_message(DoorbellMessageType.DO_NOT_DISTURB, "nope")


@pytest.mark.parametrize(
    ("method", "kwarg"),
    [
        ("set_osd_name", "osd_name_enabled"),
        ("set_osd_date", "osd_date_enabled"),
        ("set_osd_logo", "osd_logo_enabled"),
        ("set_osd_nerd_mode", "osd_nerd_mode_enabled"),
    ],
)
@pytest.mark.asyncio
async def test_public_camera_osd_toggles(method: str, kwarg: str) -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(return_value=cam)

    result = await getattr(cam, method)(True)

    assert result is cam
    api.update_camera_public.assert_awaited_once_with(cam.id, **{kwarg: True})


@pytest.mark.asyncio
async def test_public_camera_osd_overlay_location() -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(return_value=cam)

    await cam.set_osd_overlay_location(OsdOverlayLocation.TOP_RIGHT)

    api.update_camera_public.assert_awaited_once_with(
        cam.id, osd_overlay_location=OsdOverlayLocation.TOP_RIGHT
    )


_OBJECT_DETECTION = [
    ("set_person_detection", SmartDetectObjectType.PERSON),
    ("set_vehicle_detection", SmartDetectObjectType.VEHICLE),
    ("set_animal_detection", SmartDetectObjectType.ANIMAL),
    ("set_package_detection", SmartDetectObjectType.PACKAGE),
    ("set_face_detection", SmartDetectObjectType.FACE),
    ("set_license_plate_detection", SmartDetectObjectType.LICENSE_PLATE),
]


@pytest.mark.parametrize(("method", "obj_type"), _OBJECT_DETECTION)
@pytest.mark.asyncio
async def test_public_camera_object_detection_enable(
    method: str, obj_type: SmartDetectObjectType
) -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.smart_detect_types = list(SmartDetectObjectType)
    new_types = [*cam.smart_detect_settings.object_types, obj_type]
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(
            update={
                "smart_detect_settings": cam.smart_detect_settings.model_copy(
                    update={"object_types": new_types}
                )
            }
        )
    )

    result = await getattr(cam, method)(True)

    assert result is cam
    assert obj_type in cam.smart_detect_settings.object_types


@pytest.mark.asyncio
async def test_public_camera_object_detection_disable() -> None:
    api = MagicMock()
    cam = _camera(api)
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(
            update={
                "smart_detect_settings": cam.smart_detect_settings.model_copy(
                    update={"object_types": []}
                )
            }
        )
    )

    await cam.set_person_detection(False)

    assert SmartDetectObjectType.PERSON not in cam.smart_detect_settings.object_types
    body = api.update_camera_public.call_args.kwargs["smart_detect_object_types"]
    assert SmartDetectObjectType.PERSON not in body


@pytest.mark.asyncio
async def test_public_camera_object_detection_unsupported() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.smart_detect_types = []
    with pytest.raises(BadRequest, match="does not support"):
        await cam.set_person_detection(True)


_AUDIO_DETECTION = [
    ("set_smoke_detection", SmartDetectAudioType.SMOKE),
    ("set_co_detection", SmartDetectAudioType.CMONX),
    ("set_siren_detection", SmartDetectAudioType.SIREN),
    ("set_baby_cry_detection", SmartDetectAudioType.BABY_CRY),
    ("set_speaking_detection", SmartDetectAudioType.SPEAK),
    ("set_bark_detection", SmartDetectAudioType.BARK),
    ("set_burglar_detection", SmartDetectAudioType.BURGLAR),
    ("set_car_horn_detection", SmartDetectAudioType.CAR_HORN),
    ("set_glass_break_detection", SmartDetectAudioType.GLASS_BREAK),
]


@pytest.mark.parametrize(("method", "audio_type"), _AUDIO_DETECTION)
@pytest.mark.asyncio
async def test_public_camera_audio_detection_enable(
    method: str, audio_type: SmartDetectAudioType
) -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.smart_detect_audio_types = list(SmartDetectAudioType)
    new_types = [*cam.smart_detect_settings.audio_types, audio_type]
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(
            update={
                "smart_detect_settings": cam.smart_detect_settings.model_copy(
                    update={"audio_types": new_types}
                )
            }
        )
    )

    result = await getattr(cam, method)(True)

    assert result is cam
    assert audio_type in cam.smart_detect_settings.audio_types


@pytest.mark.asyncio
async def test_public_camera_audio_detection_disable() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.smart_detect_audio_types = list(SmartDetectAudioType)
    cam.smart_detect_settings.audio_types = [SmartDetectAudioType.SMOKE]
    api.update_camera_public = AsyncMock(
        return_value=cam.model_copy(
            update={
                "smart_detect_settings": cam.smart_detect_settings.model_copy(
                    update={"audio_types": []}
                )
            }
        )
    )

    await cam.set_smoke_detection(False)

    assert cam.smart_detect_settings.audio_types == []


@pytest.mark.asyncio
async def test_public_camera_audio_detection_unsupported() -> None:
    api = MagicMock()
    cam = _camera(api)
    cam.feature_flags.smart_detect_audio_types = []
    with pytest.raises(BadRequest, match="does not support"):
        await cam.set_smoke_detection(True)


# ---------------------------------------------------------------------------
# Light
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_light_set_name() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(
        return_value=light.model_copy(update={"name": "Renamed"})
    )

    result = await light.set_name("Renamed")

    assert result is light
    assert light.name == "Renamed"


@pytest.mark.asyncio
async def test_public_light_set_flood_light() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(
        return_value=light.model_copy(update={"is_light_force_enabled": True})
    )

    await light.set_flood_light(True)

    assert light.is_light_force_enabled is True
    api.update_light_public.assert_awaited_once_with(
        light.id, is_light_force_enabled=True
    )


@pytest.mark.asyncio
async def test_public_light_set_led_level() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(
        return_value=light.model_copy(
            update={
                "light_device_settings": light.light_device_settings.model_copy(
                    update={"led_level": 4}
                )
            }
        )
    )

    result = await light.set_led_level(4)

    assert result is light
    assert light.light_device_settings.led_level == 4
    sent = api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.led_level == 4


@pytest.mark.parametrize("bad", [0, 7])
@pytest.mark.asyncio
async def test_public_light_led_level_out_of_range(bad: int) -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock()
    with pytest.raises(BadRequest):
        await light.set_led_level(bad)
    assert not api.update_light_public.called


@pytest.mark.asyncio
async def test_public_light_set_status_light() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(return_value=light)

    await light.set_status_light(False)

    sent = api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.is_indicator_enabled is False


@pytest.mark.asyncio
async def test_public_light_set_sensitivity() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(return_value=light)

    await light.set_sensitivity(80)

    sent = api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.pir_sensitivity == 80


@pytest.mark.asyncio
async def test_public_light_set_duration() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(return_value=light)

    await light.set_duration(timedelta(seconds=60))

    sent = api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.pir_duration == 60000


@pytest.mark.asyncio
async def test_public_light_set_duration_out_of_range() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock()
    with pytest.raises(BadRequest, match="15s to 900s"):
        await light.set_duration(timedelta(seconds=5))
    assert not api.update_light_public.called


@pytest.mark.asyncio
async def test_public_light_set_light_mode() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(return_value=light)

    await light.set_light_mode(LightModeType.MANUAL, LightModeEnableType.DARK)

    sent = api.update_light_public.call_args.kwargs["light_mode_settings"]
    assert sent.mode is LightModeType.MANUAL
    assert sent.enable_at is LightModeEnableType.DARK


@pytest.mark.asyncio
async def test_public_light_set_light_settings() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock(return_value=light)

    await light.set_light_settings(
        LightModeType.MOTION,
        enable_at=LightModeEnableType.DARK,
        duration=timedelta(seconds=30),
        sensitivity=45,
    )

    kwargs = api.update_light_public.call_args.kwargs
    assert kwargs["light_mode_settings"].mode is LightModeType.MOTION
    assert kwargs["light_mode_settings"].enable_at is LightModeEnableType.DARK
    assert kwargs["light_device_settings"].pir_duration == 30000
    assert kwargs["light_device_settings"].pir_sensitivity == 45


@pytest.mark.asyncio
async def test_public_light_set_light_settings_bad_duration() -> None:
    api = MagicMock()
    light = _light(api)
    api.update_light_public = AsyncMock()

    with pytest.raises(BadRequest, match="15s to 900s"):
        await light.set_light_settings(
            LightModeType.MOTION, duration=timedelta(seconds=1000)
        )
    assert not api.update_light_public.called


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_sensor_set_name() -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(
        return_value=sensor.model_copy(update={"name": "New"})
    )

    result = await sensor.set_name("New")

    assert result is sensor
    assert sensor.name == "New"


@pytest.mark.asyncio
async def test_public_sensor_set_motion_settings_retains_when_armed() -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(
        return_value=sensor.model_copy(
            update={
                "motion_settings": sensor.motion_settings.model_copy(
                    update={"sensitivity": 30, "sensitivity_when_armed": 80}
                )
            }
        )
    )

    result = await sensor.set_motion_settings(sensitivity=30, sensitivity_when_armed=80)

    assert result is sensor
    assert sensor.motion_settings.sensitivity == 30
    assert sensor.motion_settings.sensitivity_when_armed == 80
    sent = api.update_sensor_public.call_args.kwargs["motion_settings"]
    assert sent == {"sensitivity": 30, "sensitivityWhenArmed": 80}


@pytest.mark.asyncio
async def test_public_sensor_motion_settings_requires_arg() -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock()
    with pytest.raises(BadRequest):
        await sensor.set_motion_settings()
    assert not api.update_sensor_public.called


@pytest.mark.parametrize(
    ("method", "kwargs", "key"),
    [
        ("set_temperature_settings", {"is_enabled": True}, "temperature_settings"),
        ("set_humidity_settings", {"is_enabled": True}, "humidity_settings"),
        ("set_light_settings", {"is_enabled": True}, "light_settings"),
        ("set_glass_break_settings", {"is_enabled": True}, "glass_break_settings"),
    ],
)
@pytest.mark.asyncio
async def test_public_sensor_settings_setters(
    method: str, kwargs: dict[str, Any], key: str
) -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(return_value=sensor)

    result = await getattr(sensor, method)(**kwargs)

    assert result is sensor
    assert key in api.update_sensor_public.call_args.kwargs


@pytest.mark.parametrize(
    "method",
    [
        "set_temperature_settings",
        "set_humidity_settings",
        "set_light_settings",
        "set_glass_break_settings",
    ],
)
@pytest.mark.asyncio
async def test_public_sensor_settings_require_arg(method: str) -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock()
    with pytest.raises(BadRequest):
        await getattr(sensor, method)()
    assert not api.update_sensor_public.called


@pytest.mark.parametrize(
    ("method", "field"),
    [
        ("set_temperature_settings", "temperature"),
        ("set_humidity_settings", "humidity"),
        ("set_light_settings", "light"),
    ],
)
@pytest.mark.asyncio
async def test_public_sensor_threshold_low_out_of_range(
    method: str, field: str
) -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock()
    with pytest.raises(BadRequest):
        await getattr(sensor, method)(low_threshold=-9999)
    assert not api.update_sensor_public.called


@pytest.mark.asyncio
async def test_public_sensor_threshold_full_payload() -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(return_value=sensor)

    await sensor.set_temperature_settings(
        is_enabled=True, low_threshold=10.5, high_threshold=40.5, margin=2.0
    )

    sent = api.update_sensor_public.call_args.kwargs["temperature_settings"]
    assert sent == {
        "isEnabled": True,
        "lowThreshold": 10.5,
        "highThreshold": 40.5,
        "margin": 2.0,
    }


@pytest.mark.parametrize(
    ("method", "key", "low"),
    [
        ("set_humidity_settings", "humidity_settings", 10.0),
        ("set_light_settings", "light_settings", 10.0),
    ],
)
@pytest.mark.asyncio
async def test_public_sensor_threshold_full_payload_variants(
    method: str, key: str, low: float
) -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(return_value=sensor)

    await getattr(sensor, method)(
        is_enabled=True, low_threshold=low, high_threshold=40, margin=3
    )

    sent = api.update_sensor_public.call_args.kwargs[key]
    assert sent == {
        "isEnabled": True,
        "lowThreshold": low,
        "highThreshold": 40,
        "margin": 3,
    }


@pytest.mark.asyncio
async def test_public_sensor_glass_break_full() -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(return_value=sensor)

    await sensor.set_glass_break_settings(
        is_enabled=True, sensitivity=50, sensitivity_when_armed=70
    )

    sent = api.update_sensor_public.call_args.kwargs["glass_break_settings"]
    assert sent == {
        "isEnabled": True,
        "sensitivity": 50,
        "sensitivityWhenArmed": 70,
    }


@pytest.mark.asyncio
async def test_public_sensor_set_alarm_and_scalars() -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(return_value=sensor)

    await sensor.set_alarm(True)
    assert api.update_sensor_public.call_args.kwargs["alarm_settings"] == {
        "isEnabled": True
    }

    await sensor.set_schedule_mode(SensorScheduleMode.WHEN_ARMED)
    assert (
        api.update_sensor_public.call_args.kwargs["schedule_mode"]
        is SensorScheduleMode.WHEN_ARMED
    )

    await sensor.set_arm_profile_ids(["p1"])
    assert api.update_sensor_public.call_args.kwargs["arm_profile_ids"] == ["p1"]

    await sensor.set_custom_sensitivity_when_armed(True)
    assert (
        api.update_sensor_public.call_args.kwargs["has_custom_sensitivity_when_armed"]
        is True
    )


@pytest.mark.parametrize(
    "method",
    [
        "set_motion_status",
        "set_temperature_status",
        "set_humidity_status",
        "set_light_status",
        "set_glass_break_status",
    ],
)
@pytest.mark.asyncio
async def test_public_sensor_status_delegators(method: str) -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(return_value=sensor)

    result = await getattr(sensor, method)(True)

    assert result is sensor
    assert api.update_sensor_public.called


@pytest.mark.asyncio
async def test_public_sensor_set_motion_sensitivity() -> None:
    api = MagicMock()
    sensor = _sensor(api)
    api.update_sensor_public = AsyncMock(return_value=sensor)

    await sensor.set_motion_sensitivity(66)

    assert api.update_sensor_public.call_args.kwargs["motion_settings"] == {
        "sensitivity": 66
    }


# ---------------------------------------------------------------------------
# Chime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_chime_set_ring_settings() -> None:
    api = MagicMock()
    chime = _chime(api)
    body = [{"cameraId": "cam-a", "volume": 20, "repeatTimes": 3}]
    api.update_chime_public = AsyncMock(
        return_value=chime.model_copy(
            update={
                "ring_settings": [
                    r.model_copy(update={"volume": 20, "repeat_times": 3})
                    for r in chime.ring_settings
                    if r.camera_id == "cam-a"
                ]
            }
        )
    )

    result = await chime.set_ring_settings(body)

    assert result is chime
    api.update_chime_public.assert_awaited_once_with(chime.id, ring_settings=body)


@pytest.mark.asyncio
async def test_public_chime_set_volume_for_camera() -> None:
    api = MagicMock()
    chime = _chime(api)

    async def fake_update(cid: str, *, ring_settings: list[Any]) -> PublicChime:
        return chime.model_copy(
            update={
                "ring_settings": [
                    r.model_copy(update={"volume": rs["volume"]})
                    for r, rs in zip(chime.ring_settings, ring_settings, strict=True)
                ]
            }
        )

    api.update_chime_public = AsyncMock(side_effect=fake_update)

    result = await chime.set_volume_for_camera("cam-a", 15)

    assert result is chime
    body = api.update_chime_public.call_args.kwargs["ring_settings"]
    assert body[0] == {"cameraId": "cam-a", "volume": 15, "repeatTimes": 1}
    assert body[1]["volume"] == 60
    assert chime.ring_settings[0].volume == 15


@pytest.mark.asyncio
async def test_public_chime_set_repeat_times_for_camera() -> None:
    api = MagicMock()
    chime = _chime(api)
    api.update_chime_public = AsyncMock(return_value=chime)

    await chime.set_repeat_times_for_camera("cam-b", 4)

    body = api.update_chime_public.call_args.kwargs["ring_settings"]
    assert body[1] == {"cameraId": "cam-b", "volume": 60, "repeatTimes": 4}


@pytest.mark.asyncio
async def test_public_chime_unpaired_camera() -> None:
    api = MagicMock()
    chime = _chime(api)
    api.update_chime_public = AsyncMock()
    with pytest.raises(BadRequest, match="not paired"):
        await chime.set_volume_for_camera("nope", 10)
    assert not api.update_chime_public.called


@pytest.mark.asyncio
async def test_public_chime_volume_out_of_range() -> None:
    api = MagicMock()
    chime = _chime(api)
    api.update_chime_public = AsyncMock()
    with pytest.raises(BadRequest):
        await chime.set_volume_for_camera("cam-a", 200)
    assert not api.update_chime_public.called


@pytest.mark.asyncio
async def test_public_chime_ringtone_preserved() -> None:
    api = MagicMock()
    chime = PublicChime.from_unifi_dict(
        api=api,
        id="chime-2",
        modelKey="chime",
        state="CONNECTED",
        mac="AABBCCDDEE04",
        name="Chime",
        cameraIds=["cam-a"],
        ringSettings=[
            {
                "cameraId": "cam-a",
                "volume": 50,
                "repeatTimes": 1,
                "ringtoneId": "tone-1",
            }
        ],
    )
    api.update_chime_public = AsyncMock(return_value=chime)

    await chime.set_volume_for_camera("cam-a", 25)

    body = api.update_chime_public.call_args.kwargs["ring_settings"]
    assert body[0]["ringtoneId"] == "tone-1"


@pytest.mark.asyncio
async def test_public_chime_concurrent_volume_no_lost_update() -> None:
    api = MagicMock()
    chime = _chime(api)

    async def fake_update(cid: str, *, ring_settings: list[Any]) -> PublicChime:
        # Yield mid-flight so a second unlocked caller could interleave; the
        # per-object lock must prevent that. The response is the full list, so
        # an interleaved caller reading a stale list would clobber the other's
        # write on write-through (lost update).
        await asyncio.sleep(0)
        return chime.model_copy(
            update={
                "ring_settings": [
                    r.model_copy(update={"volume": rs["volume"]})
                    for r, rs in zip(chime.ring_settings, ring_settings, strict=True)
                ]
            }
        )

    api.update_chime_public = AsyncMock(side_effect=fake_update)

    await asyncio.gather(
        chime.set_volume_for_camera("cam-a", 10),
        chime.set_volume_for_camera("cam-b", 90),
    )

    volumes = {rs.camera_id: rs.volume for rs in chime.ring_settings}
    assert volumes == {"cam-a": 10, "cam-b": 90}


@pytest.mark.asyncio
async def test_public_light_concurrent_settings_no_lost_update() -> None:
    api = MagicMock()
    light = _light(api)

    async def fake_update(cid: str, *, light_device_settings: Any) -> PublicLight:
        # Yield mid-flight so a second unlocked caller could interleave; the
        # per-object lock must serialise the whole-object PATCH so neither
        # caller reads a stale ``light_device_settings`` and clobbers the other.
        await asyncio.sleep(0)
        return light.model_copy(update={"light_device_settings": light_device_settings})

    api.update_light_public = AsyncMock(side_effect=fake_update)

    await asyncio.gather(
        light.set_led_level(4),
        light.set_sensitivity(80),
    )

    assert light.light_device_settings.led_level == 4
    assert light.light_device_settings.pir_sensitivity == 80


# ---------------------------------------------------------------------------
# Central write-through (private-with-public-bootstrap keeps the twin fresh)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_through_refreshes_cached_twin(
    protect_client_no_debug: Any,
) -> None:
    client = protect_client_no_debug
    client._public_bootstrap = PublicBootstrap()
    cam = _camera(client)
    client._public_bootstrap.cameras[cam.id] = cam
    client.api_request_obj = AsyncMock(
        return_value={
            "id": cam.id,
            "modelKey": "camera",
            "state": "CONNECTED",
            "name": "Cam",
            "mac": cam.mac,
            "isMicEnabled": True,
            "osdSettings": {},
            "ledSettings": {"isEnabled": False},
            "lcdMessage": {},
            "micVolume": 77,
            "videoMode": "default",
            "hdrType": "auto",
            "featureFlags": {},
            "smartDetectSettings": {},
            "hasPackageCamera": False,
        }
    )

    result = await client.update_camera_public(cam.id, mic_volume=77)

    assert result is not cam
    assert cam.mic_volume == 77


@pytest.mark.asyncio
async def test_write_through_no_bootstrap_is_noop(protect_client_no_debug: Any) -> None:
    client = protect_client_no_debug
    client._public_bootstrap = None
    cam = _camera(client)
    client._write_through_public_twin(cam)  # must not raise


@pytest.mark.asyncio
async def test_write_through_uncached_is_noop(protect_client_no_debug: Any) -> None:
    client = protect_client_no_debug
    client._public_bootstrap = PublicBootstrap()
    cam = _camera(client)
    client._write_through_public_twin(cam)  # camera not in cache -> no-op
    assert cam.id not in client._public_bootstrap.cameras


@pytest.mark.asyncio
async def test_write_through_wrong_store_is_noop(protect_client_no_debug: Any) -> None:
    client = protect_client_no_debug
    client._public_bootstrap = PublicBootstrap()
    siren = Siren.from_unifi_dict(
        api=client,
        id="siren-1",
        modelKey="siren",
        state="CONNECTED",
        mac="AABBCCDDEE09",
        name="Siren",
        volume=50,
        ledSettings={"isEnabled": True},
        sirenStatus={"isActive": False},
        connectionType="wired",
    )
    client._public_bootstrap.sirens[siren.id] = siren
    # Not a camera/light/sensor/chime write-through path, but resolves a store;
    # applying to a same-typed cached twin is still a no-op change here.
    client._write_through_public_twin(siren)
