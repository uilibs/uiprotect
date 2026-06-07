"""Coverage for exception paths touched by the ruff EM message-extraction sweep."""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from tests.conftest import TEST_CAMERA_EXISTS
from uiprotect.data import Permission
from uiprotect.data.types import ModelType, get_field_type
from uiprotect.data.websocket import WSJSONPacketFrame
from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError, WSEncodeError
from uiprotect.utils import profile_ws

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient
    from uiprotect.data import Camera, User


def test_get_field_type_list_without_args() -> None:
    with pytest.raises(ValueError, match="Unable to determine args"):
        get_field_type(typing.List)  # noqa: UP006


def test_get_field_type_dict_without_args() -> None:
    with pytest.raises(ValueError, match="Unable to determine args"):
        get_field_type(typing.Dict)  # noqa: UP006


def test_model_type_is_immutable() -> None:
    with pytest.raises(AttributeError, match="Cannot modify ModelType"):
        ModelType.CAMERA.example = "nope"  # type: ignore[attr-defined]


def test_ws_frame_packed_without_header() -> None:
    with pytest.raises(WSEncodeError, match="No header to encode"):
        _ = WSJSONPacketFrame().packed


@pytest.mark.asyncio()
async def test_profile_ws_already_in_progress(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.bootstrap.capture_ws_stats = True
    with pytest.raises(NvrError, match="Profile already in progress"):
        await profile_ws(protect_client, 1)


@pytest.mark.asyncio()
async def test_adopt_device_not_adopted(protect_client: ProtectApiClient) -> None:
    protect_client.api_request_obj = AsyncMock(return_value={})
    with pytest.raises(BadRequest, match="Could not adopt device"):
        await protect_client.adopt_device(ModelType.CAMERA, "device_id")


@pytest.mark.asyncio()
async def test_get_versions_from_api_client_error(
    protect_client: ProtectApiClient,
) -> None:
    class _RaisingContext:
        async def __aenter__(self) -> None:
            raise aiohttp.ClientError("boom")

        async def __aexit__(self, *_: object) -> None:
            return None

    session = Mock()
    session.get = lambda _url: _RaisingContext()
    protect_client.get_session = AsyncMock(return_value=session)

    with pytest.raises(NvrError, match="Error packages from"):
        await protect_client._get_versions_from_api("http://example.test/Packages")


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_api_property_without_client(camera_obj: Camera) -> None:
    camera_obj._api = None  # type: ignore[assignment]
    with pytest.raises(BadRequest, match="API Client not initialized"):
        _ = camera_obj.api


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_save_device_changes_read_only_field(camera_obj: Camera) -> None:
    read_only = next(iter(camera_obj.__class__._get_read_only_fields()))
    before = camera_obj.model_dump()
    async with camera_obj._update_sync.lock:
        with pytest.raises(BadRequest, match="read only"):
            await camera_obj._save_device_changes(
                before, {read_only: "x"}, revert_on_fail=False
            )


def _restrict_to_read_only(camera_obj: Camera, user_obj: User) -> None:
    user_obj.all_permissions = [
        Permission.from_unifi_dict(rawPermission="camera:read:*", api=camera_obj.api),
    ]


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_reboot_without_permission(camera_obj: Camera, user_obj: User) -> None:
    _restrict_to_read_only(camera_obj, user_obj)
    with pytest.raises(NotAuthorized, match="permission to reboot"):
        await camera_obj.reboot()


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_unadopt_not_adopted(camera_obj: Camera) -> None:
    camera_obj.is_adopted = False
    with pytest.raises(BadRequest, match="Device is not adopted"):
        await camera_obj.unadopt()


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_unadopt_without_permission(camera_obj: Camera, user_obj: User) -> None:
    camera_obj.is_adopted = True
    camera_obj.is_adopted_by_other = False
    _restrict_to_read_only(camera_obj, user_obj)
    with pytest.raises(NotAuthorized, match="permission to unadopt"):
        await camera_obj.unadopt()


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_adopt_cannot_adopt(camera_obj: Camera) -> None:
    camera_obj.can_adopt = False
    with pytest.raises(BadRequest, match="Device cannot be adopted"):
        await camera_obj.adopt()


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_adopt_without_permission(camera_obj: Camera, user_obj: User) -> None:
    camera_obj.can_adopt = True
    _restrict_to_read_only(camera_obj, user_obj)
    with pytest.raises(NotAuthorized, match="permission to adopt"):
        await camera_obj.adopt()
