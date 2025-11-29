"""Tests for Light Public API methods."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from uiprotect.data.devices import (
    LightDeviceSettings,
    LightModeEnableType,
    LightModeSettings,
    LightModeType,
)
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient

LIGHT_ID = "663d0aa401218803e4000449"


# GET LIGHTS TESTS


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_get_lights_public_success(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test successful lights retrieval from public API."""
    mock_light1 = Mock()
    mock_light1.id = "663d0aa401218803e4000449"
    mock_light1.name = "Light 1"

    mock_light2 = Mock()
    mock_light2.id = "663d0aa401218803e4000450"
    mock_light2.name = "Light 2"

    mock_create.side_effect = [mock_light1, mock_light2]
    protect_client.api_request_list = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])  # type: ignore[method-assign]

    result = await protect_client.get_lights_public()

    assert result is not None
    assert len(result) == 2
    assert result[0].id == "663d0aa401218803e4000449"
    assert result[1].id == "663d0aa401218803e4000450"
    protect_client.api_request_list.assert_called_with(
        url="/v1/lights", public_api=True
    )  # type: ignore[attr-defined]


@pytest.mark.asyncio()
async def test_get_lights_public_error(
    protect_client: ProtectApiClient,
) -> None:
    """Test lights retrieval error handling."""
    protect_client.api_request_list = AsyncMock(side_effect=Exception("API Error"))  # type: ignore[method-assign]

    with pytest.raises(Exception, match="API Error"):
        await protect_client.get_lights_public()

    protect_client.api_request_list.assert_called_with(
        url="/v1/lights", public_api=True
    )  # type: ignore[attr-defined]


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_get_light_public_success(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test successful single light retrieval from public API."""
    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_light.name = "Light 1"

    mock_create.return_value = mock_light
    protect_client.api_request_obj = AsyncMock(return_value={"id": "test"})  # type: ignore[method-assign]

    result = await protect_client.get_light_public(LIGHT_ID)

    assert result is not None
    assert result.id == LIGHT_ID
    assert result.name == "Light 1"
    protect_client.api_request_obj.assert_called_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}", public_api=True
    )


@pytest.mark.asyncio()
async def test_get_light_public_error(
    protect_client: ProtectApiClient,
) -> None:
    """Test single light retrieval error handling."""
    protect_client.api_request_obj = AsyncMock(side_effect=Exception("API Error"))  # type: ignore[method-assign]

    with pytest.raises(Exception, match="API Error"):
        await protect_client.get_light_public(LIGHT_ID)

    protect_client.api_request_obj.assert_called_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}", public_api=True
    )


# UPDATE LIGHT TESTS


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_name_only(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating only the name of a light via public API."""
    new_name = "Updated Light Name"

    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_light.name = new_name
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {"id": LIGHT_ID, "name": new_name}
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(LIGHT_ID, name=new_name)

    assert result is not None
    assert result.id == LIGHT_ID
    assert result.name == new_name
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}",
        method="patch",
        json={"name": new_name},
        public_api=True,
    )
    mock_create.assert_called_once_with(**mock_light_data, api=protect_client)


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_force_enabled(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating force enabled setting."""
    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {"id": LIGHT_ID, "isLightForceEnabled": True}
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(
        LIGHT_ID, is_light_force_enabled=True
    )

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}",
        method="patch",
        json={"isLightForceEnabled": True},
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_light_mode_settings(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating light mode settings."""
    light_mode_settings = LightModeSettings(
        mode=LightModeType.MOTION,
        enable_at=LightModeEnableType.DARK,
    )

    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {
        "id": LIGHT_ID,
        "lightModeSettings": {
            "mode": "motion",
            "enableAt": "dark",
        },
    }
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(
        LIGHT_ID, light_mode_settings=light_mode_settings
    )

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}",
        method="patch",
        json={
            "lightModeSettings": {
                "mode": "motion",
                "enableAt": "dark",
            }
        },
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_light_device_settings(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating light device settings."""
    light_device_settings = LightDeviceSettings(
        is_indicator_enabled=True,
        led_level=6,
        pir_duration=timedelta(seconds=60),
        pir_sensitivity=80,
    )

    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {
        "id": LIGHT_ID,
        "lightDeviceSettings": {
            "isIndicatorEnabled": True,
            "ledLevel": 6,
            "pirDuration": 60000,
            "pirSensitivity": 80,
        },
    }
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(
        LIGHT_ID, light_device_settings=light_device_settings
    )

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}",
        method="patch",
        json={
            "lightDeviceSettings": {
                "isIndicatorEnabled": True,
                "ledLevel": 6,
                "pirDuration": 60000,
                "pirSensitivity": 80,
            }
        },
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_all_parameters(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test updating all parameters at once."""
    light_mode_settings = LightModeSettings(
        mode=LightModeType.WHEN_DARK,
        enable_at=LightModeEnableType.DARK,
    )
    light_device_settings = LightDeviceSettings(
        is_indicator_enabled=True,
        led_level=6,
        pir_duration=timedelta(seconds=60),
        pir_sensitivity=80,
    )

    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_light.name = "Complete Update"
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {
        "id": LIGHT_ID,
        "name": "Complete Update",
        "isLightForceEnabled": True,
        "lightModeSettings": {"mode": "always", "enableAt": "dark"},
        "lightDeviceSettings": {
            "isIndicatorEnabled": True,
            "ledLevel": 6,
            "pirDuration": 60000,
            "pirSensitivity": 80,
        },
    }
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(
        LIGHT_ID,
        name="Complete Update",
        is_light_force_enabled=True,
        light_mode_settings=light_mode_settings,
        light_device_settings=light_device_settings,
    )

    assert result is not None
    assert result.id == LIGHT_ID
    protect_client.api_request_obj.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio()
async def test_update_light_public_no_parameters(
    protect_client: ProtectApiClient,
) -> None:
    """Test that calling with no parameters raises BadRequest."""
    with pytest.raises(BadRequest, match="At least one parameter must be provided"):
        await protect_client.update_light_public(LIGHT_ID)


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_api_error(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test API error handling."""
    protect_client.api_request_obj = AsyncMock(side_effect=Exception("API Error"))  # type: ignore[method-assign]

    with pytest.raises(Exception, match="API Error"):
        await protect_client.update_light_public(LIGHT_ID, name="Test")


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_false_values(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test that False values are not filtered out."""
    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {"id": LIGHT_ID, "isLightForceEnabled": False}
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(
        LIGHT_ID, is_light_force_enabled=False
    )

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}",
        method="patch",
        json={"isLightForceEnabled": False},
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_partial_update(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test partial updates with subset of parameters."""
    light_mode_settings = LightModeSettings(
        mode=LightModeType.MANUAL,
        enable_at=LightModeEnableType.ALWAYS,
    )

    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {
        "id": LIGHT_ID,
        "lightModeSettings": {"mode": "off", "enableAt": "fulltime"},
    }
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(
        LIGHT_ID, light_mode_settings=light_mode_settings
    )

    assert result is not None
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url=f"/v1/lights/{LIGHT_ID}",
        method="patch",
        json={"lightModeSettings": {"mode": "off", "enableAt": "fulltime"}},
        public_api=True,
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Light.from_unifi_dict")
async def test_update_light_public_returns_light_object(
    mock_create: Mock,
    protect_client: ProtectApiClient,
) -> None:
    """Test that the method returns a proper Light object."""
    mock_light = Mock()
    mock_light.id = LIGHT_ID
    mock_light.name = "Test Light"
    mock_create.return_value = mock_light

    mock_light_data: dict[str, Any] = {"id": LIGHT_ID, "name": "Test Light"}
    protect_client.api_request_obj = AsyncMock(return_value=mock_light_data)  # type: ignore[method-assign]

    result = await protect_client.update_light_public(LIGHT_ID, name="Test Light")

    assert result is not None
    assert result.id == LIGHT_ID
    assert result.name == "Test Light"
    mock_create.assert_called_once_with(**mock_light_data, api=protect_client)
