"""Tests for Camera Public API methods."""

from __future__ import annotations

import datetime as dt
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tests.conftest import TEST_CAMERA_EXISTS, read_camera_json_file
from uiprotect.data import (
    Camera,
    OsdOverlayLocation,
    PublicCamera,
    PublicHdrMode,
    PublicPosTransactionResponse,
)
from uiprotect.data.types import (
    HDRMode,
    PosTransactionType,
    SmartDetectAudioType,
    SmartDetectObjectType,
)
from uiprotect.exceptions import BadRequest
from uiprotect.utils import to_js_time

if TYPE_CHECKING:
    from collections.abc import Iterator

    from uiprotect.api import ProtectApiClient

CAMERA_ID = "6878d82800215803e45928e1"


@pytest.fixture
def patched_camera_response(protect_client: ProtectApiClient) -> Iterator[Mock]:
    """Patch Camera.from_unifi_dict and set a minimal successful API response."""
    mock_cam = Mock()
    mock_cam.id = CAMERA_ID
    with patch(
        "uiprotect.data.public_devices.PublicCamera.from_unifi_dict"
    ) as mock_create:
        mock_create.return_value = mock_cam
        protect_client.api_request_obj = AsyncMock(return_value={"id": CAMERA_ID})
        yield mock_create


@pytest.fixture
def camera(camera_obj: Camera | None) -> Camera:
    """Unwrap camera_obj, skipping the test when test data is absent."""
    if camera_obj is None:
        pytest.skip("Missing camera test data")
    return camera_obj  # type: ignore[return-value]


@pytest.mark.asyncio()
@patch("uiprotect.data.public_devices.PublicCamera.from_unifi_dict")
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
@patch("uiprotect.data.public_devices.PublicCamera.from_unifi_dict")
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
        (
            {"lcd_message": {"type": "DO_NOT_DISTURB", "resetAt": 0}},
            {"lcdMessage": {"type": "DO_NOT_DISTURB", "resetAt": 0}},
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
async def test_update_camera_public_drops_private_only_fields(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """PublicCamera keeps only spec fields; private-only keys are dropped, not stored."""
    camera_data = read_camera_json_file()
    protect_client_no_debug.api_request_obj = AsyncMock(return_value=camera_data)

    result = await protect_client_no_debug.update_camera_public(CAMERA_ID, name="Test")

    assert isinstance(result, PublicCamera)
    assert "recording_settings" not in PublicCamera.model_fields
    assert "isp_settings" not in PublicCamera.model_fields
    assert "channels" not in PublicCamera.model_fields
    protect_client_no_debug.api_request_obj.assert_called_once_with(
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
    PublicCamera.from_unifi_dict parses a payload matching the public API schema
    (integration.json #/components/schemas/camera), including a ``null`` name.

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

    assert isinstance(result, PublicCamera)
    assert result.name == "Test Camera"
    assert result.osd_settings.overlay_location == OsdOverlayLocation.TOP_LEFT
    assert result.led_settings.welcome_led is None
    assert result.led_settings.flood_led is None

    public_response["name"] = None
    protect_client_no_debug.api_request_obj = AsyncMock(return_value=public_response)
    result_null = await protect_client_no_debug.update_camera_public(
        CAMERA_ID, name="x"
    )
    assert isinstance(result_null, PublicCamera)
    assert result_null.name is None


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
        json={"smartDetectSettings": {"audioTypes": ["alrmSmoke", "alrmCmonx"]}},
        public_api=True,
    )


def _hdr_updated_mock(camera_obj: Camera, hdr_on: bool) -> Mock:  # type: ignore[type-arg]
    m = Mock()
    m.hdr_mode = hdr_on
    m.isp_settings.hdr_mode = HDRMode.NORMAL
    return m


@pytest.mark.asyncio()
async def test_create_pos_transaction_public_minimal_body(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_obj = AsyncMock(return_value={"created": True})

    result = await protect_client.create_pos_transaction_public(
        CAMERA_ID,
        type=PosTransactionType.SALE,
        external_id="txn-1",
        amount=12.5,
    )

    assert isinstance(result, PublicPosTransactionResponse)
    assert result.created is True
    assert result.event_id is None
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/pos/cameras/{CAMERA_ID}/transactions",
        method="post",
        json={"type": "sale", "externalId": "txn-1", "amount": 12.5},
        public_api=True,
    )


@pytest.mark.asyncio()
async def test_create_pos_transaction_public_full_body(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_obj = AsyncMock(
        return_value={"created": True, "eventId": "evt-1"}
    )

    # The server rejects a timestamp older than 24 hours, so pin one that is
    # always inside the window.
    timestamp = to_js_time(dt.datetime.now(tz=dt.UTC))

    result = await protect_client.create_pos_transaction_public(
        CAMERA_ID,
        type=PosTransactionType.REFUND,
        external_id="txn-2",
        amount=12.5,
        currency="USD",
        line_items=[{"title": "Coffee", "quantity": 2}],
        location={"id": "reg-1", "name": "Register 1"},
        payment_types=["card"],
        timestamp=timestamp,
    )

    assert result.created is True
    assert result.event_id == "evt-1"
    _args, kwargs = protect_client.api_request_obj.call_args
    assert kwargs["json"] == {
        "type": "refund",
        "externalId": "txn-2",
        "amount": 12.5,
        "currency": "USD",
        "lineItems": [{"title": "Coffee", "quantity": 2}],
        "location": {"id": "reg-1", "name": "Register 1"},
        "paymentTypes": ["card"],
        "timestamp": timestamp,
    }


@pytest.mark.asyncio()
async def test_create_pos_transaction_public_duplicate_not_created(
    protect_client: ProtectApiClient,
) -> None:
    """A repeated ``external_id`` echoes the already-ingested event id."""
    protect_client.api_request_obj = AsyncMock(
        return_value={"created": False, "eventId": "evt-1"}
    )

    result = await protect_client.create_pos_transaction_public(
        CAMERA_ID,
        type=PosTransactionType.SALE,
        external_id="txn-1",
        amount=12.5,
    )

    assert result.created is False
    assert result.event_id == "evt-1"


@pytest.mark.asyncio()
async def test_create_pos_transaction_public_conflict_raises(
    protect_client: ProtectApiClient,
) -> None:
    """The server's documented 409 on a concurrent repeat surfaces as ``BadRequest``."""
    response = Mock()
    response.status = HTTPStatus.CONFLICT.value
    response.url = "https://test.com/v1/pos/cameras/x/transactions"
    with (
        patch("uiprotect.api.get_response_reason", return_value="Conflict"),
        pytest.raises(BadRequest),
    ):
        await protect_client._raise_for_status(response, raise_exception=True)

    protect_client.api_request_obj = AsyncMock(
        side_effect=BadRequest("Request failed: 409 - Conflict")
    )
    with pytest.raises(BadRequest, match="409"):
        await protect_client.create_pos_transaction_public(
            CAMERA_ID,
            type=PosTransactionType.SALE,
            external_id="txn-1",
            amount=12.5,
        )
