"""Public events contract for UniFi Protect."""

from __future__ import annotations

from .protect_event import (
    EVENT_TYPE_TO_CHANNEL,
    INSTANTANEOUS_EVENT_TYPES,
    EventChange,
    EventIdentity,
    ProtectEvent,
    ProtectEventChannel,
    UlpUserIdentity,
    UnknownIdentity,
)

__all__ = [
    "EVENT_TYPE_TO_CHANNEL",
    "INSTANTANEOUS_EVENT_TYPES",
    "EventChange",
    "EventIdentity",
    "ProtectEvent",
    "ProtectEventChannel",
    "UlpUserIdentity",
    "UnknownIdentity",
]
