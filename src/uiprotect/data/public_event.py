"""
Public Integration API event model.

Parsed 1:1 from the public ``event`` payload (the ``oneOf`` over the
``*Event`` schemas). This is the source of truth for the public events
path; it deliberately shares no structure with the private
:class:`~uiprotect.data.nvr.Event` / ``EventMetadata`` models so the two
paths can diverge as their respective specs do.

Metadata is a single model of all-optional, strongly-typed fields — the
union across every public event type. The ``{"text": <value>}`` (and the
lone ``{"number": <value>}``) envelopes the spec wraps each metadata value
in are collapsed to the inner value on parse and re-wrapped on serialise,
mirroring the private ``EventMetadata`` shape without importing it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import cache
from typing import Any, ClassVar

from pydantic import Field

from ..utils import convert_smart_types, convert_to_datetime
from .base import ProtectBaseObject, ProtectModelWithId
from .types import (
    EventButtonType,
    EventType,
    ModelType,
    MountType,
    RelayInputCircuitState,
    SensorAlarmType,
    SensorExtremeMetricType,
    SensorStatusType,
    SmartDetectObjectType,
    SmokeTestSource,
)

# Every ``type`` the public ``event`` union can carry. ``EventType`` is a
# superset — it also carries private-API-only events — so this is the subset a
# public-API consumer can actually see. ``scripts/validate_spec.py`` pins it
# against the spec's ``event`` ``oneOf`` discriminator.
PUBLIC_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.RING,
        EventType.SENSOR_EXTREME_VALUE,
        EventType.SENSOR_WATER_LEAK,
        EventType.SENSOR_TAMPER,
        EventType.SENSOR_BATTERY_LOW,
        EventType.SENSOR_ALARM,
        EventType.SENSOR_VAPE,
        EventType.SENSOR_OPENED,
        EventType.SENSOR_CLOSED,
        EventType.SENSOR_SMOKE_TEST,
        EventType.SENSOR_SMOKE_BATTERY_LOW,
        EventType.SENSOR_SMOKE_NEEDS_CLEANING,
        EventType.SENSOR_SMOKE_FAULT,
        EventType.SENSOR_CO_FAULT,
        EventType.SENSOR_SMOKE_END_OF_LIFE,
        EventType.MOTION_SENSOR,
        EventType.SENSOR_BUTTON_PRESSED,
        EventType.MOTION_LIGHT,
        EventType.MOTION,
        EventType.SMART_AUDIO_DETECT,
        EventType.SMART_DETECT,
        EventType.SMART_DETECT_LINE,
        EventType.SMART_DETECT_LOITER,
        EventType.RELAY_INPUT_CHANGED,
        EventType.CAMERA_DIGITAL_INPUT_CHANGED,
        EventType.ALARM_HUB_MOTION,
        EventType.ALARM_HUB_ENTRY_OPENED,
        EventType.ALARM_HUB_ENTRY_CLOSED,
        EventType.ALARM_HUB_SMOKE,
        EventType.ALARM_HUB_GLASS_BREAK,
        EventType.ALARM_HUB_BUTTON_PRESS,
        EventType.ALARM_HUB_TAMPER,
        EventType.ALARM_HUB_DEVICE_TAMPER,
        EventType.ALARM_HUB_RELAY_SWITCHED,
        EventType.ALARM_HUB_BATTERY_LOW,
        EventType.ALARM_HUB_BATTERY_CONNECTED,
        EventType.NFC_CARD_SCANNED,
        EventType.FINGERPRINT_IDENTIFIED,
    }
)


class PublicNfcMetadata(ProtectBaseObject):
    """``nfc`` block of an ``nfcCardScanned`` event (public spec)."""

    ulp_id: str | None = None


class PublicFingerprintMetadata(ProtectBaseObject):
    """``fingerprint`` block of a ``fingerprintIdentified`` event (public spec)."""

    ulp_id: str | None = None


class PublicEventMetadata(ProtectBaseObject):
    """Union of every public ``*Event`` metadata field, all optional."""

    # ``{"text": <enum/str>}`` envelopes.
    sensor_type: SensorExtremeMetricType | None = None
    sensor_value: float | None = None
    status: SensorStatusType | None = None
    sensor_mount_type: MountType | None = None
    alarm_type: SensorAlarmType | None = None
    button: EventButtonType | None = None
    input_state: RelayInputCircuitState | None = None
    input_token: str | None = None
    input_channel: str | None = None
    pin: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    # ``{"number": <number>}`` envelope.
    sensor_battery_percentage: float | None = None
    # Flat string (no envelope).
    source: SmokeTestSource | None = None
    # Nested identity holders (public-only, never imported from ``nvr.py``).
    nfc: PublicNfcMetadata | None = None
    fingerprint: PublicFingerprintMetadata | None = None

    # Wire keys carrying a ``{"text": ...}`` envelope around their value.
    _text_keys: ClassVar[set[str]] = {
        "sensorType",
        "sensorValue",
        "status",
        "sensorMountType",
        "alarmType",
        "button",
        "inputState",
        "inputToken",
        "inputChannel",
        "pin",
        "deviceId",
        "deviceName",
    }
    # Wire keys carrying a ``{"number": ...}`` envelope around their value.
    _number_keys: ClassVar[set[str]] = {"sensorBatteryPercentage"}

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Collapse the ``{text|number: value}`` metadata envelopes to inner values."""
        for inner_key, wire_keys in (
            ("text", cls._text_keys),
            ("number", cls._number_keys),
        ):
            for wire_key in wire_keys.intersection(data):
                value = data[wire_key]
                if isinstance(value, dict):
                    if inner_key in value:
                        data[wire_key] = value[inner_key]
                    else:
                        del data[wire_key]
        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        """Serialise, dropping ``None`` fields and re-wrapping metadata envelopes."""
        data = super().unifi_dict(data=data, exclude=exclude)
        for key, value in list(data.items()):
            if value is None:
                del data[key]
        for key in self._text_keys.intersection(data):
            data[key] = {"text": data[key]}
        for key in self._number_keys.intersection(data):
            data[key] = {"number": data[key]}
        return data


class PublicEvent(ProtectModelWithId):
    """Event delivered over the Public Integration API events websocket."""

    model: ModelType | None = ModelType.EVENT
    type: EventType
    start: datetime
    end: datetime | None = None
    # Public ``add`` payloads carry the originating device under ``device``.
    device_id: str | None = None
    smart_detect_types: list[SmartDetectObjectType] = Field(default_factory=list)
    metadata: PublicEventMetadata | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        """Remap the wire ``device`` key onto ``deviceId``."""
        return {**super()._get_unifi_remaps(), "device": "deviceId"}

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        """Parse the ``start`` / ``end`` wire timestamps into ``datetime``."""
        return (
            dict.fromkeys(("start", "end"), convert_to_datetime)
            | {"smartDetectTypes": convert_smart_types}
            | super().unifi_dict_conversions()
        )
