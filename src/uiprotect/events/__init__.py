"""Public events contract for UniFi Protect."""

from __future__ import annotations

from ..data.nvr import Event
from ..data.public_devices import PublicUlpUser
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

UlpUserIdentity.model_rebuild()
ProtectEvent.model_rebuild()
del Event, PublicUlpUser

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
