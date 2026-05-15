"""Tests for Camera Public API methods."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tests.conftest import TEST_CAMERA_EXISTS, read_camera_json_file
from uiprotect.data import Camera, OsdOverlayLocation, PublicHdrMode
from uiprotect.data.types import (
    HDRMode,
    PercentInt,
    SmartDetectAudioType,
    SmartDetectObjectType,
    VideoMode,
)
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient

CAMERA_ID = "6878d82800215803e45928e1"


@pytest.fixture
def patched_camera_response(protect_client: ProtectApiClient) -> Iterator[Mock]:
    """Patch Camera.from_unifi_dict and set a minimal successful API response."""
    mock_cam = Mock()
    mock_cam.id = CAMERA_ID
    with patch("uiprotect.data.devices.Camera.from_unifi_dict") as mock_create:
        mock_create.return_value = mock_cam
        protect_client.api_request_obj = AsyncMock(return_value={"id": CAMERA_ID})
        yield mock_create


# =============================================================================
# GET CAMERA TESTS
# =============================================================================


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Camera.from_unifi_dict")
async def test_get_cameras_public_success(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test successful cameras retrieval from public API."""
    mock_cam1 = Mock()
    mock_cam1.id = CAMERA_ID
    mock_cam2 = Mock()
    mock_cam2.id = "other-camera-id"
    mock_create.side_effect = [mock_cam1, mock_cam2]
    protect_client.api_request_list = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])

    result = await protect_client.get_cameras_public()

    assert len(result) == 2
    protect_client.api_request_list.assert_called_with(
        url="/v1/cameras", public_api=True
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Camera.from_unifi_dict")
async def test_get_camera_public_success(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test successful single camera retrieval from public API."""
    mock_cam = Mock()
    mock_cam.id = CAMERA_ID
    mock_create.return_value = mock_cam
    protect_client.api_request_obj = AsyncMock(return_value={"id": CAMERA_ID})

    result = await protect_client.get_camera_public(CAMERA_ID)

    assert result.id == CAMERA_ID
    protect_client.api_request_obj.assert_called_with(
        url=f"/v1/cameras/{CAMERA_ID}", public_api=True
    )


# =============================================================================
# UPDATE CAMERA TESTS
# =============================================================================


@pytest.mark.parametrize(
    ("kwargs", "payload"),
    [
        ({"name": "Front Door"}, {"name": "Front Door"}),
        ({"hdr_type": PublicHdrMode.AUTO}, {"hdrType": "auto"}),
        ({"led_is_enabled": True}, {"ledSettings": {"isEnabled": True}}),
        ({"led_welcome_led": False}, {"ledSettings": {"welcomeLed": False}}),
        ({"led_flood_led": True}, {"ledSettings": {"floodLed": True}}),
        ({"mic_volume": 80}, {"micVolume": 80}),
        ({"mic_volume": 0}, {"micVolume": 0}),
        (
            {
                "osd_name_enabled": True,
                "osd_date_enabled": False,
                "osd_logo_enabled": True,
                "osd_nerd_mode_enabled": False,
            },
            {
                "osdSettings": {
                    "isNameEnabled": True,
                    "isDateEnabled": False,
                    "isLogoEnabled": True,
                    "isDebugEnabled": False,
                }
            },
        ),
        (
            {"osd_overlay_location": OsdOverlayLocation.TOP_LEFT},
            {"osdSettings": {"overlayLocation": "topLeft"}},
        ),
        (
            {
                "smart_detect_object_types": [
                    SmartDetectObjectType.PERSON,
                    SmartDetectObjectType.VEHICLE,
                ]
            },
            {"smartDetectSettings": {"objectTypes": ["person", "vehicle"]}},
        ),
        (
            {"smart_detect_audio_types": [SmartDetectAudioType.SMOKE]},
            {"smartDetectSettings": {"audioTypes": ["alrmSmoke"]}},
        ),
        (
            {
                "smart_detect_object_types": [SmartDetectObjectType.PERSON],
                "smart_detect_audio_types": [SmartDetectAudioType.SMOKE],
            },
            {
                "smartDetectSettings": {
                    "objectTypes": ["person"],
                    "audioTypes": ["alrmSmoke"],
                }
            },
        ),
        (
            {"lcd_message": {"type": "CUSTOM_MESSAGE", "text": "Hello"}},
            {"lcdMessage": {"type": "CUSTOM_MESSAGE", "text": "Hello"}},
        ),
    ],
)
@pytest.mark.asyncio()
async def test_update_camera_public_payloads(
    protect_client: ProtectApiClient,
    patched_camera_response: Mock,
    kwargs: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    await protect_client.update_camera_public(CAMERA_ID, **kwargs)

    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/cameras/{CAMERA_ID}",
        method="patch",
        json=payload,
        public_api=True,
    )
    patched_camera_response.assert_called_once_with(id=CAMERA_ID, api=protect_client)


@pytest.mark.asyncio()
async def test_update_camera_public_mic_volume_out_of_range(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest, match="mic_volume must be between 0 and 100"):
        await protect_client.update_camera_public(CAMERA_ID, mic_volume=101)

    with pytest.raises(BadRequest, match="mic_volume must be between 0 and 100"):
        await protect_client.update_camera_public(CAMERA_ID, mic_volume=-1)


@pytest.mark.asyncio()
async def test_update_camera_public_no_parameters(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(BadRequest, match="At least one parameter must be provided"):
        await protect_client.update_camera_public(CAMERA_ID)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_update_camera_public_parses_private_fixture(
    protect_client: ProtectApiClient,
) -> None:
    """Private-API fixture is a strict superset of the public schema; parse succeeds."""
    camera_data = read_camera_json_file()
    protect_client.api_request_obj = AsyncMock(return_value=camera_data)

    result = await protect_client.update_camera_public(CAMERA_ID, name="Test")

    assert isinstance(result, Camera)
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/cameras/{CAMERA_ID}",
        method="patch",
        json={"name": "Test"},
        public_api=True,
    )


@pytest.mark.asyncio()
async def test_update_camera_public_parses_public_response_schema(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """
    Camera.from_unifi_dict must parse a minimal response matching the public API
    schema (integration.json #/components/schemas/camera).

    The public PATCH response is a *strict subset* of the private schema: only the
    fields exposed by the Integration API are present.  This test uses those fields
    directly so regressions in Camera's required-field handling are caught here
    rather than only discovered at runtime against a real controller.

    Must run in no-debug mode: production uses model_construct (no validation);
    debug mode uses the strict constructor which rejects partial schemas.
    """
    public_response = {
        "id": CAMERA_ID,
        "modelKey": "camera",
        "state": "CONNECTED",
        "name": "Test Camera",
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
    protect_client_no_debug.api_request_obj = AsyncMock(return_value=public_response)

    result = await protect_client_no_debug.update_camera_public(CAMERA_ID, name="Test")

    assert isinstance(result, Camera)
    assert result.osd_settings.overlay_location == OsdOverlayLocation.TOP_LEFT
    assert result.led_settings.welcome_led is None
    assert result.led_settings.flood_led is None


@pytest.mark.asyncio()
async def test_update_camera_public_audio_types_passed_through(
    protect_client: ProtectApiClient,
    patched_camera_response: Mock,
) -> None:
    """Audio types are passed through as-is; SMOKE_CMONX is not a valid public API value."""
    await protect_client.update_camera_public(
        CAMERA_ID,
        smart_detect_audio_types=[
            SmartDetectAudioType.SMOKE,
            SmartDetectAudioType.CMONX,
        ],
    )

    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/cameras/{CAMERA_ID}",
        method="patch",
        json={
            "smartDetectSettings": {
                "audioTypes": [SmartDetectAudioType.SMOKE, SmartDetectAudioType.CMONX]
            }
        },
        public_api=True,
    )


# =============================================================================
# CAMERA DEVICE METHOD TESTS
# =============================================================================


def _led_updated_mock(camera_obj: Camera) -> Mock:  # type: ignore[type-arg]
    m = Mock()
    m.led_settings = camera_obj.led_settings.model_copy(
        update={"is_enabled": not camera_obj.led_settings.is_enabled}
    )
    return m


def _hdr_updated_mock(camera_obj: Camera, hdr_on: bool) -> Mock:  # type: ignore[type-arg]
    m = Mock()
    m.hdr_mode = hdr_on
    m.isp_settings.hdr_mode = HDRMode.NORMAL
    return m


def _video_updated_mock(mode: VideoMode) -> Mock:  # type: ignore[type-arg]
    m = Mock()
    m.video_mode = mode
    return m


def _mic_updated_mock(level: int) -> Mock:  # type: ignore[type-arg]
    m = Mock()
    m.mic_volume = PercentInt(level)
    return m


def _osd_updated_mock(camera_obj: Camera) -> Mock:  # type: ignore[type-arg]
    m = Mock()
    m.osd_settings = camera_obj.osd_settings.model_copy(
        update={"is_name_enabled": not camera_obj.osd_settings.is_name_enabled}
    )
    return m


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_status_light_public(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = True
    camera_obj.use_global = False
    updated = _led_updated_mock(camera_obj)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_status_light_public(True)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, led_is_enabled=True
    )
    assert camera_obj.led_settings == updated.led_settings


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_status_light_public_no_led(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = False

    with pytest.raises(BadRequest, match="does not have status light"):
        await camera_obj.set_status_light_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_welcome_led_public(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = True
    camera_obj.led_settings.welcome_led = False
    updated = _led_updated_mock(camera_obj)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_welcome_led_public(True)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, led_welcome_led=True
    )
    assert camera_obj.led_settings == updated.led_settings


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_welcome_led_public_no_led_status(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = False

    with pytest.raises(BadRequest, match="does not have status light"):
        await camera_obj.set_welcome_led_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_welcome_led_public_not_supported(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = True
    camera_obj.led_settings.welcome_led = None

    with pytest.raises(BadRequest, match="does not have welcome LED"):
        await camera_obj.set_welcome_led_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_flood_led_public(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = True
    camera_obj.led_settings.flood_led = False
    updated = _led_updated_mock(camera_obj)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_flood_led_public(True)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, led_flood_led=True
    )
    assert camera_obj.led_settings == updated.led_settings


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_flood_led_public_no_led_status(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = False

    with pytest.raises(BadRequest, match="does not have status light"):
        await camera_obj.set_flood_led_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_flood_led_public_not_supported(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_led_status = True
    camera_obj.led_settings.flood_led = None

    with pytest.raises(BadRequest, match="does not have flood LED"):
        await camera_obj.set_flood_led_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_hdr_mode_public(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_hdr = True
    updated = _hdr_updated_mock(camera_obj, hdr_on=True)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_hdr_mode_public(PublicHdrMode.AUTO)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, hdr_type=PublicHdrMode.AUTO
    )
    assert camera_obj.hdr_mode == updated.hdr_mode


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_hdr_mode_public_on(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_hdr = True
    camera_obj._api.update_camera_public = AsyncMock(
        return_value=_hdr_updated_mock(camera_obj, hdr_on=True)
    )

    await camera_obj.set_hdr_mode_public(PublicHdrMode.ON)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, hdr_type=PublicHdrMode.ON
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_hdr_mode_public_no_hdr(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_hdr = False

    with pytest.raises(BadRequest, match="does not have HDR"):
        await camera_obj.set_hdr_mode_public(PublicHdrMode.ON)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_hdr_mode_public_updates_isp_settings(
    camera_obj: Camera | None,
) -> None:
    """isp_settings.hdr_mode is updated when it is not None."""
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_hdr = True
    camera_obj.isp_settings.hdr_mode = HDRMode.NORMAL  # make it non-None
    camera_obj._api.update_camera_public = AsyncMock(
        return_value=_hdr_updated_mock(camera_obj, hdr_on=True)
    )

    await camera_obj.set_hdr_mode_public(PublicHdrMode.ON)

    assert camera_obj.hdr_mode is True
    assert camera_obj.isp_settings.hdr_mode == HDRMode.ALWAYS_ON


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_video_mode_public(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.video_modes = [VideoMode.DEFAULT]
    updated = _video_updated_mock(VideoMode.DEFAULT)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_video_mode_public(VideoMode.DEFAULT)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, video_mode=VideoMode.DEFAULT.value
    )
    assert camera_obj.video_mode == VideoMode.DEFAULT


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_video_mode_public_unsupported(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.video_modes = []

    with pytest.raises(BadRequest, match="Camera does not have"):
        await camera_obj.set_video_mode_public(VideoMode.HIGH_FPS)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_mic_volume_public(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_mic = True
    updated = _mic_updated_mock(75)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_mic_volume_public(75)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, mic_volume=75
    )
    assert camera_obj.mic_volume == 75


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_mic_volume_public_no_mic(camera_obj: Camera | None) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_mic = False

    with pytest.raises(BadRequest, match="does not have mic"):
        await camera_obj.set_mic_volume_public(50)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("method", "kwarg"),
    [
        ("set_osd_name_public", "osd_name_enabled"),
        ("set_osd_date_public", "osd_date_enabled"),
        ("set_osd_logo_public", "osd_logo_enabled"),
        ("set_osd_nerd_mode_public", "osd_nerd_mode_enabled"),
    ],
)
@pytest.mark.asyncio()
async def test_camera_set_osd_public(
    camera_obj: Camera | None,
    method: str,
    kwarg: str,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.use_global = False
    updated = _osd_updated_mock(camera_obj)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await getattr(camera_obj, method)(True)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, **{kwarg: True}
    )
    assert camera_obj.osd_settings == updated.osd_settings


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_osd_overlay_location_public(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.use_global = False
    updated = _osd_updated_mock(camera_obj)
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_osd_overlay_location_public(OsdOverlayLocation.TOP_LEFT)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, osd_overlay_location=OsdOverlayLocation.TOP_LEFT
    )
    assert camera_obj.osd_settings == updated.osd_settings


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_osd_overlay_location_public_use_global(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.use_global = True

    with pytest.raises(BadRequest, match="global recording settings"):
        await camera_obj.set_osd_overlay_location_public(OsdOverlayLocation.TOP_LEFT)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "method",
    [
        "set_osd_name_public",
        "set_osd_date_public",
        "set_osd_logo_public",
        "set_osd_nerd_mode_public",
    ],
)
@pytest.mark.asyncio()
async def test_camera_set_osd_public_use_global(
    camera_obj: Camera | None,
    method: str,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.use_global = True

    with pytest.raises(BadRequest, match="global recording settings"):
        await getattr(camera_obj, method)(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("method", "obj_type"),
    [
        ("set_person_detection_public", SmartDetectObjectType.PERSON),
        ("set_vehicle_detection_public", SmartDetectObjectType.VEHICLE),
        ("set_package_detection_public", SmartDetectObjectType.PACKAGE),
        ("set_animal_detection_public", SmartDetectObjectType.ANIMAL),
        ("set_face_detection_public", SmartDetectObjectType.FACE),
        ("set_license_plate_detection_public", SmartDetectObjectType.LICENSE_PLATE),
    ],
)
@pytest.mark.asyncio()
async def test_camera_set_object_detection_public_enable(
    camera_obj: Camera | None,
    method: str,
    obj_type: SmartDetectObjectType,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = False
    camera_obj.feature_flags.smart_detect_types = [obj_type]
    camera_obj.smart_detect_settings.object_types = []
    updated = Mock()
    updated.smart_detect_settings.object_types = [obj_type]
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await getattr(camera_obj, method)(True)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, smart_detect_object_types=[obj_type]
    )
    assert camera_obj.smart_detect_settings.object_types == [obj_type]


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_object_detection_public_no_smart_detect(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = False

    with pytest.raises(BadRequest, match="does not have smart detections"):
        await camera_obj.set_person_detection_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_object_detection_public_use_global(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = True

    with pytest.raises(BadRequest, match="global recording settings"):
        await camera_obj.set_person_detection_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_object_detection_public_consecutive_calls(
    camera_obj: Camera | None,
) -> None:
    """Consecutive enable calls must not clobber each other's state."""
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = False
    camera_obj.feature_flags.smart_detect_types = [
        SmartDetectObjectType.PERSON,
        SmartDetectObjectType.VEHICLE,
    ]
    camera_obj.smart_detect_settings.object_types = []

    after_person = Mock()
    after_person.smart_detect_settings.object_types = [SmartDetectObjectType.PERSON]
    after_vehicle = Mock()
    after_vehicle.smart_detect_settings.object_types = [
        SmartDetectObjectType.PERSON,
        SmartDetectObjectType.VEHICLE,
    ]
    camera_obj._api.update_camera_public = AsyncMock(
        side_effect=[after_person, after_vehicle]
    )

    await camera_obj.set_person_detection_public(True)
    await camera_obj.set_vehicle_detection_public(True)

    calls = camera_obj._api.update_camera_public.call_args_list
    assert calls[0] == (
        (camera_obj.id,),
        {"smart_detect_object_types": [SmartDetectObjectType.PERSON]},
    )
    assert calls[1] == (
        (camera_obj.id,),
        {
            "smart_detect_object_types": [
                SmartDetectObjectType.PERSON,
                SmartDetectObjectType.VEHICLE,
            ]
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_object_detection_public_disable(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = False
    camera_obj.feature_flags.smart_detect_types = [SmartDetectObjectType.PERSON]
    camera_obj.smart_detect_settings.object_types = [SmartDetectObjectType.PERSON]
    updated = Mock()
    updated.smart_detect_settings.object_types = []
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_person_detection_public(False)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, smart_detect_object_types=[]
    )
    assert camera_obj.smart_detect_settings.object_types == []


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_object_detection_public_unsupported(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.smart_detect_types = []

    with pytest.raises(BadRequest, match="does not support"):
        await camera_obj.set_person_detection_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("method", "audio_type"),
    [
        ("set_smoke_detection_public", SmartDetectAudioType.SMOKE),
        ("set_co_detection_public", SmartDetectAudioType.CMONX),
        ("set_siren_detection_public", SmartDetectAudioType.SIREN),
        ("set_baby_cry_detection_public", SmartDetectAudioType.BABY_CRY),
        ("set_speaking_detection_public", SmartDetectAudioType.SPEAK),
        ("set_bark_detection_public", SmartDetectAudioType.BARK),
        ("set_burglar_detection_public", SmartDetectAudioType.BURGLAR),
        ("set_car_horn_detection_public", SmartDetectAudioType.CAR_HORN),
        ("set_glass_break_detection_public", SmartDetectAudioType.GLASS_BREAK),
    ],
)
@pytest.mark.asyncio()
async def test_camera_set_audio_detection_public_enable(
    camera_obj: Camera | None,
    method: str,
    audio_type: SmartDetectAudioType,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = False
    camera_obj.feature_flags.smart_detect_audio_types = [audio_type]
    camera_obj.smart_detect_settings.audio_types = []
    updated = Mock()
    updated.smart_detect_settings.audio_types = [audio_type]
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await getattr(camera_obj, method)(True)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, smart_detect_audio_types=[audio_type]
    )
    assert camera_obj.smart_detect_settings.audio_types == [audio_type]


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_audio_detection_public_disable(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = False
    camera_obj.feature_flags.smart_detect_audio_types = [SmartDetectAudioType.SMOKE]
    camera_obj.smart_detect_settings.audio_types = [SmartDetectAudioType.SMOKE]
    updated = Mock()
    updated.smart_detect_settings.audio_types = []
    camera_obj._api.update_camera_public = AsyncMock(return_value=updated)

    await camera_obj.set_smoke_detection_public(False)

    camera_obj._api.update_camera_public.assert_called_once_with(
        camera_obj.id, smart_detect_audio_types=[]
    )
    assert camera_obj.smart_detect_settings.audio_types == []


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_audio_detection_public_unsupported(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = False
    camera_obj.feature_flags.smart_detect_audio_types = None

    with pytest.raises(BadRequest, match="does not support"):
        await camera_obj.set_smoke_detection_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_audio_detection_public_no_smart_detect(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = False

    with pytest.raises(BadRequest, match="does not have smart detections"):
        await camera_obj.set_smoke_detection_public(True)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_camera_set_audio_detection_public_use_global(
    camera_obj: Camera | None,
) -> None:
    if camera_obj is None:
        pytest.skip("No camera_obj found")
    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.use_global = True

    with pytest.raises(BadRequest, match="global recording settings"):
        await camera_obj.set_smoke_detection_public(True)
