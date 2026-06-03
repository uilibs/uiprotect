"""Phase 2 mapping tests for the public events contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import orjson

from tests.conftest import SAMPLE_DATA_DIRECTORY
from uiprotect.data.nvr import Event, NfcMetadata
from uiprotect.data.types import EventType, SmartDetectObjectType
from uiprotect.events import EVENT_TYPE_TO_CHANNEL, ProtectEventChannel
from uiprotect.events._mapping import event_to_protect_event

_FIXTURES = SAMPLE_DATA_DIRECTORY / "events_ws_public"


def _load(name: str) -> Any:
    return orjson.loads((_FIXTURES / name).read_bytes())


def _event_from_payload(item: dict[str, Any]) -> Event:
    return Event.from_unifi_dict(**item)


def test_nfc_metadata_optionality_and_ulp_id() -> None:
    md = NfcMetadata.from_unifi_dict(ulpId="22222222-2222-2222-2222-222222222222")
    assert md.ulp_id == "22222222-2222-2222-2222-222222222222"
    assert md.nfc_id is None
    assert md.user_id is None


def test_event_device_id_remap_from_public_payload() -> None:
    payload = _load("nfc_add_with_end.json")["item"]
    event = _event_from_payload(payload)
    assert event.device_id == "aabbccddeeff00112233aabb"
    assert event.camera_id is None


def test_map_nfc_event_to_access_channel() -> None:
    payload = _load("nfc_add_with_end.json")["item"]
    event = _event_from_payload(payload)
    channel = EVENT_TYPE_TO_CHANNEL[event.type]
    assert channel is ProtectEventChannel.ACCESS

    out = event_to_protect_event(event, channel, identity=None)
    assert out.id == event.id
    assert out.device_id == event.device_id
    assert out.type is EventType.NFC_CARD_SCANNED
    assert out.end is not None
    assert out.smart_detect_types == ()
    assert out.raw is event


def test_map_light_motion_with_end_override() -> None:
    payload = _load("light_motion_add.json")["item"]
    event = _event_from_payload(payload)
    channel = EVENT_TYPE_TO_CHANNEL[event.type]
    assert channel is ProtectEventChannel.DETECTION

    end_override = datetime(2026, 1, 1, tzinfo=UTC)
    out = event_to_protect_event(
        event, channel, identity=None, end_override=end_override
    )
    assert out.end == end_override


def test_map_smart_detect_carries_smart_types() -> None:
    payloads = _load("smartdetect_lifecycle.json")
    event = _event_from_payload(payloads[0]["item"])
    channel = EVENT_TYPE_TO_CHANNEL[event.type]
    assert channel is ProtectEventChannel.DETECTION
    out = event_to_protect_event(event, channel, identity=None)
    assert SmartDetectObjectType.PERSON in out.smart_detect_types
    assert isinstance(out.smart_detect_types, tuple)


def test_fingerprint_payload_with_ulpid_null() -> None:
    payload = _load("fingerprint_add_ulpid_null.json")["item"]
    event = _event_from_payload(payload)
    assert event.metadata is not None
    assert event.metadata.fingerprint is not None
    assert event.metadata.fingerprint.ulp_id is None
