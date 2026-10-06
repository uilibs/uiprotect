"""UniFi Protect Data."""

from __future__ import annotations

import asyncio
import logging
import zoneinfo
from collections.abc import Callable
from datetime import datetime, timedelta, tzinfo
from functools import cache
from ipaddress import IPv4Address, IPv6Address
from typing import Any, ClassVar, Literal

from convertertools import pop_dict_set_if_none, pop_dict_tuple
from pydantic import ConfigDict, Field
from pydantic.fields import PrivateAttr

from ..exceptions import BadRequest, NotAuthorized
from ..utils import convert_smart_types, convert_to_datetime
from .base import (
    ProtectBaseObject,
    ProtectDeviceModel,
    ProtectModelWithId,
)
from .devices import (
    Camera,
    CameraZone,
    Light,
    OSDSettings,
    RecordingSettings,
    Sensor,
    SmartDetectSettings,
)
from .types import (
    AnalyticsOption,
    DoorbellMessageType,
    DoorbellText,
    EventCategories,
    EventType,
    ModelType,
    MountType,
    PercentFloat,
    PermissionNode,
    RecordingMode,
    RecordingType,
    ResolutionStorageType,
    SensorAlarmType,
    SensorStatusType,
    SmartDetectObjectType,
    StorageType,
    Version,
)
from .user import User

_LOGGER = logging.getLogger(__name__)
MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2
DELETE_KEYS_THUMB = {"color", "vehicleType"}
DELETE_KEYS_EVENT = {"category", "device"}


class MetaInfo(ProtectBaseObject):
    application_version: str

    @property
    def version(self) -> Version:
        """Parsed application version, comparable to the private ``NVR.version``."""
        return Version(self.application_version)


class SmartDetectItemAttribute(ProtectBaseObject):
    """Attribute value with confidence for smart detect items (e.g., color, vehicle type)."""

    val: str
    confidence: int


class SmartDetectItem(ProtectBaseObject):
    id: str
    timestamp: datetime
    coord: tuple[int, int, int, int]
    object_type: SmartDetectObjectType
    zone_ids: list[int]
    duration: timedelta
    confidence: int
    first_shown_time_ms: int
    idle_since_time_ms: int
    stationary: bool
    license_plate: str | None = None  # only populated for vehicle object_type
    depth: float | None = None
    speed: float | None = None
    attributes: dict[str, SmartDetectItemAttribute] | None = None
    lines: list[int] | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "zones": "zone_ids",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "duration": lambda x: timedelta(milliseconds=x),
        } | super().unifi_dict_conversions()


class SmartDetectTrack(ProtectBaseObject):
    id: str
    payload: list[SmartDetectItem]
    camera_id: str
    event_id: str

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "camera": "cameraId",
            "event": "eventId",
        }

    @property
    def camera(self) -> Camera:
        return self._api.bootstrap.cameras[self.camera_id]

    @property
    def event(self) -> Event | None:
        return self._api.bootstrap.events.get(self.event_id)


class EventThumbnailGroup(ProtectBaseObject):
    """Group information for detected thumbnails (e.g., license plate recognition)."""

    id: str
    name: str | None = None
    matched_name: str | None = None
    confidence: int

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"matchedName", "name"})
        return data


class EventThumbnailAttribute(ProtectBaseObject):
    confidence: int
    val: str


class NfcMetadata(ProtectBaseObject):
    nfc_id: str | None = None
    user_id: str | None = None
    ulp_id: str | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "nfcId": "nfc_id",
            "userId": "user_id",
            "ulpId": "ulp_id",
        }

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"nfcId", "userId", "ulpId"})
        return data


class FingerprintMetadata(ProtectBaseObject):
    ulp_id: str | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "ulpId": "ulp_id",
        }


