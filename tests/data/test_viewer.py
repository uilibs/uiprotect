# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest

from tests.conftest import TEST_VIEWPORT_EXISTS
from uiprotect.data.public_devices import PublicViewer
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.data import Liveview, Viewer


def _public_viewer_response(**overrides: object) -> PublicViewer:
    raw: dict[str, object] = {
        "id": "viewer-1",
        "modelKey": "viewer",
        "state": "CONNECTED",
        "name": "Viewer 1",
        "mac": "AABBCCDDEE01",
        "liveview": "lv-1",
        "streamLimit": 16,
    }
    raw.update(overrides)
    return PublicViewer.from_unifi_dict(**raw)


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_viewer_set_liveview_invalid(viewer_obj: Viewer, liveview_obj: Liveview):
    viewer_obj.api.api_request.reset_mock()

    liveview = liveview_obj.update_from_dict({"id": "bad_id"})

    with pytest.raises(BadRequest):
        await viewer_obj.set_liveview(liveview)

    assert not viewer_obj.api.api_request.called


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_viewer_set_liveview_valid(viewer_obj: Viewer, liveview_obj: Liveview):
    viewer_obj.api.api_request.reset_mock()
    viewer_obj.api.emit_message = Mock()

    viewer_obj.liveview_id = "bad_id"

    await viewer_obj.set_liveview(liveview_obj)
    viewer_obj.api.api_request.assert_called_with(
        f"viewers/{viewer_obj.id}",
        method="patch",
        json={"liveview": liveview_obj.id},
    )

    # old/new is actually the same here since the client
    # generating the message is the one that changed it
    viewer_obj.api.emit_message.assert_called_with(
        WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=viewer_obj.api.bootstrap.last_update_id,
            changed_data={"liveview_id": liveview_obj.id},
            old_obj=viewer_obj,
            new_obj=viewer_obj,
        ),
    )


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_viewer_set_name_public(viewer_obj: Viewer) -> None:
    viewer_obj.api.update_viewer_public = AsyncMock(
        return_value=_public_viewer_response(name="Renamed"),
    )

    await viewer_obj.set_name_public("Renamed")

    viewer_obj.api.update_viewer_public.assert_awaited_once_with(
        viewer_obj.id,
        name="Renamed",
    )
    assert viewer_obj.name == "Renamed"


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_viewer_set_liveview_public(viewer_obj: Viewer) -> None:
    viewer_obj.api.update_viewer_public = AsyncMock(
        return_value=_public_viewer_response(liveview="lv-9"),
    )

    await viewer_obj.set_liveview_public("lv-9")

    viewer_obj.api.update_viewer_public.assert_awaited_once_with(
        viewer_obj.id,
        liveview="lv-9",
    )
    assert viewer_obj.liveview_id == "lv-9"


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_viewer_set_liveview_public_clear(viewer_obj: Viewer) -> None:
    viewer_obj.api.update_viewer_public = AsyncMock(
        return_value=_public_viewer_response(liveview=None),
    )

    await viewer_obj.set_liveview_public(None)

    viewer_obj.api.update_viewer_public.assert_awaited_once_with(
        viewer_obj.id,
        liveview=None,
    )
    assert viewer_obj.liveview_id == ""
