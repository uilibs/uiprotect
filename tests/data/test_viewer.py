# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, Mock

import orjson
import pytest

from tests.conftest import TEST_VIEWPORT_EXISTS
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.public_devices import PublicLiveview, PublicViewer
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient
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


def _public_liveview(liveview_id: str, name: str) -> PublicLiveview:
    return PublicLiveview.from_unifi_dict(
        id=liveview_id,
        modelKey="liveview",
        name=name,
        isDefault=False,
        isGlobal=True,
        owner="user-1",
        layout=1,
        slots=[{"cameras": [], "cycleMode": "motion", "cycleInterval": 10}],
    )


def _prime_liveviews(client: ProtectApiClient) -> None:
    client._public_bootstrap = PublicBootstrap()
    client._public_bootstrap.liveviews = {
        "lv-1": _public_liveview("lv-1", "Garage"),
        "lv-2": _public_liveview("lv-2", "Front"),
    }


def _devices_ws(data: dict[str, Any]) -> MagicMock:
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = orjson.dumps(data)
    return msg


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


@pytest.mark.parametrize(
    ("liveview_id", "expected_name"),
    [("lv-1", "Garage"), ("lv-2", "Front"), (None, None), ("personal-lv", None)],
)
def test_public_viewer_liveview_resolves(
    protect_client_no_debug: ProtectApiClient,
    liveview_id: str | None,
    expected_name: str | None,
) -> None:
    _prime_liveviews(protect_client_no_debug)
    viewer = PublicViewer.from_unifi_dict(
        api=protect_client_no_debug,
        **_public_viewer_response(liveview=liveview_id).unifi_dict(),
    )

    liveview = viewer.liveview

    if expected_name is None:
        assert liveview is None
    else:
        assert (
            liveview is protect_client_no_debug.public_bootstrap.liveviews[liveview_id]
        )
        assert liveview.name == expected_name


def test_public_viewer_liveview_without_public_bootstrap(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    protect_client_no_debug._public_bootstrap = None
    viewer = PublicViewer.from_unifi_dict(
        api=protect_client_no_debug,
        **_public_viewer_response().unifi_dict(),
    )

    assert viewer.liveview is None


def test_public_viewer_liveview_follows_devices_ws_update(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime_liveviews(client)
    raw = _public_viewer_response().unifi_dict()

    client._process_devices_ws_message(_devices_ws({"type": "add", "item": raw}))
    viewer = client.public_bootstrap.viewers["viewer-1"]
    assert viewer.liveview is client.public_bootstrap.liveviews["lv-1"]

    client._process_devices_ws_message(
        _devices_ws(
            {
                "type": "update",
                "item": {"id": "viewer-1", "modelKey": "viewer", "liveview": "lv-2"},
            }
        )
    )

    assert viewer is client.public_bootstrap.viewers["viewer-1"]
    assert viewer.liveview is client.public_bootstrap.liveviews["lv-2"]
    assert viewer.liveview.name == "Front"
