"""Value types for the public events contract."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from ..data.public_devices import PublicUlpUser
from ..data.public_event import PublicEvent, PublicEventMetadata
from ..data.types import EventType, SensorAlarmType, SmartDetectObjectType


class ProtectEventChannel(enum.StrEnum):
    """High-level grouping for public events."""

    DETECTION = "detection"
    SENSOR = "sensor"
    ALARM_HUB = "alarm_hub"
    ACCESS = "access"
    OTHER = "other"


_DETECTION: frozenset[EventType] = frozenset(
    {
        EventType.MOTION,
        EventType.RING,
        EventType.SMART_DETECT,
        EventType.SMART_AUDIO_DETECT,
        EventType.SMART_DETECT_LINE,
        EventType.SMART_DETECT_LOITER,
        EventType.FACE_GROUP_DETECTED,
        EventType.MOTION_LIGHT,
    }
)

_SENSOR: frozenset[EventType] = frozenset(
    {
        EventType.MOTION_SENSOR,
        EventType.SENSOR_BUTTON_PRESSED,
        EventType.SENSOR_OPENED,
        EventType.SENSOR_CLOSED,
        EventType.SENSOR_ALARM,
        EventType.SENSOR_EXTREME_VALUE,
        EventType.SENSOR_WATER_LEAK,
        EventType.SENSOR_BATTERY_LOW,
        EventType.SENSOR_SMOKE_TEST,
        EventType.SENSOR_TAMPER,
        EventType.SENSOR_VAPE,
        EventType.SENSOR_SMOKE_BATTERY_LOW,
        EventType.SENSOR_SMOKE_NEEDS_CLEANING,
        EventType.SENSOR_SMOKE_FAULT,
        EventType.SENSOR_CO_FAULT,
        EventType.SENSOR_SMOKE_END_OF_LIFE,
    }
)

_ALARM_HUB: frozenset[EventType] = frozenset(
    {
        EventType.ALARM_HUB_MOTION,
        EventType.ALARM_HUB_ENTRY_OPENED,
        EventType.ALARM_HUB_ENTRY_CLOSED,
        EventType.ALARM_HUB_RELAY_SWITCHED,
        EventType.ALARM_HUB_BUTTON_PRESS,
        EventType.ALARM_HUB_SMOKE,
        EventType.ALARM_HUB_GLASS_BREAK,
        EventType.ALARM_HUB_TAMPER,
        EventType.ALARM_HUB_BATTERY_CONNECTED,
        EventType.ALARM_HUB_BATTERY_LOW,
    }
)

_ACCESS: frozenset[EventType] = frozenset(
    {
        EventType.NFC_CARD_SCANNED,
        EventType.FINGERPRINT_IDENTIFIED,
        EventType.DOOR_ACCESS,
        EventType.ACCESS,
        EventType.DOORLOCK_OPEN,
        EventType.DOORLOCK_CLOSE,
        EventType.DOORLOCK_BATTERY_LOW,
    }
)


def _build_channel_map() -> dict[EventType, ProtectEventChannel]:
    channels: dict[EventType, ProtectEventChannel] = {}
    for et in EventType:
        if et in _DETECTION:
            channels[et] = ProtectEventChannel.DETECTION
        elif et in _SENSOR:
            channels[et] = ProtectEventChannel.SENSOR
        elif et in _ALARM_HUB:
            channels[et] = ProtectEventChannel.ALARM_HUB
        elif et in _ACCESS:
            channels[et] = ProtectEventChannel.ACCESS
        else:
            channels[et] = ProtectEventChannel.OTHER
    return channels


EVENT_TYPE_TO_CHANNEL: dict[EventType, ProtectEventChannel] = _build_channel_map()


# Schema-level instantaneous types: the server never emits an "end" later
# (one-shot frame). Dispatcher synthesises end == start so subscribers always
# see a paired STARTED / ENDED pair.
INSTANTANEOUS_EVENT_TYPES: frozenset[EventType] = frozenset({EventType.MOTION_LIGHT})


class EventChange(enum.StrEnum):
    """Lifecycle tag for a ProtectEvent dispatch."""

    STARTED = "started"
    UPDATED = "updated"
    ENDED = "ended"
    REMOVED = "removed"


class UlpUserIdentity(BaseModel):
    """ULP-cached identity attached to a credential event."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    kind: Literal["ulp_user"] = "ulp_user"
    ulp_id: str
    user: PublicUlpUser | None = None


class UnknownIdentity(BaseModel):
    """Identity unresolvable from the cached public bootstrap."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["unknown"] = "unknown"
    reason: Literal["no_metadata", "ulp_user_not_cached", "ulp_id_null"]


EventIdentity = Annotated[
    Union[UlpUserIdentity, UnknownIdentity],
    Field(discriminator="kind"),
]


class ProtectEvent(BaseModel):
    """Frozen public value type emitted by ``subscribe_events``."""

    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
    )

    id: str
    type: EventType
    channel: ProtectEventChannel
    device_id: str
    # Resolved from ``device_id`` against the public bootstrap device stores
    # at emit time. ``None`` when the device is not (yet) in the bootstrap —
    # the same eventual-consistency property as ``identity``: a device unknown
    # at first sight resolves on the next ``update_public()`` / reconnect.
    device_mac: str | None = None
    start: datetime
    end: datetime | None = None
    smart_detect_types: tuple[SmartDetectObjectType, ...] = ()
    identity: EventIdentity | None = None
    # Sensor alarm sound (``sensorAlarm`` events), collapsed from the public
    # ``metadata.alarmType.text``; ``None`` for other event types.
    alarm_type: SensorAlarmType | None = None
    # Strongly-typed metadata union (all fields optional). Consumers read typed
    # values off here (``metadata.sensor_type``, ``metadata.input_state``, …)
    # rather than parsing raw strings. ``None`` for events without metadata.
    metadata: PublicEventMetadata | None = None
    raw: PublicEvent | None = Field(default=None, repr=False, exclude=True)
