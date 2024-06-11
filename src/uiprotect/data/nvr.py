"""UniFi Protect Data."""

from __future__ import annotations

import asyncio
import logging
import zoneinfo
from datetime import datetime, timedelta, tzinfo
from functools import cache
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal
from uuid import UUID

import aiofiles
import orjson
from aiofiles import os as aos

from ..exceptions import BadRequest, NotAuthorized
from ..utils import RELEASE_CACHE, convert_to_datetime
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
    FirmwareReleaseChannel,
    IteratorCallback,
    ModelType,
    MountType,
    PercentFloat,
    PercentInt,
    PermissionNode,
    ProgressCallback,
    RecordingMode,
    RecordingType,
    ResolutionStorageType,
    SensorStatusType,
    SensorType,
    SmartDetectObjectType,
    StorageType,
    Version,
)
from .user import User, UserLocation

try:
    from pydantic.v1.fields import PrivateAttr
except ImportError:
    from pydantic.fields import PrivateAttr

if TYPE_CHECKING:
    try:
        from pydantic.v1.typing import SetStr
    except ImportError:
        from pydantic.typing import SetStr  # type: ignore[assignment, no-redef]


_LOGGER = logging.getLogger(__name__)
MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2
DELETE_KEYS_THUMB = {"color", "vehicleType"}
DELETE_KEYS_EVENT = {"deletedAt", "category", "subCategory"}


class NVRLocation(UserLocation):
    is_geofencing_enabled: bool
    radius: int
    model: ModelType | None = None


class SmartDetectItem(ProtectBaseObject):
    id: str
    timestamp: datetime
    level: PercentInt
    coord: tuple[int, int, int, int]
    object_type: SmartDetectObjectType
    zone_ids: list[int]
    duration: timedelta

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "zones": "zoneIds",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "duration" in data:
            data["duration"] = timedelta(milliseconds=data["duration"])

        return super().unifi_dict_to_dict(data)


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


class LicensePlateMetadata(ProtectBaseObject):
    name: str
    confidence_level: int


class EventThumbnailAttribute(ProtectBaseObject):
    confidence: int
    val: str


class EventThumbnailAttributes(ProtectBaseObject):
    color: EventThumbnailAttribute | None = None
    vehicle_type: EventThumbnailAttribute | None = None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        for key in DELETE_KEYS_THUMB.intersection(data):
            if data[key] is None:
                del data[key]

        return data


class EventDetectedThumbnail(ProtectBaseObject):
    clock_best_wall: datetime | None = None
    type: str
    cropped_id: str
    attributes: EventThumbnailAttributes | None = None
    name: str | None

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "clockBestWall" in data:
            if data["clockBestWall"]:
                data["clockBestWall"] = convert_to_datetime(data["clockBestWall"])
            else:
                del data["clockBestWall"]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "name" in data and data["name"] is None:
            del data["name"]

        return data