class EventThumbnailAttributes(ProtectBaseObject):
    """
    Dynamic attributes for detected thumbnails.

    All attributes are stored as extra fields for full flexibility.

    Common attribute types:
    - color, vehicleType, faceMask: EventThumbnailAttribute (with val and confidence)
    - zone: list[int] - Zone IDs where detection occurred
    - trackerId: int - Unique tracker ID for this detection

    Allows any attributes for forward compatibility with new UFP features.

    Example usage:
        >>> attrs = thumbnail.attributes
        >>> if attrs:
        ...     # Access EventThumbnailAttribute objects
        ...     color = attrs.color  # EventThumbnailAttribute
        ...     if color:
        ...         print(f"Color: {color.val} (confidence: {color.confidence})")
        ...     # Access primitive types
        ...     zones = attrs.zone  # list[int] | None
        ...     tracker = attrs.trackerId  # int | None
    """

    model_config = ConfigDict(extra="allow")

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        return {
            key: EventThumbnailAttribute.from_unifi_dict(**value)
            if isinstance(value, dict) and "val" in value and "confidence" in value
            else value
            for key, value in data.items()
        }

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        return {k: v for k, v in data.items() if v is not None}


class EventDetectedThumbnail(ProtectBaseObject):
    clock_best_wall: datetime | None = None
    type: str
    cropped_id: str
    attributes: EventThumbnailAttributes | None = None
    name: str | None = None
    coord: list[int] | None = None
    confidence: int | None = None
    # requires 6.0.0+
    group: EventThumbnailGroup | None = None
    object_id: str | None = None

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {"clockBestWall": convert_to_datetime} | super().unifi_dict_conversions()

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"name", "group", "objectId", "coord", "confidence"})
        return data


class EventMetadata(ProtectBaseObject):
    reason: str | None = None
    light_id: str | None = None
    light_name: str | None = None
    type: str | None = None
    sensor_id: str | None = None
    from_value: str | None = None
    to_value: str | None = None
    mount_type: MountType | None = None
    status: SensorStatusType | None = None
    alarm_type: SensorAlarmType | None = None
    device_id: str | None = None
    mac: str | None = None
    # requires 2.11.13+
    detected_thumbnails: list[EventDetectedThumbnail] | None = None
    # requires 5.1.34+
    nfc: NfcMetadata | None = None
    fingerprint: FingerprintMetadata | None = None

    _collapse_keys: ClassVar[set[str]] = {
        "lightId",
        "lightName",
        "type",
        "sensorId",
        "mountType",
        "status",
        "alarmType",
        "deviceId",
        "mac",
    }

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "from": "fromValue",
            "to": "toValue",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        for key in cls._collapse_keys.intersection(data):
            if isinstance(data[key], dict):
                if "text" in data[key]:
                    data[key] = data[key]["text"]
                else:
                    _LOGGER.debug(
                        "Unexpected format for EventMetadata key %s: %s",
                        key,
                        data[key],
                    )
                    del data[key]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        # all metadata keys optionally appear
        for key, value in list(data.items()):
            if value is None:
                del data[key]

        for key in self._collapse_keys.intersection(data):
            # AI Theta/Hotplug exception
            if key != "type" or data[key] not in {"audio", "video", "extender"}:
                data[key] = {"text": data[key]}

        return data


