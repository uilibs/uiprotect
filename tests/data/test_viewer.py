# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from tests.conftest import TEST_VIEWPORT_EXISTS
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.data import Liveview, Viewer


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