class EventMetadata(ProtectBaseObject):
    client_platform: str | None
    reason: str | None
    app_update: str | None
    light_id: str | None
    light_name: str | None
    type: str | None
    sensor_id: str | None
    sensor_name: str | None
    sensor_type: SensorType | None
    doorlock_id: str | None
    doorlock_name: str | None
    from_value: str | None
    to_value: str | None
    mount_type: MountType | None
    status: SensorStatusType | None
    alarm_type: str | None
    device_id: str | None
    mac: str | None
    # require 2.7.5+
    license_plate: LicensePlateMetadata | None = None
    # requires 2.11.13+
    detected_thumbnails: list[EventDetectedThumbnail] | None = None

    _collapse_keys: ClassVar[SetStr] = {
        "lightId",
        "lightName",
        "type",
        "sensorId",
        "sensorName",
        "sensorType",
        "doorlockId",
        "doorlockName",
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
                data[key] = data[key]["text"]

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
    end: datetime | None
    score: int
    heatmap_id: str | None
    camera_id: str | None
    smart_detect_types: list[SmartDetectObjectType]
    smart_detect_event_ids: list[str]
    thumbnail_id: str | None
    user_id: str | None
    timestamp: datetime | None
    metadata: EventMetadata | None
    # requires 2.7.5+
    deleted_at: datetime | None = None
    deletion_type: Literal["manual", "automatic"] | None = None
    # only appears if `get_events` is called with category
    category: EventCategories | None = None
    sub_category: str | None = None

    # TODO:
    # partition
    # description

    _smart_detect_events: list[Event] | None = PrivateAttr(None)
    _smart_detect_track: SmartDetectTrack | None = PrivateAttr(None)
    _smart_detect_zones: dict[int, CameraZone] | None = PrivateAttr(None)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "camera": "cameraId",
            "heatmap": "heatmapId",
            "user": "userId",
            "thumbnail": "thumbnailId",
            "smartDetectEvents": "smartDetectEventIds",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        for key in {"start", "end", "timestamp", "deletedAt"}.intersection(data):
            data[key] = convert_to_datetime(data[key])

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        for key in DELETE_KEYS_EVENT.intersection(data):
            if data[key] is None:
                del data[key]

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

    @property
    def smart_detect_events(self) -> list[Event]:
        if self._smart_detect_events is not None:
            return self._smart_detect_events

        self._smart_detect_events = [
            self._api.bootstrap.events[g]
            for g in self.smart_detect_event_ids
            if g in self._api.bootstrap.events
        ]
        return self._smart_detect_events

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

    async def get_animated_thumbnail(
        self,
        width: int | None = None,
        height: int | None = None,
        *,
        speedup: int = 10,
    ) -> bytes | None:
        """Gets animated thumbnail for event"""
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
        return await self._api.get_event_animated_thumbnail(
            self.thumbnail_id,
            width,
            height,
            speedup=speedup,
        )

    async def get_heatmap(self) -> bytes | None:
        """Gets heatmap for event"""
        if self.heatmap_id is None:
            return None
        if not self._api.bootstrap.auth_user.can(
            ModelType.CAMERA,
            PermissionNode.READ_MEDIA,
            self.camera,
        ):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}",
            )
        return await self._api.get_event_heatmap(self.heatmap_id)

    async def get_video(
        self,
        channel_index: int = 0,
        output_file: Path | None = None,
        iterator_callback: IteratorCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        chunk_size: int = 65536,
    ) -> bytes | None:
        """
        Get the MP4 video clip for this given event

        Args:
        ----
            channel_index: index of `CameraChannel` on the camera to use to retrieve video from

        Will raise an exception if event does not have a camera, end time or the channel index is wrong.

        """
        if self.camera is None:
            raise BadRequest("Event does not have a camera")
        if self.end is None:
            raise BadRequest("Event is ongoing")

        if not self._api.bootstrap.auth_user.can(
            ModelType.CAMERA,
            PermissionNode.READ_MEDIA,
            self.camera,
        ):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}",
            )
        return await self._api.get_camera_video(
            self.camera.id,
            self.start,
            self.end,
            channel_index,
            output_file=output_file,
            iterator_callback=iterator_callback,
            progress_callback=progress_callback,
            chunk_size=chunk_size,
        )

    async def get_smart_detect_track(self) -> SmartDetectTrack:
        """
        Gets smart detect track for given smart detect event.

        If event is not a smart detect event, it will raise a `BadRequest`
        """
        if self.type not in {EventType.SMART_DETECT, EventType.SMART_DETECT_LINE}:
            raise BadRequest("Not a smart detect event")

        if self._smart_detect_track is None:
            self._smart_detect_track = await self._api.get_event_smart_detect_track(
                self.id,
            )

        return self._smart_detect_track

    async def get_smart_detect_zones(self) -> dict[int, CameraZone]:
        """Gets the triggering zones for the smart detection"""
        if self.camera is None:
            raise BadRequest("No camera on event")

        if self._smart_detect_zones is None:
            smart_track = await self.get_smart_detect_track()

            ids: set[int] = set()
            for item in smart_track.payload:
                ids |= set(item.zone_ids)

            self._smart_detect_zones = {
                z.id: z for z in self.camera.smart_detect_zones if z.id in ids
            }

        return self._smart_detect_zones


