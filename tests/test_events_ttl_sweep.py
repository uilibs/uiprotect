"""Phase 5a TTL sweep tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.types import EventType
from uiprotect.data.websocket import WSAction
from uiprotect.events import EventChange, ProtectEvent
from uiprotect.events.dispatcher import (
    EVENTS_ACTIVE_TTL,
    EventDispatcher,
)


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
        id=f"e-{int(start.timestamp() * 1000)}",
        type=EventType.MOTION,
        start=start,
        device_id="cam-1",
    )
    dispatcher.dispatch(WSAction.ADD, ev)
    return ev.id


def test_sweep_force_ends_stale_entry() -> None:
    api = _make_client()
    dispatcher = EventDispatcher(api)
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))

    _push_started(api, dispatcher, age=EVENTS_ACTIVE_TTL + timedelta(seconds=10))
    fresh_id = _push_started(api, dispatcher, age=timedelta(seconds=30))

    received.clear()
    count = dispatcher.sweep_stale()
    assert count == 1
    assert [c for _, c in received] == [EventChange.ENDED]
    assert [e.id for e in dispatcher.active_events()] == [fresh_id]


def test_sweep_no_op_when_within_ttl() -> None:
    api = _make_client()
    dispatcher = EventDispatcher(api)
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))

    _push_started(api, dispatcher, age=timedelta(seconds=60))
    received.clear()
    assert dispatcher.sweep_stale() == 0
    assert received == []


@pytest.mark.asyncio
async def test_sweep_task_cancelled_when_last_subscriber_unsubscribes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _make_client()
    api._public_bootstrap = PublicBootstrap()
    api.get_ulp_users_public = AsyncMock(return_value=[])  # type: ignore[method-assign]

    class _WS:
        def start(self) -> None: ...
        def stop(self) -> None: ...

    ws = _WS()
    monkeypatch.setattr(api, "_get_events_websocket", lambda: ws)

    unsub = api.subscribe_events(lambda e, c: None)
    assert api._event_dispatcher is not None
    sweep_task = api._event_dispatcher._sweep_task
    assert sweep_task is not None
    assert not sweep_task.done()

    unsub()
    # Give the cancel a chance to propagate.
    await asyncio.sleep(0)
    assert api._event_dispatcher._sweep_task is None
    assert sweep_task.cancelled() or sweep_task.done()
