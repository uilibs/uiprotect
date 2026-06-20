"""Map public-API ``PublicEvent`` instances onto the public ``ProtectEvent``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protect_event import (
    EventIdentity,
    ProtectEvent,
    ProtectEventChannel,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ..data.public_event import PublicEvent


def event_to_protect_event(
    raw: PublicEvent,
    channel: ProtectEventChannel,
    identity: EventIdentity | None,
    *,
    end_override: datetime | None = None,
    device_mac: str | None = None,
) -> ProtectEvent:
    """Build a frozen ``ProtectEvent`` from a validated ``PublicEvent``."""
    if raw.device_id is None:
        raise ValueError("device_id must be present")
    end = end_override if end_override is not None else raw.end
    metadata = raw.metadata
    return ProtectEvent(
        id=raw.id,
        type=raw.type,
        channel=channel,
        device_id=raw.device_id,
        device_mac=device_mac,
        start=raw.start,
        end=end,
        smart_detect_types=tuple(raw.smart_detect_types),
        identity=identity,
        alarm_type=metadata.alarm_type if metadata is not None else None,
        metadata=metadata,
        raw=raw,
    )
