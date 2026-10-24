"""UniFi Protect Data."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import cache
from ipaddress import IPv4Address, IPv6Address
from typing import Any, ClassVar, Literal

from convertertools import pop_dict_set_if_none, pop_dict_tuple
from pydantic import ConfigDict, Field
from pydantic.fields import PrivateAttr

from ..exceptions import BadRequest
from ..utils import convert_smart_types, convert_to_datetime
from .base import (
    ProtectBaseObject,
    ProtectDeviceModel,
    ProtectModelWithId,
)
from .devices import (
    Camera,
    Light,
    RecordingSettings,
    Sensor,
    SmartDetectSettings,
)
from .types import (
    AnalyticsOption,
    DoorbellMessageType,
    DoorbellText,
    EventType,
    RecordingMode,
    RecordingType,
    ResolutionStorageType,
    SensorAlarmType,
    SmartDetectObjectType,
    Version,
)

_LOGGER = logging.getLogger(__name__)
MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2
DELETE_KEYS_THUMB = {"color", "vehicleType"}


class MetaInfo(ProtectBaseObject):
    application_version: str

    @property
    def version(self) -> Version:
        """Parsed application version, comparable to the private ``NVR.version``."""
        return Version(self.application_version)


class EventThumbnailGroup(ProtectBaseObject):
    """Group information for detected thumbnails (e.g., license plate recognition)."""

    matched_name: str | None = None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"matchedName"})
        return data


class EventThumbnailAttribute(ProtectBaseObject):
    confidence: int
    val: str


class NfcMetadata(ProtectBaseObject):
    nfc_id: str | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "nfcId": "nfc_id",
        }

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"nfcId"})
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
    attributes: EventThumbnailAttributes | None = None
    name: str | None = None
    confidence: int | None = None
    # requires 6.0.0+
    group: EventThumbnailGroup | None = None

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
        pop_dict_set_if_none(data, {"name", "group", "confidence"})
        return data


class EventMetadata(ProtectBaseObject):
    light_id: str | None = None
    sensor_id: str | None = None
    alarm_type: SensorAlarmType | None = None
    device_id: str | None = None
    # requires 2.11.13+
    detected_thumbnails: list[EventDetectedThumbnail] | None = None
    # requires 5.1.34+
    nfc: NfcMetadata | None = None
    fingerprint: FingerprintMetadata | None = None

    _collapse_keys: ClassVar[set[str]] = {
        "lightId",
        "sensorId",
        "alarmType",
        "deviceId",
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
    smart_detect_types: list[SmartDetectObjectType] = Field(default_factory=list)
    metadata: EventMetadata | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "camera": "cameraId",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return (
            dict.fromkeys(("start", "end"), convert_to_datetime)
            | {"smartDetectTypes": convert_smart_types}
            | super().unifi_dict_conversions()
        )

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


class CPUInfo(ProtectBaseObject):
    average_load: float
    temperature: float


class MemoryInfo(ProtectBaseObject):
    available: int | None = None
    total: int | None = None


class UOSDisk(ProtectBaseObject):
    slot: int
    state: str

    type: Literal["SSD", "HDD"] | None = None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        if "state" in data and data["state"] == "nodisk":
            pop_dict_tuple(data, ("type",))
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
    all_messages: list[DoorbellMessage]
    custom_messages: list[DoorbellText]


class RecordingTypeDistribution(ProtectBaseObject):
    recording_type: RecordingType
    percentage: float


class ResolutionDistribution(ProtectBaseObject):
    resolution: ResolutionStorageType
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


class GlobalRecordingSettings(ProtectBaseObject):
    recording_settings: RecordingSettings
    smart_detect_settings: SmartDetectSettings


class NVR(ProtectDeviceModel):
    version: Version
    hosts: list[IPv4Address | IPv6Address | str]
    analytics_data: AnalyticsOption
    system_info: SystemInfo
    doorbell_settings: DoorbellSettings
    storage_stats: StorageStats
    market_name: str | None = None
    is_insights_enabled: bool | None = None
    # requires 3.0.22+
    global_camera_settings: GlobalRecordingSettings | None = None

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "version",
            "hosts",
            "storageStats",
            "avgMotions",
        }

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


class Liveview(ProtectModelWithId):
    name: str
