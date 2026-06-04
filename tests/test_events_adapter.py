"""Adapter tests for ``ProtectApiClient._adapt_events_ws_message``."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.events.dispatcher import EventDispatcher


def _make_client() -> ProtectApiClient:
    return ProtectApiClient(
        host="127.0.0.1",
        port=443,
        username="u",
        password="p",  # noqa: S106
        verify_ssl=False,
        store_sessions=False,
    )


def _attach(
    api: ProtectApiClient,
) -> tuple[EventDispatcher, list[tuple[Any, Any, Any]]]:
    dispatcher = EventDispatcher(api)
    api._event_dispatcher = dispatcher
    received: list[tuple[Any, Any, Any]] = []
    dispatcher.dispatch = (  # type: ignore[method-assign]
        lambda action, new, old: received.append((action, new, old))
    )
    return dispatcher, received


def _motion(api: ProtectApiClient, event_id: str = "m1") -> Event:
    return Event(
        api=api,
        id=event_id,
        type=EventType.MOTION,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
    )


def test_adapter_no_dispatcher_is_noop() -> None:
    api = _make_client()
    msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id="u",
        changed_data={},
        new_obj=_motion(api),
    )
    api._adapt_events_ws_message(msg)


def test_adapter_add_without_new_obj_warns_and_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    _, received = _attach(api)
    msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id="u",
        changed_data={},
        new_obj=None,
    )
    with caplog.at_level("WARNING", logger="uiprotect.api"):
        api._adapt_events_ws_message(msg)
    assert received == []
    assert any("without merged Event obj" in r.message for r in caplog.records)


def test_adapter_update_with_wrong_obj_type_warns_and_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    _, received = _attach(api)
    msg = WSSubscriptionMessage(
        action=WSAction.UPDATE,
        new_update_id="u",
        changed_data={},
        new_obj=cast("Any", object()),
    )
    with caplog.at_level("WARNING", logger="uiprotect.api"):
        api._adapt_events_ws_message(msg)
    assert received == []
    assert any("without merged Event obj" in r.message for r in caplog.records)


def test_adapter_add_forwards_to_dispatch_with_old_obj() -> None:
    api = _make_client()
    _, received = _attach(api)
    new = _motion(api)
    old = _motion(api)
    msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id="u",
        changed_data={},
        new_obj=new,
        old_obj=old,
    )
    api._adapt_events_ws_message(msg)
    assert received == [(WSAction.ADD, new, old)]


def test_adapter_add_forwards_none_old_when_absent() -> None:
    api = _make_client()
    _, received = _attach(api)
    new = _motion(api)
    msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id="u",
        changed_data={},
        new_obj=new,
    )
    api._adapt_events_ws_message(msg)
    assert received == [(WSAction.ADD, new, None)]


def test_adapter_remove_unknown_event_logs_once_within_throttle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    _, received = _attach(api)
    msg = WSSubscriptionMessage(
        action=WSAction.REMOVE,
        new_update_id="u",
        changed_data={"id": "ghost"},
        old_obj=None,
    )

    with caplog.at_level("INFO", logger="uiprotect.api"):
        api._adapt_events_ws_message(msg)
        first_ts = api._events_remove_unknown_last_log
        api._adapt_events_ws_message(msg)

    matching = [r for r in caplog.records if "remove for unknown event" in r.message]
    assert len(matching) == 1
    assert received == []
    assert api._events_remove_unknown_last_log == first_ts


def test_adapter_remove_unknown_event_relogs_after_throttle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    _attach(api)
    msg = WSSubscriptionMessage(
        action=WSAction.REMOVE,
        new_update_id="u",
        changed_data={"id": "ghost"},
        old_obj=None,
    )

    with caplog.at_level("INFO", logger="uiprotect.api"):
        api._adapt_events_ws_message(msg)
        api._events_remove_unknown_last_log = time.monotonic() - 120.0
        api._adapt_events_ws_message(msg)

    matching = [r for r in caplog.records if "remove for unknown event" in r.message]
    assert len(matching) == 2


def test_adapter_remove_known_event_forwards_old_obj_to_dispatch() -> None:
    api = _make_client()
    _, received = _attach(api)
    old = _motion(api, event_id="kept")
    msg = WSSubscriptionMessage(
        action=WSAction.REMOVE,
        new_update_id="u",
        changed_data={"id": "kept"},
        old_obj=old,
    )
    api._adapt_events_ws_message(msg)
    assert received == [(WSAction.REMOVE, None, old)]
