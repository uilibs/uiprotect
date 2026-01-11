# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr, method-assign"
"""Tests for Chime Public API methods."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from tests.conftest import TEST_CAMERA_EXISTS, TEST_CHIME_EXISTS
from uiprotect.api import PublicApiChimeRingSettingRequest
from uiprotect.data import RingSetting
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient
    from uiprotect.data import Camera, Chime

CHIME_ID = "6878d82800155803e45928e0"
CAMERA_ID = "6878d82800215803e45928e1"
RINGTONE_ID = "67ececbd02fe9603e40003f0"


# =============================================================================
# GET CHIMES TESTS
# =============================================================================


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_get_chimes_public_success(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test successful chimes retrieval from public API."""
    mock_chime1 = Mock()
    mock_chime1.id = CHIME_ID
    mock_chime1.name = "Chime 1"

    mock_chime2 = Mock()
    mock_chime2.id = "other-chime-id"
    mock_chime2.name = "Chime 2"

    mock_create.side_effect = [mock_chime1, mock_chime2]
    protect_client.api_request_list = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])

    result = await protect_client.get_chimes_public()

    assert result is not None
    assert len(result) == 2
    assert result[0].id == CHIME_ID
    assert result[1].id == "other-chime-id"
    protect_client.api_request_list.assert_called_with(
        url="/v1/chimes", public_api=True
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_get_chime_public_success(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test successful single chime retrieval from public API."""
    mock_chime = Mock()
    mock_chime.id = CHIME_ID
    mock_chime.name = "Smart PoE Chime"

    mock_create.return_value = mock_chime
    protect_client.api_request_obj = AsyncMock(return_value={"id": CHIME_ID})

    result = await protect_client.get_chime_public(CHIME_ID)

    assert result is not None
    assert result.id == CHIME_ID
    protect_client.api_request_obj.assert_called_with(
        url=f"/v1/chimes/{CHIME_ID}", public_api=True
    )


# =============================================================================
# UPDATE CHIME TESTS
# =============================================================================


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_update_chime_public_name_only(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating only the name of a chime via public API."""
    new_name = "Updated Chime Name"

    mock_chime = Mock()
    mock_chime.id = CHIME_ID
    mock_chime.name = new_name
    mock_create.return_value = mock_chime

    mock_chime_data: dict[str, Any] = {"id": CHIME_ID, "name": new_name}
    protect_client.api_request_obj = AsyncMock(return_value=mock_chime_data)

    result = await protect_client.update_chime_public(CHIME_ID, name=new_name)

    assert result is not None
    assert result.name == new_name
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/chimes/{CHIME_ID}",
        method="patch",
        json={"name": new_name},
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_update_chime_public_camera_ids(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating camera_ids via public API."""
    camera_ids = [CAMERA_ID, "camera-2"]

    mock_chime = Mock()
    mock_chime.id = CHIME_ID
    mock_create.return_value = mock_chime

    mock_chime_data: dict[str, Any] = {"id": CHIME_ID, "cameraIds": camera_ids}
    protect_client.api_request_obj = AsyncMock(return_value=mock_chime_data)

    result = await protect_client.update_chime_public(CHIME_ID, camera_ids=camera_ids)

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/chimes/{CHIME_ID}",
        method="patch",
        json={"cameraIds": camera_ids},
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_update_chime_public_ring_settings(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating ring_settings via public API."""
    ring_settings: list[PublicApiChimeRingSettingRequest] = [
        {
            "cameraId": CAMERA_ID,
            "volume": 80,
            "repeatTimes": 2,
            "ringtoneId": RINGTONE_ID,
        }
    ]

    mock_chime = Mock()
    mock_chime.id = CHIME_ID
    mock_create.return_value = mock_chime

    mock_chime_data: dict[str, Any] = {"id": CHIME_ID, "ringSettings": ring_settings}
    protect_client.api_request_obj = AsyncMock(return_value=mock_chime_data)

    result = await protect_client.update_chime_public(
        CHIME_ID, ring_settings=ring_settings
    )

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/chimes/{CHIME_ID}",
        method="patch",
        json={"ringSettings": ring_settings},
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_update_chime_public_all_parameters(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating all chime parameters via public API."""
    new_name = "Full Update Chime"
    camera_ids = [CAMERA_ID]
    ring_settings: list[PublicApiChimeRingSettingRequest] = [
        {
            "cameraId": CAMERA_ID,
            "volume": 50,
            "repeatTimes": 3,
            "ringtoneId": RINGTONE_ID,
        }
    ]

    mock_chime = Mock()
    mock_chime.id = CHIME_ID
    mock_chime.name = new_name
    mock_create.return_value = mock_chime

    mock_chime_data: dict[str, Any] = {
        "id": CHIME_ID,
        "name": new_name,
        "cameraIds": camera_ids,
        "ringSettings": ring_settings,
    }
    protect_client.api_request_obj = AsyncMock(return_value=mock_chime_data)

    result = await protect_client.update_chime_public(
        CHIME_ID,
        name=new_name,
        camera_ids=camera_ids,
        ring_settings=ring_settings,
    )

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/chimes/{CHIME_ID}",
        method="patch",
        json={
            "name": new_name,
            "cameraIds": camera_ids,
            "ringSettings": ring_settings,
        },
        public_api=True,
    )


@pytest.mark.asyncio()
async def test_update_chime_public_no_parameters(
    protect_client: ProtectApiClient,
) -> None:
    """Test that update_chime_public raises BadRequest without parameters."""
    with pytest.raises(BadRequest, match="At least one parameter must be provided"):
        await protect_client.update_chime_public(CHIME_ID)


# =============================================================================
# CHIME DEVICE METHOD TESTS (set_ring_settings_public, set_volume_for_camera_public)
# =============================================================================


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_ring_settings_public(
    chime_obj: Chime | None,
    camera_obj: Camera | None,
) -> None:
    """Test set_ring_settings_public updates ring settings via public API."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    # Setup initial state
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=1,  # type: ignore[arg-type]
            ringtone_id=RINGTONE_ID,
            volume=50,
        ),
    ]

    # Mock the API response
    updated_chime = Mock()
    updated_chime.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=3,  # type: ignore[arg-type]
            ringtone_id=RINGTONE_ID,
            volume=80,
        ),
    ]
    chime_obj.api.update_chime_public = AsyncMock(return_value=updated_chime)

    # Call method
    ring_settings_update = [
        {
            "cameraId": camera_obj.id,
            "volume": 80,
            "repeatTimes": 3,
            "ringtoneId": RINGTONE_ID,
        }
    ]
    await chime_obj.set_ring_settings_public(ring_settings_update)

    # Verify API was called correctly
    chime_obj.api.update_chime_public.assert_called_once_with(
        chime_obj.id,
        ring_settings=ring_settings_update,
    )

    # Verify local state was updated
    assert chime_obj.ring_settings[0].volume == 80
    assert chime_obj.ring_settings[0].repeat_times == 3


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_volume_for_camera_public(
    chime_obj: Chime | None,
    camera_obj: Camera | None,
) -> None:
    """Test set_volume_for_camera_public sets volume for specific camera."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    # Setup initial state
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=2,  # type: ignore[arg-type]
            ringtone_id=RINGTONE_ID,
            volume=50,
        ),
    ]

    # Mock the API response
    updated_chime = Mock()
    updated_chime.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=2,  # type: ignore[arg-type]
            ringtone_id=RINGTONE_ID,
            volume=80,
        ),
    ]
    chime_obj.api.update_chime_public = AsyncMock(return_value=updated_chime)

    # Call method
    await chime_obj.set_volume_for_camera_public(camera_obj, 80)

    # Verify API was called with correct ring_settings
    chime_obj.api.update_chime_public.assert_called_once()
    call_args = chime_obj.api.update_chime_public.call_args
    assert call_args[0][0] == chime_obj.id
    ring_settings = call_args[1]["ring_settings"]
    assert len(ring_settings) == 1
    assert ring_settings[0]["cameraId"] == camera_obj.id
    assert ring_settings[0]["volume"] == 80
    assert ring_settings[0]["repeatTimes"] == 2
    assert ring_settings[0]["ringtoneId"] == RINGTONE_ID


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_volume_for_camera_public_not_paired(
    chime_obj: Chime | None,
    camera_obj: Camera | None,
) -> None:
    """Test set_volume_for_camera_public raises BadRequest for unpaired camera."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    # Setup with different camera
    chime_obj.ring_settings = [
        RingSetting(
            camera_id="other-camera-id",
            repeat_times=1,  # type: ignore[arg-type]
            ringtone_id=RINGTONE_ID,
            volume=50,
        ),
    ]

    with pytest.raises(BadRequest):
        await chime_obj.set_volume_for_camera_public(camera_obj, 80)


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_volume_for_camera_public_multiple_cameras(
    chime_obj: Chime | None,
    camera_obj: Camera | None,
) -> None:
    """Test set_volume_for_camera_public preserves settings for other cameras."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    other_camera_id = "other-doorbell-camera"

    # Setup with multiple cameras
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=2,  # type: ignore[arg-type]
            ringtone_id=RINGTONE_ID,
            volume=50,
        ),
        RingSetting(
            camera_id=other_camera_id,
            repeat_times=1,  # type: ignore[arg-type]
            ringtone_id="other-ringtone",
            volume=70,
        ),
    ]

    # Mock the API response
    updated_chime = Mock()
    updated_chime.ring_settings = chime_obj.ring_settings
    chime_obj.api.update_chime_public = AsyncMock(return_value=updated_chime)

    # Call method for first camera
    await chime_obj.set_volume_for_camera_public(camera_obj, 90)

    # Verify both cameras included in API call
    call_args = chime_obj.api.update_chime_public.call_args
    ring_settings = call_args[1]["ring_settings"]
    assert len(ring_settings) == 2

    # Find the settings for each camera
    target_setting = next(s for s in ring_settings if s["cameraId"] == camera_obj.id)
    other_setting = next(s for s in ring_settings if s["cameraId"] == other_camera_id)

    # Target camera should have new volume
    assert target_setting["volume"] == 90
    assert target_setting["repeatTimes"] == 2

    # Other camera should be unchanged
    assert other_setting["volume"] == 70
    assert other_setting["repeatTimes"] == 1


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
@pytest.mark.parametrize("invalid_level", [-1, 101, 200])
async def test_chime_set_volume_for_camera_public_invalid_level(
    chime_obj: Chime | None,
    camera_obj: Camera | None,
    invalid_level: int,
) -> None:
    """Test set_volume_for_camera_public raises ValidationError for invalid level."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=1,  # type: ignore[arg-type]
            ringtone_id=RINGTONE_ID,
            volume=50,
        ),
    ]

    with pytest.raises(ValidationError):
        await chime_obj.set_volume_for_camera_public(camera_obj, invalid_level)


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_ring_setting_to_api_dict_omits_none_ringtone_id(
    chime_obj: Chime | None,
    camera_obj: Camera | None,
) -> None:
    """Test that to_api_dict omits ringtoneId when it's None."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    ring_setting = RingSetting(
        camera_id=camera_obj.id,
        repeat_times=2,  # type: ignore[arg-type]
        ringtone_id=None,
        volume=50,
    )

    result = ring_setting.to_api_dict()

    assert "cameraId" in result
    assert "volume" in result
    assert "repeatTimes" in result
    assert "ringtoneId" not in result


# =============================================================================
# PLAY_SPEAKER EDGE CASE TESTS
# =============================================================================


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play_with_volume_minimum(chime_obj: Chime | None) -> None:
    """Test that volume=1 (minimum in Protect UI) is properly handled."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")

    chime_obj.volume = 100
    chime_obj.repeat_times = 1
    chime_obj.api.api_request.reset_mock()

    await chime_obj.play(volume=1)

    # volume=1 should be sent, not ignored or replaced with default
    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json={
            "volume": 1,
            "repeatTimes": 1,
        },
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play_with_ringtone_id(chime_obj: Chime | None) -> None:
    """Test playing chime with specific ringtone_id."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")

    chime_obj.volume = 50
    chime_obj.repeat_times = 2
    chime_obj.api.api_request.reset_mock()

    await chime_obj.play(ringtone_id=RINGTONE_ID)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json={
            "volume": 50,
            "repeatTimes": 2,
            "ringtoneId": RINGTONE_ID,
        },
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_play_speaker_track_no_deprecation_warning(
    chime_obj: Chime | None,
) -> None:
    """Test that using track_no emits a deprecation warning."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")

    chime_obj.volume = 50
    chime_obj.repeat_times = 1
    chime_obj.api.api_request.reset_mock()

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await chime_obj._api.play_speaker(chime_obj.id, track_no=1)

        # Check deprecation warning was raised
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "track_no is deprecated" in str(w[0].message)

    # trackNo should still be sent
    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json={
            "volume": 50,
            "repeatTimes": 1,
            "trackNo": 1,
        },
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play_track_no_deprecation_warning(
    chime_obj: Chime | None,
) -> None:
    """Test that Chime.play() with track_no emits a deprecation warning."""
    if chime_obj is None:
        pytest.skip("No chime_obj found")

    chime_obj.volume = 50
    chime_obj.repeat_times = 1
    chime_obj.api.api_request.reset_mock()

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await chime_obj.play(track_no=1)

        # Check deprecation warning was raised (from play() and play_speaker())
        assert len(w) >= 1
        deprecation_warnings = [
            warning for warning in w if issubclass(warning.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) >= 1
        assert any(
            "track_no is deprecated" in str(warning.message)
            for warning in deprecation_warnings
        )

    # trackNo should still be sent
    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json={
            "volume": 50,
            "repeatTimes": 1,
            "trackNo": 1,
        },
    )
