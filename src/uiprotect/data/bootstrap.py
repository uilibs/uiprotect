"""UniFi Protect Bootstrap."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import TYPE_CHECKING, Any, cast

from aiohttp.client_exceptions import ServerDisconnectedError

try:
    from pydantic.v1 import PrivateAttr, ValidationError
except ImportError:
    from pydantic import PrivateAttr, ValidationError  # type: ignore[assignment]

from ..exceptions import ClientError
from ..utils import normalize_mac, utc_now
from .base import (
    RECENT_EVENT_MAX,
    ProtectBaseObject,
    ProtectDeviceModel,
    ProtectModel,
    ProtectModelWithId,
)
from .convert import create_from_unifi_dict
from .devices import (
    Bridge,
    Camera,
    Chime,
    Doorlock,
    Light,
    ProtectAdoptableDeviceModel,
    Sensor,
    Viewer,
)
from .nvr import NVR, Event, Liveview
from .types import EventType, FixSizeOrderedDict, ModelType
from .user import Group, User
from .websocket import (
    WSAction,
    WSPacket,
    WSSubscriptionMessage,
)

if TYPE_CHECKING:
    from ..api import ProtectApiClient


_LOGGER = logging.getLogger(__name__)

MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2
STATS_KEYS = {
    "storageStats",
    "stats",
    "systemInfo",
    "phyRate",
    "wifiConnectionState",
    "upSince",
    "uptime",
    "lastSeen",
    "recordingSchedules",
}
IGNORE_DEVICE_KEYS = {"nvrMac", "guid"}
STATS_AND_IGNORE_DEVICE_KEYS = STATS_KEYS | IGNORE_DEVICE_KEYS

CAMERA_EVENT_ATTR_MAP: dict[EventType, tuple[str, str]] = {
    EventType.MOTION: ("last_motion", "last_motion_event_id"),
    EventType.SMART_DETECT: ("last_smart_detect", "last_smart_detect_event_id"),
    EventType.SMART_DETECT_LINE: ("last_smart_detect", "last_smart_detect_event_id"),
    EventType.SMART_AUDIO_DETECT: (
        "last_smart_audio_detect",
        "last_smart_audio_detect_event_id",
    ),
    EventType.RING: ("last_ring", "last_ring_event_id"),
}


def _process_light_event(event: Event, light: Light) -> None:
    if _event_is_in_range(event, light.last_motion):
        light.last_motion_event_id = event.id


def _event_is_in_range(event: Event, dt: datetime | None) -> bool:
    """Check if event is in range of datetime."""
    return (
        dt is None or event.start >= dt or (event.end is not None and event.end >= dt)
    )


def _process_sensor_event(event: Event, sensor: Sensor) -> None:
    if event.type is EventType.MOTION_SENSOR:
        if _event_is_in_range(event, sensor.motion_detected_at):
            sensor.last_motion_event_id = event.id
    elif event.type in {EventType.SENSOR_CLOSED, EventType.SENSOR_OPENED}:
        if _event_is_in_range(event, sensor.open_status_changed_at):
            sensor.last_contact_event_id = event.id
    elif event.type is EventType.SENSOR_EXTREME_VALUE:
        if _event_is_in_range(event, sensor.extreme_value_detected_at):
            sensor.extreme_value_detected_at = event.end
            sensor.last_value_event_id = event.id
    elif event.type is EventType.SENSOR_ALARM:
        if _event_is_in_range(event, sensor.alarm_triggered_at):
            sensor.last_value_event_id = event.id


_CAMERA_SMART_AND_LINE_EVENTS = {
    EventType.SMART_DETECT,
    EventType.SMART_DETECT_LINE,
}
_CAMERA_SMART_AUDIO_EVENT = EventType.SMART_AUDIO_DETECT


def _process_camera_event(event: Event, camera: Camera) -> None:
    event_type = event.type
    dt_attr, event_attr = CAMERA_EVENT_ATTR_MAP[event_type]
    dt: datetime | None = getattr(camera, dt_attr)
    if not _event_is_in_range(event, dt):
        return

    event_id = event.id
    event_start = event.start

    setattr(camera, event_attr, event_id)
    setattr(camera, dt_attr, event_start)
    if event_type in _CAMERA_SMART_AND_LINE_EVENTS:
        for smart_type in event.smart_detect_types:
            camera.last_smart_detect_event_ids[smart_type] = event_id
            camera.last_smart_detects[smart_type] = event_start
    elif event_type is _CAMERA_SMART_AUDIO_EVENT:
        for smart_type in event.smart_detect_types:
            if (audio_type := smart_type.audio_type) is None:
                continue
            camera.last_smart_audio_detect_event_ids[audio_type] = event_id
            camera.last_smart_audio_detects[audio_type] = event_start


@dataclass
class WSStat:
    model: str
    action: str
    keys: list[str]
    keys_set: list[str]
    size: int
    filtered: bool


class ProtectDeviceRef(ProtectBaseObject):
    model: ModelType
    id: str


class Bootstrap(ProtectBaseObject):
    auth_user_id: str
    access_key: str
    cameras: dict[str, Camera]
    users: dict[str, User]
    groups: dict[str, Group]
    liveviews: dict[str, Liveview]
    nvr: NVR
    viewers: dict[str, Viewer]
    lights: dict[str, Light]
    bridges: dict[str, Bridge]
    sensors: dict[str, Sensor]
    doorlocks: dict[str, Doorlock]
    chimes: dict[str, Chime]
    last_update_id: str

    # TODO:
    # schedules
    # agreements

    # not directly from UniFi
    events: dict[str, Event] = FixSizeOrderedDict()
    capture_ws_stats: bool = False
    mac_lookup: dict[str, ProtectDeviceRef] = {}
    id_lookup: dict[str, ProtectDeviceRef] = {}
    _ws_stats: list[WSStat] = PrivateAttr([])
    _has_doorbell: bool | None = PrivateAttr(None)
    _has_smart: bool | None = PrivateAttr(None)
    _has_media: bool | None = PrivateAttr(None)
    _recording_start: datetime | None = PrivateAttr(None)
    _refresh_tasks: set[asyncio.Task[None]] = PrivateAttr(set())

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        api: ProtectApiClient | None = data.get("api") or (
            cls._api if isinstance(cls, ProtectBaseObject) else None
        )
        mac_lookup: dict[str, dict[str, str | ModelType]] = {}
        id_lookup: dict[str, dict[str, str | ModelType]] = {}
        data["idLookup"] = id_lookup
        data["macLookup"] = mac_lookup

        for model_type in ModelType.bootstrap_models_types_set:
            key = model_type.devices_key  # type: ignore[attr-defined]
            items: dict[str, ProtectModel] = {}
            for item in data[key]:
                if (
                    api is not None
                    and api.ignore_unadopted
                    and not item.get("isAdopted", True)
                ):
                    continue

                id_: str = item["id"]
                ref = {"model": model_type, "id": id_}
                items[id_] = item
                id_lookup[id_] = ref
                if "mac" in item:
                    cleaned_mac = normalize_mac(item["mac"])
                    mac_lookup[cleaned_mac] = ref
            data[key] = items

        return super().unifi_dict_to_dict(data)

    @classmethod
    @cache
    def _unifi_dict_remove_keys(cls) -> set[str]:
        return {"events", "captureWsStats", "macLookup", "idLookup"}

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        for key in Bootstrap._unifi_dict_remove_keys():
            if key in data:
                del data[key]
        for model_type in ModelType.bootstrap_models_types_set:
            attr = model_type.devices_key  # type: ignore[attr-defined]
            if attr in data and isinstance(data[attr], dict):
                data[attr] = list(data[attr].values())

        return data

    @property
    def ws_stats(self) -> list[WSStat]:
        return self._ws_stats

    def clear_ws_stats(self) -> None:
        self._ws_stats = []

    @property
    def auth_user(self) -> User:
        return self._api.bootstrap.users[self.auth_user_id]

    @property
    def has_doorbell(self) -> bool:
        if self._has_doorbell is None:
            self._has_doorbell = any(
                c.feature_flags.is_doorbell for c in self.cameras.values()
            )

        return self._has_doorbell

    @property
    def recording_start(self) -> datetime | None:
        """Get earilest recording date."""
        if self._recording_start is None:
            try:
                self._recording_start = min(
                    c.stats.video.recording_start
                    for c in self.cameras.values()
                    if c.stats.video.recording_start is not None
                )
            except ValueError:
                return None
        return self._recording_start

    @property
    def has_smart_detections(self) -> bool:
        """Check if any camera has smart detections."""
        if self._has_smart is None:
            self._has_smart = any(
                c.feature_flags.has_smart_detect for c in self.cameras.values()
            )
        return self._has_smart

    @property
    def has_media(self) -> bool:
        """Checks if user can read media for any camera."""
        if self._has_media is None:
            if self.recording_start is None:
                return False
            self._has_media = any(
                c.can_read_media(self.auth_user) for c in self.cameras.values()
            )
        return self._has_media

    def get_device_from_mac(self, mac: str) -> ProtectAdoptableDeviceModel | None:
        """Retrieve a device from MAC address."""
        ref = self.mac_lookup.get(normalize_mac(mac))
        if ref is None:
            return None

        devices: dict[str, ProtectModelWithId] = getattr(self, ref.model.devices_key)
        return cast(ProtectAdoptableDeviceModel, devices.get(ref.id))

    def get_device_from_id(self, device_id: str) -> ProtectAdoptableDeviceModel | None:
        """Retrieve a device from device ID (without knowing model type)."""
        ref = self.id_lookup.get(device_id)
        if ref is None:
            return None
        devices: dict[str, ProtectModelWithId] = getattr(self, ref.model.devices_key)
        return cast(ProtectAdoptableDeviceModel, devices.get(ref.id))

    def process_event(self, event: Event) -> None:
        event_type = event.type
        if event_type in CAMERA_EVENT_ATTR_MAP and (camera := event.camera):
            _process_camera_event(event, camera)
        elif event_type is EventType.MOTION_LIGHT and (light := event.light):
            _process_light_event(event, light)
        elif event_type is EventType.MOTION_SENSOR and (sensor := event.sensor):
            _process_sensor_event(event, sensor)

        self.events[event.id] = event

    def _create_stat(
        self,
        packet: WSPacket,
        keys_set: Iterable[str] | None,
        filtered: bool,
    ) -> None:
        if self.capture_ws_stats:
            self._ws_stats.append(
                WSStat(
                    model=packet.action_frame.data["modelKey"],
                    action=packet.action_frame.data["action"],
                    keys=list(packet.data_frame.data),
                    keys_set=[] if keys_set is None else list(keys_set),
                    size=len(packet.raw),
                    filtered=filtered,
                ),
            )

    def _process_add_packet(
        self,
        model_type: ModelType,
        packet: WSPacket,
        data: dict[str, Any],
    ) -> WSSubscriptionMessage | None:
        obj = create_from_unifi_dict(data, api=self._api, model_type=model_type)
        if model_type is ModelType.EVENT:
            if TYPE_CHECKING:
                assert isinstance(obj, Event)
            self.process_event(obj)
        elif model_type is ModelType.NVR:
            if TYPE_CHECKING:
                assert isinstance(obj, NVR)
            self.nvr = obj
        elif model_type in ModelType.bootstrap_models_types_set:
            if TYPE_CHECKING:
                assert isinstance(obj, ProtectAdoptableDeviceModel)
            if not self._api.ignore_unadopted or (
                obj.is_adopted and not obj.is_adopted_by_other
            ):
                id_ = obj.id
                getattr(self, model_type.devices_key)[id_] = obj
                ref = ProtectDeviceRef(model=model_type, id=id_)
                self.id_lookup[id_] = ref
                self.mac_lookup[normalize_mac(obj.mac)] = ref
        else:
            _LOGGER.debug("Unexpected bootstrap model type for add: %s", model_type)
            return None

        updated = obj.dict()

        self._create_stat(packet, updated, False)

        return WSSubscriptionMessage(
            action=WSAction.ADD,
            new_update_id=self.last_update_id,
            changed_data=updated,
            new_obj=obj,
        )

    def _process_remove_packet(
        self, model_type: ModelType, packet: WSPacket
    ) -> WSSubscriptionMessage | None:
        devices: dict[str, ProtectDeviceModel] | None = getattr(
            self, model_type.devices_key, None
        )

        if devices is None:
            return None

        device_id: str = packet.action_frame.data["id"]
        self.id_lookup.pop(device_id, None)
        if (device := devices.pop(device_id, None)) is None:
            return None
        self.mac_lookup.pop(normalize_mac(device.mac), None)

        self._create_stat(packet, None, False)
        return WSSubscriptionMessage(
            action=WSAction.REMOVE,
            new_update_id=self.last_update_id,
            changed_data={},
            old_obj=device,
        )

    def _process_nvr_update(
        self,
        packet: WSPacket,
        data: dict[str, Any],
        ignore_stats: bool,
    ) -> WSSubscriptionMessage | None:
        if ignore_stats:
            for key in STATS_KEYS.intersection(data):
                del data[key]
        # nothing left to process
        if not data:
            self._create_stat(packet, None, True)
            return None

        # for another NVR in stack
        nvr_id: str | None = packet.action_frame.data.get("id")
        if nvr_id and nvr_id != self.nvr.id:
            self._create_stat(packet, None, True)
            return None

        # nothing left to process
        if not (data := self.nvr.unifi_dict_to_dict(data)):
            self._create_stat(packet, None, True)
            return None

        old_nvr = self.nvr.copy()
        self.nvr = self.nvr.update_from_dict(deepcopy(data))

        self._create_stat(packet, data, False)
        return WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=self.last_update_id,
            changed_data=data,
            new_obj=self.nvr,
            old_obj=old_nvr,
        )

    def _process_device_update(
        self,
        model_type: ModelType,
        packet: WSPacket,
        action: dict[str, Any],
        data: dict[str, Any],
        ignore_stats: bool,
    ) -> WSSubscriptionMessage | None:
        remove_keys = (
            STATS_AND_IGNORE_DEVICE_KEYS if ignore_stats else IGNORE_DEVICE_KEYS
        )
        for key in remove_keys.intersection(data):
            del data[key]
        # `last_motion` from cameras update every 100 milliseconds when a motion event is active
        # this overrides the behavior to only update `last_motion` when a new event starts
        if model_type is ModelType.CAMERA and "lastMotion" in data:
            del data["lastMotion"]
        # nothing left to process
        if not data:
            self._create_stat(packet, None, True)
            return None

        devices: dict[str, ProtectModelWithId] = getattr(self, model_type.devices_key)
        action_id: str = action["id"]
        if action_id not in devices:
            # ignore updates to events that phase out
            if model_type is not ModelType.EVENT:
                _LOGGER.debug("Unexpected %s: %s", key, action_id)
            return None

        obj = devices[action_id]
        data = obj.unifi_dict_to_dict(data)
        old_obj = obj.copy()
        obj = obj.update_from_dict(deepcopy(data))

        if model_type is ModelType.EVENT:
            if TYPE_CHECKING:
                assert isinstance(obj, Event)
            self.process_event(obj)
        elif model_type is ModelType.CAMERA:
            if TYPE_CHECKING:
                assert isinstance(obj, Camera)
            if "last_ring" in data and (last_ring := obj.last_ring):
                if is_recent := last_ring + RECENT_EVENT_MAX >= utc_now():
                    obj.set_ring_timeout()
                _LOGGER.debug("last_ring for %s (%s)", obj.id, is_recent)
        elif model_type is ModelType.SENSOR:
            if TYPE_CHECKING:
                assert isinstance(obj, Sensor)
            if "alarm_triggered_at" in data and (trigged_at := obj.alarm_triggered_at):
                if is_recent := trigged_at + RECENT_EVENT_MAX >= utc_now():
                    obj.set_alarm_timeout()
                _LOGGER.debug("alarm_triggered_at for %s (%s)", obj.id, is_recent)

        devices[action_id] = obj
        self._create_stat(packet, data, False)
        return WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=self.last_update_id,
            changed_data=data,
            new_obj=obj,
            old_obj=old_obj,
        )

    def process_ws_packet(
        self,
        packet: WSPacket,
        models: set[ModelType] | None = None,
        ignore_stats: bool = False,
    ) -> WSSubscriptionMessage | None:
        """Process a WS packet."""
        action = packet.action_frame.data
        data = packet.data_frame.data
        if self.capture_ws_stats:
            action = deepcopy(action)
            data = deepcopy(data)

        new_update_id: str = action["newUpdateId"]
        if new_update_id is not None:
            self.last_update_id = new_update_id

        model_key: str = action["modelKey"]
        if model_key not in ModelType.values_set():
            _LOGGER.debug("Unknown model type: %s", model_key)
            self._create_stat(packet, None, True)
            return None

        model_type = ModelType.from_string(model_key)
        if models and model_type not in models:
            self._create_stat(packet, None, True)
            return None

        action_action: str = action["action"]
        if action_action == "remove":
            return self._process_remove_packet(model_type, packet)

        if not data:
            self._create_stat(packet, None, True)
            return None

        try:
            if action_action == "add":
                return self._process_add_packet(model_type, packet, data)
            if action_action == "update":
                if model_type is ModelType.NVR:
                    return self._process_nvr_update(packet, data, ignore_stats)
                if model_type in ModelType.bootstrap_models_types_and_event_set:
                    return self._process_device_update(
                        model_type,
                        packet,
                        action,
                        data,
                        ignore_stats,
                    )
        except (ValidationError, ValueError) as err:
            self._handle_ws_error(action, err)

        _LOGGER.debug(
            "Unexpected bootstrap model type deviceadoptedfor update: %s", model_key
        )
        self._create_stat(packet, None, True)
        return None

    def _handle_ws_error(self, action: dict[str, Any], err: Exception) -> None:
        msg = ""
        if action["modelKey"] == "event":
            msg = f"Validation error processing event: {action['id']}. Ignoring event."
        else:
            try:
                model_type = ModelType.from_string(action["modelKey"])
                device_id: str = action["id"]
                task = asyncio.create_task(self.refresh_device(model_type, device_id))
                self._refresh_tasks.add(task)
                task.add_done_callback(self._refresh_tasks.discard)
            except (ValueError, IndexError):
                msg = f"{action['action']} packet caused invalid state. Unable to refresh device."
            else:
                msg = f"{action['action']} packet caused invalid state. Refreshing device: {model_type} {device_id}"
        _LOGGER.debug("%s Error: %s", msg, err)

    async def refresh_device(self, model_type: ModelType, device_id: str) -> None:
        """Refresh a device in the bootstrap."""
        try:
            if model_type == ModelType.NVR:
                device: ProtectModelWithId = await self._api.get_nvr()
            else:
                device = await self._api.get_device(model_type, device_id)
        except (
            ValidationError,
            TimeoutError,
            asyncio.TimeoutError,
            asyncio.CancelledError,
            ClientError,
            ServerDisconnectedError,
        ):
            _LOGGER.warning("Failed to refresh model: %s %s", model_type, device_id)
            return

        if isinstance(device, NVR):
            self.nvr = device
        else:
            devices: dict[str, ProtectModelWithId] = getattr(
                self, model_type.devices_key
            )
            devices[device.id] = device
        _LOGGER.debug("Successfully refresh model: %s %s", model_type, device_id)

    async def get_is_prerelease(self) -> bool:
        """Get if current version of Protect is a prerelease version."""
        return await self.nvr.get_is_prerelease()
