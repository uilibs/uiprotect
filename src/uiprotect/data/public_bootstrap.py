"""
UniFi Protect Public Integration API bootstrap.

This is an opt-in, separate cache for the Public Integration API. It is
*not* populated by :meth:`ProtectApiClient.update` and does not
touch the private :class:`~uiprotect.data.bootstrap.Bootstrap` in any way.

Consumers (e.g. Home Assistant) pick one of two ordering contracts:

* **Typed** (``subscribe_devices`` / ``subscribe_events``): call
  ``await update_public()`` *first* to prime the cache, then subscribe. These
  deliver merged public models, so they require the primed cache and raise
  ``RuntimeError`` if it is missing.
* **Raw** (``subscribe_devices_websocket`` / ``subscribe_events_websocket``):
  subscribe *first*, then ``await update_public()``. The websocket is live
  during priming so no frame is missed; pre-prime frames arrive via
  ``changed_data`` with ``new_obj=None``.

WS messages that arrive while ``update_public()`` is still priming are
delivered to raw subscribers (via ``changed_data``), but they may not yet be
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
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from .base import ProtectModelWithId
from .convert import create_from_unifi_dict
from .public_devices import (
    ArmProfile,
    Fob,
    LinkStation,
    NvrArmMode,
    PublicBridge,
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicLiveview,
    PublicNVR,
    PublicSensor,
    PublicUlpUser,
    PublicViewer,
    Relay,
    Siren,
    Speaker,
)
from .public_event import PublicEvent
from .types import DeviceState, ModelType
from .websocket import WSAction, WSSubscriptionMessage

if TYPE_CHECKING:
    from ..api import ProtectApiClient


_LOGGER = logging.getLogger(__name__)


class EventsFrameResult(NamedTuple):
    """Outputs of applying one public events-WS frame to the cache."""

    new_event: PublicEvent | None
    old_event: PublicEvent | None
    model_updates: list[WSSubscriptionMessage]


# Default cap on the public event cache. Matches the private Bootstrap
# default so memory behaviour is symmetric between the two caches.
DEFAULT_PUBLIC_EVENT_CACHE_SIZE = 1000

# Fields a lone ``update`` event frame must carry (all non-``None``) before it
# can be promoted to a synthesized ``add`` — only *completed* events whose
# payload is self-sufficient qualify, so no dangling open event is ever created.
_BORN_CLOSED_REQUIRED_FIELDS = ("id", "type", "start", "end", "device")


# Single source of truth: ``ModelType`` -> (store attribute, public model
# class | None). Only the device types the Public Integration API actually
# exposes are listed; unsupported keys (``doorlock`` etc.) resolve to ``None``
# and are logged at DEBUG in :meth:`process_devices_ws_message`.
#
# ``public_cls`` is set for the four types whose ``ModelType`` collides with a
# private ``MODEL_TO_CLASS`` entry (``camera``/``light``/``sensor``/``chime``):
# the generic ``create_from_unifi_dict`` path would build the private model
# (reintroducing phantom fields), so they get a dedicated public-API factory
# slot via :meth:`_public_device_slot`. ``None`` means the generic path builds
# the correct class. Every store here carries a ``mac`` field, so
# :meth:`get_device_mac` iterates this registry directly.
_PUBLIC_STORES: dict[ModelType, tuple[str, type[ProtectModelWithId] | None]] = {
    ModelType.CAMERA: ("cameras", PublicCamera),
    ModelType.LIGHT: ("lights", PublicLight),
    ModelType.SENSOR: ("sensors", PublicSensor),
    ModelType.CHIME: ("chimes", PublicChime),
    ModelType.SIREN: ("sirens", None),
    ModelType.RELAY: ("relays", None),
    ModelType.FOB: ("fobs", None),
    ModelType.SPEAKER: ("speakers", None),
    ModelType.LINK_STATION: ("link_stations", None),
}

# Collision-routed types that keep a dedicated ``_X_slot()`` factory (their
# ``ModelType`` is owned by a private class in ``MODEL_TO_CLASS``). They carry
# no ``mac`` and so are excluded from :data:`_PUBLIC_STORES`.
_DEDICATED_SLOT_STORE_ATTRS: dict[ModelType, str] = {
    ModelType.LIVEVIEW: "liveviews",
    ModelType.BRIDGE: "bridges",
    ModelType.VIEWPORT: "viewers",
}


@dataclass(frozen=True, slots=True)
class DeviceWSResult:
    """One expanded per-device outcome of a public devices WS frame."""

    model_type: ModelType | None
    new_obj: ProtectModelWithId | None
    old_obj: ProtectModelWithId | None
    # Per-id raw payload (``id`` is always scalar here, even for bulk frames).
    item: dict[str, Any]


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
    #
    # ``cameras``/``lights``/``sensors``/``chimes`` hold dedicated ``Public*``
    # models — they share a ``ModelType`` with the private classes, so they are
    # routed via factory slots (see :meth:`_custom_slot_for`), not the generic
    # ``MODEL_TO_CLASS`` path.
    cameras: dict[str, PublicCamera] = field(default_factory=dict)
    lights: dict[str, PublicLight] = field(default_factory=dict)
    sensors: dict[str, PublicSensor] = field(default_factory=dict)
    chimes: dict[str, PublicChime] = field(default_factory=dict)
    sirens: dict[str, Siren] = field(default_factory=dict)
    relays: dict[str, Relay] = field(default_factory=dict)
    fobs: dict[str, Fob] = field(default_factory=dict)
    speakers: dict[str, Speaker] = field(default_factory=dict)
    # Link stations *and* alarm hubs share one schema (``modelKey: "linkstation"``),
    # so a single store catches WS frames for both. Use :attr:`alarm_hubs` for the
    # filtered view.
    link_stations: dict[str, LinkStation] = field(default_factory=dict)
    # ``liveviews``, ``bridges`` and ``viewers`` are deliberately kept out of
    # :data:`_DEVICE_STORES` because their ``ModelType`` values
    # (``LIVEVIEW`` / ``BRIDGE`` / ``VIEWPORT``) are already owned by the
    # private ``Liveview`` / ``Bridge`` / ``Viewer`` classes in
    # ``MODEL_TO_CLASS``. The WS handler routes each to its own store via an
    # explicit branch with a public-API-aware factory.
    liveviews: dict[str, PublicLiveview] = field(default_factory=dict)
    bridges: dict[str, PublicBridge] = field(default_factory=dict)
    viewers: dict[str, PublicViewer] = field(default_factory=dict)

    # Events received via the events websocket (:meth:`process_events_ws_message`).
    # Bounded by :attr:`max_event_cache_size`; oldest events are evicted first.
    # Entries may be synthetically end-marked (``end`` set) by the public
    # events TTL/reconnect sweep, not only by a server-sent close frame — so a
    # non-``None`` ``end`` here does not always correspond to a WS payload.
    events: OrderedDict[str, PublicEvent] = field(default_factory=OrderedDict)
    max_event_cache_size: int = DEFAULT_PUBLIC_EVENT_CACHE_SIZE

    # UniFi Identity (ULP) users, indexed by ulp id. Single source of truth
    # for event-identity enrichment; refreshed by ``update_public`` (and so,
    # via the reconnect resync, refreshed on reconnect too). Empty when the
    # Identity service is disabled.
    ulp_users: dict[str, PublicUlpUser] = field(default_factory=dict)

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

    # Per-camera detection-state snapshots taken before the first mutation of an
    # events-WS frame, keyed by camera id. Populated while a single
    # :meth:`process_events_ws_message` call applies its frame (including any
    # eviction it triggers) and drained by :meth:`_drain_detection_updates`.
    # Transient within one synchronous call, so per-instance is sufficient.
    _detection_state_before: dict[str, dict[str, bool]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @property
    def alarm_hubs(self) -> dict[str, LinkStation]:
        """Subset of :attr:`link_stations` filtered to alarm hubs."""
        return {k: v for k, v in self.link_stations.items() if v.is_alarm_hub}

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

    def _store_for(self, model_type: ModelType) -> dict[str, ProtectModelWithId] | None:
        store = _PUBLIC_STORES.get(model_type)
        if store is not None:
            attr: str | None = store[0]
        else:
            attr = _DEDICATED_SLOT_STORE_ATTRS.get(model_type)
        if attr is None:
            return None
        return cast("dict[str, ProtectModelWithId]", getattr(self, attr))

    def get(self, model_type: ModelType, obj_id: str) -> ProtectModelWithId | None:
        """Look up a cached device by model type and id."""
        store = self._store_for(model_type)
        if store is None:
            return None
        return store.get(obj_id)

    def get_device_mac(self, device_id: str) -> str | None:
        """Resolve a device id to its mac across the public device stores."""
        for store_attr, _cls in _PUBLIC_STORES.values():
            obj = getattr(self, store_attr).get(device_id)
            if obj is not None:
                return getattr(obj, "mac", None)
        return None

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

    def supports_device(self, model_type: ModelType) -> bool:
        """Return whether ``model_type`` maps to a public device store."""
        return model_type in _PUBLIC_STORES or model_type in _DEDICATED_SLOT_STORE_ATTRS

    def process_devices_ws_messages(
        self,
        api: ProtectApiClient,
        data: dict[str, Any],
    ) -> list[DeviceWSResult]:
        """
        Apply a public *devices* WS frame to the cache, expanding bulk forms.

        The bulk envelopes (``devicesAdd`` / ``devicesBulkUpdate`` /
        ``devicesBulkRemove``) share a single ``item`` whose ``id`` is a list
        of ids with one shared ``modelKey`` and payload. This fans that out to
        one :class:`DeviceWSResult` per id (each carrying a scalar-``id``
        ``item``); a single-id frame yields a one-element list. An empty
        ``id`` array yields an empty list.
        """
        action_type, item, _obj_id = _parse_ws_envelope(data)
        if action_type is None:
            return []
        raw_id = item.get("id")
        if isinstance(raw_id, list):
            expanded = [{**item, "id": one_id} for one_id in raw_id]
        else:
            expanded = [item]
        return [self._apply_one(api, action_type, one) for one in expanded]

    def process_devices_ws_message(
        self,
        api: ProtectApiClient,
        data: dict[str, Any],
    ) -> tuple[ModelType | None, ProtectModelWithId | None, ProtectModelWithId | None]:
        """
        Apply a public *devices* WS payload to the cache.

        Back-compat façade over :meth:`process_devices_ws_messages`: returns
        the first expanded result's ``(model_type, new_obj, old_obj)`` 3-tuple,
        or ``(None, None, None)`` when nothing was produced. Callers that need
        per-device frames for bulk envelopes should use the plural form.

        ``update`` messages carry **partial diffs** — only the changed
        fields. They are merged into the existing cached object via
        :meth:`ProtectBaseObject.update_from_dict`; reconstructing from a
        partial payload would fail strict validation for required fields.
        """
        results = self.process_devices_ws_messages(api, data)
        if not results:
            return None, None, None
        first = results[0]
        return first.model_type, first.new_obj, first.old_obj

    def _apply_one(
        self,
        api: ProtectApiClient,
        action_type: str,
        item: dict[str, Any],
    ) -> DeviceWSResult:
        """Route a single scalar-``id`` device item to its cache slot."""
        model_key = item["modelKey"]
        model_type = ModelType.from_string(model_key)

        # NVR is cached in a dedicated single-object slot; collision-routed
        # types (Liveview / Bridge / Viewer share their ``ModelType`` with the
        # private ``MODEL_TO_CLASS`` entries) get their own factory-equipped
        # slot. Everything else routes through the generic ``_store_for`` dict.
        # Snapshot the pre-apply camera state: ``update`` merges in place, so
        # the ``old`` returned by ``_apply_action`` is the same (now mutated)
        # instance as ``new`` and can't be compared against it afterwards.
        prev_state = self._camera_state_before_apply(model_type, item)

        custom_slot = self._custom_slot_for(model_type)
        if custom_slot is not None:
            new, old = self._apply_action(
                api, action_type, item, model_type, custom_slot
            )
            self._refresh_rtsps_on_reconnect(api, model_type, new, prev_state)
            self._evict_rtsps_on_remove(api, model_type, action_type, item)
            return DeviceWSResult(model_type, new, old, item)

        store = self._store_for(model_type)
        if store is None:
            _LOGGER.debug(
                "Public WS message for unsupported model %s ignored", model_key
            )
            return DeviceWSResult(model_type, None, None, item)

        new, old = self._apply_action(
            api, action_type, item, model_type, _dict_slot(store)
        )
        return DeviceWSResult(model_type, new, old, item)

    def _camera_state_before_apply(
        self, model_type: ModelType, item: dict[str, Any]
    ) -> DeviceState | None:
        """Return the cached camera's ``state`` prior to applying this frame."""
        if model_type is not ModelType.CAMERA:
            return None
        cached = self.cameras.get(item["id"])
        return cached.state if cached is not None else None

    def _refresh_rtsps_on_reconnect(
        self,
        api: ProtectApiClient,
        model_type: ModelType,
        new: ProtectModelWithId | None,
        prev_state: DeviceState | None,
    ) -> None:
        """
        Schedule an RTSPS prime/refresh when a camera transitions to CONNECTED.

        A camera that was offline at ``update_public()`` time carries no streams;
        the CONNECTED transition primes it. An already-populated one is refreshed
        in place.
        """
        if model_type is not ModelType.CAMERA or new is None:
            return
        if (
            getattr(new, "state", None) is DeviceState.CONNECTED
            and prev_state is not DeviceState.CONNECTED
        ):
            api._schedule_rtsps_refresh(new.id)

    def _evict_rtsps_on_remove(
        self,
        api: ProtectApiClient,
        model_type: ModelType,
        action_type: str,
        item: dict[str, Any],
    ) -> None:
        """
        Cancel any in-flight RTSPS refresh for a removed camera.

        A ``remove`` frame deletes the camera from the device store, taking its
        ``rtsps_streams`` field with it. Any in-flight background refresh for the
        camera is cancelled so it cannot resurrect a now-removed camera.
        """
        if model_type is ModelType.CAMERA and action_type == "remove":
            api._cancel_rtsps_refresh(item["id"])

    def _custom_slot_for(self, model_type: ModelType) -> _Slot | None:
        """Return the dedicated public-API slot for collision-routed types."""
        if model_type is ModelType.NVR:
            return self._nvr_slot()
        if model_type is ModelType.LIVEVIEW:
            return self._liveviews_slot()
        if model_type is ModelType.BRIDGE:
            return self._bridges_slot()
        if model_type is ModelType.VIEWPORT:
            return self._viewers_slot()
        store = _PUBLIC_STORES.get(model_type)
        if store is not None:
            store_attr, cls = store
            if cls is not None:
                return self._public_device_slot(getattr(self, store_attr), cls)
        return None

    @staticmethod
    def _public_device_slot(
        store: dict[str, Any],
        cls: type[ProtectModelWithId],
    ) -> _Slot:
        """Return a slot around a public device store with a public-API factory."""

        def _factory(item: dict[str, Any], api: ProtectApiClient) -> ProtectModelWithId:
            return cls.from_unifi_dict(api=api, **item)

        return _dict_slot(
            cast("dict[str, ProtectModelWithId]", store),
            factory=_factory,
        )

    def process_events_ws_message(
        self,
        api: ProtectApiClient,
        data: dict[str, Any],
    ) -> EventsFrameResult:
        """
        Apply a public *events* WS payload to the event cache.

        Returns an :class:`EventsFrameResult` (a tuple-compatible
        ``NamedTuple`` of ``new_event``, ``old_event``, ``model_updates``).
        ``new_event`` /
        ``old_event`` may be ``None``; ``old_event`` is a **pre-merge snapshot**
        of the cached event taken before this frame is applied — ``update``
        merges its partial diff into the cached object *in place*, so without
        the snapshot ``old`` and ``new`` would be the same mutated instance.
        The snapshot lets a consumer detect the open→closed transition
        (``old.end is None`` and ``new.end is not None``) and reject retransmits
        idempotently.

        ``model_updates`` are devices-WS ``update`` messages for any camera
        whose derived detection booleans net-flipped over this frame — the
        first-class device-model outputs of processing the events frame. The
        api handler emits them through the standard devices channel with no
        knowledge that they originated from a detection event.
        """
        action_type, item, _obj_id = _parse_ws_envelope(data)
        if action_type is None or item.get("modelKey") != ModelType.EVENT.value:
            return EventsFrameResult(None, None, [])
        obj_id = item.get("id")
        cached = self.events.get(obj_id) if obj_id else None
        # Intentionally a shallow copy: the idempotency chokepoint only reads
        # the top-level ``end`` (captured pre-merge here). Nested objects are
        # shared, but a deep copy on every event frame is avoided on this hot
        # path.
        old_snapshot = cached.model_copy() if cached is not None else None
        self._detection_state_before.clear()
        new, _old = self._apply_action(
            api, action_type, item, ModelType.EVENT, self._events_slot()
        )
        return EventsFrameResult(
            cast("PublicEvent | None", new),
            old_snapshot,
            self._drain_detection_updates(),
        )

    def _drain_detection_updates(self) -> list[WSSubscriptionMessage]:
        """
        Build devices-WS ``update`` messages for cameras whose detection flipped.

        Diffs each camera's pre-frame snapshot against its current derived
        booleans, yielding one ``update`` (``new_obj=camera``, ``changed_data``
        naming only the flipped fields) per camera whose flags actually changed.
        Clears the pending snapshots, so a second call returns an empty list.
        """
        updates: list[WSSubscriptionMessage] = []
        for camera_id, before in self._detection_state_before.items():
            camera = self.cameras.get(camera_id)
            if camera is None:
                continue
            after = camera._detection_state()
            changed = {k: v for k, v in after.items() if v != before[k]}
            if changed:
                updates.append(
                    WSSubscriptionMessage(
                        action=WSAction.UPDATE,
                        new_update_id=camera.id,
                        changed_data=cast("dict[str, Any]", changed),
                        new_obj=camera,
                        old_obj=None,
                    )
                )
        self._detection_state_before.clear()
        return updates

    def _snapshot_camera_detection_state(self, camera: PublicCamera) -> None:
        """Record a camera's pre-mutation detection snapshot once per events frame."""
        if camera.id not in self._detection_state_before:
            self._detection_state_before[camera.id] = camera._detection_state()

    def _sync_camera_detection_state(self, event: PublicEvent) -> None:
        """Fold a cached event into its owning camera's active detection set."""
        if event.device_id is None:
            return
        camera = self.cameras.get(event.device_id)
        if camera is not None:
            self._snapshot_camera_detection_state(camera)
            camera._apply_detection_event(event)

    def _clear_camera_detection_event(self, event: PublicEvent) -> None:
        """Drop an evicted/removed event from its owning camera's active set."""
        if event.device_id is None:
            return
        camera = self.cameras.get(event.device_id)
        if camera is not None:
            self._snapshot_camera_detection_state(camera)
            camera._clear_detection_event(event.id)

    def _sync_force_ended_events(
        self, events: list[PublicEvent]
    ) -> list[WSSubscriptionMessage]:
        """
        Clear force-ended events from their cameras' active detection sets.

        Returns one devices-WS ``update`` per camera whose derived detection
        flags flipped, so a sweep that force-ends events out-of-band (TTL /
        reconnect) keeps the camera model and its subscribers in sync through
        the same choke point the normal events path uses.
        """
        self._detection_state_before.clear()
        for event in events:
            self._clear_camera_detection_event(event)
        return self._drain_detection_updates()

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
                        "ProtectModelWithId",
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
                return self._apply_unknown_update(api, item, model_type, slot, obj_id)
            merged = _merge(old, item, self._warned_merge_failures)
            if merged is not None:
                slot.put(obj_id, merged)
                return merged, old

        return None, old

    def _apply_unknown_update(
        self,
        api: ProtectApiClient,
        item: dict[str, Any],
        model_type: ModelType,
        slot: _Slot,
        obj_id: str,
    ) -> tuple[ProtectModelWithId | None, ProtectModelWithId | None]:
        """
        Handle an ``update`` whose id is not in the cache.

        Born-closed event: a lone ``update`` for an unseen event id whose
        payload is self-sufficient and already closed (package smart-detect
        arrives this way — one closed frame, no preceding ``add``) is promoted
        to an ``add`` so the dispatcher's close-window logic can emit STARTED +
        ENDED. Returns ``(new, None)`` on promotion.

        Otherwise drops: returns ``(None, None)`` — distinct from a merge
        failure on a *known* id, which returns ``(None, old)`` (cache entry
        preserved; only the diff could not be applied). The reconnect hook /
        next ``update_public`` refetches full state.
        """
        synthesized = self._synthesize_born_closed_event(api, item, model_type)
        if synthesized is not None:
            slot.put(obj_id, synthesized)
            return synthesized, None
        _LOGGER.debug(
            "Public WS update for unknown %s id=%s; needs full refresh",
            model_type.value,
            obj_id,
        )
        return None, None

    def _synthesize_born_closed_event(
        self,
        api: ProtectApiClient,
        item: dict[str, Any],
        model_type: ModelType,
    ) -> ProtectModelWithId | None:
        """
        Build a closed :class:`PublicEvent` from a lone ``update`` for an unseen
        id.

        Returns the event only when scoped to the EVENT store and the payload
        is self-sufficient and already closed (every field in
        :data:`_BORN_CLOSED_REQUIRED_FIELDS` set); otherwise ``None`` so the
        caller keeps the drop-and-refresh behaviour. Devices/NVR are never
        synthesized from a partial diff.
        """
        if model_type is not ModelType.EVENT:
            return None
        if any(
            item.get(field_name) is None for field_name in _BORN_CLOSED_REQUIRED_FIELDS
        ):
            return None
        try:
            return PublicEvent.from_unifi_dict(api=api, **item)
        except Exception as err:
            _warn_once(
                self._warned_merge_failures,
                ("born_closed", model_type.value),
                "Could not synthesize %s from public API born-closed update: %s",
                model_type.value,
                err,
            )
            return None

    def _nvr_slot(self) -> _Slot:
        """Return a slot that stores the NVR in :attr:`nvr`."""

        def _get(_id: str) -> ProtectModelWithId | None:
            return self.nvr

        def _put(_id: str, obj: ProtectModelWithId) -> None:
            self.nvr = cast("PublicNVR", obj)

        def _delete(_id: str) -> None:
            self.nvr = None

        def _factory(item: dict[str, Any], api: ProtectApiClient) -> PublicNVR:
            return PublicNVR.from_unifi_dict(api=api, **item)

        return _Slot(_get, _put, _delete, factory=_factory)

    def _liveviews_slot(self) -> _Slot:
        """Return a slot around :attr:`liveviews` with a public-API factory."""

        def _factory(item: dict[str, Any], api: ProtectApiClient) -> PublicLiveview:
            return PublicLiveview.from_unifi_dict(api=api, **item)

        return _dict_slot(
            cast("dict[str, ProtectModelWithId]", self.liveviews),
            factory=_factory,
        )

    def _bridges_slot(self) -> _Slot:
        """Return a slot around :attr:`bridges` with a public-API factory."""

        def _factory(item: dict[str, Any], api: ProtectApiClient) -> PublicBridge:
            return PublicBridge.from_unifi_dict(api=api, **item)

        return _dict_slot(
            cast("dict[str, ProtectModelWithId]", self.bridges),
            factory=_factory,
        )

    def _viewers_slot(self) -> _Slot:
        """Return a slot around :attr:`viewers` with a public-API factory."""

        def _factory(item: dict[str, Any], api: ProtectApiClient) -> PublicViewer:
            return PublicViewer.from_unifi_dict(api=api, **item)

        return _dict_slot(
            cast("dict[str, ProtectModelWithId]", self.viewers),
            factory=_factory,
        )

    def _events_slot(self) -> _Slot:
        """Return a slot around :attr:`events` with LRU eviction."""
        events = self.events
        limit = self.max_event_cache_size

        def _get(obj_id: str) -> ProtectModelWithId | None:
            return events.get(obj_id)

        def _put(obj_id: str, obj: ProtectModelWithId) -> None:
            event = cast("PublicEvent", obj)
            events[obj_id] = event
            events.move_to_end(obj_id)
            # Sync the owning camera's active set at the single cache choke
            # point: an open event turns its flag(s) on, an ended one off.
            self._sync_camera_detection_state(event)
            while events and len(events) > limit:
                _evicted_id, evicted = events.popitem(last=False)
                # An evicted open event can never receive its close update, so
                # clear it here to keep the camera flag from sticking on (and
                # the active set bounded to the cache).
                self._clear_camera_detection_event(cast("PublicEvent", evicted))

        def _delete(obj_id: str) -> None:
            evicted = events.pop(obj_id, None)
            if evicted is not None:
                self._clear_camera_detection_event(evicted)

        def _factory(item: dict[str, Any], api: ProtectApiClient) -> PublicEvent:
            return PublicEvent.from_unifi_dict(api=api, **item)

        return _Slot(_get, _put, _delete, factory=_factory)


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


def _dict_slot(
    store: dict[str, ProtectModelWithId],
    factory: Callable[[dict[str, Any], ProtectApiClient], ProtectModelWithId]
    | None = None,
) -> _Slot:
    """Return a slot backed by an id-keyed dict."""

    def _delete(obj_id: str) -> None:
        store.pop(obj_id, None)

    return _Slot(
        store.get,
        store.__setitem__,
        _delete,
        factory=factory,
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