class PortConfig(ProtectBaseObject):
    ump: int
    http: int
    https: int
    rtsp: int
    rtsps: int
    rtmp: int
    devices_wss: int
    camera_https: int
    live_ws: int
    live_wss: int
    tcp_streams: int
    playback: int
    ems_cli: int
    ems_live_flv: int
    camera_events: int
    tcp_bridge: int
    ucore: int
    discovery_client: int
    piongw: int | None = None
    ems_json_cli: int | None = None
    stacking: int | None = None
    # 3.0.22+
    ai_feature_console: int | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "emsCLI": "emsCli",
            "emsLiveFLV": "emsLiveFlv",
            "emsJsonCLI": "emsJsonCli",
        }


class CPUInfo(ProtectBaseObject):
    average_load: float
    temperature: float


class MemoryInfo(ProtectBaseObject):
    available: int | None
    free: int | None
    total: int | None


class StorageDevice(ProtectBaseObject):
    model: str
    size: int
    healthy: bool | str


class StorageInfo(ProtectBaseObject):
    available: int
    is_recycling: bool
    size: int
    type: StorageType
    used: int
    devices: list[StorageDevice]
    # requires 2.8.14+
    capability: str | None = None

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


class StorageSpace(ProtectBaseObject):
    total: int
    used: int
    available: int


class TMPFSInfo(ProtectBaseObject):
    available: int
    total: int
    used: int
    path: Path


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
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "estimate" in data and data["estimate"] is not None:
            data["estimate"] = timedelta(seconds=data.pop("estimate"))

        return super().unifi_dict_to_dict(data)

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
            delete_keys = [
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
            ]
            for key in delete_keys:
                if key in data:
                    del data[key]

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


class UOSSpace(ProtectBaseObject):
    device: str
    total_bytes: int
    used_bytes: int
    action: str
    progress: PercentFloat | None = None
    estimate: timedelta | None = None
    # requires 2.8.14+
    health: str | None = None
    # requires 2.8.22+
    space_type: str | None = None

    # TODO:
    # reasons

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "total_bytes": "totalBytes",
            "used_bytes": "usedBytes",
            "space_type": "spaceType",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "estimate" in data and data["estimate"] is not None:
            data["estimate"] = timedelta(seconds=data.pop("estimate"))

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        # estimate is actually in seconds, not milliseconds
        if "estimate" in data and data["estimate"] is not None:
            data["estimate"] /= 1000

        return data


class UOSStorage(ProtectBaseObject):
    disks: list[UOSDisk]
    space: list[UOSSpace]

    # TODO:
    # sdcards


class SystemInfo(ProtectBaseObject):
    cpu: CPUInfo
    memory: MemoryInfo
    storage: StorageInfo
    tmpfs: TMPFSInfo
    ustorage: UOSStorage | None = None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if data is not None and "ustorage" in data and data["ustorage"] is None:
            del data["ustorage"]

        return data


class DoorbellMessage(ProtectBaseObject):
    type: DoorbellMessageType
    text: DoorbellText


class DoorbellSettings(ProtectBaseObject):
    default_message_text: DoorbellText
    default_message_reset_timeout: timedelta
    all_messages: list[DoorbellMessage]
    custom_messages: list[DoorbellText]

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "defaultMessageResetTimeoutMs": "defaultMessageResetTimeout",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "defaultMessageResetTimeoutMs" in data:
            data["defaultMessageResetTimeout"] = timedelta(
                milliseconds=data.pop("defaultMessageResetTimeoutMs"),
            )

        return super().unifi_dict_to_dict(data)


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
    capacity: timedelta | None
    remaining_capacity: timedelta | None
    recording_space: StorageSpace
    storage_distribution: StorageDistribution

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "capacity" in data and data["capacity"] is not None:
            data["capacity"] = timedelta(milliseconds=data.pop("capacity"))
        if "remainingCapacity" in data and data["remainingCapacity"] is not None:
            data["remainingCapacity"] = timedelta(
                milliseconds=data.pop("remainingCapacity"),
            )

        return super().unifi_dict_to_dict(data)


