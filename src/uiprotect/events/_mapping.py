"""Map private-API ``Event`` instances onto the public ``ProtectEvent``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protect_event import (
    EventIdentity,
    ProtectEvent,
    ProtectEventChannel,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ..data.nvr import Event


def event_to_protect_event(
    raw: Event,
    channel: ProtectEventChannel,
    identity: EventIdentity | None,
    *,
    end_override: datetime | None = None,
) -> ProtectEvent:
    """Build a frozen ``ProtectEvent`` from a validated ``Event``."""
    assert raw.device_id is not None, "device_id must be present"
    end = end_override if end_override is not None else raw.end
    return ProtectEvent(
        id=raw.id,
        type=raw.type,
        channel=channel,
        device_id=raw.device_id,
        start=raw.start,
        end=end,
        smart_detect_types=tuple(raw.smart_detect_types),
        identity=identity,
        raw=raw,
    )
