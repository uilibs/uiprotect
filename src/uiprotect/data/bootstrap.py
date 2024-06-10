"""UniFi Protect Bootstrap."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from aiohttp.client_exceptions import ServerDisconnectedError

try:
    from pydantic.v1 import PrivateAttr, ValidationError
except ImportError:
    from pydantic import PrivateAttr, ValidationError  # type: ignore[assignment]

from uiprotect.data.base import (
    RECENT_EVENT_MAX,
    ProtectBaseObject,
    ProtectModel,
    ProtectModelWithId,
)
from uiprotect.data.convert import create_from_unifi_dict
from uiprotect.data.devices import (
    Bridge,
    Camera,
    Chime,
    Doorlock,
    Light,
    ProtectAdoptableDeviceModel,
    Sensor,
    Viewer,
)
from uiprotect.data.nvr import NVR, Event, Liveview
from uiprotect.data.types import EventType, FixSizeOrderedDict, ModelType
from uiprotect.data.user import Group, User
from uiprotect.data.websocket import (
    WSAction,
    WSJSONPacketFrame,
    WSPacket,
    WSSubscriptionMessage,
)
from uiprotect.exceptions import ClientError
from uiprotect.utils import utc_now

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


def _remove_stats_keys(data: dict[str, Any]) -> None:
    for key in STATS_KEYS.intersection(data):
        del data[key]


def _process_light_event(event: Event) -> None:
    if event.light is None:
        return

    dt = event.light.last_motion
    if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
        event.light.last_motion_event_id = event.id


def _process_sensor_event(event: Event) -> None:
    if event.sensor is None:
        return

    if event.type == EventType.MOTION_SENSOR:
        dt = event.sensor.motion_detected_at
        if (
            dt is None
            or event.start >= dt
            or (event.end is not None and event.end >= dt)
        ):
            event.sensor.last_motion_event_id = event.id
    elif event.type in {EventType.SENSOR_CLOSED, EventType.SENSOR_OPENED}:
        dt = event.sensor.open_status_changed_at
        if (
            dt is None
            or event.start >= dt
            or (event.end is not None and event.end >= dt)
        ):
            event.sensor.last_contact_event_id = event.id
    elif event.type == EventType.SENSOR_EXTREME_VALUE:
        dt = event.sensor.extreme_value_detected_at
        if (
            dt is None
            or event.start >= dt
            or (event.end is not None and event.end >= dt)
        ):
            event.sensor.extreme_value_detected_at = event.end
            event.sensor.last_value_event_id = event.id
    elif event.type == EventType.SENSOR_ALARM:
        dt = event.sensor.alarm_triggered_at
        if (
            dt is None
            or event.start >= dt
            or (event.end is not None and event.end >= dt)
        ):
            event.sensor.last_value_event_id = event.id


def _process_camera_event(event: Event) -> None:
    if event.camera is None:
        return

    dt_attr, event_attr = CAMERA_EVENT_ATTR_MAP[event.type]
    dt = getattr(event.camera, dt_attr)
    if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
        setattr(event.camera, event_attr, event.id)
        setattr(event.camera, dt_attr, event.start)
        if event.type in {EventType.SMART_DETECT, EventType.SMART_DETECT_LINE}:
            for smart_type in event.smart_detect_types:
                event.camera.last_smart_detect_event_ids[smart_type] = event.id
                event.camera.last_smart_detects[smart_type] = event.start
        elif event.type == EventType.SMART_AUDIO_DETECT:
            for smart_type in event.smart_detect_types:
                audio_type = smart_type.audio_type
                if audio_type is None:
                    continue
                event.camera.last_smart_audio_detect_event_ids[audio_type] = event.id
                event.camera.last_smart_audio_detects[audio_type] = event.start


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
        api = cls._get_api(data.get("api"))
        data["macLookup"] = {}
        data["idLookup"] = {}
        for model_type in ModelType.bootstrap_models():
            key = model_type + "s"
            items: dict[str, ProtectModel] = {}
            for item in data[key]:
                if (
                    api is not None
                    and api.ignore_unadopted
                    and not item.get("isAdopted", True)
                ):
                    continue

                ref = {"model": model_type, "id": item["id"]}
                items[item["id"]] = item
                data["idLookup"][item["id"]] = ref
                if "mac" in item:
                    cleaned_mac = item["mac"].lower().replace(":", "")
                    data["macLookup"][cleaned_mac] = ref
            data[key] = items

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "events" in data:
            del data["events"]
        if "captureWsStats" in data:
            del data["captureWsStats"]
        if "macLookup" in data:
            del data["macLookup"]
        if "idLookup" in data:
            del data["idLookup"]

        for model_type in ModelType.bootstrap_models():
            attr = model_type + "s"
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
        user: User = self.api.bootstrap.users[self.auth_user_id]
        return user

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
        mac = mac.lower().replace(":", "").replace("-", "").replace("_", "")
        ref = self.mac_lookup.get(mac)
        if ref is None:
            return None

        devices = getattr(self, f"{ref.model.value}s")
        return cast(ProtectAdoptableDeviceModel, devices.get(ref.id))

    def get_device_from_id(self, device_id: str) -> ProtectAdoptableDeviceModel | None:
        """Retrieve a device from device ID (without knowing model type)."""
        ref = self.id_lookup.get(device_id)
        if ref is None:
            return None
        devices = getattr(self, f"{ref.model.value}s")
        return cast(ProtectAdoptableDeviceModel, devices.get(ref.id))

    def process_event(self, event: Event) -> None:
        if event.type in CAMERA_EVENT_ATTR_MAP and event.camera is not None:
            _process_camera_event(event)
        elif event.type == EventType.MOTION_LIGHT and event.light is not None:
            _process_light_event(event)
        elif event.type == EventType.MOTION_SENSOR and event.sensor is not None:
            _process_sensor_event(event)

        self.events[event.id] = event

    def _create_stat(
        self,
        packet: WSPacket,
        keys_set: list[str],
        filtered: bool,
    ) -> None:
        if self.capture_ws_stats:
            self._ws_stats.append(
                WSStat(
                    model=packet.action_frame.data["modelKey"],
                    action=packet.action_frame.data["action"],
                    keys=list(packet.data_frame.data),
                    keys_set=keys_set,
                    size=len(packet.raw),
                    filtered=filtered,
                ),
            )

    def _get_frame_data(
        self,
        packet: WSPacket,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if self.capture_ws_stats:
            return deepcopy(packet.action_frame.data), deepcopy(packet.data_frame.data)
        return packet.action_frame.data, packet.data_frame.data

    def _process_add_packet(
        self,
        packet: WSPacket,
        data: dict[str, Any],
    ) -> WSSubscriptionMessage | None:
        obj = create_from_unifi_dict(data, api=self._api)

        if isinstance(obj, Event):
            self.process_event(obj)
        elif isinstance(obj, NVR):
            self.nvr = obj
        elif (
            isinstance(obj, ProtectAdoptableDeviceModel)
            and obj.model is not None
            and obj.model.value in ModelType.bootstrap_models()
        ):
            key = obj.model.value + "s"
            if not self.api.ignore_unadopted or (
                obj.is_adopted and not obj.is_adopted_by_other
            ):
                getattr(self, key)[obj.id] = obj
                ref = ProtectDeviceRef(model=obj.model, id=obj.id)
                self.id_lookup[obj.id] = ref
                self.mac_lookup[obj.mac.lower().replace(":", "")] = ref
        else:
            _LOGGER.debug("Unexpected bootstrap model type for add: %s", obj.model)
            return None

        updated = obj.dict()
        self._create_stat(packet, list(updated), False)
        return WSSubscriptionMessage(
            action=WSAction.ADD,
            new_update_id=self.last_update_id,
            changed_data=updated,
            new_obj=obj,
        )

    def _process_remove_packet(
        self,
        packet: WSPacket,
        data: dict[str, Any] | None,
    ) -> WSSubscriptionMessage | None:
        model = packet.action_frame.data.get("modelKey")
        device_id = packet.action_frame.data.get("id")
        devices = getattr(self, f"{model}s", None)

        if devices is None:
            return None

        self.id_lookup.pop(device_id, None)
        device = devices.pop(device_id, None)
        if device is None:
            return None
        self.mac_lookup.pop(device.mac.lower().replace(":", ""), None)

        self._create_stat(packet, [], False)
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
            _remove_stats_keys(data)
        # nothing left to process
        if not data:
            self._create_stat(packet, [], True)
            return None

        # for another NVR in stack
        nvr_id = packet.action_frame.data.get("id")
        if nvr_id and nvr_id != self.nvr.id:
            self._create_stat(packet, [], True)
            return None

        data = self.nvr.unifi_dict_to_dict(data)
        # nothing left to process
        if not data:
            self._create_stat(packet, [], True)
            return None

        old_nvr = self.nvr.copy()
        self.nvr = self.nvr.update_from_dict(deepcopy(data))

        self._create_stat(packet, list(data), False)
        return WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=self.last_update_id,
            changed_data=data,
            new_obj=self.nvr,
            old_obj=old_nvr,
        )

    def _process_device_update(
        self,
        packet: WSPacket,
        action: dict[str, Any],
        data: dict[str, Any],
        ignore_stats: bool,
    ) -> WSSubscriptionMessage | None:
        model_type = action["modelKey"]
        if ignore_stats:
            _remove_stats_keys(data)
        for key in IGNORE_DEVICE_KEYS.intersection(data):
            del data[key]
        # `last_motion` from cameras update every 100 milliseconds when a motion event is active
        # this overrides the behavior to only update `last_motion` when a new event starts
        if model_type == "camera" and "lastMotion" in data:
            del data["lastMotion"]
        # nothing left to process
        if not data:
            self._create_stat(packet, [], True)
            return None

        key = f"{model_type}s"
        devices = getattr(self, key)
        if action["id"] in devices:
            if action["id"] not in devices:
                raise ValueError(
                    f"Unknown device update for {model_type}: { action['id']}",
                )
            obj: ProtectModelWithId = devices[action["id"]]
            data = obj.unifi_dict_to_dict(data)
            old_obj = obj.copy()
            obj = obj.update_from_dict(deepcopy(data))
            now = utc_now()

            if isinstance(obj, Event):
                self.process_event(obj)
            elif isinstance(obj, Camera):
                if "last_ring" in data and obj.last_ring:
                    is_recent = obj.last_ring + RECENT_EVENT_MAX >= now
                    _LOGGER.debug("last_ring for %s (%s)", obj.id, is_recent)
                    if is_recent:
                        obj.set_ring_timeout()
            elif (
                isinstance(obj, Sensor)
                and "alarm_triggered_at" in data
                and obj.alarm_triggered_at
            ):
                is_recent = obj.alarm_triggered_at + RECENT_EVENT_MAX >= now
                _LOGGER.debug("alarm_triggered_at for %s (%s)", obj.id, is_recent)
                if is_recent:
                    obj.set_alarm_timeout()

            devices[action["id"]] = obj

            self._create_stat(packet, list(data), False)
            return WSSubscriptionMessage(
                action=WSAction.UPDATE,
                new_update_id=self.last_update_id,
                changed_data=data,
                new_obj=obj,
                old_obj=old_obj,
            )

        # ignore updates to events that phase out
        if model_type != ModelType.EVENT.value:
            _LOGGER.debug("Unexpected %s: %s", key, action["id"])
        return None

    def process_ws_packet(
        self,
        packet: WSPacket,
        models: set[ModelType] | None = None,
        ignore_stats: bool = False,
    ) -> WSSubscriptionMessage | None:
        if models is None:
            models = set()

        if not isinstance(packet.action_frame, WSJSONPacketFrame):
            _LOGGER.debug(
                "Unexpected action frame format: %s",
                packet.action_frame.payload_format,
            )

        if not isinstance(packet.data_frame, WSJSONPacketFrame):
            _LOGGER.debug(
                "Unexpected data frame format: %s",
                packet.data_frame.payload_format,
            )

        action, data = self._get_frame_data(packet)
        if action["newUpdateId"] is not None:
            self.last_update_id = action["newUpdateId"]

        if action["modelKey"] not in ModelType.values():
            _LOGGER.debug("Unknown model type: %s", action["modelKey"])
            self._create_stat(packet, [], True)
            return None

        if len(models) > 0 and ModelType(action["modelKey"]) not in models:
            self._create_stat(packet, [], True)
            return None

        if action["action"] == "remove":
            return self._process_remove_packet(packet, data)

        if data is None or len(data) == 0:
            self._create_stat(packet, [], True)
            return None

        try:
            if action["action"] == "add":
                return self._process_add_packet(packet, data)

            if action["action"] == "update":
                if action["modelKey"] == ModelType.NVR.value:
                    return self._process_nvr_update(packet, data, ignore_stats)
                if (
                    action["modelKey"] in ModelType.bootstrap_models()
                    or action["modelKey"] == ModelType.EVENT.value
                ):
                    return self._process_device_update(
                        packet,
                        action,
                        data,
                        ignore_stats,
                    )
                _LOGGER.debug(
                    "Unexpected bootstrap model type deviceadoptedfor update: %s",
                    action["modelKey"],
                )
        except (ValidationError, ValueError) as err:
            self._handle_ws_error(action, err)

        self._create_stat(packet, [], True)
        return None

    def _handle_ws_error(self, action: dict[str, Any], err: Exception) -> None:
        msg = ""
        if action["modelKey"] == "event":
            msg = f"Validation error processing event: {action['id']}. Ignoring event."
        else:
            try:
                model_type = ModelType(action["modelKey"])
                device_id = action["id"]
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
                device: ProtectModelWithId = await self.api.get_nvr()
            else:
                device = await self.api.get_device(model_type, device_id)
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
            devices = getattr(self, f"{model_type.value}s")
            devices[device.id] = device
        _LOGGER.debug("Successfully refresh model: %s %s", model_type, device_id)

    async def get_is_prerelease(self) -> bool:
        """Get if current version of Protect is a prerelease version."""
        return await self.nvr.get_is_prerelease()
