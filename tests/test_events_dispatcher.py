"""Phase 4 dispatcher tests for the public events contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import orjson
import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.types import EventType
from uiprotect.data.websocket import WSAction
from uiprotect.events import EventChange, ProtectEvent
from uiprotect.events.dispatcher import MAX_ACTIVE, EventDispatcher

_FIXTURES = Path(__file__).parent / "sample_data" / "events_ws_public"


def _load(name: str) -> Any:
    return orjson.loads((_FIXTURES / name).read_bytes())


def _payload_to_event(api: ProtectApiClient, payload: dict[str, Any]) -> Event:
    return Event.from_unifi_dict(api=api, **payload)


def _make_client() -> ProtectApiClient:
    return ProtectApiClient(
        host="127.0.0.1",
        port=443,
        username="u",
        password="p",  # noqa: S106
        verify_ssl=False,
        store_sessions=False,
    )


@pytest.fixture
def api() -> ProtectApiClient:
    return _make_client()


@pytest.fixture
def dispatcher(api: ProtectApiClient) -> EventDispatcher:
    return EventDispatcher(api)


def _collect(
    dispatcher: EventDispatcher,
) -> list[tuple[ProtectEvent, EventChange]]:
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))
    return received


def test_dispatch_drops_non_device_event(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    event = Event(
        api=api,
        id="x",
        type=EventType.REBOOT,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
    )
    dispatcher.dispatch(WSAction.ADD, event)
    assert received == []


def test_dispatch_drops_missing_device_id(
    api: ProtectApiClient,
    dispatcher: EventDispatcher,
    caplog: pytest.LogCaptureFixture,
) -> None:
    received = _collect(dispatcher)
    event = Event(
        api=api,
        id="y",
        type=EventType.MOTION,
        start=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with caplog.at_level("WARNING", logger="uiprotect.events.dispatcher"):
        dispatcher.dispatch(WSAction.ADD, event)
    assert received == []
    assert any("missing required 'device'" in r.message for r in caplog.records)


def test_dispatch_started_then_ended_through_update(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    add = Event(
        api=api,
        id="m1",
        type=EventType.MOTION,
        start=start,
        device_id="cam-1",
    )
    dispatcher.dispatch(WSAction.ADD, add)
    assert dispatcher.active_events() == [received[0][0]]

    upd = Event(
        api=api,
        id="m1",
        type=EventType.MOTION,
        start=start,
        end=start + timedelta(seconds=5),
        device_id="cam-1",
    )
    dispatcher.dispatch(WSAction.UPDATE, upd)
    assert [c for _, c in received] == [EventChange.STARTED, EventChange.ENDED]
    assert dispatcher.active_events() == []


def test_dispatch_close_window_nfc_add_with_end(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    payload = _load("nfc_add_with_end.json")["item"]
    event = _payload_to_event(api, payload)
    dispatcher.dispatch(WSAction.ADD, event)

    assert [c for _, c in received] == [EventChange.STARTED, EventChange.ENDED]
    assert received[0][0].id == received[1][0].id
    assert dispatcher.active_events() == []


def test_dispatch_close_window_light_motion(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    payload = _load("light_motion_add.json")["item"]
    event = _payload_to_event(api, payload)
    dispatcher.dispatch(WSAction.ADD, event)

    assert [c for _, c in received] == [EventChange.STARTED, EventChange.ENDED]
    pe = received[0][0]
    assert pe.end == pe.start
    assert dispatcher.active_events() == []


def test_dispatch_smartdetect_lifecycle_idempotent_ended(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    payloads = _load("smartdetect_lifecycle.json")
    merged: dict[str, Any] = {}
    for frame in payloads:
        merged.update(frame["item"])
        event = _payload_to_event(api, dict(merged))
        dispatcher.dispatch(WSAction(frame["type"]), event)

    changes = [c for _, c in received]
    assert changes.count(EventChange.STARTED) == 1
    assert changes.count(EventChange.ENDED) == 1
    assert dispatcher.active_events() == []


def test_dispatch_remove_terminates(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    add = Event(
        api=api,
        id="r1",
        type=EventType.MOTION,
        start=start,
        device_id="cam-1",
    )
    dispatcher.dispatch(WSAction.ADD, add)
    dispatcher.dispatch(WSAction.REMOVE, add)
    assert [c for _, c in received] == [EventChange.STARTED, EventChange.REMOVED]
    assert dispatcher.active_events() == []


def test_subscriber_exception_isolation(
    api: ProtectApiClient,
    dispatcher: EventDispatcher,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def bad(_e: ProtectEvent, _c: EventChange) -> None:
        raise RuntimeError("boom")

    good: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(bad)
    dispatcher.add_subscriber(lambda e, c: good.append((e, c)))

    add = Event(
        api=api,
        id="m",
        type=EventType.MOTION,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
    )
    with caplog.at_level("ERROR", logger="uiprotect.events.dispatcher"):
        dispatcher.dispatch(WSAction.ADD, add)
    assert len(good) == 1


def test_active_events_filter_by_device(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    _collect(dispatcher)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for idx, dev in enumerate(["cam-a", "cam-b"]):
        event = Event(
            api=api,
            id=f"e-{idx}",
            type=EventType.MOTION,
            start=start,
            device_id=dev,
        )
        dispatcher.dispatch(WSAction.ADD, event)
    assert {e.device_id for e in dispatcher.active_events()} == {"cam-a", "cam-b"}
    assert [e.device_id for e in dispatcher.active_events("cam-a")] == ["cam-a"]


def test_enforce_max_active_evicts_oldest(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for idx in range(MAX_ACTIVE + 1):
        ev = Event(
            api=api,
            id=f"e-{idx:04d}",
            type=EventType.MOTION,
            start=base + timedelta(seconds=idx),
            device_id="cam-1",
        )
        dispatcher.dispatch(WSAction.ADD, ev)

    starteds = [c for _, c in received if c == EventChange.STARTED]
    endeds = [c for _, c in received if c == EventChange.ENDED]
    assert len(starteds) == MAX_ACTIVE + 1
    assert len(endeds) == 1
    # The very first one was evicted
    ended_event = next(e for e, c in received if c == EventChange.ENDED)
    assert ended_event.id == "e-0000"


@pytest.mark.asyncio
async def test_subscribe_events_requires_public_bootstrap() -> None:
    api = _make_client()
    with pytest.raises(RuntimeError, match="update_public"):
        api.subscribe_events(lambda e, c: None)


@pytest.mark.asyncio
async def test_subscribe_events_reference_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _make_client()
    api._public_bootstrap = PublicBootstrap()
    api.get_ulp_users_public = AsyncMock(return_value=[])  # type: ignore[method-assign]

    starts: list[None] = []
    stops: list[None] = []

    class _WS:
        def start(self) -> None:
            starts.append(None)

        def stop(self) -> None:
            stops.append(None)

    ws = _WS()
    monkeypatch.setattr(api, "_get_events_websocket", lambda: ws)

    unsub_a = api.subscribe_events(lambda e, c: None)
    unsub_b = api.subscribe_events(lambda e, c: None)

    assert len(starts) == 1
    assert api._event_dispatcher is not None
    assert api._event_dispatcher.subscriber_count == 2

    unsub_a()
    assert stops == []
    assert api._event_dispatcher.subscriber_count == 1

    unsub_b()
    assert len(stops) == 1
    assert api._event_dispatcher.subscriber_count == 0
