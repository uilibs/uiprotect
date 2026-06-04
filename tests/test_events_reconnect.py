"""Reconnect-sweep tests for the public events contract (single store)."""

from __future__ import annotations

import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.types import EventType
from uiprotect.data.websocket import WSAction
from uiprotect.events import EventChange, ProtectEvent
from uiprotect.events.dispatcher import EventDispatcher
from uiprotect.websocket import WebsocketState


def _make_client() -> ProtectApiClient:
    return ProtectApiClient(
        host="127.0.0.1",
        port=443,
        username="u",
        password="p",  # noqa: S106
        verify_ssl=False,
        store_sessions=False,
    )


def _store_started(
    api: ProtectApiClient, *, age: timedelta, event_id: str | None = None
) -> str:
    start = datetime.now(tz=UTC) - age
    eid = event_id or f"e-{int(start.timestamp() * 1000)}"
    ev = Event(
        api=api,
        id=eid,
        type=EventType.MOTION,
        start=start,
        device_id="cam-1",
    )
    api.public_bootstrap.events[eid] = ev
    return eid


def _wire(api: ProtectApiClient) -> list[tuple[ProtectEvent, EventChange]]:
    api._public_bootstrap = PublicBootstrap()
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher = EventDispatcher(api)
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))
    api._event_dispatcher = dispatcher
    # Mark devices WS already connected and suppress the resync (debounced)
    # so only the sweep runs in these unit tests.
    api._devices_ws_has_been_connected = True
    api._last_public_resync = time.monotonic()
    return received


@pytest.mark.asyncio
async def test_reconnect_flushes_stale_entries() -> None:
    api = _make_client()
    received = _wire(api)
    _store_started(api, age=timedelta(hours=2), event_id="stale")
    fresh = _store_started(api, age=timedelta(seconds=30), event_id="fresh")

    api._on_devices_websocket_state_change(WebsocketState.CONNECTED)

    assert [c for _, c in received] == [EventChange.ENDED]
    # The 2h entry is now closed in the store; the 30s entry survives open.
    assert api.public_bootstrap.events["stale"].end is not None
    assert api.public_bootstrap.events[fresh].end is None
    assert [e.id for e in api._event_dispatcher.active_events()] == ["fresh"]


@pytest.mark.asyncio
async def test_reconnect_swept_entry_not_refired_on_close_retransmit() -> None:
    api = _make_client()
    received = _wire(api)
    _store_started(api, age=timedelta(hours=2), event_id="stale")

    api._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert [c for _, c in received] == [EventChange.ENDED]

    # A later real close retransmit for the same id: the stored event already
    # carries ``end`` (sweep marked it), so the chokepoint suppresses it.
    received.clear()
    stored = api.public_bootstrap.events["stale"]
    snapshot = stored.model_copy()  # already terminal
    api._event_dispatcher.dispatch(WSAction.UPDATE, stored, snapshot)
    assert received == []


@pytest.mark.asyncio
async def test_first_connect_is_not_treated_as_reconnect() -> None:
    api = _make_client()
    api._public_bootstrap = PublicBootstrap()
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher = EventDispatcher(api)
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))
    api._event_dispatcher = dispatcher
    api.public_bootstrap.events = OrderedDict()
    _store_started(api, age=timedelta(hours=2), event_id="stale")

    # First connect: not a reconnect, so no sweep.
    api._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert api._devices_ws_has_been_connected is True
    assert received == []


@pytest.mark.asyncio
async def test_reconnect_warning_logged_when_entries_swept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    _wire(api)
    _store_started(api, age=timedelta(hours=2), event_id="stale")

    with caplog.at_level("WARNING", logger="uiprotect.api"):
        api._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert sum("reconnected" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_reconnect_with_no_stale_entries_skips_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    _wire(api)
    _store_started(api, age=timedelta(seconds=30), event_id="fresh")

    with caplog.at_level("WARNING", logger="uiprotect.api"):
        api._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert not any("reconnected" in r.message for r in caplog.records)
