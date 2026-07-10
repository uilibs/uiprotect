"""Stateless public events dispatcher over the single PublicBootstrap store."""

from __future__ import annotations

import asyncio
import logging
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
    from ..data.public_event import PublicEvent


_LOGGER = logging.getLogger(__name__)


EVENTS_ACTIVE_TTL: timedelta = timedelta(minutes=30)
EVENTS_TTL_SWEEP_INTERVAL: timedelta = timedelta(minutes=15)
EVENTS_RECONNECT_STALENESS_WINDOW: timedelta = timedelta(hours=1)


class EventDispatcher:
    """Derive ``(ProtectEvent, EventChange)`` from the single event store."""

    def __init__(self, api: ProtectApiClient) -> None:
        self._api = api
        self._enricher = EventEnricher(api)
        self._subscribers: list[Callable[[ProtectEvent, EventChange], None]] = []
        self._sweep_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Subscriber book-keeping
    # ------------------------------------------------------------------

    def add_subscriber(self, cb: Callable[[ProtectEvent, EventChange], None]) -> None:
        self._subscribers.append(cb)

    def remove_subscriber(
        self, cb: Callable[[ProtectEvent, EventChange], None]
    ) -> None:
        # Idempotent: the unsubscribe callable returned by ``subscribe_events``
        # may be invoked more than once (e.g. double cleanup on HA reload).
        if cb in self._subscribers:
            self._subscribers.remove(cb)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _device_mac(self, device_id: str | None) -> str | None:
        if device_id is None:
            return None
        return self._api.public_bootstrap.get_device_mac(device_id)

    # ------------------------------------------------------------------
    # Active set — pure derivation over the single store
    # ------------------------------------------------------------------

    def active_events(self, device_id: str | None = None) -> list[ProtectEvent]:
        out: list[ProtectEvent] = []
        for raw in self._api.public_bootstrap.events.values():
            if raw.end is not None:
                continue
            channel = EVENT_TYPE_TO_CHANNEL.get(raw.type, ProtectEventChannel.OTHER)
            if channel is ProtectEventChannel.OTHER or raw.device_id is None:
                continue
            if device_id is not None and raw.device_id != device_id:
                continue
            out.append(
                event_to_protect_event(
                    raw,
                    channel,
                    self._enricher.enrich(raw),
                    device_mac=self._device_mac(raw.device_id),
                )
            )
        return out

    # ------------------------------------------------------------------
    # Main dispatch — one terminal chokepoint fed by the store's old/new
    # ------------------------------------------------------------------

    def dispatch(
        self,
        action: WSAction,
        new_event: PublicEvent | None,
        old_event: PublicEvent | None,
    ) -> None:
        # ``new_event`` is the post-merge cached object (``None`` only on
        # REMOVE); ``old_event`` is the pre-merge snapshot the store handed
        # back. The subject is whichever one carries the event payload.
        subject = new_event if new_event is not None else old_event
        if subject is None:
            return

        channel = EVENT_TYPE_TO_CHANNEL.get(subject.type, ProtectEventChannel.OTHER)
        # Drop administrative events (provision, factoryReset, fwUpdate, …)
        # that land in the OTHER channel while keeping detection / sensor /
        # alarm-hub / access events that consumers care about.
        if channel is ProtectEventChannel.OTHER:
            return
        if subject.device_id is None:
            _LOGGER.warning(
                "Public event %s missing required 'device' field — dropping",
                subject.id,
            )
            return

        for event, change in self._derive(
            action, subject, channel, new_event, old_event
        ):
            self._fan_out(event, change)

    def _derive(
        self,
        action: WSAction,
        subject: PublicEvent,
        channel: ProtectEventChannel,
        new_event: PublicEvent | None,
        old_event: PublicEvent | None,
    ) -> list[tuple[ProtectEvent, EventChange]]:
        identity = self._enricher.enrich(subject)
        device_mac = self._device_mac(subject.device_id)
        # The single idempotency guard: was the event already terminal in the
        # store before this frame? A retransmit/replay finds it so and is
        # suppressed.
        old_terminal = old_event is not None and old_event.end is not None

        instantaneous = subject.type in INSTANTANEOUS_EVENT_TYPES
        if action is WSAction.ADD and (subject.end is not None or instantaneous):
            # Close-window: emit STARTED + ENDED on first sight only.
            if old_terminal:
                return []
            end_value = subject.end if subject.end is not None else subject.start
            # Close the event in the store so a replay ADD is suppressed (its
            # snapshot will then carry ``end``) and ``active_events`` does not
            # surface an instantaneous event as still open.
            if subject.end is None and new_event is not None:
                new_event.end = end_value
            event = event_to_protect_event(
                subject,
                channel,
                identity,
                end_override=end_value,
                device_mac=device_mac,
            )
            return [(event, EventChange.STARTED), (event, EventChange.ENDED)]

        if action is WSAction.ADD:
            change = EventChange.STARTED
        elif action is WSAction.REMOVE:
            if old_terminal:
                return []
            change = EventChange.REMOVED
        elif subject.end is not None:
            if old_terminal:
                return []
            change = EventChange.ENDED
        else:
            change = EventChange.UPDATED
        return [
            (
                event_to_protect_event(
                    subject, channel, identity, device_mac=device_mac
                ),
                change,
            )
        ]

    def _fan_out(self, event: ProtectEvent, change: EventChange) -> None:
        # Snapshot: a subscriber may unsubscribe (itself or another) mid-delivery,
        # mutating the list and skipping callbacks if iterated live.
        for cb in tuple(self._subscribers):
            try:
                cb(event, change)
            except Exception:
                _LOGGER.exception("Exception while running subscribe_events subscriber")

    # ------------------------------------------------------------------
    # TTL / reconnect sweep — one mechanism over the single store
    # ------------------------------------------------------------------

    def start_ttl_sweep(self) -> None:
        if self._sweep_task is not None and not self._sweep_task.done():
            return
        self._sweep_task = asyncio.create_task(self._ttl_sweep_loop())
        self._sweep_task.add_done_callback(self._on_sweep_task_done)

    def stop_ttl_sweep(self) -> None:
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            self._sweep_task = None

    @staticmethod
    def _on_sweep_task_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _LOGGER.exception("TTL sweep loop terminated unexpectedly", exc_info=exc)

    def sweep_stale(self) -> int:
        """Force-end events open past :data:`EVENTS_ACTIVE_TTL`."""
        count = self._sweep(EVENTS_ACTIVE_TTL)
        if count > 0:
            _LOGGER.warning("TTL-swept %d stale active events", count)
        return count

    def flush_stale_on_reconnect(self) -> int:
        """Force-end events open past the reconnect staleness window."""
        return self._sweep(EVENTS_RECONNECT_STALENESS_WINDOW)

    def force_end_on_events_reconnect(self) -> int:
        """
        Reconcile the store after an events-WS reconnect.

        Events arrive *only* on the events WS, so an END missed during the gap
        leaves the event active and a camera's derived ``is_*_currently_detected``
        stuck ON. The staleness window is 1 h, which would miss a short blip, so
        detection-channel events are force-ended regardless of age — a genuinely
        still-active detection re-asserts on its next frame. Other channels keep
        the age gate.
        """
        return self._sweep(EVENTS_RECONNECT_STALENESS_WINDOW, force_detection=True)

    def _sweep(
        self, staleness_window: timedelta, *, force_detection: bool = False
    ) -> int:
        now = utc_now()
        cutoff = now - staleness_window
        pb = self._api.public_bootstrap
        ended: list[PublicEvent] = []
        for raw in list(pb.events.values()):
            if raw.end is not None:
                continue
            channel = EVENT_TYPE_TO_CHANNEL.get(raw.type, ProtectEventChannel.OTHER)
            if channel is ProtectEventChannel.OTHER or raw.device_id is None:
                continue
            forced = force_detection and channel is ProtectEventChannel.DETECTION
            if not forced and raw.start >= cutoff:
                continue
            # Mark the stored event ended so a later close retransmit is
            # suppressed by the dispatch chokepoint and derivation stays
            # consistent.
            raw.end = now
            event = event_to_protect_event(
                raw,
                channel,
                self._enricher.enrich(raw),
                device_mac=self._device_mac(raw.device_id),
            )
            self._fan_out(event, EventChange.ENDED)
            ended.append(raw)
        # Sync the owning cameras' derived detection state through the store's
        # single choke point and push the resulting device updates so pull and
        # subscribe_devices consumers see the flag drop, not just the TTL sweep.
        for update in pb._sync_force_ended_events(ended):
            self._api.emit_devices_message(update)
        return len(ended)

    async def _ttl_sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(EVENTS_TTL_SWEEP_INTERVAL.total_seconds())
                try:
                    self.sweep_stale()
                except Exception:
                    _LOGGER.exception("TTL sweep iteration failed — continuing loop")
        except asyncio.CancelledError:
            return
