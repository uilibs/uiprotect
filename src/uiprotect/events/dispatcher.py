"""Public events dispatcher."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import timedelta
from typing import TYPE_CHECKING

from ..data.websocket import WSAction
from ..utils import utc_now
from ._mapping import event_to_protect_event
from .enricher import EventEnricher
from .protect_event import (
    EVENT_TYPE_TO_CHANNEL,
    INSTANTANEOUS_EVENT_TYPES,
    EventChange,
    ProtectEvent,
    ProtectEventChannel,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..api import ProtectApiClient
    from ..data.nvr import Event


_LOGGER = logging.getLogger(__name__)


MAX_ACTIVE: int = 1024
_RECENTLY_ENDED_CAP: int = 256
EVENTS_ACTIVE_TTL: timedelta = timedelta(minutes=30)
EVENTS_TTL_SWEEP_INTERVAL: timedelta = timedelta(minutes=15)
EVENTS_RECONNECT_STALENESS_WINDOW: timedelta = timedelta(hours=1)


class EventDispatcher:
    """Owns ``_active`` state and fans out ``(ProtectEvent, EventChange)``."""

    def __init__(self, api: ProtectApiClient) -> None:
        self._api = api
        self._enricher = EventEnricher(api)
        self._subscribers: list[Callable[[ProtectEvent, EventChange], None]] = []
        self._active: dict[str, ProtectEvent] = {}
        self._recently_ended: OrderedDict[str, None] = OrderedDict()
        self._sweep_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Subscriber book-keeping
    # ------------------------------------------------------------------

    def add_subscriber(
        self, cb: Callable[[ProtectEvent, EventChange], None]
    ) -> None:
        self._subscribers.append(cb)

    def remove_subscriber(
        self, cb: Callable[[ProtectEvent, EventChange], None]
    ) -> None:
        self._subscribers.remove(cb)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def start_ttl_sweep(self) -> None:
        if self._sweep_task is not None and not self._sweep_task.done():
            return
        self._sweep_task = asyncio.create_task(self._ttl_sweep_loop())

    def stop_ttl_sweep(self) -> None:
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            self._sweep_task = None

    def reset(self) -> None:
        self._active.clear()
        self._recently_ended.clear()

    # ------------------------------------------------------------------
    # Active set helpers
    # ------------------------------------------------------------------

    def active_events(
        self, device_id: str | None = None
    ) -> list[ProtectEvent]:
        if device_id is None:
            return list(self._active.values())
        return [e for e in self._active.values() if e.device_id == device_id]

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def dispatch(self, action: WSAction, raw_event: Event) -> None:
        channel = EVENT_TYPE_TO_CHANNEL.get(raw_event.type, ProtectEventChannel.OTHER)
        # Filter to types HA-style consumers actually care about: anything
        # that lands in a non-OTHER channel. Drops administrative events
        # (provision, factoryReset, fwUpdate, …) while keeping schema-level
        # instantaneous lightMotion, sensor*, alarmHub* and access events
        # that ``device_events_set()`` historically omits.
        if channel is ProtectEventChannel.OTHER:
            return
        if raw_event.device_id is None:
            _LOGGER.warning(
                "Public event %s missing required 'device' field — dropping",
                raw_event.id,
            )
            return
        identity = self._enricher.enrich(raw_event)

        # Close-window branch: ADD already carrying ``end``, or schema-level
        # instantaneous type. Emit STARTED+ENDED, skip ``_active``.
        if action is WSAction.ADD and (
            raw_event.end is not None
            or raw_event.type in INSTANTANEOUS_EVENT_TYPES
        ):
            end_value = (
                raw_event.end if raw_event.end is not None else raw_event.start
            )
            event = event_to_protect_event(
                raw_event, channel, identity, end_override=end_value
            )
            self._fan_out(event, EventChange.STARTED)
            self._fan_out(event, EventChange.ENDED)
            self._record_terminal(event.id)
            return

        change = self._derive_change(action, raw_event)
        assert change is not None

        # Idempotency check for terminals: server retransmits ``update``+``end``
        # for the same id; surface exactly one terminal per id.
        if (
            change in (EventChange.ENDED, EventChange.REMOVED)
            and raw_event.id not in self._active
            and raw_event.id in self._recently_ended
        ):
            return

        event = event_to_protect_event(raw_event, channel, identity)

        if change is EventChange.STARTED:
            self._active[event.id] = event
            self._enforce_max_active()
        elif change is EventChange.UPDATED:
            if event.id in self._active:
                self._active[event.id] = event
        elif change in (EventChange.ENDED, EventChange.REMOVED):
            self._active.pop(event.id, None)
            self._record_terminal(event.id)

        self._fan_out(event, change)

    def _derive_change(
        self, action: WSAction, raw_event: Event
    ) -> EventChange | None:
        if action is WSAction.ADD:
            return EventChange.STARTED
        if action is WSAction.UPDATE:
            if raw_event.end is not None:
                return EventChange.ENDED
            return EventChange.UPDATED
        # WSAction.REMOVE
        return EventChange.REMOVED

    # ------------------------------------------------------------------
    # Bookkeeping helpers
    # ------------------------------------------------------------------

    def _record_terminal(self, event_id: str) -> None:
        if event_id in self._recently_ended:
            self._recently_ended.move_to_end(event_id)
        else:
            self._recently_ended[event_id] = None
        while len(self._recently_ended) > _RECENTLY_ENDED_CAP:
            self._recently_ended.popitem(last=False)

    def _enforce_max_active(self) -> None:
        while len(self._active) > MAX_ACTIVE:
            oldest_id = min(self._active, key=lambda k: self._active[k].start)
            oldest = self._active.pop(oldest_id)
            synth = oldest.model_copy(update={"end": utc_now()})
            self._fan_out(synth, EventChange.ENDED)
            self._record_terminal(oldest_id)

    def _fan_out(self, event: ProtectEvent, change: EventChange) -> None:
        for cb in self._subscribers:
            try:
                cb(event, change)
            except Exception:
                _LOGGER.exception(
                    "Exception while running subscribe_events subscriber"
                )

    # ------------------------------------------------------------------
    # Reconnect / TTL sweep
    # ------------------------------------------------------------------

    def flush_stale_on_reconnect(self) -> int:
        cutoff = utc_now() - EVENTS_RECONNECT_STALENESS_WINDOW
        count = 0
        for event_id in list(self._active):
            event = self._active[event_id]
            if event.start < cutoff:
                self._active.pop(event_id, None)
                synth = event.model_copy(update={"end": utc_now()})
                self._fan_out(synth, EventChange.ENDED)
                self._record_terminal(event_id)
                count += 1
        return count

    def sweep_stale(self) -> int:
        cutoff = utc_now() - EVENTS_ACTIVE_TTL
        count = 0
        for event_id in list(self._active):
            event = self._active[event_id]
            if event.start < cutoff:
                self._active.pop(event_id, None)
                synth = event.model_copy(update={"end": utc_now()})
                self._fan_out(synth, EventChange.ENDED)
                self._record_terminal(event_id)
                count += 1
        if count > 0:
            _LOGGER.warning("TTL-swept %d stale active events", count)
        return count

    async def _ttl_sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(EVENTS_TTL_SWEEP_INTERVAL.total_seconds())
                self.sweep_stale()
        except asyncio.CancelledError:
            return