class Event(ProtectModelWithId):
    type: EventType
    start: datetime
    end: datetime | None = None
    # ``score`` / ``smart_detect_*`` are always present on the private API
    # but the Public Integration API websocket omits them on minimal
    # payloads (motion start, doorbell ring, etc.). Defaults keep the
    # strict model constructable from either source.
    score: int = 0
    camera_id: str | None = None
    # Public Integration API ``add`` payloads carry the originating device
    # identifier under a top-level ``device`` field; private-API payloads
    # never populate this. Distinct from ``camera_id`` because non-camera
    # events (sensors, alarm hubs) flow through the public WS.
    device_id: str | None = None
    smart_detect_types: list[SmartDetectObjectType] = Field(default_factory=list)
    smart_detect_event_ids: list[str] = Field(default_factory=list)
    thumbnail_id: str | None = None
    user_id: str | None = None
    timestamp: datetime | None = None
    metadata: EventMetadata | None = None
    # only appears if `get_events_raw` is called with category
    category: EventCategories | None = None

    _smart_detect_track: SmartDetectTrack | None = PrivateAttr(None)
    _smart_detect_zones: dict[int, CameraZone] | None = PrivateAttr(None)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "camera": "cameraId",
            "user": "userId",
            "thumbnail": "thumbnailId",
            "smartDetectEvents": "smartDetectEventIds",
            "device": "deviceId",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return (
            dict.fromkeys(("start", "end", "timestamp"), convert_to_datetime)
            | {"smartDetectTypes": convert_smart_types}
            | super().unifi_dict_conversions()
        )

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, DELETE_KEYS_EVENT)
        return data

    @property
    def camera(self) -> Camera | None:
        if self.camera_id is None:
            return None

        return self._api.bootstrap.cameras.get(self.camera_id)

    @property
    def light(self) -> Light | None:
        if self.metadata is None or self.metadata.light_id is None:
            return None

        return self._api.bootstrap.lights.get(self.metadata.light_id)

    @property
    def sensor(self) -> Sensor | None:
        if self.metadata is None or self.metadata.sensor_id is None:
            return None

        return self._api.bootstrap.sensors.get(self.metadata.sensor_id)

    @property
    def user(self) -> User | None:
        if self.user_id is None:
            return None

        return self._api.bootstrap.users.get(self.user_id)

    async def get_thumbnail(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Gets thumbnail for event"""
        if self.thumbnail_id is None:
            return None
        if not self._api.bootstrap.auth_user.can(
            ModelType.CAMERA,
            PermissionNode.READ_MEDIA,
            self.camera,
        ):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}",
            )
        return await self._api.get_event_thumbnail(self.thumbnail_id, width, height)


class PortConfig(ProtectBaseObject):
    rtsps: int


class CPUInfo(ProtectBaseObject):
    average_load: float
    temperature: float


class MemoryInfo(ProtectBaseObject):
    available: int | None = None
    free: int | None = None
    total: int | None = None


class StorageInfo(ProtectBaseObject):
    type: StorageType
    used: int

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "type" in data:
            storage_type = data.pop("type")
            try:
                data["type"] = StorageType(storage_type)
            except ValueError:
                _LOGGER.warning("Unknown storage type: %s", storage_type)
                data["type"] = StorageType.UNKNOWN

        return super().unifi_dict_to_dict(data)


class UOSDisk(ProtectBaseObject):
    slot: int
    state: str

    type: Literal["SSD", "HDD"] | None = None
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    rpm: int | None = None
    ata: str | None = None
    sata: str | None = None
    action: str | None = None
    healthy: str | None = None
    reason: list[Any] | None = None
    temperature: int | None = None
    power_on_hours: int | None = None
    life_span: PercentFloat | None = None
    bad_sector: int | None = None
    threshold: int | None = None
    progress: PercentFloat | None = None
    estimate: timedelta | None = None
    # 2.10.10+
    size: int | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "poweronhrs": "powerOnHours",
            "life_span": "lifeSpan",
            "bad_sector": "badSector",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "estimate": lambda x: timedelta(seconds=x)
        } | super().unifi_dict_conversions()

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        # estimate is actually in seconds, not milliseconds
        if "estimate" in data and data["estimate"] is not None:
            data["estimate"] /= 1000

        if "state" in data and data["state"] == "nodisk":
            pop_dict_tuple(
                data,
                (
                    "action",
                    "ata",
                    "bad_sector",
                    "estimate",
                    "firmware",
                    "healthy",
                    "life_span",
                    "model",
                    "poweronhrs",
                    "progress",
                    "reason",
                    "rpm",
                    "sata",
                    "serial",
                    "tempature",
                    "temperature",
                    "threshold",
                    "type",
                ),
            )
        return data

    @property
    def has_disk(self) -> bool:
        return self.state != "nodisk"

    @property
    def is_healthy(self) -> bool:
        return self.state in {
            "initializing",
            "expanding",
            "spare",
            "normal",
        }


class UOSStorage(ProtectBaseObject):
    disks: list[UOSDisk]


class SystemInfo(ProtectBaseObject):
    cpu: CPUInfo
    memory: MemoryInfo
    storage: StorageInfo
    ustorage: UOSStorage | None = None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"ustorage"})
        return data


class DoorbellMessage(ProtectBaseObject):
    type: DoorbellMessageType
    text: DoorbellText


class DoorbellSettings(ProtectBaseObject):
    default_message_text: DoorbellText
    all_messages: list[DoorbellMessage]
    custom_messages: list[DoorbellText]


class RecordingTypeDistribution(ProtectBaseObject):
    recording_type: RecordingType
    size: int
    percentage: float


class ResolutionDistribution(ProtectBaseObject):
    resolution: ResolutionStorageType
    size: int
    percentage: float


class StorageDistribution(ProtectBaseObject):
    recording_type_distributions: list[RecordingTypeDistribution]
    resolution_distributions: list[ResolutionDistribution]

    _recording_type_dict: dict[RecordingType, RecordingTypeDistribution] | None = (
        PrivateAttr(None)
    )
    _resolution_dict: dict[ResolutionStorageType, ResolutionDistribution] | None = (
        PrivateAttr(None)
    )

    def _get_recording_type_dict(
        self,
    ) -> dict[RecordingType, RecordingTypeDistribution]:
        if self._recording_type_dict is None:
            self._recording_type_dict = {}
            for recording_type in self.recording_type_distributions:
                self._recording_type_dict[recording_type.recording_type] = (
                    recording_type
                )

        return self._recording_type_dict

    def _get_resolution_dict(
        self,
    ) -> dict[ResolutionStorageType, ResolutionDistribution]:
        if self._resolution_dict is None:
            self._resolution_dict = {}
            for resolution in self.resolution_distributions:
                self._resolution_dict[resolution.resolution] = resolution

        return self._resolution_dict

    @property
    def timelapse_recordings(self) -> RecordingTypeDistribution | None:
        return self._get_recording_type_dict().get(RecordingType.TIMELAPSE)

    @property
    def continuous_recordings(self) -> RecordingTypeDistribution | None:
        return self._get_recording_type_dict().get(RecordingType.CONTINUOUS)

    @property
    def detections_recordings(self) -> RecordingTypeDistribution | None:
        return self._get_recording_type_dict().get(RecordingType.DETECTIONS)

    @property
    def uhd_usage(self) -> ResolutionDistribution | None:
        return self._get_resolution_dict().get(ResolutionStorageType.UHD)

    @property
    def hd_usage(self) -> ResolutionDistribution | None:
        return self._get_resolution_dict().get(ResolutionStorageType.HD)

    @property
    def free(self) -> ResolutionDistribution | None:
        return self._get_resolution_dict().get(ResolutionStorageType.FREE)

    def update_from_dict(self, data: dict[str, Any]) -> StorageDistribution:
        # reset internal look ups when data changes
        self._recording_type_dict = None
        self._resolution_dict = None

        return super().update_from_dict(data)


class StorageStats(ProtectBaseObject):
    utilization: float
    capacity: timedelta | None = None
    storage_distribution: StorageDistribution

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "capacity": lambda x: timedelta(milliseconds=x),
        } | super().unifi_dict_conversions()


class NVRFeatureFlags(ProtectBaseObject):
    pass


class NVRSmartDetection(ProtectBaseObject):
    enable: bool


class GlobalRecordingSettings(ProtectBaseObject):
    osd_settings: OSDSettings
    recording_settings: RecordingSettings
    smart_detect_settings: SmartDetectSettings


class NVR(ProtectDeviceModel):
    timezone: tzinfo
    version: Version
    ports: PortConfig
    hosts: list[IPv4Address | IPv6Address | str]
    analytics_data: AnalyticsOption
    feature_flags: NVRFeatureFlags
    system_info: SystemInfo
    doorbell_settings: DoorbellSettings
    storage_stats: StorageStats
    market_name: str | None = None
    is_insights_enabled: bool | None = None
    # requires 3.0.22+
    smart_detection: NVRSmartDetection | None = None
    global_camera_settings: GlobalRecordingSettings | None = None

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "version",
            "ports",
            "hosts",
            "storageStats",
            "avgMotions",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "timezone": zoneinfo.ZoneInfo,
        } | super().unifi_dict_conversions()

    async def _api_update(self, data: dict[str, Any]) -> None:
        return await self._api.update_nvr(data)

    @property
    def is_analytics_enabled(self) -> bool:
        return self.analytics_data is not AnalyticsOption.NONE

    @property
    def protect_url(self) -> str:
        return f"{self._api.base_url}/protect/devices/{self._api.bootstrap.nvr.id}"

    @property
    def display_name(self) -> str:
        return self.name or self.market_name or self.type

    @property
    def is_global_recording_enabled(self) -> bool:
        """
        Is recording footage/events from the camera enabled?

        If recording is not enabled, cameras will not produce any footage, thumbnails,
        motion/smart detection events.
        """
        return (
            (global_camera_settings := self.global_camera_settings) is not None
            and global_camera_settings.recording_settings.mode
            is not RecordingMode.NEVER
        )

    def update_all_messages(self) -> None:
        """Updates doorbell_settings.all_messages after adding/removing custom message"""
        messages = self.doorbell_settings.custom_messages
        self.doorbell_settings.all_messages = [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),  # type: ignore[arg-type]
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),  # type: ignore[arg-type]
            ),
            *(
                DoorbellMessage(
                    type=DoorbellMessageType.CUSTOM_MESSAGE,
                    text=message,
                )
                for message in messages
            ),
        ]

    async def set_insights(self, enabled: bool) -> None:
        """Sets analytics collection for NVR"""

        def callback() -> None:
            self.is_insights_enabled = enabled

        await self.queue_update(callback)

    async def set_analytics(self, value: AnalyticsOption) -> None:
        """Sets analytics collection for NVR"""

        def callback() -> None:
            self.analytics_data = value

        await self.queue_update(callback)

    async def set_anonymous_analytics(self, enabled: bool) -> None:
        """Enables or disables anonymous analytics for NVR"""
        if enabled:
            await self.set_analytics(AnalyticsOption.ANONYMOUS)
        else:
            await self.set_analytics(AnalyticsOption.NONE)

    async def add_custom_doorbell_message(self, message: str) -> None:
        """Adds custom doorbell message"""
        if len(message) > 30:
            raise BadRequest("Message length over 30 characters")

        if message in self.doorbell_settings.custom_messages:
            raise BadRequest("Custom doorbell message already exists")

        await self._update_doorbell_messages(
            lambda: self.doorbell_settings.custom_messages.append(
                DoorbellText(message)
            ),
        )

    async def remove_custom_doorbell_message(self, message: str) -> None:
        """Removes custom doorbell message"""
        if message not in self.doorbell_settings.custom_messages:
            raise BadRequest("Custom doorbell message does not exists")

        await self._update_doorbell_messages(
            lambda: self.doorbell_settings.custom_messages.remove(
                DoorbellText(message)
            ),
        )

    async def _update_doorbell_messages(
        self, update_callback: Callable[[], None]
    ) -> None:
        """Updates doorbell messages and saves to Protect."""
        async with self._update_sync.lock:
            # yield to the event loop once we have the lock to ensure websocket updates are processed
            await asyncio.sleep(0)
            data_before_changes = self.dict_with_excludes()
            update_callback()
            await self.save_device(data_before_changes)
            self.update_all_messages()

    async def reboot(self) -> None:
        """Reboots the NVR"""
        await self._api.reboot_nvr()


class LiveviewSlot(ProtectBaseObject):
    camera_ids: list[str]
    cycle_mode: str
    cycle_interval: int

    _cameras: list[Camera] | None = PrivateAttr(None)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "cameras": "cameraIds"}

    @property
    def cameras(self) -> list[Camera]:
        if self._cameras is not None:
            return self._cameras

        # user may not have permission to see the cameras in the liveview
        self._cameras = [
            self._api.bootstrap.cameras[g]
            for g in self.camera_ids
            if g in self._api.bootstrap.cameras
        ]
        return self._cameras


class Liveview(ProtectModelWithId):
    name: str
    is_default: bool
    is_global: bool
    layout: int
    slots: list[LiveviewSlot]
    owner_id: str

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "owner": "ownerId"}

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {"isDefault", "owner"}

    @property
    def owner(self) -> User | None:
        """
        Owner of liveview.

        Will be none if the user only has read only access and it was not made by their user.
        """
        return self._api.bootstrap.users.get(self.owner_id)

    @property
    def protect_url(self) -> str:
        return f"{self._api.base_url}/protect/liveview/{self.id}"
