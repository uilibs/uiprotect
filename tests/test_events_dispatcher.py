"""Dispatcher tests for the public events contract (single-store model)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
import pytest

from tests.conftest import SAMPLE_DATA_DIRECTORY
from uiprotect.api import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.types import EventType
from uiprotect.data.websocket import WSAction
from uiprotect.events import EventChange, ProtectEvent
from uiprotect.events.dispatcher import EventDispatcher

_FIXTURES = SAMPLE_DATA_DIRECTORY / "events_ws_public"


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
    client = _make_client()
    client._public_bootstrap = PublicBootstrap()
    return client


@pytest.fixture
def dispatcher(api: ProtectApiClient) -> EventDispatcher:
    return EventDispatcher(api)


def _collect(
    dispatcher: EventDispatcher,
) -> list[tuple[ProtectEvent, EventChange]]:
    received: list[tuple[ProtectEvent, EventChange]] = []
    dispatcher.add_subscriber(lambda e, c: received.append((e, c)))
    return received


def _store(api: ProtectApiClient, event: Event) -> None:
    """Place ``event`` in the single store, mirroring the WS merge path."""
    api.public_bootstrap.events[event.id] = event


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
    dispatcher.dispatch(WSAction.ADD, event, None)
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
        dispatcher.dispatch(WSAction.ADD, event, None)
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
    _store(api, add)
    dispatcher.dispatch(WSAction.ADD, add, None)
    assert [e.id for e in dispatcher.active_events()] == ["m1"]

    old_snapshot = add.model_copy()
    upd = add
    upd.end = start + timedelta(seconds=5)
    dispatcher.dispatch(WSAction.UPDATE, upd, old_snapshot)
    assert [c for _, c in received] == [EventChange.STARTED, EventChange.ENDED]
    assert dispatcher.active_events() == []


def test_dispatch_close_window_nfc_add_with_end(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    payload = _load("nfc_add_with_end.json")["item"]
    event = _payload_to_event(api, payload)
    _store(api, event)
    dispatcher.dispatch(WSAction.ADD, event, None)

    assert [c for _, c in received] == [EventChange.STARTED, EventChange.ENDED]
    assert received[0][0].id == received[1][0].id
    assert dispatcher.active_events() == []


def test_dispatch_close_window_light_motion(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    payload = _load("light_motion_add.json")["item"]
    event = _payload_to_event(api, payload)
    _store(api, event)
    dispatcher.dispatch(WSAction.ADD, event, None)

    assert [c for _, c in received] == [EventChange.STARTED, EventChange.ENDED]
    pe = received[0][0]
    assert pe.end == pe.start
    # The dispatcher closes the instantaneous event in the store so it no
    # longer shows as active and a replay is suppressed.
    assert dispatcher.active_events() == []
    assert event.end is not None


def test_dispatch_close_window_add_with_end_replay_suppressed(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    payload = _load("nfc_add_with_end.json")["item"]
    first = _payload_to_event(api, payload)
    _store(api, first)
    dispatcher.dispatch(WSAction.ADD, first, None)

    # Server retransmits the same ADD-with-end; the snapshot now carries the
    # terminal ``end`` so the chokepoint suppresses both STARTED and ENDED.
    snapshot = first.model_copy()
    replay = _payload_to_event(api, payload)
    _store(api, replay)
    dispatcher.dispatch(WSAction.ADD, replay, snapshot)

    changes = [c for _, c in received]
    assert changes.count(EventChange.STARTED) == 1
    assert changes.count(EventChange.ENDED) == 1


def test_dispatch_smartdetect_lifecycle_idempotent_ended(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    payloads = _load("smartdetect_lifecycle.json")
    merged: dict[str, Any] = {}
    prev: Event | None = None
    for frame in payloads:
        merged.update(frame["item"])
        event = _payload_to_event(api, dict(merged))
        snapshot = prev.model_copy() if prev is not None else None
        _store(api, event)
        dispatcher.dispatch(WSAction(frame["type"]), event, snapshot)
        prev = event

    changes = [c for _, c in received]
    assert changes.count(EventChange.STARTED) == 1
    assert changes.count(EventChange.ENDED) == 1
    assert dispatcher.active_events() == []


def test_dispatch_update_to_end_retransmit_suppressed(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    add = Event(api=api, id="r", type=EventType.MOTION, start=start, device_id="cam-1")
    _store(api, add)
    dispatcher.dispatch(WSAction.ADD, add, None)

    open_snapshot = add.model_copy()
    add.end = start + timedelta(seconds=5)
    dispatcher.dispatch(WSAction.UPDATE, add, open_snapshot)

    # Retransmitted close: old snapshot already terminal -> suppressed.
    terminal_snapshot = add.model_copy()
    dispatcher.dispatch(WSAction.UPDATE, add, terminal_snapshot)

    changes = [c for _, c in received]
    assert changes.count(EventChange.ENDED) == 1


def test_dispatch_update_still_open_is_updated(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    add = Event(api=api, id="u", type=EventType.MOTION, start=start, device_id="cam-1")
    _store(api, add)
    dispatcher.dispatch(WSAction.ADD, add, None)
    snapshot = add.model_copy()
    dispatcher.dispatch(WSAction.UPDATE, add, snapshot)
    assert [c for _, c in received] == [EventChange.STARTED, EventChange.UPDATED]


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
    _store(api, add)
    dispatcher.dispatch(WSAction.ADD, add, None)
    snapshot = add.model_copy()
    api.public_bootstrap.events.pop("r1", None)
    dispatcher.dispatch(WSAction.REMOVE, None, snapshot)
    assert [c for _, c in received] == [EventChange.STARTED, EventChange.REMOVED]
    assert dispatcher.active_events() == []


def test_dispatch_remove_already_terminal_suppressed(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    ended = Event(
        api=api,
        id="r2",
        type=EventType.MOTION,
        start=start,
        end=start + timedelta(seconds=1),
        device_id="cam-1",
    )
    dispatcher.dispatch(WSAction.REMOVE, None, ended)
    assert received == []


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
        dispatcher.dispatch(WSAction.ADD, add, None)
    assert len(good) == 1


def test_active_events_filter_by_device(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for idx, dev in enumerate(["cam-a", "cam-b"]):
        event = Event(
            api=api,
            id=f"e-{idx}",
            type=EventType.MOTION,
            start=start,
            device_id=dev,
        )
        _store(api, event)
    assert {e.device_id for e in dispatcher.active_events()} == {"cam-a", "cam-b"}
    assert [e.device_id for e in dispatcher.active_events("cam-a")] == ["cam-a"]


def test_active_events_skips_ended_and_other(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    open_a = Event(
        api=api, id="open-a", type=EventType.MOTION, start=start, device_id="cam-a"
    )
    open_b = Event(
        api=api, id="open-b", type=EventType.RING, start=start, device_id="cam-b"
    )
    ended = Event(
        api=api,
        id="ended",
        type=EventType.MOTION,
        start=start,
        end=start + timedelta(seconds=1),
        device_id="cam-a",
    )
    other = Event(
        api=api, id="other", type=EventType.REBOOT, start=start, device_id="cam-a"
    )
    for ev in (open_a, open_b, ended, other):
        _store(api, ev)
    assert {e.id for e in dispatcher.active_events()} == {"open-a", "open-b"}


class _MacStub:
    """Minimal device stand-in carrying an ``id`` and ``mac``."""

    def __init__(self, obj_id: str, mac: str) -> None:
        self.id = obj_id
        self.mac = mac


def test_dispatch_resolves_device_mac_when_device_known(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    api.public_bootstrap.cameras["cam-1"] = _MacStub("cam-1", "aabbccddeeff")  # type: ignore[assignment]
    add = Event(
        api=api,
        id="m1",
        type=EventType.MOTION,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
    )
    _store(api, add)
    dispatcher.dispatch(WSAction.ADD, add, None)
    assert received[0][0].device_mac == "aabbccddeeff"


def test_dispatch_device_mac_none_when_device_absent(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    add = Event(
        api=api,
        id="m2",
        type=EventType.MOTION,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-missing",
    )
    _store(api, add)
    dispatcher.dispatch(WSAction.ADD, add, None)
    assert received[0][0].device_mac is None


def test_dispatch_subject_none_is_noop(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    received = _collect(dispatcher)
    dispatcher.dispatch(WSAction.REMOVE, None, None)
    assert received == []


def test_active_events_without_dispatcher_returns_empty() -> None:
    api = _make_client()
    assert api._event_dispatcher is None
    assert api.active_events() == []
    assert api.active_events(device_id="cam-1") == []


def test_active_events_derives_before_subscribe(
    api: ProtectApiClient,
) -> None:
    assert api._event_dispatcher is None
    start = datetime(2026, 1, 1, tzinfo=UTC)
    event = Event(
        api=api, id="pre", type=EventType.MOTION, start=start, device_id="cam-1"
    )
    _store(api, event)
    assert [e.id for e in api.active_events()] == ["pre"]


def test_active_events_with_dispatcher_delegates(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    api._event_dispatcher = dispatcher
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for idx, dev in enumerate(["cam-a", "cam-b"]):
        event = Event(
            api=api,
            id=f"api-e-{idx}",
            type=EventType.MOTION,
            start=start,
            device_id=dev,
        )
        _store(api, event)
    assert {e.device_id for e in api.active_events()} == {"cam-a", "cam-b"}
    assert [e.device_id for e in api.active_events(device_id="cam-a")] == ["cam-a"]


def test_unsubscribe_events_without_dispatcher_is_noop() -> None:
    api = _make_client()
    assert api._event_dispatcher is None
    # Should silently no-op rather than raise.
    api._unsubscribe_events(lambda e, c: None)


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


@pytest.mark.asyncio
async def test_start_ttl_sweep_idempotent_while_running(
    dispatcher: EventDispatcher,
) -> None:
    dispatcher.start_ttl_sweep()
    first = dispatcher._sweep_task
    assert first is not None
    dispatcher.start_ttl_sweep()
    assert dispatcher._sweep_task is first
    dispatcher.stop_ttl_sweep()


def test_merge_precedes_fan_out_invariant(
    api: ProtectApiClient, dispatcher: EventDispatcher
) -> None:
    """During a callback the event is already present in the store."""
    seen: list[bool] = []

    def cb(event: ProtectEvent, _change: EventChange) -> None:
        seen.append(event.id in api.public_bootstrap.events)

    dispatcher.add_subscriber(cb)
    add = Event(
        api=api,
        id="inv",
        type=EventType.MOTION,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
    )
    # The WS path stores before fan-out; emulate that ordering here.
    _store(api, add)
    dispatcher.dispatch(WSAction.ADD, add, None)
    assert seen == [True]
