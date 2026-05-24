"""
UniFi Protect Public Integration API bootstrap.

This is an opt-in, separate cache for the Public Integration API. It is
*not* populated by :meth:`ProtectApiClient.update` and does not
touch the private :class:`~uiprotect.data.bootstrap.Bootstrap` in any way.

Consumers (e.g. Home Assistant) should:

1. ``subscribe_devices_websocket(callback)`` / ``subscribe_events_websocket(callback)``
2. ``await update_public()`` to prime the cache

That ordering guarantees subscribers are registered before priming starts.
WS messages that arrive while ``update_public()`` is still priming are still
delivered to subscribers (via ``changed_data``), but they may not yet be
applied to the in-memory :class:`PublicBootstrap` cache (an ``update`` for
an object not in the cache is dropped — the cache catches up on the next
``update_public()`` / reconnect refresh). Messages that arrive after priming
are merged into the fresh cache normally.

WS messages carry partial diffs for ``update`` actions; the cache therefore
*merges* updates into the existing in-memory object instead of reconstructing
it from the partial payload. Only ``add`` messages are treated as full
payloads.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from .base import ProtectModelWithId
from .convert import create_from_unifi_dict
from .devices import Camera, Chime, Light, Sensor
from .nvr import Event
from .public_devices import (
    ArmProfile,
    Fob,
    NvrArmMode,
    PublicBridge,
    PublicLinkStation,
    PublicLiveview,
    PublicNVR,
    PublicViewer,
    Relay,
    Siren,
    Speaker,
)
from .types import ModelType

if TYPE_CHECKING:
    from ..api import ProtectApiClient


_LOGGER = logging.getLogger(__name__)

# Default cap on the public event cache. Matches the private Bootstrap
# default so memory behaviour is symmetric between the two caches.
DEFAULT_PUBLIC_EVENT_CACHE_SIZE = 1000


# ModelType -> attribute on ``PublicBootstrap`` holding ``dict[id, obj]``.
# Only the models that the Public Integration API actually exposes are
# listed here. Unsupported model keys (``doorlock``, ``viewport`` etc.) are
# logged at DEBUG and ignored in :meth:`process_devices_ws_message`.
_DEVICE_STORES: dict[ModelType, str] = {
    ModelType.CAMERA: "cameras",
    ModelType.LIGHT: "lights",
    ModelType.SENSOR: "sensors",
    ModelType.CHIME: "chimes",
    ModelType.SIREN: "sirens",
    ModelType.RELAY: "relays",
    ModelType.SPEAKER: "speakers",
    ModelType.FOB: "fobs",
    ModelType.LINKSTATION: "link_stations",
}


@dataclass
class PublicBootstrap:
    """
    In-memory cache of the Public Integration API resources.

    All device dicts map ``id`` -> object. Empty by default; populated by
    :meth:`ProtectApiClient.update_public`.

    **Staleness on websocket reconnect.** While the devices/events websocket
    is connected, incoming ``add``/``update``/``remove`` messages are merged
    into the cache. If the websocket drops and reconnects, any messages
    emitted during the gap are lost. :class:`ProtectApiClient` automatically
    schedules an :meth:`~ProtectApiClient.update_public` refresh on
    *reconnect* (the initial connect does not trigger a refresh).
    """

    # NVR metadata (populated by ``update_public``). Useful for HA's
    # ``DeviceInfo``. Merged in place by :meth:`process_devices_ws_message`
    # when an ``nvr`` update arrives.
    nvr: PublicNVR | None = None

    # Device stores (indexed by id). Only the device classes that the
    # Public Integration API actually exposes are kept here.
    cameras: dict[str, Camera] = field(default_factory=dict)
    lights: dict[str, Light] = field(default_factory=dict)
    sensors: dict[str, Sensor] = field(default_factory=dict)
    chimes: dict[str, Chime] = field(default_factory=dict)
    sirens: dict[str, Siren] = field(default_factory=dict)
    relays: dict[str, Relay] = field(default_factory=dict)
    speakers: dict[str, Speaker] = field(default_factory=dict)
    fobs: dict[str, Fob] = field(default_factory=dict)
    # Both /v1/link-stations and /v1/alarm-hubs return ``linkstation`` objects
    # (alarm hubs are the ``is_alarm_hub`` subset); cached together here.
    link_stations: dict[str, PublicLinkStation] = field(default_factory=dict)
    # Populated by ``update_public`` only. These model keys are also served by
    # the private bootstrap, so they are intentionally absent from
    # ``_DEVICE_STORES`` (the shared ``MODEL_TO_CLASS`` would route websocket
    # diffs to the private models) — there is no live WS merge for them.
    bridges: dict[str, PublicBridge] = field(default_factory=dict)
    viewers: dict[str, PublicViewer] = field(default_factory=dict)
    liveviews: dict[str, PublicLiveview] = field(default_factory=dict)

    # Events received via the events websocket (:meth:`process_events_ws_message`).
    # Bounded by :attr:`max_event_cache_size`; oldest events are evicted first.
    events: OrderedDict[str, Event] = field(default_factory=OrderedDict)
    max_event_cache_size: int = DEFAULT_PUBLIC_EVENT_CACHE_SIZE

    # Arm manager state.
    arm_profiles: dict[str, ArmProfile] = field(default_factory=dict)

    # Per-instance one-shot warning dedupe for merge/add failures.
    # This must not be module-global because callers can have multiple
    # Protect servers in one process.
    _warned_merge_failures: set[tuple[str, str]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    @property
    def arm_mode(self) -> NvrArmMode | None:
        """
        Current arm-manager state. Shortcut for ``nvr.arm_mode``.

        Returns ``None`` when the NVR cache hasn't been primed yet, when the
        firmware does not expose the alarm manager, or when the alarm
        manager is set to global.
        """
        return self.nvr.arm_mode if self.nvr is not None else None

    def __post_init__(self) -> None:
        """Validate cache bounds used by event eviction logic."""
        if self.max_event_cache_size < 0:
            raise ValueError("max_event_cache_size must be >= 0")

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def _store_for(self, model_type: ModelType) -> dict[str, ProtectModelWithId] | None:
        attr = _DEVICE_STORES.get(model_type)
        if attr is None:
            return None
        return cast("dict[str, ProtectModelWithId]", getattr(self, attr))

    def get(self, model_type: ModelType, obj_id: str) -> ProtectModelWithId | None:
        """Look up a cached device by model type and id."""
        store = self._store_for(model_type)
        if store is None:
            return None
        return store.get(obj_id)

    def apply_fetch_result(self, attr: str, objs: list[ProtectModelWithId]) -> None:
        """
        Merge fetched objects into ``self.<attr>`` without wholesale replace.

        Used by :meth:`ProtectApiClient.update_public` so that ``add``/
        ``update``/``remove`` WS messages arriving concurrently with the
        HTTP fetch are not clobbered. IDs present in ``objs`` overwrite
        the cache entry; IDs absent from ``objs`` but present in the
        cache are removed.
        """
        store = cast("dict[str, ProtectModelWithId]", getattr(self, attr))
        fetched_ids = {obj.id for obj in objs}
        # Remove objects no longer reported by the API.
        for stale in [k for k in store if k not in fetched_ids]:
            store.pop(stale, None)
        # Upsert — newer fetched payload wins over in-place WS merges. This
        # is the intended semantic because `update_public` is the ground
        # truth at the moment it returns.
        for obj in objs:
            store[obj.id] = obj

    # ------------------------------------------------------------------
    # WS message handlers
    # ------------------------------------------------------------------

    def process_devices_ws_message(
        self,
        api: ProtectApiClient,
        data: dict[str, Any],
    ) -> tuple[ModelType | None, ProtectModelWithId | None, ProtectModelWithId | None]:
        """
        Apply a public *devices* WS payload to the cache.

        Returns ``(model_type, new_obj, old_obj)``. Any of them may be
        ``None`` when the message couldn't be applied (unknown model,
        malformed payload, or an update for an object not yet in the
        cache).

        ``update`` messages carry **partial diffs** — only the changed
        fields. They are merged into the existing cached object via
        :meth:`ProtectBaseObject.update_from_dict`; reconstructing from a
        partial payload would fail strict validation for required fields.
        """
        action_type, item, _obj_id = _parse_ws_envelope(data)
        if action_type is None:
            return None, None, None
        model_key = item["modelKey"]
        model_type = ModelType.from_string(model_key)

        # NVR is cached in a dedicated single-object slot; devices in dicts.
        if model_type is ModelType.NVR:
            new, old = self._apply_action(
                api, action_type, item, model_type, self._nvr_slot()
            )
            return model_type, new, old

        store = self._store_for(model_type)
        if store is None:
            _LOGGER.debug(
                "Public WS message for unsupported model %s ignored", model_key
            )
            return model_type, None, None

        new, old = self._apply_action(
            api, action_type, item, model_type, _dict_slot(store)
        )
        return model_type, new, old

    def process_events_ws_message(
        self,
        api: ProtectApiClient,
        data: dict[str, Any],
    ) -> tuple[Event | None, Event | None]:
        """
        Apply a public *events* WS payload to the event cache.

        Returns ``(new_event, old_event)``; either may be ``None``. Like
        devices, ``update`` is a partial diff that is merged into the
        existing event object.
        """
        action_type, item, _obj_id = _parse_ws_envelope(data)
        if action_type is None or item.get("modelKey") != ModelType.EVENT.value:
            return None, None
        new, old = self._apply_action(
            api, action_type, item, ModelType.EVENT, self._events_slot()
        )
        return cast("Event | None", new), cast("Event | None", old)

    # ------------------------------------------------------------------
    # Action application (shared by devices / NVR / events)
    # ------------------------------------------------------------------

    def _apply_action(
        self,
        api: ProtectApiClient,
        action_type: str,
        item: dict[str, Any],
        model_type: ModelType,
        slot: _Slot,
    ) -> tuple[ProtectModelWithId | None, ProtectModelWithId | None]:
        """
        Apply ``add`` / ``update`` / ``remove`` to a cache slot.

        ``slot`` abstracts over the storage shape (single-object NVR vs.
        id-keyed dict) so all three handlers share one code path.

        Return value semantics ``(new, old)``:

        * ``add`` success → ``(new, old)`` (``old`` is whatever was cached).
        * ``add`` failure → ``(None, old)`` — cache untouched.
        * ``remove`` → ``(None, old)`` — ``old`` removed from cache.
        * ``update`` on unknown id → ``(None, None)`` — cache untouched.
        * ``update`` merge success → ``(merged, old)``.
        * ``update`` merge failure → ``(None, old)`` — cache still contains
          ``old``; subscribers should not treat this as a delete.
        """
        obj_id = item["id"]
        old = slot.get(obj_id)

        if action_type == "remove":
            if old is not None:
                slot.delete(obj_id)
            return None, old

        if action_type == "add":
            try:
                if slot.factory is not None:
                    new = slot.factory(item, api)
                else:
                    new = cast(
                        ProtectModelWithId,
                        create_from_unifi_dict(item, api=api, model_type=model_type),
                    )
            except Exception as err:
                _warn_once(
                    self._warned_merge_failures,
                    ("add", model_type.value),
                    "Could not create %s from public API add payload: %s",
                    model_type.value,
                    err,
                )
                return None, old
            slot.put(obj_id, new)
            return new, old

        if action_type == "update":
            if old is None:
                # Update for an object not in the cache — typical when the
                # cache hasn't been primed yet. Drop; the reconnect hook /
                # next ``update_public`` refetches full state.
                # NOTE: returns ``(None, None)`` — distinct from a
                # merge-failure on a *known* id, which returns ``(None, old)``
                # (cache entry preserved; only the diff could not be applied).
                _LOGGER.debug(
                    "Public WS update for unknown %s id=%s; needs full refresh",
                    model_type.value,
                    obj_id,
                )
                return None, None
            merged = _merge(old, item, self._warned_merge_failures)
            if merged is not None:
                slot.put(obj_id, merged)
                return merged, old

        return None, old

    # ------------------------------------------------------------------
    # Slot factories
    # ------------------------------------------------------------------

    def _nvr_slot(self) -> _Slot:
        """Return a slot that stores the NVR in :attr:`nvr`."""

        def _get(_id: str) -> ProtectModelWithId | None:
            return self.nvr

        def _put(_id: str, obj: ProtectModelWithId) -> None:
            self.nvr = cast(PublicNVR, obj)

        def _delete(_id: str) -> None:
            self.nvr = None

        def _factory(item: dict[str, Any], api: ProtectApiClient) -> PublicNVR:
            return PublicNVR.from_unifi_dict(api=api, **item)

        return _Slot(_get, _put, _delete, factory=_factory)

    def _events_slot(self) -> _Slot:
        """Return a slot around :attr:`events` with LRU eviction."""
        events = self.events
        limit = self.max_event_cache_size

        def _get(obj_id: str) -> ProtectModelWithId | None:
            return events.get(obj_id)

        def _put(obj_id: str, obj: ProtectModelWithId) -> None:
            events[obj_id] = cast(Event, obj)
            events.move_to_end(obj_id)
            while events and len(events) > limit:
                events.popitem(last=False)

        def _delete(obj_id: str) -> None:
            events.pop(obj_id, None)

        return _Slot(_get, _put, _delete)


@dataclass(frozen=True, slots=True)
class _Slot:
    """Uniform get/put/delete interface over heterogeneous storage."""

    get: Callable[[str], ProtectModelWithId | None]
    put: Callable[[str, ProtectModelWithId], None]
    delete: Callable[[str], None]
    # Optional override for the ``add`` action; receives the raw item dict and
    # the ``ProtectApiClient`` instance.  When ``None`` the generic
    # ``create_from_unifi_dict`` path is used.
    factory: Callable[[dict[str, Any], ProtectApiClient], ProtectModelWithId] | None = (
        None
    )


def _dict_slot(store: dict[str, ProtectModelWithId]) -> _Slot:
    """Return a slot backed by an id-keyed dict."""

    def _delete(obj_id: str) -> None:
        store.pop(obj_id, None)

    return _Slot(
        store.get,
        store.__setitem__,
        _delete,
    )


def _parse_ws_envelope(
    data: dict[str, Any],
) -> tuple[str | None, dict[str, Any], str | None]:
    """
    Extract ``(action_type, item, id)`` from a WS envelope.

    Returns ``(None, {}, None)`` if required fields are missing.
    """
    action_type = data.get("type")
    item = data.get("item") or {}
    model_key = item.get("modelKey")
    obj_id = item.get("id")
    if not action_type or not model_key or not obj_id:
        return None, {}, None
    return action_type, item, obj_id


def _warn_once(
    warned_keys: set[tuple[str, str]], key: tuple[str, str], msg: str, *args: Any
) -> None:
    """Emit ``msg % args`` at WARNING on first occurrence, DEBUG afterwards."""
    if key in warned_keys:
        _LOGGER.debug(msg, *args)
        return
    warned_keys.add(key)
    _LOGGER.warning(msg, *args)


def _merge(
    old_obj: ProtectModelWithId,
    item: dict[str, Any],
    warned_keys: set[tuple[str, str]],
) -> ProtectModelWithId | None:
    """
    Merge a partial WS payload into ``old_obj`` in place.

    Drops ``id`` / ``modelKey`` (identity fields, never changed via update),
    feeds the remaining camelCase payload through the object's own
    :meth:`ProtectBaseObject.unifi_dict_to_dict` (which remaps keys, snake-
    cases and coerces types) and then applies the cleaned diff via
    :meth:`update_from_dict`. Returns the updated object, the original
    object (for empty / no-op payloads), or ``None`` if the payload could
    not be applied.
    """
    payload = {k: v for k, v in item.items() if k not in ("id", "modelKey")}
    if not payload:
        return old_obj
    try:
        cleaned = type(old_obj).unifi_dict_to_dict(dict(payload))
        if not cleaned:
            return old_obj
        old_obj.update_from_dict(cleaned)
    except Exception as err:
        # First occurrence per (ModelType, first-diff-key) is WARNING so a
        # schema break is visible in HA logs; subsequent occurrences drop
        # to DEBUG to avoid flooding.
        first_key = next(iter(payload), "?")
        _warn_once(
            warned_keys,
            (type(old_obj).__name__, first_key),
            "Failed to merge public WS update for %s (fields=%s): %s",
            type(old_obj).__name__,
            list(payload),
            err,
        )
        return None
    return old_obj
