"""Tests for the typed public device-state contract (``subscribe_devices``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import orjson
import pytest

from uiprotect.data.public_bootstrap import DeviceWSResult, PublicBootstrap
from uiprotect.data.public_devices import PublicCamera
from uiprotect.data.types import ModelType
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.devices import DeviceChange, ProtectDeviceChange
from uiprotect.devices.dispatcher import DeviceDispatcher

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient

CAMERA_ID = "cam-1"
CAMERA_MAC = "AABBCCDDEEFF"


def _camera_payload(cam_id: str = CAMERA_ID, **over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": cam_id,
        "modelKey": "camera",
        "state": "CONNECTED",
        "name": "Test Camera",
        "mac": CAMERA_MAC,
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
        "smartDetectSettings": {
            "objectTypes": ["person"],
            "audioTypes": ["alrmSmoke"],
        },
        "hasPackageCamera": False,
    }
    payload.update(over)
    return payload


def _ws(data: dict[str, Any]) -> MagicMock:
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = orjson.dumps(data)
    return msg


def _prime(client: ProtectApiClient) -> None:
    client._public_bootstrap = PublicBootstrap()


def _subscribe(
    client: ProtectApiClient,
) -> tuple[list[ProtectDeviceChange], Any]:
    received: list[ProtectDeviceChange] = []
    unsub = client.subscribe_devices(received.append)
    return received, unsub


# ---------------------------------------------------------------------------
# Full message-path tests (orjson frame -> dispatch -> ProtectDeviceChange)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_add_emits_added(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    client._process_devices_ws_message(_ws({"type": "add", "item": _camera_payload()}))

    assert len(received) == 1
    change = received[0]
    assert change.change is DeviceChange.ADDED
    assert change.model_type is ModelType.CAMERA
    assert change.device_id == CAMERA_ID
    assert change.device_mac == CAMERA_MAC
    assert isinstance(change.model, PublicCamera)
    assert change.changed_fields == frozenset()
    assert client.public_bootstrap.cameras[CAMERA_ID] is change.model
    unsub()


@pytest.mark.asyncio
async def test_state_update_emits_updated_with_changed_fields(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    client._process_devices_ws_message(_ws({"type": "add", "item": _camera_payload()}))
    client._process_devices_ws_message(
        _ws(
            {
                "type": "update",
                "item": {
                    "id": CAMERA_ID,
                    "modelKey": "camera",
                    "state": "DISCONNECTED",
                },
            }
        )
    )

    assert [c.change for c in received] == [
        DeviceChange.ADDED,
        DeviceChange.UPDATED,
    ]
    update = received[1]
    assert "state" in update.changed_fields
    assert update.model is client.public_bootstrap.cameras[CAMERA_ID]
    unsub()


@pytest.mark.asyncio
async def test_multi_field_update_changed_fields(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    client._process_devices_ws_message(_ws({"type": "add", "item": _camera_payload()}))
    client._process_devices_ws_message(
        _ws(
            {
                "type": "update",
                "item": {
                    "id": CAMERA_ID,
                    "modelKey": "camera",
                    "state": "DISCONNECTED",
                    "name": "Renamed",
                },
            }
        )
    )

    update = received[1]
    assert {"state", "name"} <= update.changed_fields
    unsub()


@pytest.mark.asyncio
async def test_remove_emits_removed(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    client._process_devices_ws_message(_ws({"type": "add", "item": _camera_payload()}))
    client._process_devices_ws_message(
        _ws({"type": "remove", "item": {"id": CAMERA_ID, "modelKey": "camera"}})
    )

    removed = received[-1]
    assert removed.change is DeviceChange.REMOVED
    assert removed.device_id == CAMERA_ID
    assert removed.model is None
    assert removed.device_mac == CAMERA_MAC
    assert CAMERA_ID not in client.public_bootstrap.cameras
    unsub()


@pytest.mark.asyncio
async def test_bulk_add_expands_per_id(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    ids = ["cam-a", "cam-b", "cam-c"]
    item = _camera_payload()
    item["id"] = ids
    client._process_devices_ws_message(_ws({"type": "add", "item": item}))

    assert len(received) == 3
    assert {c.device_id for c in received} == set(ids)
    assert all(c.change is DeviceChange.ADDED for c in received)
    assert set(client.public_bootstrap.cameras) == set(ids)
    unsub()


@pytest.mark.asyncio
async def test_bulk_single_element_id_is_one_change(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    item = _camera_payload()
    item["id"] = [CAMERA_ID]
    client._process_devices_ws_message(_ws({"type": "add", "item": item}))

    assert len(received) == 1
    assert received[0].device_id == CAMERA_ID
    unsub()


@pytest.mark.asyncio
async def test_empty_id_array_emits_nothing(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    item = _camera_payload()
    item["id"] = []
    client._process_devices_ws_message(_ws({"type": "add", "item": item}))

    assert received == []
    unsub()


@pytest.mark.asyncio
async def test_update_for_uncached_id_dropped(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    client._process_devices_ws_message(
        _ws(
            {
                "type": "update",
                "item": {"id": "ghost", "modelKey": "camera", "state": "OFFLINE"},
            }
        )
    )

    assert received == []
    unsub()


@pytest.mark.asyncio
async def test_remove_unsupported_model_dropped(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    received, unsub = _subscribe(client)

    client._process_devices_ws_message(
        _ws({"type": "remove", "item": {"id": "dl-1", "modelKey": "doorlock"}})
    )

    assert received == []
    unsub()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_requires_public_bootstrap(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    client._public_bootstrap = None
    with pytest.raises(RuntimeError, match="update_public"):
        client.subscribe_devices(lambda c: None)


@pytest.mark.asyncio
async def test_subscribe_reference_counted(
    protect_client_no_debug: ProtectApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = protect_client_no_debug
    _prime(client)

    starts: list[None] = []
    stops: list[None] = []

    class _WS:
        def start(self) -> None:
            starts.append(None)

        def stop(self) -> None:
            stops.append(None)

    ws = _WS()
    monkeypatch.setattr(client, "_get_devices_websocket", lambda: ws)

    unsub_a = client.subscribe_devices(lambda c: None)
    unsub_b = client.subscribe_devices(lambda c: None)

    assert len(starts) == 1
    assert client._device_dispatcher is not None
    assert client._device_dispatcher.subscriber_count == 2

    unsub_a()
    assert stops == []
    unsub_b()
    assert len(stops) == 1
    assert client._device_dispatcher.subscriber_count == 0
    # Idempotent double-unsubscribe must not raise.
    unsub_b()


def test_unsubscribe_without_dispatcher_is_noop(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    client._device_dispatcher = None
    client._unsubscribe_devices(lambda c: None)


# ---------------------------------------------------------------------------
# Façade parity + dispatcher-direct behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_singular_facade_returns_first_tuple(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    bootstrap = PublicBootstrap()
    data = {"type": "add", "item": _camera_payload()}

    model_type, new_obj, old_obj = bootstrap.process_devices_ws_message(client, data)

    assert model_type is ModelType.CAMERA
    assert isinstance(new_obj, PublicCamera)
    assert old_obj is None


@pytest.mark.asyncio
async def test_plural_returns_one_result_per_id(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    bootstrap = PublicBootstrap()
    item = _camera_payload()
    item["id"] = ["cam-a", "cam-b"]

    results = bootstrap.process_devices_ws_messages(
        client, {"type": "add", "item": item}
    )

    assert [r.item["id"] for r in results] == ["cam-a", "cam-b"]
    assert all(isinstance(r, DeviceWSResult) for r in results)


def test_dispatch_raising_callback_is_isolated(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    client = protect_client_no_debug
    _prime(client)
    dispatcher = DeviceDispatcher(client)

    seen: list[ProtectDeviceChange] = []

    def boom(_change: ProtectDeviceChange) -> None:
        raise ValueError("boom")

    dispatcher.add_subscriber(boom)
    dispatcher.add_subscriber(seen.append)

    camera = PublicCamera.from_unifi_dict(api=client, **_camera_payload())
    client.public_bootstrap.cameras[CAMERA_ID] = camera
    msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id=CAMERA_ID,
        changed_data={"id": CAMERA_ID, "modelKey": "camera"},
        new_obj=camera,
    )
    dispatcher.dispatch(msg)

    assert len(seen) == 1
    assert seen[0].change is DeviceChange.ADDED


def test_dispatch_generic_model_type(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """A model type with no per-type allowlist still dispatches."""
    client = protect_client_no_debug
    _prime(client)
    dispatcher = DeviceDispatcher(client)
    seen: list[ProtectDeviceChange] = []
    dispatcher.add_subscriber(seen.append)

    camera = PublicCamera.from_unifi_dict(api=client, **_camera_payload("siren-1"))
    msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id="siren-1",
        changed_data={"id": "siren-1", "modelKey": "siren"},
        new_obj=camera,
    )
    dispatcher.dispatch(msg)

    assert len(seen) == 1
    assert seen[0].model_type is ModelType.SIREN
    assert seen[0].device_id == "siren-1"
