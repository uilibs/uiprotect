"""Phase 1 value-type tests for the public events contract."""

from __future__ import annotations

from datetime import UTC, datetime

import orjson
import pytest
from pydantic import TypeAdapter, ValidationError

from uiprotect.data.types import EventType
from uiprotect.events import (
    EVENT_TYPE_TO_CHANNEL,
    INSTANTANEOUS_EVENT_TYPES,
    EventChange,
    EventIdentity,
    ProtectEvent,
    ProtectEventChannel,
    UlpUserIdentity,
    UnknownIdentity,
)


def test_event_type_to_channel_is_exhaustive() -> None:
    assert set(EVENT_TYPE_TO_CHANNEL) == set(EventType)


def test_event_type_to_channel_buckets() -> None:
    assert EVENT_TYPE_TO_CHANNEL[EventType.MOTION] is ProtectEventChannel.DETECTION
    assert EVENT_TYPE_TO_CHANNEL[EventType.RING] is ProtectEventChannel.DETECTION
    assert (
        EVENT_TYPE_TO_CHANNEL[EventType.SMART_DETECT] is ProtectEventChannel.DETECTION
    )
    assert (
        EVENT_TYPE_TO_CHANNEL[EventType.MOTION_LIGHT] is ProtectEventChannel.DETECTION
    )
    assert EVENT_TYPE_TO_CHANNEL[EventType.SENSOR_OPENED] is ProtectEventChannel.SENSOR
    assert (
        EVENT_TYPE_TO_CHANNEL[EventType.ALARM_HUB_MOTION]
        is ProtectEventChannel.ALARM_HUB
    )
    assert (
        EVENT_TYPE_TO_CHANNEL[EventType.NFC_CARD_SCANNED] is ProtectEventChannel.ACCESS
    )
    assert (
        EVENT_TYPE_TO_CHANNEL[EventType.FINGERPRINT_IDENTIFIED]
        is ProtectEventChannel.ACCESS
    )
    assert EVENT_TYPE_TO_CHANNEL[EventType.DOORLOCK_OPEN] is ProtectEventChannel.ACCESS
    assert EVENT_TYPE_TO_CHANNEL[EventType.REBOOT] is ProtectEventChannel.OTHER


def test_instantaneous_event_types_includes_light_motion() -> None:
    assert EventType.MOTION_LIGHT in INSTANTANEOUS_EVENT_TYPES


def test_event_change_members() -> None:
    assert {c.value for c in EventChange} == {
        "started",
        "updated",
        "ended",
        "removed",
    }


def test_event_identity_round_trip_via_json() -> None:
    adapter: TypeAdapter[EventIdentity] = TypeAdapter(EventIdentity)
    ulp = UlpUserIdentity(ulp_id="abc")
    blob = adapter.dump_json(ulp)
    assert orjson.loads(blob)["kind"] == "ulp_user"
    assert adapter.validate_json(blob) == ulp

    unk = UnknownIdentity(reason="no_metadata")
    blob = adapter.dump_json(unk)
    assert orjson.loads(blob)["kind"] == "unknown"
    assert adapter.validate_json(blob) == unk


def test_protect_event_is_frozen() -> None:
    event = ProtectEvent(
        id="abcd",
        type=EventType.MOTION,
        channel=ProtectEventChannel.DETECTION,
        device_id="cam-1",
        start=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        event.id = "x"  # type: ignore[misc]


def test_protect_event_defaults_smart_detect_types_to_empty_tuple() -> None:
    event = ProtectEvent(
        id="abcd",
        type=EventType.MOTION,
        channel=ProtectEventChannel.DETECTION,
        device_id="cam-1",
        start=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert event.smart_detect_types == ()
    assert event.end is None
    assert event.identity is None
    assert event.raw is None


def test_protect_event_excludes_raw_from_dump() -> None:
    event = ProtectEvent(
        id="abcd",
        type=EventType.MOTION,
        channel=ProtectEventChannel.DETECTION,
        device_id="cam-1",
        start=datetime(2026, 1, 1, tzinfo=UTC),
    )
    dumped = event.model_dump()
    assert "raw" not in dumped
