"""Events-WS reconnect force-ends active detection events and syncs camera state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.public_event import PublicEvent
from uiprotect.data.types import EventType
from uiprotect.events import EventChange, ProtectEvent
from uiprotect.events.dispatcher import EventDispatcher
from uiprotect.websocket import WebsocketState

from .test_public_devices_models import CAMERA_PAYLOAD

if TYPE_CHECKING:
    from uiprotect.data.websocket import WSSubscriptionMessage


def _make_client() -> ProtectApiClient:
    client = ProtectApiClient(
        host="127.0.0.1",
        port=443,
        username="u",
        password="p",  # noqa: S106
        verify_ssl=False,
        store_sessions=False,
    )
    client._public_bootstrap = PublicBootstrap()
    client.public_bootstrap.process_devices_ws_message(
        Mock(), {"type": "add", "item": dict(CAMERA_PAYLOAD)}
    )
    return client


def _capture_devices(client: ProtectApiClient) -> list[WSSubscriptionMessage]:
    updates: list[WSSubscriptionMessage] = []
    client._devices_ws_subscriptions.append(updates.append)
    return updates


def _add_motion(client: ProtectApiClient, *, age: timedelta, event_id: str) -> None:
    start_ms = int((datetime.now(tz=UTC) - age).timestamp() * 1000)
    client.public_bootstrap.process_events_ws_message(
        Mock(),
        {
            "type": "add",
            "item": {
                "modelKey": "event",
                "id": event_id,
                "type": "motion",
                "start": start_ms,
                "device": "cam1",
            },
        },
    )


def _store_sensor(client: ProtectApiClient, *, age: timedelta, event_id: str) -> None:
    start = datetime.now(tz=UTC) - age
    client.public_bootstrap.events[event_id] = PublicEvent(
        api=client,
        id=event_id,
        type=EventType.SENSOR_OPENED,
        start=start,
        device_id="sensor-1",
    )


def _reconnect(client: ProtectApiClient) -> None:
    # First CONNECTED is the initial connect; the second is the reconnect.
    client._on_events_websocket_state_change(WebsocketState.CONNECTED)
    client._on_events_websocket_state_change(WebsocketState.CONNECTED)


@pytest.mark.asyncio
async def test_reconnect_force_ends_short_gap_detection() -> None:
    """A recent motion whose END was missed clears on events-WS reconnect."""
    client = _make_client()
    cam = client.public_bootstrap.cameras["cam1"]
    dispatcher = EventDispatcher(client)
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))
    client._event_dispatcher = dispatcher
    device_updates = _capture_devices(client)

    _add_motion(client, age=timedelta(seconds=30), event_id="m1")
    assert cam.is_motion_detected is True

    _reconnect(client)

    assert cam.is_motion_detected is False
    assert client.public_bootstrap.events["m1"].end is not None
    assert [c for _, c in received] == [EventChange.ENDED]
    assert len(device_updates) == 1
    assert list(device_updates[0].changed_data) == ["is_motion_detected"]
    assert device_updates[0].new_obj is cam


@pytest.mark.asyncio
async def test_first_connect_does_not_force_end() -> None:
    """The initial events-WS connect is not treated as a reconnect."""
    client = _make_client()
    cam = client.public_bootstrap.cameras["cam1"]
    client._event_dispatcher = EventDispatcher(client)
    _add_motion(client, age=timedelta(seconds=30), event_id="m1")

    client._on_events_websocket_state_change(WebsocketState.CONNECTED)

    assert client._events_ws_has_been_connected is True
    assert cam.is_motion_detected is True
    assert client.public_bootstrap.events["m1"].end is None


@pytest.mark.asyncio
async def test_reconnect_lazily_creates_dispatcher() -> None:
    """A reconnect with no prior events subscriber still fixes camera state."""
    client = _make_client()
    cam = client.public_bootstrap.cameras["cam1"]
    device_updates = _capture_devices(client)
    _add_motion(client, age=timedelta(seconds=30), event_id="m1")
    assert client._event_dispatcher is None

    _reconnect(client)

    assert client._event_dispatcher is not None
    assert cam.is_motion_detected is False
    assert list(device_updates[0].changed_data) == ["is_motion_detected"]


@pytest.mark.asyncio
async def test_reconnect_keeps_age_gate_for_non_detection_channels() -> None:
    """Non-detection channels are only flushed once past the staleness window."""
    client = _make_client()
    client._event_dispatcher = EventDispatcher(client)
    _store_sensor(client, age=timedelta(minutes=5), event_id="fresh")
    _store_sensor(client, age=timedelta(hours=2), event_id="stale")

    _reconnect(client)

    assert client.public_bootstrap.events["fresh"].end is None
    assert client.public_bootstrap.events["stale"].end is not None


@pytest.mark.asyncio
async def test_reconnect_no_public_bootstrap_is_noop() -> None:
    """Reconnect without a materialised public cache only fans out WS state."""
    client = ProtectApiClient(
        host="127.0.0.1",
        port=443,
        username="u",
        password="p",  # noqa: S106
        verify_ssl=False,
        store_sessions=False,
    )
    states: list[WebsocketState] = []
    client.subscribe_events_websocket_state(states.append)

    _reconnect(client)

    assert client._event_dispatcher is None
    assert states == [WebsocketState.CONNECTED, WebsocketState.CONNECTED]


@pytest.mark.asyncio
async def test_reconnect_logs_warning_when_events_force_ended(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A force-end on reconnect emits a single warning naming the count."""
    client = _make_client()
    client._event_dispatcher = EventDispatcher(client)
    _add_motion(client, age=timedelta(seconds=30), event_id="m1")

    with caplog.at_level("WARNING", logger="uiprotect.api"):
        _reconnect(client)

    assert sum("reconnected after gap" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_reconnect_with_nothing_active_skips_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reconnect with no active events logs no warning."""
    client = _make_client()
    client._event_dispatcher = EventDispatcher(client)

    with caplog.at_level("WARNING", logger="uiprotect.api"):
        _reconnect(client)

    assert not any("reconnected after gap" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_reconnect_force_end_raise_still_delivers_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising force-end is logged and does not skip CONNECTED delivery."""
    client = _make_client()
    client._events_ws_has_been_connected = True
    dispatcher = EventDispatcher(client)
    dispatcher.force_end_on_events_reconnect = Mock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    client._event_dispatcher = dispatcher
    states: list[WebsocketState] = []
    client._events_ws_state_subscriptions.append(states.append)

    with caplog.at_level("ERROR", logger="uiprotect.api"):
        client._on_events_websocket_state_change(WebsocketState.CONNECTED)

    assert states == [WebsocketState.CONNECTED]
    assert any("force-ending events" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_devices_reconnect_flush_raise_still_delivers_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising devices-WS flush is logged and does not skip CONNECTED delivery."""
    client = _make_client()
    client._devices_ws_has_been_connected = True
    dispatcher = EventDispatcher(client)
    dispatcher.add_subscriber(lambda e, c: None)
    dispatcher.flush_stale_on_reconnect = Mock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    client._event_dispatcher = dispatcher
    states: list[WebsocketState] = []
    client._devices_ws_state_subscriptions.append(states.append)

    with caplog.at_level("ERROR", logger="uiprotect.api"):
        client._on_devices_websocket_state_change(WebsocketState.CONNECTED)

    assert states == [WebsocketState.CONNECTED]
    assert any("flushing stale events" in r.message for r in caplog.records)
