# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr, arg-type"

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from pydantic.v1 import ValidationError

from tests.conftest import TEST_CAMERA_EXISTS
from uiprotect.data import (
    Camera,
    ChimeType,
    DoorbellMessageType,
    HDRMode,
    IRLEDMode,
    LCDMessage,
    PTZPreset,
    RecordingMode,
    SmartDetectAudioType,
    VideoMode,
)
from uiprotect.data.devices import CameraZone, Hotplug, HotplugExtender
from uiprotect.data.types import DEFAULT, SmartDetectObjectType
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.exceptions import BadRequest
from uiprotect.utils import to_js_time


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_motion_detection(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.recording_settings.enable_motion_detection = not status

    await camera_obj.set_motion_detection(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"recordingSettings": {"enableMotionDetection": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [RecordingMode.ALWAYS, RecordingMode.DETECTIONS])
@pytest.mark.asyncio()
async def test_camera_set_recording_mode(
    camera_obj: Camera | None,
    mode: RecordingMode,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.recording_settings.mode = RecordingMode.NEVER

    await camera_obj.set_recording_mode(mode)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"recordingSettings": {"mode": mode.value}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_ir_led_model_no_ir(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_ir = False

    with pytest.raises(BadRequest):
        await camera_obj.set_ir_led_model(IRLEDMode.AUTO)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [IRLEDMode.AUTO, IRLEDMode.ON])
@pytest.mark.asyncio()
async def test_camera_set_ir_led_model(camera_obj: Camera | None, mode: IRLEDMode):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_ir = True
    camera_obj.isp_settings.ir_led_mode = IRLEDMode.OFF

    await camera_obj.set_ir_led_model(mode)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"ispSettings": {"irLedMode": mode.value}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_status_light_no_status(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_status = False

    with pytest.raises(BadRequest):
        await camera_obj.set_status_light(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_status_light(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_status = True
    camera_obj.led_settings.is_enabled = not status
    camera_obj.led_settings.blink_rate = 10

    await camera_obj.set_status_light(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"ledSettings": {"isEnabled": status, "blinkRate": 0}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_hdr_no_hdr(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = False

    with pytest.raises(BadRequest):
        await camera_obj.set_hdr_mode("off")

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("auto", (True, HDRMode.NORMAL)),
        ("off", (False, HDRMode.NORMAL)),
        ("always", (True, HDRMode.ALWAYS_ON)),
    ],
)
@pytest.mark.asyncio()
async def test_camera_set_hdr(
    camera_obj: Camera | None,
    status: str,
    state: tuple[bool, HDRMode],
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = True
    camera_obj.hdr_mode = not state[0]
    camera_obj.isp_settings.hdr_mode = (
        HDRMode.NORMAL if state[1] == HDRMode.ALWAYS_ON else HDRMode.ALWAYS_ON
    )

    await camera_obj.set_hdr_mode(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"hdrMode": state[0], "ispSettings": {"hdrMode": state[1]}},
    )

    assert camera_obj.hdr_mode_display == status


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_color_night_vision(
    camera_obj: Camera | None,
    status: bool,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.hotplug = Hotplug()
    camera_obj.feature_flags.hotplug.extender = HotplugExtender()
    camera_obj.feature_flags.hotplug.extender.is_attached = True

    camera_obj.isp_settings.is_color_night_vision_enabled = not status

    await camera_obj.set_color_night_vision(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"ispSettings": {"isColorNightVisionEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_color_night_vision_no_color_night_vision(
    camera_obj: Camera | None,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await camera_obj.set_color_night_vision(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_ssh(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.is_ssh_enabled = not status

    await camera_obj.set_ssh(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"isSshEnabled": status},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_video_mode_no_highfps(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.video_modes = [VideoMode.DEFAULT]
    camera_obj.video_mode = VideoMode.DEFAULT

    with pytest.raises(BadRequest):
        await camera_obj.set_video_mode(VideoMode.HIGH_FPS)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_video_mode(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.video_modes = [VideoMode.DEFAULT, VideoMode.HIGH_FPS]
    camera_obj.video_mode = VideoMode.DEFAULT

    await camera_obj.set_video_mode(VideoMode.HIGH_FPS)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"videoMode": VideoMode.HIGH_FPS.value},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_camera_zoom_no_zoom(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.can_optical_zoom = False

    with pytest.raises(BadRequest):
        await camera_obj.set_camera_zoom(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio()
async def test_camera_set_camera_zoom(camera_obj: Camera | None, level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.can_optical_zoom = True
    camera_obj.isp_settings.zoom_position = 10

    if level in {-1, 200}:
        with pytest.raises(ValidationError):
            await camera_obj.set_camera_zoom(level)
        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_camera_zoom(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"ispSettings": {"zoomPosition": level}},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 3, 4])
@pytest.mark.asyncio()
async def test_camera_set_wdr_level(camera_obj: Camera | None, level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = False
    camera_obj.isp_settings.wdr = 2

    if level in {-1, 4}:
        with pytest.raises(ValidationError):
            await camera_obj.set_wdr_level(level)
        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_wdr_level(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"ispSettings": {"wdr": level}},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_wdr_level_hdr(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = True

    with pytest.raises(BadRequest):
        await camera_obj.set_wdr_level(1)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_mic_volume_no_mic(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_mic = False

    with pytest.raises(BadRequest):
        await camera_obj.set_mic_volume(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio()
async def test_camera_set_mic_volume(camera_obj: Camera | None, level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_mic = True
    camera_obj.mic_volume = 10

    if level in {-1, 200}:
        with pytest.raises(ValidationError):
            await camera_obj.set_mic_volume(level)
        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_mic_volume(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"micVolume": level},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_speaker_volume_no_speaker(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = False

    with pytest.raises(BadRequest):
        await camera_obj.set_speaker_volume(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio()
async def test_camera_set_speaker_volume(camera_obj: Camera | None, level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = True
    camera_obj.speaker_settings.volume = 10

    if level in {-1, 200}:
        with pytest.raises(ValidationError):
            await camera_obj.set_speaker_volume(level)
        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_speaker_volume(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"speakerSettings": {"volume": level}},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_chime_duration_no_chime(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_chime = False

    with pytest.raises(BadRequest):
        await camera_obj.set_chime_duration(1000)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_mechanical_chime(
    camera_obj: Camera | None,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")
    camera_obj.feature_flags.has_chime = True
    camera_obj.chime_duration = timedelta(seconds=0.3)
    assert camera_obj.chime_duration_seconds == 0.3
    assert camera_obj.chime_type is ChimeType.MECHANICAL


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_no_chime(
    camera_obj: Camera | None,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")
    camera_obj.feature_flags.has_chime = True
    camera_obj.chime_duration = timedelta(seconds=0)
    assert camera_obj.chime_duration_seconds == 0
    assert camera_obj.chime_type is ChimeType.NONE


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("duration", [-1, 0, 0.5, 1, 20])
@pytest.mark.asyncio()
async def test_camera_set_chime_duration_duration(
    camera_obj: Camera | None,
    duration: int,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_chime = True
    camera_obj.chime_duration = timedelta(seconds=300)
    assert camera_obj.chime_duration_seconds == 300
    assert camera_obj.chime_type is ChimeType.DIGITAL
    camera_obj.mic_volume = 10

    if duration in {-1, 20}:
        with pytest.raises(BadRequest):
            await camera_obj.set_chime_duration(duration)

        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_chime_duration(duration)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"chimeDuration": duration * 1000},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_system_sounds_no_speaker(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = False

    with pytest.raises(BadRequest):
        await camera_obj.set_system_sounds(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_system_sounds(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = True
    camera_obj.speaker_settings.are_system_sounds_enabled = not status

    await camera_obj.set_system_sounds(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"speakerSettings": {"areSystemSoundsEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_osd_name(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_name_enabled = not status

    await camera_obj.set_osd_name(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isNameEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_osd_date(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_date_enabled = not status

    await camera_obj.set_osd_date(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isDateEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_osd_logo(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_logo_enabled = not status

    await camera_obj.set_osd_logo(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isLogoEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_osd_bitrate(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_debug_enabled = not status

    await camera_obj.set_osd_bitrate(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isDebugEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_smart_detect_types_no_smart(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_smart_detect = False

    with pytest.raises(BadRequest):
        await camera_obj.set_smart_detect_types([])

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_smart_detect_types(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.smart_detect_settings.object_types = []

    await camera_obj.set_smart_detect_types([SmartDetectObjectType.PERSON])

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"smartDetectSettings": {"objectTypes": ["person"]}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_lcd_text_no_lcd(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = False

    with pytest.raises(BadRequest):
        await camera_obj.set_lcd_text(DoorbellMessageType.DO_NOT_DISTURB)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_lcd_text_custom(camera_obj: Camera | None):
    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )

    now = datetime.now(tz=timezone.utc)
    await camera_obj.set_lcd_text(DoorbellMessageType.CUSTOM_MESSAGE, "Test", now)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.CUSTOM_MESSAGE.value,
                "text": "Test",
                "resetAt": to_js_time(now),
            },
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_lcd_text_custom_to_custom(camera_obj: Camera | None):
    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.CUSTOM_MESSAGE,
        text="Welcome",
        reset_at=None,
    )

    now = datetime.now(tz=timezone.utc)
    await camera_obj.set_lcd_text(DoorbellMessageType.CUSTOM_MESSAGE, "Test", now)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.CUSTOM_MESSAGE.value,
                "text": "Test",
                "resetAt": to_js_time(now),
            },
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_lcd_text_invalid_text(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True

    with pytest.raises(BadRequest):
        await camera_obj.set_lcd_text(DoorbellMessageType.DO_NOT_DISTURB, "Test")

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_lcd_text(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )

    await camera_obj.set_lcd_text(DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value,
                "text": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace(
                    "_",
                    " ",
                ),
                "resetAt": None,
            },
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
@patch("uiprotect.data.devices.utc_now")
async def test_camera_set_lcd_text_none(
    mock_now,
    camera_obj: Camera | None,
    now: datetime,
):
    mock_now.return_value = now

    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.emit_message = Mock()
    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )

    await camera_obj.set_lcd_text(None)

    expected_dt = now - timedelta(seconds=10)
    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "resetAt": to_js_time(expected_dt),
            },
        },
    )

    # old/new is actually the same here since the client
    # generating the message is the one that changed it
    camera_obj.api.emit_message.assert_called_with(
        WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=camera_obj.api.bootstrap.last_update_id,
            changed_data={"lcd_message": {"reset_at": expected_dt}},
            old_obj=camera_obj,
            new_obj=camera_obj,
        ),
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
@patch("uiprotect.data.devices.utc_now")
async def test_camera_set_lcd_text_default(
    mock_now,
    camera_obj: Camera | None,
    now: datetime,
):
    mock_now.return_value = now

    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )

    await camera_obj.set_lcd_text(
        DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
        reset_at=DEFAULT,
    )

    expected_dt = (
        now
        + camera_obj.api.bootstrap.nvr.doorbell_settings.default_message_reset_timeout
    )
    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value,
                "text": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace(
                    "_",
                    " ",
                ),
                "resetAt": to_js_time(expected_dt),
            },
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_privacy_no_privacy(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_privacy_mask = False

    with pytest.raises(BadRequest):
        await camera_obj.set_privacy(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("actual_enabled", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("level", [None, -1, 0, 100, 200])
@pytest.mark.parametrize("mode", [None, RecordingMode.ALWAYS])
@pytest.mark.asyncio()
async def test_camera_set_privacy(
    camera_obj: Camera | None,
    actual_enabled: bool,
    enabled: bool,
    level: int | None,
    mode: RecordingMode | None,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_privacy_mask = True
    camera_obj.privacy_zones = []
    if actual_enabled:
        camera_obj.add_privacy_zone()
    camera_obj.mic_volume = 10
    camera_obj.recording_settings.mode = RecordingMode.NEVER

    if level in {-1, 200}:
        with pytest.raises(ValidationError):
            await camera_obj.set_privacy(enabled, level, mode)
        assert not camera_obj.api.api_request.called
    else:
        expected = {}

        if level is not None:
            expected.update({"micVolume": level})

        if mode is not None:
            expected.update(
                {
                    "recordingSettings": {
                        "mode": mode.value,
                    },
                },
            )

        if actual_enabled != enabled:
            if enabled:
                expected.update(
                    {"privacyZones": [CameraZone.create_privacy_zone(0).unifi_dict()]},
                )
            else:
                expected.update({"privacyZones": []})

        await camera_obj.set_privacy(enabled, level, mode)

        if not expected:
            assert not camera_obj.api.api_request.called
        else:
            camera_obj.api.api_request.assert_called_with(
                f"cameras/{camera_obj.id}",
                method="patch",
                json=expected,
            )

        if enabled:
            assert camera_obj.is_privacy_on
        else:
            assert not camera_obj.is_privacy_on


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_person_track_no_ptz(camera_obj: Camera | None):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.is_ptz = False

    with pytest.raises(BadRequest):
        await camera_obj.set_person_track(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_set_person_track(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.feature_flags.is_ptz = True
    camera_obj.recording_settings.mode = RecordingMode.ALWAYS

    if status:
        camera_obj.smart_detect_settings.auto_tracking_object_types = []
    else:
        camera_obj.smart_detect_settings.auto_tracking_object_types = [
            SmartDetectObjectType.PERSON,
        ]

    camera_obj.api.api_request.reset_mock()

    await camera_obj.set_person_track(status)

    assert camera_obj.is_person_tracking_enabled is status

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json=(
            {"smartDetectSettings": {"autoTrackingObjectTypes": ["person"]}}
            if status
            else {"smartDetectSettings": {"autoTrackingObjectTypes": []}}
        ),
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_camera_disable_co(camera_obj: Camera | None, status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.feature_flags.is_ptz = True
    camera_obj.recording_settings.mode = RecordingMode.ALWAYS

    if status:
        camera_obj.smart_detect_settings.audio_types = []
    else:
        camera_obj.smart_detect_settings.audio_types = [
            SmartDetectAudioType.SMOKE,
            SmartDetectAudioType.CMONX,
            SmartDetectAudioType.SMOKE_CMONX,
        ]

    camera_obj.api.api_request.reset_mock()

    await camera_obj.set_smart_audio_detect_types(
        [SmartDetectAudioType.SMOKE, SmartDetectAudioType.SMOKE_CMONX]
    )

    assert camera_obj.smart_detect_settings.audio_types == [
        SmartDetectAudioType.SMOKE,
        SmartDetectAudioType.SMOKE_CMONX,
    ]

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"smartDetectSettings": {"audioTypes": ["alrmSmoke"]}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("value", "lux"),
    [
        (1, 1),
        (2, 3),
        (3, 5),
        (4, 7),
        (5, 10),
        (6, 12),
        (7, 15),
        (8, 20),
        (9, 25),
        (10, 30),
    ],
)
@pytest.mark.asyncio()
async def test_camera_set_icr_custom_lux(
    camera_obj: Camera | None,
    value: int,
    lux: int,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.feature_flags.has_led_ir = True
    camera_obj.isp_settings.icr_custom_value = 0

    camera_obj.api.api_request.reset_mock()

    await camera_obj.set_icr_custom_lux(lux)

    assert camera_obj.isp_settings.icr_custom_value == value
    assert camera_obj.icr_lux_display == lux

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json=({"ispSettings": {"icrCustomValue": value}}),
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("pan", "tilt", "pan_native", "tilt_native"),
    [
        (0, 0, 0, 0),
        (1, 1, 97, 88),
        (5, 5, 488, 444),
        (20, 20, 1955, 1777),
        (40, 40, 3911, 3554),
        (-1, -1, -97, -88),
        (-5, -5, -488, -444),
        (-20, -20, -1955, -1777),
        (-40, -40, -3911, -3554),
    ],
)
@pytest.mark.asyncio()
async def test_camera_ptz_relative_move(
    ptz_camera: Camera | None,
    pan: float,
    tilt: float,
    pan_native: float,
    tilt_native: float,
):
    if ptz_camera is None:
        pytest.skip("No camera_obj obj found")

    ptz_camera.api.api_request.reset_mock()

    await ptz_camera.ptz_relative_move(pan=pan, tilt=tilt)

    ptz_camera.api.api_request.assert_called_with(
        f"cameras/{ptz_camera.id}/move",
        method="post",
        json=(
            {
                "type": "relative",
                "payload": {
                    "panPos": pan_native,
                    "tiltPos": tilt_native,
                    "panSpeed": 10,
                    "tiltSpeed": 10,
                    "scale": 0,
                },
            }
        ),
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_ptz_center(ptz_camera: Camera | None):
    if ptz_camera is None:
        pytest.skip("No camera_obj obj found")

    ptz_camera.api.api_request.reset_mock()

    await ptz_camera.ptz_center(x=500, y=500, z=0)

    ptz_camera.api.api_request.assert_called_with(
        f"cameras/{ptz_camera.id}/move",
        method="post",
        json=(
            {
                "type": "center",
                "payload": {
                    "x": 500,
                    "y": 500,
                    "z": 0,
                },
            }
        ),
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("zoom", "zoom_native"),
    [
        (1, 0),
        (5, 382),
        (20, 1818),
        (22, 2009),
    ],
)
@pytest.mark.asyncio()
async def test_camera_ptz_zoom(
    ptz_camera: Camera | None,
    zoom: float,
    zoom_native: float,
):
    if ptz_camera is None:
        pytest.skip("No camera_obj obj found")

    ptz_camera.api.api_request.reset_mock()

    await ptz_camera.ptz_zoom(zoom=zoom)

    ptz_camera.api.api_request.assert_called_with(
        f"cameras/{ptz_camera.id}/move",
        method="post",
        json=(
            {
                "type": "zoom",
                "payload": {
                    "zoomPos": zoom_native,
                    "zoomSpeed": 100,
                },
            }
        ),
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_goto_ptz_slot(ptz_camera: Camera | None):
    if ptz_camera is None:
        pytest.skip("No camera_obj obj found")

    ptz_camera.api.api_request.reset_mock()

    await ptz_camera.goto_ptz_slot(slot=-1)

    ptz_camera.api.api_request.assert_called_with(
        f"cameras/{ptz_camera.id}/ptz/goto/-1",
        method="post",
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_create_ptz_preset(ptz_camera: Camera | None):
    if ptz_camera is None:
        pytest.skip("No camera_obj obj found")

    ptz_camera.api.api_request.reset_mock()

    preset = await ptz_camera.create_ptz_preset(name="Test")

    assert preset == PTZPreset(
        id="test-id",
        name="Test",
        slot=0,
        ptz={
            "pan": 100,
            "tilt": 100,
            "zoom": 0,
        },
    )

    ptz_camera.api.api_request.assert_called_with(
        url=f"cameras/{ptz_camera.id}/ptz/preset",
        method="post",
        require_auth=True,
        raise_exception=True,
        json={"name": "Test"},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_delete_ptz_preset(ptz_camera: Camera | None):
    if ptz_camera is None:
        pytest.skip("No camera_obj obj found")

    ptz_camera.api.api_request.reset_mock()

    await ptz_camera.delete_ptz_preset(slot=0)

    ptz_camera.api.api_request.assert_called_with(
        f"cameras/{ptz_camera.id}/ptz/preset/0",
        method="delete",
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_ptz_home(ptz_camera: Camera | None):
    if ptz_camera is None:
        pytest.skip("No camera_obj obj found")

    ptz_camera.api.api_request.reset_mock()

    preset = await ptz_camera.set_ptz_home()

    assert preset == PTZPreset(
        id="test-id",
        name="Home",
        slot=-1,
        ptz={
            "pan": 100,
            "tilt": 100,
            "zoom": 0,
        },
    )

    ptz_camera.api.api_request.assert_called_with(
        url=f"cameras/{ptz_camera.id}/ptz/home",
        method="post",
        require_auth=True,
        raise_exception=True,
    )