class NVRFeatureFlags(ProtectBaseObject):
    beta: bool
    dev: bool
    notifications_v2: bool
    homekit_paired: bool | None = None
    ulp_role_management: bool | None = None
    # 2.9.20+
    detection_labels: bool | None = None
    has_two_way_audio_media_streams: bool | None = None


class NVRSmartDetection(ProtectBaseObject):
    enable: bool
    face_recognition: bool
    license_plate_recognition: bool


class GlobalRecordingSettings(ProtectBaseObject):
    osd_settings: OSDSettings
    recording_settings: RecordingSettings
    smart_detect_settings: SmartDetectSettings

    # TODO:
    # recordingSchedulesV2


class NVR(ProtectDeviceModel):
    can_auto_update: bool
    is_stats_gathering_enabled: bool
    timezone: tzinfo
    version: Version
    ucore_version: str
    hardware_platform: str
    ports: PortConfig
    last_update_at: datetime | None
    is_station: bool
    enable_automatic_backups: bool
    enable_stats_reporting: bool
    release_channel: FirmwareReleaseChannel
    hosts: list[IPv4Address | IPv6Address | str]
    enable_bridge_auto_adoption: bool
    hardware_id: UUID
    host_type: int
    host_shortname: str
    is_hardware: bool
    is_wireless_uplink_enabled: bool | None
    time_format: Literal["12h", "24h"]
    temperature_unit: Literal["C", "F"]
    recording_retention_duration: timedelta | None
    enable_crash_reporting: bool
    disable_audio: bool
    analytics_data: AnalyticsOption
    anonymous_device_id: UUID | None
    camera_utilization: int
    is_recycling: bool
    disable_auto_link: bool
    skip_firmware_update: bool
    location_settings: NVRLocation
    feature_flags: NVRFeatureFlags
    system_info: SystemInfo
    doorbell_settings: DoorbellSettings
    storage_stats: StorageStats
    is_away: bool
    is_setup: bool
    network: str
    max_camera_capacity: dict[Literal["4K", "2K", "HD"], int]
    market_name: str | None = None
    stream_sharing_available: bool | None = None
    is_db_available: bool | None = None
    is_insights_enabled: bool | None = None
    is_recording_disabled: bool | None = None
    is_recording_motion_only: bool | None = None
    ui_version: str | None = None
    sso_channel: FirmwareReleaseChannel | None = None
    is_stacked: bool | None = None
    is_primary: bool | None = None
    last_drive_slow_event: datetime | None = None
    is_u_core_setup: bool | None = None
    vault_camera_ids: list[str] = []
    # requires 2.8.14+
    corruption_state: str | None = None
    country_code: str | None = None
    has_gateway: bool | None = None
    is_vault_registered: bool | None = None
    public_ip: IPv4Address | None = None
    ulp_version: str | None = None
    wan_ip: IPv4Address | IPv6Address | None = None
    # requires 2.9.20+
    hard_drive_state: str | None = None
    is_network_installed: bool | None = None
    is_protect_updatable: bool | None = None
    is_ucore_updatable: bool | None = None
    # requires 2.11.13+
    last_device_fw_updates_checked_at: datetime | None = None
    # requires 3.0.22+
    smart_detection: NVRSmartDetection | None = None
    is_ucore_stacked: bool | None = None
    global_camera_settings: GlobalRecordingSettings | None = None

    # TODO:
    # errorCode   read only
    # wifiSettings
    # smartDetectAgreement
    # dbRecoveryOptions
    # portStatus
    # cameraCapacity
    # deviceFirmwareSettings

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "recordingRetentionDurationMs": "recordingRetentionDuration",
            "vaultCameras": "vaultCameraIds",
            "lastDeviceFWUpdatesCheckedAt": "lastDeviceFwUpdatesCheckedAt",
            "isUCoreStacked": "isUcoreStacked",
        }

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "version",
            "uiVersion",
            "hardwarePlatform",
            "ports",
            "lastUpdateAt",
            "isStation",
            "hosts",
            "hostShortname",
            "isDbAvailable",
            "isRecordingDisabled",
            "isRecordingMotionOnly",
            "cameraUtilization",
            "storageStats",
            "isRecycling",
            "avgMotions",
            "streamSharingAvailable",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "lastUpdateAt" in data:
            data["lastUpdateAt"] = convert_to_datetime(data["lastUpdateAt"])
        if "lastDeviceFwUpdatesCheckedAt" in data:
            data["lastDeviceFwUpdatesCheckedAt"] = convert_to_datetime(
                data["lastDeviceFwUpdatesCheckedAt"]
            )
        if (
            "recordingRetentionDurationMs" in data
            and data["recordingRetentionDurationMs"] is not None
        ):
            data["recordingRetentionDuration"] = timedelta(
                milliseconds=data.pop("recordingRetentionDurationMs"),
            )
        if "timezone" in data and not isinstance(data["timezone"], tzinfo):
            data["timezone"] = zoneinfo.ZoneInfo(data["timezone"])

        return super().unifi_dict_to_dict(data)

    async def _api_update(self, data: dict[str, Any]) -> None:
        return await self._api.update_nvr(data)

    @property
    def is_analytics_enabled(self) -> bool:
        return self.analytics_data != AnalyticsOption.NONE

    @property
    def protect_url(self) -> str:
        return f"{self._api.base_url}/protect/devices/{self._api.bootstrap.nvr.id}"

    @property
    def display_name(self) -> str:
        return self.name or self.market_name or self.type

    @property
    def vault_cameras(self) -> list[Camera]:
        """Vault Cameras for NVR"""
        if len(self.vault_camera_ids) == 0:
            return []
        return [self._api.bootstrap.cameras[c] for c in self.vault_camera_ids]

    @property
    def is_global_recording_enabled(self) -> bool:
        """
        Is recording footage/events from the camera enabled?

        If recording is not enabled, cameras will not produce any footage, thumbnails,
        motion/smart detection events.
        """
        return (
            self.global_camera_settings is not None
            and self.global_camera_settings.recording_settings.mode
            is not RecordingMode.NEVER
        )

    @property
    def is_smart_detections_enabled(self) -> bool:
        """If smart detected enabled globally."""
        return self.smart_detection is not None and self.smart_detection.enable

    @property
    def is_license_plate_detections_enabled(self) -> bool:
        """If smart detected enabled globally."""
        return (
            self.smart_detection is not None
            and self.smart_detection.enable
            and self.smart_detection.license_plate_recognition
        )

    @property
    def is_face_detections_enabled(self) -> bool:
        """If smart detected enabled globally."""
        return (
            self.smart_detection is not None
            and self.smart_detection.enable
            and self.smart_detection.face_recognition
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
        """Enables or disables anonymous analystics for NVR"""
        if enabled:
            await self.set_analytics(AnalyticsOption.ANONYMOUS)
        else:
            await self.set_analytics(AnalyticsOption.NONE)

    async def set_default_reset_timeout(self, timeout: timedelta) -> None:
        """Sets the default message reset timeout"""

        def callback() -> None:
            self.doorbell_settings.default_message_reset_timeout = timeout

        await self.queue_update(callback)

    async def set_default_doorbell_message(self, message: str) -> None:
        """Sets default doorbell message"""

        def callback() -> None:
            self.doorbell_settings.default_message_text = DoorbellText(message)

        await self.queue_update(callback)

    async def add_custom_doorbell_message(self, message: str) -> None:
        """Adds custom doorbell message"""
        if len(message) > 30:
            raise BadRequest("Message length over 30 characters")

        if message in self.doorbell_settings.custom_messages:
            raise BadRequest("Custom doorbell message already exists")

        async with self._update_lock:
            await asyncio.sleep(
                0,
            )  # yield to the event loop once we have the look to ensure websocket updates are processed
            data_before_changes = self.dict_with_excludes()
            self.doorbell_settings.custom_messages.append(DoorbellText(message))
            await self.save_device(data_before_changes)
            self.update_all_messages()

    async def remove_custom_doorbell_message(self, message: str) -> None:
        """Removes custom doorbell message"""
        if message not in self.doorbell_settings.custom_messages:
            raise BadRequest("Custom doorbell message does not exists")

        async with self._update_lock:
            await asyncio.sleep(
                0,
            )  # yield to the event loop once we have the look to ensure websocket updates are processed
            data_before_changes = self.dict_with_excludes()
            self.doorbell_settings.custom_messages.remove(DoorbellText(message))
            await self.save_device(data_before_changes)
            self.update_all_messages()

    async def reboot(self) -> None:
        """Reboots the NVR"""
        await self._api.reboot_nvr()

    async def _read_cache_file(self, file_path: Path) -> set[Version] | None:
        versions: set[Version] | None = None

        if file_path.is_file():
            try:
                _LOGGER.debug("Reading release cache file: %s", file_path)
                async with aiofiles.open(file_path, "rb") as cache_file:
                    versions = {
                        Version(v) for v in orjson.loads(await cache_file.read())
                    }
            except Exception:
                _LOGGER.warning("Failed to parse cache file: %s", file_path)

        return versions

    async def get_is_prerelease(self) -> bool:
        """Get if current version of Protect is a prerelease version."""
        # only EA versions have `-beta` in versions
        if self.version.is_prerelease:
            return True

        # 2.6.14 is an EA version that looks like a release version
        cache_file_path = self._api.cache_dir / "release_cache.json"
        versions = await self._read_cache_file(
            cache_file_path,
        ) or await self._read_cache_file(RELEASE_CACHE)
        if versions is None or self.version not in versions:
            versions = await self._api.get_release_versions()
            try:
                _LOGGER.debug("Fetching releases from APT repos...")
                tmp = self._api.cache_dir / "release_cache.tmp.json"
                await aos.makedirs(self._api.cache_dir, exist_ok=True)
                async with aiofiles.open(tmp, "wb") as cache_file:
                    await cache_file.write(orjson.dumps([str(v) for v in versions]))
                await aos.rename(tmp, cache_file_path)
            except Exception:
                _LOGGER.warning("Failed write cache file.")

        return self.version not in versions

    async def set_smart_detections(self, value: bool) -> None:
        """Set if smart detections are enabled."""

        def callback() -> None:
            if self.smart_detection is not None:
                self.smart_detection.enable = value

        await self.queue_update(callback)

    async def set_face_recognition(self, value: bool) -> None:
        """Set if face detections are enabled. Requires smart detections to be enabled."""
        if self.smart_detection is None or not self.smart_detection.enable:
            raise BadRequest("Smart detections are not enabled.")

        def callback() -> None:
            if self.smart_detection is not None:
                self.smart_detection.face_recognition = value

        await self.queue_update(callback)

    async def set_license_plate_recognition(self, value: bool) -> None:
        """Set if license plate detections are enabled. Requires smart detections to be enabled."""
        if self.smart_detection is None or not self.smart_detection.enable:
            raise BadRequest("Smart detections are not enabled.")

        def callback() -> None:
            if self.smart_detection is not None:
                self.smart_detection.license_plate_recognition = value

        await self.queue_update(callback)

    async def set_global_osd_name(self, enabled: bool) -> None:
        """Sets whether camera name is in the On Screen Display"""

        def callback() -> None:
            if self.global_camera_settings:
                self.global_camera_settings.osd_settings.is_name_enabled = enabled

        await self.queue_update(callback)

    async def set_global_osd_date(self, enabled: bool) -> None:
        """Sets whether current date is in the On Screen Display"""

        def callback() -> None:
            if self.global_camera_settings:
                self.global_camera_settings.osd_settings.is_date_enabled = enabled

        await self.queue_update(callback)

    async def set_global_osd_logo(self, enabled: bool) -> None:
        """Sets whether the UniFi logo is in the On Screen Display"""

        def callback() -> None:
            if self.global_camera_settings:
                self.global_camera_settings.osd_settings.is_logo_enabled = enabled

        await self.queue_update(callback)

    async def set_global_osd_bitrate(self, enabled: bool) -> None:
        """Sets whether camera bitrate is in the On Screen Display"""

        def callback() -> None:
            # mismatch between UI internal data structure debug = bitrate data
            if self.global_camera_settings:
                self.global_camera_settings.osd_settings.is_debug_enabled = enabled

        await self.queue_update(callback)

    async def set_global_motion_detection(self, enabled: bool) -> None:
        """Sets motion detection on camera"""

        def callback() -> None:
            if self.global_camera_settings:
                self.global_camera_settings.recording_settings.enable_motion_detection = enabled

        await self.queue_update(callback)

    async def set_global_recording_mode(self, mode: RecordingMode) -> None:
        """Sets recording mode on camera"""

        def callback() -> None:
            if self.global_camera_settings:
                self.global_camera_settings.recording_settings.mode = mode

        await self.queue_update(callback)

    # object smart detections

    def _is_smart_enabled(self, smart_type: SmartDetectObjectType) -> bool:
        return (
            self.is_global_recording_enabled
            and self.global_camera_settings is not None
            and smart_type
            in self.global_camera_settings.smart_detect_settings.object_types
        )

    @property
    def is_global_person_detection_on(self) -> bool:
        """
        Is Person Detection available and enabled (camera will produce person smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.PERSON)

    @property
    def is_global_person_tracking_enabled(self) -> bool:
        """Is person tracking enabled"""
        return (
            self.global_camera_settings is not None
            and self.global_camera_settings.smart_detect_settings.auto_tracking_object_types
            is not None
            and SmartDetectObjectType.PERSON
            in self.global_camera_settings.smart_detect_settings.auto_tracking_object_types
        )

    @property
    def is_global_vehicle_detection_on(self) -> bool:
        """
        Is Vehicle Detection available and enabled (camera will produce vehicle smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.VEHICLE)

    @property
    def is_global_license_plate_detection_on(self) -> bool:
        """
        Is License Plate Detection available and enabled (camera will produce face license
        plate detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.LICENSE_PLATE)

    @property
    def is_global_package_detection_on(self) -> bool:
        """
        Is Package Detection available and enabled (camera will produce package smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.PACKAGE)

    @property
    def is_global_animal_detection_on(self) -> bool:
        """
        Is Animal Detection available and enabled (camera will produce package smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.ANIMAL)

    def _is_audio_enabled(self, smart_type: SmartDetectObjectType) -> bool:
        audio_type = smart_type.audio_type
        return (
            audio_type is not None
            and self.is_global_recording_enabled
            and self.global_camera_settings is not None
            and self.global_camera_settings.smart_detect_settings.audio_types
            is not None
            and audio_type
            in self.global_camera_settings.smart_detect_settings.audio_types
        )

    @property
    def is_global_smoke_detection_on(self) -> bool:
        """
        Is Smoke Alarm Detection available and enabled (camera will produce smoke
        smart detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.SMOKE)

    @property
    def is_global_co_detection_on(self) -> bool:
        """
        Is CO Alarm Detection available and enabled (camera will produce smoke smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.CMONX)

    @property
    def is_global_siren_detection_on(self) -> bool:
        """
        Is Siren Detection available and enabled (camera will produce siren smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.SIREN)

    @property
    def is_global_baby_cry_detection_on(self) -> bool:
        """
        Is Baby Cry Detection available and enabled (camera will produce baby cry smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.BABY_CRY)

    @property
    def is_global_speaking_detection_on(self) -> bool:
        """
        Is Speaking Detection available and enabled (camera will produce speaking smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.SPEAK)

    @property
    def is_global_bark_detection_on(self) -> bool:
        """
        Is Bark Detection available and enabled (camera will produce barking smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.BARK)

    @property
    def is_global_car_alarm_detection_on(self) -> bool:
        """
        Is Car Alarm Detection available and enabled (camera will produce car alarm smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.BURGLAR)

    @property
    def is_global_car_horn_detection_on(self) -> bool:
        """
        Is Car Horn Detection available and enabled (camera will produce car horn smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.CAR_HORN)

    @property
    def is_global_glass_break_detection_on(self) -> bool:
        """
        Is Glass Break available and enabled (camera will produce glass break smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.GLASS_BREAK)


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
