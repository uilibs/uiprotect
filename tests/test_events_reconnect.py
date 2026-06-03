"""Phase 5 events-WS reconnect tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

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


def _push_started(
    api: ProtectApiClient, dispatcher: EventDispatcher, *, age: timedelta
) -> str:
    start = datetime.now(tz=UTC) - age
    ev = Event(
        api=api,
        id=f"e-{int(start.timestamp())}",
        type=EventType.MOTION,
        start=start,
        device_id="cam-1",
    )
    dispatcher.dispatch(WSAction.ADD, ev)
    return ev.id


@pytest.mark.asyncio
async def test_reconnect_flushes_stale_entries() -> None:
    api = _make_client()
    api._public_bootstrap = PublicBootstrap()
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher = EventDispatcher(api)
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))
    api._event_dispatcher = dispatcher

    _push_started(api, dispatcher, age=timedelta(hours=2))
    _push_started(api, dispatcher, age=timedelta(seconds=30))
    assert len(dispatcher.active_events()) == 2

    received.clear()
    api._events_ws_has_been_connected = True
    api.get_ulp_users_public = AsyncMock(return_value=[])  # type: ignore[method-assign]
    api._on_events_websocket_state_change(WebsocketState.CONNECTED)

    # The 2h entry was flushed; the 30s entry survived.
    assert len(dispatcher.active_events()) == 1
    assert [c for _, c in received] == [EventChange.ENDED]


@pytest.mark.asyncio
async def test_first_connect_is_not_treated_as_reconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    api._public_bootstrap = PublicBootstrap()
    dispatcher = EventDispatcher(api)
    api._event_dispatcher = dispatcher

    api.get_ulp_users_public = AsyncMock(return_value=[])  # type: ignore[method-assign]
    with caplog.at_level("WARNING", logger="uiprotect.api"):
        api._on_events_websocket_state_change(WebsocketState.CONNECTED)
    assert not any("reconnected" in r.message for r in caplog.records)
    assert api._events_ws_has_been_connected is True


@pytest.mark.asyncio
async def test_reconnect_warning_logged_and_ulp_refreshed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    api._public_bootstrap = PublicBootstrap()
    dispatcher = EventDispatcher(api)
    api._event_dispatcher = dispatcher
    _push_started(api, dispatcher, age=timedelta(hours=2))
    api._events_ws_has_been_connected = True
    refresh_mock: Any = AsyncMock(return_value=[])
    api.get_ulp_users_public = refresh_mock  # type: ignore[method-assign]

    with caplog.at_level("WARNING", logger="uiprotect.api"):
        api._on_events_websocket_state_change(WebsocketState.CONNECTED)
    assert sum("reconnected" in r.message for r in caplog.records) == 1
    # Give the scheduled task a moment to run.
    await asyncio.sleep(0)
    refresh_mock.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_with_no_stale_entries_skips_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    api._public_bootstrap = PublicBootstrap()
    dispatcher = EventDispatcher(api)
    api._event_dispatcher = dispatcher
    _push_started(api, dispatcher, age=timedelta(seconds=30))
    api._events_ws_has_been_connected = True
    refresh_mock: Any = AsyncMock(return_value=[])
    api.get_ulp_users_public = refresh_mock  # type: ignore[method-assign]

    with caplog.at_level("WARNING", logger="uiprotect.api"):
        api._on_events_websocket_state_change(WebsocketState.CONNECTED)
    assert not any("reconnected" in r.message for r in caplog.records)
    # ULP refresh still scheduled on every reconnect.
    await asyncio.sleep(0)
    refresh_mock.assert_called_once()
