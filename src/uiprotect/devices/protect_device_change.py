"""Value types for the public device-state contract."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field

from ..data.base import ProtectModelWithId
from ..data.types import ModelType


class DeviceChange(enum.StrEnum):
    """Lifecycle tag for a ProtectDeviceChange dispatch."""

    ADDED = "added"
    UPDATED = "updated"
    REMOVED = "removed"


class ProtectDeviceChange(BaseModel):
    """Frozen public value type emitted by ``subscribe_devices``."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    change: DeviceChange
    model_type: ModelType
    device_id: str
    # Resolved from ``device_id`` against the public bootstrap device stores at
    # emit time; ``None`` until the device lands in the cache on the next
    # ``update_public()`` / reconnect, or for a REMOVED device with no cached
    # pre-removal object.
    device_mac: str | None = None
    # Merged post-``process_devices_ws_messages`` public model. ``None`` for
    # REMOVED (only an id / modelKey reference is delivered).
    model: ProtectModelWithId | None = Field(default=None, repr=False)
    # Populated for UPDATED; empty for ADDED / REMOVED.
    changed_fields: frozenset[str] = frozenset()
