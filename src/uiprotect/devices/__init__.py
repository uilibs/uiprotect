"""Public device-state contract for UniFi Protect."""

from __future__ import annotations

from .dispatcher import DeviceDispatcher
from .protect_device_change import DeviceChange, ProtectDeviceChange

__all__ = [
    "DeviceChange",
    "DeviceDispatcher",
    "ProtectDeviceChange",
]
