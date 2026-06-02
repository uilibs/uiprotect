"""
Tests for the Public API ``disable-mic-permanently`` camera endpoint.

Mock-only: the underlying action is irreversible on real hardware, so it must
never be exercised against a captured fixture or a live device.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock, patch

import pytest

from uiprotect.data import Camera

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient

CAMERA_ID = "6878d82800215803e45928e1"


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Camera.from_unifi_dict")
async def test_disable_camera_mic_permanently_public_posts_correct_url(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_cam = Mock(spec=Camera)
    mock_cam.id = CAMERA_ID
    mock_create.return_value = mock_cam
    protect_client.api_request_obj = AsyncMock(return_value={"id": CAMERA_ID})

    result = await protect_client.disable_camera_mic_permanently_public(CAMERA_ID)

    assert result is mock_cam
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/cameras/{CAMERA_ID}/disable-mic-permanently",
        method="post",
        public_api=True,
    )
    # No body is sent — ``json=`` must not be passed.
    assert "json" not in protect_client.api_request_obj.call_args.kwargs


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Camera.from_unifi_dict")
async def test_disable_camera_mic_permanently_public_returns_camera(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    mock_cam = Mock(spec=Camera)
    mock_cam.id = CAMERA_ID
    mock_create.return_value = mock_cam
    protect_client.api_request_obj = AsyncMock(return_value={"id": CAMERA_ID})

    result = await protect_client.disable_camera_mic_permanently_public(CAMERA_ID)

    assert result.id == CAMERA_ID
    mock_create.assert_called_once_with(id=CAMERA_ID, api=protect_client)
