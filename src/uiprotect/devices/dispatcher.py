"""Stateless public devices dispatcher over the PublicBootstrap device stores."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..data.types import ModelType
from ..data.websocket import WSAction
from ..utils import to_snake_case
from .protect_device_change import DeviceChange, ProtectDeviceChange

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..api import ProtectApiClient
    from ..data.base import ProtectModelWithId
    from ..data.websocket import WSSubscriptionMessage


_LOGGER = logging.getLogger(__name__)


class DeviceDispatcher:
    """Map a single per-device WS message to a typed ``ProtectDeviceChange``."""

    def __init__(self, api: ProtectApiClient) -> None:
        self._api = api
        self._subscribers: list[Callable[[ProtectDeviceChange], None]] = []

    def add_subscriber(self, cb: Callable[[ProtectDeviceChange], None]) -> None:
        self._subscribers.append(cb)

    def remove_subscriber(self, cb: Callable[[ProtectDeviceChange], None]) -> None:
        # Idempotent: the unsubscribe callable may fire more than once
        # (e.g. double cleanup on HA reload).
        if cb in self._subscribers:
            self._subscribers.remove(cb)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def dispatch(self, msg: WSSubscriptionMessage) -> None:
        change = self._derive(msg)
        if change is not None:
            self._fan_out(change)

    def _derive(self, msg: WSSubscriptionMessage) -> ProtectDeviceChange | None:
        changed = msg.changed_data or {}
        model_key = changed.get("modelKey")
        model_type = (
            ModelType.from_string(model_key) if model_key else ModelType.UNKNOWN
        )
        if msg.action is WSAction.REMOVE:
            return self._derive_remove(msg, changed, model_type)
        return self._derive_upsert(msg, changed, model_type)

    def _derive_remove(
        self,
        msg: WSSubscriptionMessage,
        changed: dict[str, Any],
        model_type: ModelType,
    ) -> ProtectDeviceChange | None:
        # Only surface removals for types the public API actually exposes;
        # unsupported model keys (e.g. doorlock) never reach a store.
        if not self._api.public_bootstrap.supports_device(model_type):
            return None
        old = msg.old_obj
        device_id = self._object_id(old) or changed.get("id")
        if device_id is None:
            _LOGGER.debug(
                "Devices-WS REMOVE without resolvable id (modelKey=%s) — "
                "dropping frame",
                changed.get("modelKey"),
            )
            return None
        return ProtectDeviceChange(
            change=DeviceChange.REMOVED,
            model_type=model_type,
            device_id=str(device_id),
            device_mac=getattr(old, "mac", None) if old is not None else None,
            model=None,
        )

    def _derive_upsert(
        self,
        msg: WSSubscriptionMessage,
        changed: dict[str, Any],
        model_type: ModelType,
    ) -> ProtectDeviceChange | None:
        new = msg.new_obj
        if new is None:
            # Benign desync: an ADD/UPDATE whose merged model is missing (update
            # for an uncached id, or a merge/construct failure already surfaced
            # by PublicBootstrap). Not a contract change — drop quietly.
            _LOGGER.debug(
                "Devices-WS %s without merged model (id=%s) — dropping frame",
                msg.action,
                changed.get("id"),
            )
            return None
        device_id = self._object_id(new) or changed.get("id")
        if device_id is None:
            return None
        device_mac = self._api.public_bootstrap.get_device_mac(str(device_id))
        if msg.action is WSAction.ADD:
            return ProtectDeviceChange(
                change=DeviceChange.ADDED,
                model_type=model_type,
                device_id=str(device_id),
                device_mac=device_mac,
                model=new,
            )
        return ProtectDeviceChange(
            change=DeviceChange.UPDATED,
            model_type=model_type,
            device_id=str(device_id),
            device_mac=device_mac,
            model=new,
            changed_fields=self._changed_fields(new, changed),
        )

    @staticmethod
    def _object_id(obj: ProtectModelWithId | None) -> str | None:
        return getattr(obj, "id", None) if obj is not None else None

    @staticmethod
    def _changed_fields(
        model: ProtectModelWithId, changed: dict[str, object]
    ) -> frozenset[str]:
        # ``new_obj is old_obj`` for UPDATE (in-place merge), so models can't be
        # diffed — derive the changed set from the payload keys instead, cleaned
        # through the model's own remap/snake-case pass.
        payload = {k: v for k, v in changed.items() if k not in ("id", "modelKey")}
        if not payload:
            return frozenset()
        try:
            cleaned = type(model).unifi_dict_to_dict(dict(payload))
        except Exception:
            # Keep the key space stable for membership checks: best-effort
            # snake_case the raw payload keys instead of leaking camelCase.
            _LOGGER.debug(
                "changed_fields conversion failed for %s — falling back to "
                "snake_cased payload keys",
                type(model).__name__,
                exc_info=True,
            )
            return frozenset(to_snake_case(k) for k in payload)
        return frozenset(cleaned)

    def _fan_out(self, change: ProtectDeviceChange) -> None:
        # Snapshot: a subscriber may unsubscribe mid-delivery, mutating the list.
        for cb in tuple(self._subscribers):
            try:
                cb(change)
            except Exception:
                _LOGGER.exception(
                    "Exception while running subscribe_devices subscriber"
                )
