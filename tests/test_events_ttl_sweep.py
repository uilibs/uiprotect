"""TTL sweep tests over the single event store."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.types import EventType
from uiprotect.events import EventChange, ProtectEvent
from uiprotect.events.dispatcher import (
    EVENTS_ACTIVE_TTL,
    EventDispatcher,
)


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
    return client


def _store_started(api: ProtectApiClient, *, age: timedelta) -> str:
    start = datetime.now(tz=UTC) - age
    eid = f"e-{int(start.timestamp() * 1000)}"
    ev = Event(
        api=api,
        id=eid,
        type=EventType.MOTION,
        start=start,
        device_id="cam-1",
    )
    api.public_bootstrap.events[eid] = ev
    return eid


def test_sweep_force_ends_stale_entry() -> None:
    api = _make_client()
    dispatcher = EventDispatcher(api)
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))

    stale = _store_started(api, age=EVENTS_ACTIVE_TTL + timedelta(seconds=10))
    fresh = _store_started(api, age=timedelta(seconds=30))

    count = dispatcher.sweep_stale()
    assert count == 1
    assert [c for _, c in received] == [EventChange.ENDED]
    assert api.public_bootstrap.events[stale].end is not None
    assert [e.id for e in dispatcher.active_events()] == [fresh]


def test_sweep_skips_other_channel_and_missing_device_id() -> None:
    api = _make_client()
    dispatcher = EventDispatcher(api)
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))

    stale = datetime.now(tz=UTC) - (EVENTS_ACTIVE_TTL + timedelta(seconds=10))
    other = Event(
        api=api, id="other", type=EventType.REBOOT, start=stale, device_id="cam-1"
    )
    no_device = Event(api=api, id="no-device", type=EventType.MOTION, start=stale)
    api.public_bootstrap.events["other"] = other
    api.public_bootstrap.events["no-device"] = no_device

    assert dispatcher.sweep_stale() == 0
    assert received == []


def test_sweep_no_op_when_within_ttl() -> None:
    api = _make_client()
    dispatcher = EventDispatcher(api)
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))

    _store_started(api, age=timedelta(seconds=60))
    assert dispatcher.sweep_stale() == 0
    assert received == []


def test_sweep_marks_store_so_retransmit_not_refired() -> None:
    api = _make_client()
    dispatcher = EventDispatcher(api)
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))

    stale = _store_started(api, age=EVENTS_ACTIVE_TTL + timedelta(seconds=10))
    assert dispatcher.sweep_stale() == 1

    # Sweeping again finds the now-terminal entry and does not re-fire.
    received.clear()
    assert dispatcher.sweep_stale() == 0
    assert received == []
    assert api.public_bootstrap.events[stale].end is not None


@pytest.mark.asyncio
async def test_sweep_task_cancelled_when_last_subscriber_unsubscribes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _make_client()

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
    await asyncio.sleep(0)
    assert api._event_dispatcher._sweep_task is None
    assert sweep_task.cancelled() or sweep_task.done()
