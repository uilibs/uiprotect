"""UniFi Protect Data."""

from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from functools import cache, lru_cache
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from convertertools import pop_dict_set_if_none, pop_dict_tuple
from pydantic import model_validator
from pydantic.fields import PrivateAttr

from ..exceptions import (
    BadRequest,
    ChimeRingtoneNotSetError,
    NotAuthorized,
    StreamError,
)
from ..stream import TalkbackSession, TalkbackStream
from ..utils import (
    convert_smart_audio_types,
    convert_smart_types,
    convert_to_datetime,
    convert_video_modes,
    format_host_for_url,
    from_js_time,
    serialize_point,
    timedelta_total_seconds,
    to_js_time,
    utc_now,
)
from .base import (
    EVENT_PING_INTERVAL,
    ProtectAdoptableDeviceModel,
    ProtectBaseObject,
    ProtectMotionDeviceModel,
)
from .public_devices import (
    _build_public_lcd_message,
)
from .types import (
    DEFAULT,
    DEFAULT_TYPE,
    AudioCodecs,
    ChannelQuality,
    ChimeType,
    Color,
    DoorbellMessageType,
    HDRMode,
    ICRCustomValue,
    ICRLuxValue,
    IRLEDMode,
    IteratorCallback,
    LEDLevel,
    LensType,
    LightModeEnableType,
    LightModeType,
    ModelType,
    MountType,
    Percent,
    PercentInt,
    PermissionNode,
    ProgressCallback,
    PTZPatrol,
    PTZPreset,
    PublicHdrMode,
    RecordingMode,
    RepeatTimes,
    SensorStatusType,
    SmartDetectAudioType,
    SmartDetectObjectType,
    VideoMode,
    WDRLevel,
)
from .user import User

if TYPE_CHECKING:
    from ..api import (
        PublicApiChimeRingSettingRequest,
    )
    from .nvr import Event, Liveview

PRIVACY_ZONE_NAME = "pyufp_privacy_zone"
LUX_MAPPING_VALUES = [30, 25, 20, 15, 12, 10, 7, 5, 3, 1, 0]
# Protect switches the ICR on the lux threshold only in these modes; `auto`/
# `autoFilterOnly` switch on sensitivity and discard icrCustomValue, and
# `manual`/`on`/`off` force the IR cut filter, so the threshold is inert there.
_ICR_LUX_IR_LED_MODES = frozenset({IRLEDMode.CUSTOM, IRLEDMode.CUSTOM_FILTER_ONLY})

_LOGGER = logging.getLogger(__name__)


class LightDeviceSettings(ProtectBaseObject):
    # Status LED
    is_indicator_enabled: bool
    # Brightness
    led_level: LEDLevel
    pir_duration: timedelta
    pir_sensitivity: PercentInt

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "pirDuration": lambda x: timedelta(milliseconds=x)
        } | super().unifi_dict_conversions()


class LightModeSettings(ProtectBaseObject):
    # main "Lighting" settings
    mode: LightModeType
    enable_at: LightModeEnableType


class Light(ProtectMotionDeviceModel):
    is_pir_motion_detected: bool
    is_light_on: bool
    light_device_settings: LightDeviceSettings
    light_mode_settings: LightModeSettings
    camera_id: str | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "isPirMotionDetected",
            "isLightOn",
        }

    @property
    def camera(self) -> Camera | None:
        """Paired Camera will always be none if no camera is paired"""
        if self.camera_id is None:
            return None

        return self._api.bootstrap.cameras[self.camera_id]

    async def set_paired_camera(self, camera: Camera | None) -> None:
        """Sets the camera paired with the light"""
        async with self._update_sync.lock:
            # yield to the event loop once we have the lock to process any pending updates
            await asyncio.sleep(0)
            data_before_changes = self.dict_with_excludes()
            if camera is None:
                self.camera_id = None
            else:
                self.camera_id = camera.id
            await self.save_device(data_before_changes, force_emit=True)


RTSPS_QUALITY_BY_CHANNEL_ID: Mapping[int, ChannelQuality] = MappingProxyType(
    {
        0: ChannelQuality.HIGH,
        1: ChannelQuality.MEDIUM,
        2: ChannelQuality.LOW,
        3: ChannelQuality.PACKAGE,
    }
)
CHANNEL_ID_BY_RTSPS_QUALITY: Mapping[ChannelQuality, int] = MappingProxyType(
    {quality: channel_id for channel_id, quality in RTSPS_QUALITY_BY_CHANNEL_ID.items()}
)


def quality_for_channel_id(channel_id: int) -> ChannelQuality | None:
    """RTSPS quality tier for a channel id (0→HIGH, 1→MEDIUM, 2→LOW, 3→PACKAGE)."""
    return RTSPS_QUALITY_BY_CHANNEL_ID.get(channel_id)


def channel_id_for_quality(quality: ChannelQuality) -> int | None:
    """Channel id for an RTSPS quality tier (inverse of quality_for_channel_id)."""
    return CHANNEL_ID_BY_RTSPS_QUALITY.get(quality)


class CameraChannel(ProtectBaseObject):
    id: int  # read only
    video_id: str  # read only
    name: str  # read only
    enabled: bool  # read only
    is_rtsp_enabled: bool
    rtsp_alias: str | None = None  # read only
    width: int
    height: int
    fps: int | None = None  # read only
    bitrate: int
    min_bitrate: int | None = None  # read only
    max_bitrate: int | None = None  # read only
    min_client_adaptive_bit_rate: int | None = None  # read only
    min_motion_adaptive_bit_rate: int | None = None  # read only
    fps_values: list[int]  # read only
    idr_interval: int
    # 3.0.22+
    auto_bitrate: bool | None = None
    auto_fps: bool | None = None

    _parent: Camera | None = PrivateAttr(None)
    _rtsps_url: str | None = PrivateAttr(None)
    _rtsps_no_srtp_url: str | None = PrivateAttr(None)

    def _get_connection_host(self) -> IPv4Address | IPv6Address | str:
        """Get connection host (camera's for stacked NVR, otherwise NVR's)."""
        if self._parent is not None and self._parent.connection_host is not None:
            return self._parent.connection_host
        return self._api.connection_host

    @property
    def rtsps_url(self) -> str | None:
        if not self.is_rtsp_enabled or self.rtsp_alias is None:
            return None

        if self._rtsps_url is not None:
            return self._rtsps_url

        host = format_host_for_url(self._get_connection_host())
        self._rtsps_url = f"rtsps://{host}:{self._api.bootstrap.nvr.ports.rtsps}/{self.rtsp_alias}?enableSrtp"
        return self._rtsps_url

    @property
    def rtsps_no_srtp_url(self) -> str | None:
        if not self.is_rtsp_enabled or self.rtsp_alias is None:
            return None

        if self._rtsps_no_srtp_url is not None:
            return self._rtsps_no_srtp_url

        host = format_host_for_url(self._get_connection_host())
        self._rtsps_no_srtp_url = (
            f"rtsps://{host}:{self._api.bootstrap.nvr.ports.rtsps}/{self.rtsp_alias}"
        )
        return self._rtsps_no_srtp_url

    @property
    def rtsps_quality(self) -> ChannelQuality | None:
        """RTSPS quality tier for this channel (id 0→HIGH, 1→MEDIUM, 2→LOW, 3→PACKAGE)."""
        return quality_for_channel_id(self.id)


class ISPSettings(ProtectBaseObject):
    ir_led_mode: IRLEDMode
    wdr: WDRLevel
    brightness: int
    zoom_position: PercentInt
    # requires 2.8.14+
    is_color_night_vision_enabled: bool | None = None
    # 3.0.22+
    hdr_mode: HDRMode | None = None
    icr_custom_value: ICRCustomValue | None = None


class OSDSettings(ProtectBaseObject):
    is_name_enabled: bool
    is_date_enabled: bool
    is_logo_enabled: bool
    is_debug_enabled: bool


class LEDSettings(ProtectBaseObject):
    is_enabled: bool


class SpeakerSettings(ProtectBaseObject):
    is_enabled: bool
    # Status Sounds
    are_system_sounds_enabled: bool
    volume: PercentInt
    # Doorbell ring volume (for doorbells)
    ring_volume: PercentInt | None = None
    ringtone_id: str | None = None
    repeat_times: int | None = None
    # Actual speaker output volume (for cameras with speakers)
    speaker_volume: PercentInt | None = None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(
            data, {"ringVolume", "ringtoneId", "repeatTimes", "speakerVolume"}
        )
        return data


class RecordingSettings(ProtectBaseObject):
    mode: RecordingMode
    enable_motion_detection: bool | None = None


class SmartDetectSettings(ProtectBaseObject):
    object_types: list[SmartDetectObjectType]
    audio_types: list[SmartDetectAudioType] | None = None
    # requires 2.8.22+
    auto_tracking_object_types: list[SmartDetectObjectType] | None = None

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "audioTypes": convert_smart_audio_types,
            "objectTypes": convert_smart_types,
            "autoTrackingObjectTypes": convert_smart_types,
        } | super().unifi_dict_conversions()

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        if audio_types := data.get("audioTypes"):
            # SMOKE_CMONX is not supported for audio types
            # and should not be sent to the camera
            data["audioTypes"] = [
                t for t in audio_types if t != SmartDetectAudioType.SMOKE_CMONX.value
            ]
        return data


class LCDMessage(ProtectBaseObject):
    type: DoorbellMessageType
    # Some doorbell firmwares send lcdMessage with a type but no text; a
    # default keeps model_construct from producing a text-less instance.
    text: str = ""
    reset_at: datetime | None = None

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "resetAt": convert_to_datetime,
        } | super().unifi_dict_conversions()

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "text" in data:
            # UniFi Protect bug: some times LCD messages can get into a bad state where message = DEFAULT MESSAGE, but no type
            if "type" not in data:
                data["type"] = DoorbellMessageType.CUSTOM_MESSAGE.value

            data["text"] = cls._fix_text(data["text"], data["type"])

        return super().unifi_dict_to_dict(data)

    @classmethod
    def _fix_text(cls, text: str, text_type: str | None) -> str:
        if text_type is None:
            text_type = cls.type.value

        if text_type != DoorbellMessageType.CUSTOM_MESSAGE.value:
            text = text_type.replace("_", " ")

        return text

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "text" in data:
            try:
                msg_type = self.type.value
            except AttributeError:
                msg_type = None

            data["text"] = self._fix_text(data["text"], data.get("type", msg_type))
        if "resetAt" in data:
            data["resetAt"] = to_js_time(data["resetAt"])

        return data


class TalkbackSettings(ProtectBaseObject):
    type_fmt: AudioCodecs
    bind_port: int
    channels: int  # 1 or 2
    sampling_rate: int  # 8000, 11025, 22050, 44100, 48000
    bits_per_sample: int
    quality: PercentInt  # only for vorbis


class VideoStats(ProtectBaseObject):
    recording_start: datetime | None = None
    recording_end: datetime | None = None
    recording_start_lq: datetime | None = None
    recording_end_lq: datetime | None = None
    timelapse_start: datetime | None = None
    timelapse_end: datetime | None = None
    timelapse_start_lq: datetime | None = None
    timelapse_end_lq: datetime | None = None

    @property
    def earliest_recording_start(self) -> datetime | None:
        """Earliest recording start across the high- and low-quality tiers."""
        starts = [
            s for s in (self.recording_start, self.recording_start_lq) if s is not None
        ]
        return min(starts, default=None)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "recordingStartLQ": "recordingStartLq",
            "recordingEndLQ": "recordingEndLq",
            "timelapseStartLQ": "timelapseStartLq",
            "timelapseEndLQ": "timelapseEndLq",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return (
            dict.fromkeys(
                (
                    "recordingStart",
                    "recordingEnd",
                    "recordingStartLQ",
                    "recordingEndLQ",
                    "timelapseStart",
                    "timelapseEnd",
                    "timelapseStartLQ",
                    "timelapseEndLQ",
                ),
                convert_to_datetime,
            )
            | super().unifi_dict_conversions()
        )


class StorageStats(ProtectBaseObject):
    used: int | None = None  # bytes
    rate: float | None = None  # bytes / millisecond

    @property
    def rate_per_second(self) -> float | None:
        if self.rate is None:
            return None

        return self.rate * 1000

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "rate" not in data:
            data["rate"] = None

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"rate"})
        return data


class CameraStats(ProtectBaseObject):
    rx_bytes: int | None = None  # deprecated: removed in Protect 6.1+
    tx_bytes: int | None = None  # deprecated: removed in Protect 6.1+
    video: VideoStats
    storage: StorageStats | None = None

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "storage" in data and data["storage"] == {}:
            del data["storage"]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "storage" in data and data["storage"] is None:
            data["storage"] = {}

        return data


class CameraZone(ProtectBaseObject):
    id: int
    name: str
    color: Color
    points: list[tuple[Percent, Percent]]

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "points": lambda x: [(p[0], p[1]) for p in x],
        } | super().unifi_dict_conversions()

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "points" in data:
            data["points"] = [serialize_point(p) for p in data["points"]]

        if "color" in data and isinstance(data["color"], dict):
            # Serialize Color object to hex string to avoid Pydantic serialization warnings
            data["color"] = self.color.as_hex().upper()

        return data

    @staticmethod
    def create_privacy_zone(zone_id: int) -> CameraZone:
        return CameraZone(
            id=zone_id,
            name=PRIVACY_ZONE_NAME,
            color=Color("#85BCEC"),
            points=[[0, 0], [1, 0], [1, 1], [0, 1]],  # type: ignore[list-item]
        )


class MotionZone(CameraZone):
    sensitivity: PercentInt


class SmartMotionZone(MotionZone):
    object_types: list[SmartDetectObjectType]

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "objectTypes": convert_smart_types,
        } | super().unifi_dict_conversions()


class HotplugExtender(ProtectBaseObject):
    is_attached: bool | None = None


class Hotplug(ProtectBaseObject):
    audio: bool | None = None
    video: bool | None = None
    extender: HotplugExtender | None = None


class PTZRange(ProtectBaseObject):
    pass


class PTZZoomRange(PTZRange):
    pass


class CameraFeatureFlags(ProtectBaseObject):
    can_optical_zoom: bool
    has_chime: bool
    has_led_ir: bool
    has_led_status: bool
    has_mic: bool
    has_privacy_mask: bool
    has_speaker: bool
    has_hdr: bool
    video_modes: list[VideoMode]
    has_lcd_screen: bool
    smart_detect_types: list[SmartDetectObjectType]
    has_package_camera: bool
    has_smart_detect: bool
    audio: list[str] = []
    lens_type: LensType | None = None
    hotplug: Hotplug | None = None
    smart_detect_audio_types: list[SmartDetectAudioType] | None = None
    # 2.7.18+
    is_doorbell: bool
    # 2.10.10+
    is_ptz: bool | None = None
    # 4.73.71+
    support_nfc: bool | None = None
    has_fingerprint_sensor: bool | None = None
    # 6.0.0+
    support_full_hd_snapshot: bool | None = None

    pan: PTZRange
    tilt: PTZRange
    zoom: PTZZoomRange

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "smartDetectTypes": convert_smart_types,
            "smartDetectAudioTypes": convert_smart_audio_types,
            "videoModes": convert_video_modes,
        } | super().unifi_dict_conversions()

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        # backport support for `is_doorbell` to older versions of Protect
        if "hasChime" in data and "isDoorbell" not in data:
            data["isDoorbell"] = data["hasChime"]

        return super().unifi_dict_to_dict(data)

    @property
    def has_highfps(self) -> bool:
        return VideoMode.HIGH_FPS in self.video_modes

    @property
    def has_wdr(self) -> bool:
        return not self.has_hdr


class CameraLenses(ProtectBaseObject):
    id: int
    video: VideoStats


@lru_cache
def _chime_type_from_total_seconds(total_seconds: float) -> ChimeType:
    if total_seconds == 0.3:
        return ChimeType.MECHANICAL
    if total_seconds > 0.3:
        return ChimeType.DIGITAL
    return ChimeType.NONE


class Camera(ProtectMotionDeviceModel):
    # Microphone Sensitivity
    mic_volume: PercentInt
    is_mic_enabled: bool
    is_recording: bool
    is_motion_detected: bool
    is_smart_detected: bool
    phy_rate: float | None = None
    hdr_mode: bool
    # Recording Quality -> High Frame
    video_mode: VideoMode
    chime_duration: timedelta
    last_ring: datetime | None = None
    channels: list[CameraChannel]
    isp_settings: ISPSettings
    talkback_settings: TalkbackSettings
    osd_settings: OSDSettings
    led_settings: LEDSettings
    speaker_settings: SpeakerSettings
    recording_settings: RecordingSettings
    smart_detect_settings: SmartDetectSettings
    motion_zones: list[MotionZone]
    privacy_zones: list[CameraZone]
    smart_detect_zones: list[SmartMotionZone]
    stats: CameraStats
    feature_flags: CameraFeatureFlags
    lcd_message: LCDMessage | None = None
    lenses: list[CameraLenses]
    platform: str | None = None
    has_speaker: bool
    voltage: float | None = None
    # requires 2.8.14+
    use_global: bool | None = None
    # requires 2.10.10+
    is_ptz: bool | None = None
    active_patrol_slot: int | None = None
    # requires 5.0.33+
    is_third_party_camera: bool | None = None

    # not directly from UniFi
    last_ring_event_id: str | None = None
    last_nfc_card_scanned_event_id: str | None = None
    last_nfc_card_scanned: datetime | None = None
    last_fingerprint_identified_event_id: str | None = None
    last_fingerprint_identified: datetime | None = None
    last_smart_detect: datetime | None = None
    last_smart_audio_detect: datetime | None = None
    last_smart_detect_event_id: str | None = None
    last_smart_audio_detect_event_id: str | None = None
    last_smart_detects: dict[SmartDetectObjectType, datetime] = {}
    last_smart_audio_detects: dict[SmartDetectAudioType, datetime] = {}
    last_smart_detect_event_ids: dict[SmartDetectObjectType, str] = {}
    last_smart_audio_detect_event_ids: dict[SmartDetectAudioType, str] = {}
    talkback_stream: TalkbackStream | None = None
    _active_smart_detect_events: dict[SmartDetectObjectType, dict[str, Event]] = (
        PrivateAttr(default_factory=dict)
    )

    @classmethod
    @cache
    def _get_excluded_changed_fields(cls) -> set[str]:
        return super()._get_excluded_changed_fields() | {
            "last_ring_event_id",
            "last_nfc_card_scanned",
            "last_nfc_card_scanned_event_id",
            "last_fingerprint_identified",
            "last_fingerprint_identified_event_id",
            "last_smart_detect",
            "last_smart_audio_detect",
            "last_smart_detect_event_id",
            "last_smart_audio_detect_event_id",
            "last_smart_detects",
            "last_smart_audio_detects",
            "last_smart_detect_event_ids",
            "last_smart_audio_detect_event_ids",
            "talkback_stream",
        }

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "stats",
            "isRecording",
            "isMotionDetected",
            "isSmartDetected",
            "phyRate",
            "lastRing",
            "lenses",
            "featureFlags",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "chimeDuration": lambda x: timedelta(milliseconds=x),
        } | super().unifi_dict_conversions()

    @model_validator(mode="after")
    def _set_channel_parents(self) -> Camera:
        """Set parent camera reference in channels after initialization."""
        for channel in getattr(self, "channels", ()):
            channel._parent = self
        return self

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        # LCD messages comes back as empty dict {}
        if "lcdMessage" in data and len(data["lcdMessage"]) == 0:
            del data["lcdMessage"]
        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        if data is not None:
            if "motion_zones" in data:
                data["motion_zones"] = [
                    MotionZone(**z).unifi_dict() for z in data["motion_zones"]
                ]
            if "privacy_zones" in data:
                data["privacy_zones"] = [
                    CameraZone(**z).unifi_dict() for z in data["privacy_zones"]
                ]
            if "smart_detect_zones" in data:
                data["smart_detect_zones"] = [
                    SmartMotionZone(**z).unifi_dict()
                    for z in data["smart_detect_zones"]
                ]

        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_tuple(
            data,
            (
                "lastFingerprintIdentified",
                "lastFingerprintIdentifiedEventId",
                "lastNfcCardScanned",
                "lastNfcCardScannedEventId",
                "lastRingEventId",
                "lastSmartDetect",
                "lastSmartAudioDetect",
                "lastSmartDetectEventId",
                "lastSmartAudioDetectEventId",
                "lastSmartDetects",
                "lastSmartAudioDetects",
                "lastSmartDetectEventIds",
                "lastSmartAudioDetectEventIds",
                "talkbackStream",
            ),
        )
        if "lcdMessage" in data and data["lcdMessage"] is None:
            data["lcdMessage"] = {}

        return data

    def get_changed(self, data_before_changes: dict[str, Any]) -> dict[str, Any]:
        updated = super().get_changed(data_before_changes)

        if "lcd_message" in updated:
            lcd_message = updated["lcd_message"]
            # to "clear" LCD message, set reset_at to a time in the past
            if lcd_message is None:
                updated["lcd_message"] = {"reset_at": utc_now() - timedelta(seconds=10)}
            # otherwise, pass full LCD message to prevent issues
            elif self.lcd_message is not None:
                updated["lcd_message"] = self.lcd_message.model_dump()

            # if reset_at is not passed in, it will default to reset in 1 minute
            if lcd_message is not None and "reset_at" not in lcd_message:
                if self.lcd_message is None:
                    updated["lcd_message"]["reset_at"] = None
                else:
                    updated["lcd_message"]["reset_at"] = self.lcd_message.reset_at

        return updated

    def update_from_dict(self, data: dict[str, Any]) -> Camera:
        # a message in the past is actually a signal to wipe the message
        if (
            reset_at := data.get("lcd_message", {}).get("reset_at")
        ) is not None and utc_now() > from_js_time(reset_at):
            # Important: Make a copy of the data before modifying it
            # since unifi_dict_to_dict will otherwise report incorrect changes
            data = data.copy()
            data["lcd_message"] = None

        return super().update_from_dict(data)

    @property
    def last_ring_event(self) -> Event | None:
        if (last_ring_event_id := self.last_ring_event_id) is None:
            return None
        return self._api.bootstrap.events.get(last_ring_event_id)

    @property
    def last_smart_detect_event(self) -> Event | None:
        """Get the last smart detect event id."""
        if (last_smart_detect_event_id := self.last_smart_detect_event_id) is None:
            return None
        # Check per-camera active index first (immune to bootstrap.events eviction)
        for active in self._active_smart_detect_events.values():
            if event := active.get(last_smart_detect_event_id):
                return event
        return self._api.bootstrap.events.get(last_smart_detect_event_id)

    @property
    def last_nfc_card_scanned_event(self) -> Event | None:
        if (
            last_nfc_card_scanned_event_id := self.last_nfc_card_scanned_event_id
        ) is None:
            return None
        return self._api.bootstrap.events.get(last_nfc_card_scanned_event_id)

    @property
    def last_fingerprint_identified_event(self) -> Event | None:
        if (
            last_fingerprint_identified_event_id
            := self.last_fingerprint_identified_event_id
        ) is None:
            return None
        return self._api.bootstrap.events.get(last_fingerprint_identified_event_id)

    @property
    def hdr_mode_display(self) -> Literal["auto", "off", "always"]:
        """Get HDR mode similar to how Protect interface works."""
        if not self.hdr_mode:
            return "off"
        if self.isp_settings.hdr_mode == HDRMode.NORMAL:
            return "auto"
        return "always"

    @property
    def icr_lux_display(self) -> int | None:
        """Get ICR Custom Lux value similar to how the Protect interface works."""
        if self.isp_settings.icr_custom_value is None:
            return None

        return LUX_MAPPING_VALUES[10 - self.isp_settings.icr_custom_value]

    def get_last_smart_detect_event(
        self,
        smart_type: SmartDetectObjectType,
    ) -> Event | None:
        """Get the last smart detect event for given type."""
        event_id = self.last_smart_detect_event_ids.get(smart_type)
        if not event_id:
            return None
        # Prefer the per-camera active index (immune to bootstrap.events eviction)
        active = self._active_smart_detect_events.get(smart_type)
        if active and (event := active.get(event_id)):
            return event
        return self._api.bootstrap.events.get(event_id)

    @property
    def last_smart_audio_detect_event(self) -> Event | None:
        """Get the last smart audio detect event id."""
        if (
            last_smart_audio_detect_event_id := self.last_smart_audio_detect_event_id
        ) is None:
            return None
        return self._api.bootstrap.events.get(last_smart_audio_detect_event_id)

    def get_last_smart_audio_detect_event(
        self,
        smart_type: SmartDetectAudioType,
    ) -> Event | None:
        """Get the last smart audio detect event for given type."""
        if (event_id := self.last_smart_audio_detect_event_ids.get(smart_type)) is None:
            return None
        return self._api.bootstrap.events.get(event_id)

    @property
    def is_privacy_on(self) -> bool:
        index, _ = self.get_privacy_zone()
        return index is not None

    @property
    def is_recording_enabled(self) -> bool:
        """
        Is recording footage/events from the camera enabled?

        If recording is not enabled, cameras will not produce any footage, thumbnails,
        motion/smart detection events.
        """
        if self.use_global:
            return self._api.bootstrap.nvr.is_global_recording_enabled
        return self.recording_settings.mode is not RecordingMode.NEVER

    @property
    def active_recording_settings(self) -> RecordingSettings:
        """Get active recording settings."""
        if self.use_global and self._api.bootstrap.nvr.global_camera_settings:
            return self._api.bootstrap.nvr.global_camera_settings.recording_settings
        return self.recording_settings

    @property
    def active_smart_detect_settings(self) -> SmartDetectSettings:
        """Get active smart detection settings."""
        if self.use_global and self._api.bootstrap.nvr.global_camera_settings:
            return self._api.bootstrap.nvr.global_camera_settings.smart_detect_settings
        return self.smart_detect_settings

    @property
    def active_smart_detect_types(self) -> set[SmartDetectObjectType]:
        """Get active smart detection types."""
        if self.use_global:
            return set(self.smart_detect_settings.object_types).intersection(
                self.feature_flags.smart_detect_types
            )
        return set(self.smart_detect_settings.object_types)

    @property
    def active_audio_detect_types(self) -> set[SmartDetectAudioType]:
        """Get active audio detection types."""
        if not (enabled_audio_types := self.smart_detect_settings.audio_types):
            return set()
        if self.use_global:
            if not (feature_audio_types := self.feature_flags.smart_detect_audio_types):
                return set()
            return set(feature_audio_types).intersection(enabled_audio_types)
        return set(enabled_audio_types)

    async def set_motion_detection(self, enabled: bool) -> None:
        """Sets motion detection on camera"""
        if self.use_global:
            raise BadRequest("Camera is using global recording settings.")

        def callback() -> None:
            self.recording_settings.enable_motion_detection = enabled

        await self.queue_update(callback)

    def can_detect(self, smart_type: SmartDetectObjectType) -> bool:
        """Whether the camera advertises ``smart_type`` (audio types via ``audio_type``)."""
        if smart_type.audio_type is not None:
            return self._can_detect_audio(smart_type)
        return smart_type in self.feature_flags.smart_detect_types

    def _is_smart_enabled(self, smart_type: SmartDetectObjectType) -> bool:
        return (
            self.is_recording_enabled and smart_type in self.active_smart_detect_types
        )

    @property
    def is_person_detection_on(self) -> bool:
        """
        Is Person Detection available and enabled (camera will produce person smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.PERSON)

    @property
    def is_person_tracking_enabled(self) -> bool:
        """Is person tracking enabled"""
        return (
            self.active_smart_detect_settings.auto_tracking_object_types is not None
            and SmartDetectObjectType.PERSON
            in self.active_smart_detect_settings.auto_tracking_object_types
        )

    @property
    def is_vehicle_detection_on(self) -> bool:
        """
        Is Vehicle Detection available and enabled (camera will produce vehicle smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.VEHICLE)

    @property
    def is_license_plate_detection_on(self) -> bool:
        """
        Is License Plate Detection available and enabled (camera will produce face license
        plate detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.LICENSE_PLATE)

    @property
    def is_package_detection_on(self) -> bool:
        """
        Is Package Detection available and enabled (camera will produce package smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.PACKAGE)

    @property
    def is_animal_detection_on(self) -> bool:
        """
        Is Animal Detection available and enabled (camera will produce package smart
        detection events)?
        """
        return self._is_smart_enabled(SmartDetectObjectType.ANIMAL)

    def _can_detect_audio(self, smart_type: SmartDetectObjectType) -> bool:
        audio_type = smart_type.audio_type
        return (
            audio_type is not None
            and (
                smart_detect_audio_types := self.feature_flags.smart_detect_audio_types
            )
            is not None
            and audio_type in smart_detect_audio_types
        )

    def _is_audio_enabled(self, smart_type: SmartDetectObjectType) -> bool:
        audio_type = smart_type.audio_type
        return (
            audio_type is not None
            and self.is_recording_enabled
            and audio_type in self.active_audio_detect_types
        )

    @property
    def is_smoke_detection_on(self) -> bool:
        """
        Is Smoke Alarm Detection available and enabled (camera will produce smoke
        smart detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.SMOKE)

    @property
    def is_co_detection_on(self) -> bool:
        """
        Is CO Alarm Detection available and enabled (camera will produce smoke smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.CMONX)

    @property
    def is_siren_detection_on(self) -> bool:
        """
        Is Siren Detection available and enabled (camera will produce siren smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.SIREN)

    @property
    def is_baby_cry_detection_on(self) -> bool:
        """
        Is Baby Cry Detection available and enabled (camera will produce baby cry smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.BABY_CRY)

    @property
    def is_speaking_detection_on(self) -> bool:
        """
        Is Speaking Detection available and enabled (camera will produce speaking smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.SPEAK)

    @property
    def is_bark_detection_on(self) -> bool:
        """
        Is Bark Detection available and enabled (camera will produce barking smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.BARK)

    # SmartDetectObjectType.BURGLAR is "Car Alarm" in the Protect UI.
    @property
    def is_car_alarm_detection_on(self) -> bool:
        """
        Is Car Alarm Detection available and enabled (camera will produce car alarm smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.BURGLAR)

    @property
    def is_car_horn_detection_on(self) -> bool:
        """
        Is Car Horn Detection available and enabled (camera will produce car horn smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.CAR_HORN)

    @property
    def is_glass_break_detection_on(self) -> bool:
        """
        Is Glass Break available and enabled (camera will produce glass break smart
        detection events)?
        """
        return self._is_audio_enabled(SmartDetectObjectType.GLASS_BREAK)

    @property
    def chime_type(self) -> ChimeType:
        return _chime_type_from_total_seconds(
            timedelta_total_seconds(self.chime_duration)
        )

    @property
    def chime_duration_seconds(self) -> float:
        return timedelta_total_seconds(self.chime_duration)

    @property
    def is_digital_chime(self) -> bool:
        return self.chime_type is ChimeType.DIGITAL

    @property
    def high_camera_channel(self) -> CameraChannel | None:
        if len(self.channels) >= 3:
            return self.channels[0]
        return None

    @property
    def package_camera_channel(self) -> CameraChannel | None:
        if self.feature_flags.has_package_camera and len(self.channels) == 4:
            return self.channels[3]
        return None

    @property
    def is_high_fps_enabled(self) -> bool:
        return self.video_mode is VideoMode.HIGH_FPS

    @property
    def is_video_ready(self) -> bool:
        return (
            lens_type := self.feature_flags.lens_type
        ) is None or lens_type is not LensType.NONE

    @property
    def has_removable_lens(self) -> bool:
        return (
            hotplug := self.feature_flags.hotplug
        ) is not None and hotplug.video is not None

    @property
    def has_removable_speaker(self) -> bool:
        return (
            hotplug := self.feature_flags.hotplug
        ) is not None and hotplug.audio is not None

    @property
    def has_mic(self) -> bool:
        """Does the camera have a microphone, counting a hot-plugged audio module."""
        return self.feature_flags.has_mic or self.has_removable_speaker

    @property
    def has_color_night_vision(self) -> bool:
        if (
            (hotplug := self.feature_flags.hotplug) is not None
            and (extender := hotplug.extender) is not None
            and (is_attached := extender.is_attached) is not None
        ):
            return is_attached

        return False

    def get_privacy_zone(self) -> tuple[int | None, CameraZone | None]:
        for index, zone in enumerate(self.privacy_zones):
            if zone.name == PRIVACY_ZONE_NAME:
                return index, zone
        return None, None

    def add_privacy_zone(self) -> None:
        index, _ = self.get_privacy_zone()
        if index is None:
            zone_id = 0
            privacy_zones = self.privacy_zones
            if len(privacy_zones) > 0:
                zone_id = privacy_zones[-1].id + 1

            privacy_zones.append(CameraZone.create_privacy_zone(zone_id))

    def remove_privacy_zone(self) -> None:
        index, _ = self.get_privacy_zone()
        if index is not None:
            self.privacy_zones.pop(index)

    async def get_snapshot(
        self,
        width: int | None = None,
        height: int | None = None,
        dt: datetime | None = None,
    ) -> bytes | None:
        """
        Gets snapshot for camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """
        # Use READ_LIVE if dt is None, otherwise READ_MEDIA
        auth_user = self._api.bootstrap.auth_user
        if dt is None:
            if not (
                auth_user.can(ModelType.CAMERA, PermissionNode.READ_LIVE, self)
                or auth_user.can(ModelType.CAMERA, PermissionNode.READ_MEDIA, self)
            ):
                raise NotAuthorized(
                    f"Do not have permission to read live or media for camera: {self.id}"
                )
        elif not auth_user.can(ModelType.CAMERA, PermissionNode.READ_MEDIA, self):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}"
            )

        if height is None and width is None and self.high_camera_channel is not None:
            height = self.high_camera_channel.height

        return await self._api.get_camera_snapshot(self.id, width, height, dt=dt)

    async def get_video(
        self,
        start: datetime,
        end: datetime,
        channel_index: int = 0,
        output_file: Path | None = None,
        iterator_callback: IteratorCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        chunk_size: int = 65536,
        fps: int | None = None,
    ) -> bytes | None:
        """
        Exports MP4 video from a given camera at a specific time.

        Start/End of video export are approximate. It may be +/- a few seconds.

        It is recommended to provide a output file or progress callback for larger
        video clips, otherwise the full video must be downloaded to memory before
        being written.

        Providing the `fps` parameter creates a "timelapse" export with the given FPS
        value. Protect app gives the options for 60x (fps=4), 120x (fps=8), 300x
        (fps=20), and 600x (fps=40).
        """
        if not self._api.bootstrap.auth_user.can(
            ModelType.CAMERA,
            PermissionNode.READ_MEDIA,
            self,
        ):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}",
            )

        return await self._api.get_camera_video(
            self.id,
            start,
            end,
            channel_index,
            output_file=output_file,
            iterator_callback=iterator_callback,
            progress_callback=progress_callback,
            chunk_size=chunk_size,
            fps=fps,
        )

    async def set_recording_mode(self, mode: RecordingMode) -> None:
        """Sets recording mode on camera"""
        if self.use_global:
            raise BadRequest("Camera is using global recording settings.")

        def callback() -> None:
            self.recording_settings.mode = mode

        await self.queue_update(callback)

    async def set_ir_led_model(self, mode: IRLEDMode) -> None:
        """Sets IR LED mode on camera"""
        if not self.feature_flags.has_led_ir:
            raise BadRequest("Camera does not have an LED IR")

        def callback() -> None:
            self.isp_settings.ir_led_mode = mode

        await self.queue_update(callback)

    async def set_icr_custom_lux(self, value: ICRLuxValue) -> None:
        """Set ICRCustomValue from lux value."""
        if not self.feature_flags.has_led_ir:
            raise BadRequest("Camera does not have an LED IR")

        icr_value = 0
        for index, threshold in enumerate(LUX_MAPPING_VALUES):
            if value >= threshold:
                icr_value = 10 - index
                break

        def callback() -> None:
            self.isp_settings.icr_custom_value = cast("ICRCustomValue", icr_value)

        await self.queue_update(callback)

    @property
    def is_ir_led_slider_enabled(self) -> bool:
        """Return if IR LED custom slider is enabled."""
        return (
            self.feature_flags.has_led_ir
            and self.isp_settings.ir_led_mode in _ICR_LUX_IR_LED_MODES
        )

    async def set_color_night_vision(self, enabled: bool) -> None:
        """Sets Color Night Vision on camera"""
        if not self.has_color_night_vision:
            raise BadRequest("Camera does not have Color Night Vision")

        def callback() -> None:
            self.isp_settings.is_color_night_vision_enabled = enabled

        await self.queue_update(callback)

    async def set_camera_zoom(self, level: int) -> None:
        """Sets zoom level for camera"""
        if not self.feature_flags.can_optical_zoom:
            raise BadRequest("Camera cannot optical zoom")

        def callback() -> None:
            self.isp_settings.zoom_position = PercentInt(level)

        await self.queue_update(callback)

    async def set_wdr_level(self, level: int) -> None:
        """Sets WDR (Wide Dynamic Range) on camera"""
        if self.feature_flags.has_hdr:
            raise BadRequest("Cannot set WDR on cameras with HDR")

        def callback() -> None:
            self.isp_settings.wdr = WDRLevel(level)

        await self.queue_update(callback)

    async def set_speaker_volume(self, level: int) -> None:
        """Sets the speaker output volume on camera. Requires camera to have speakers"""
        if not self.feature_flags.has_speaker:
            raise BadRequest("Camera does not have speaker")

        def callback() -> None:
            self.speaker_settings.speaker_volume = PercentInt(level)

        await self.queue_update(callback)

    async def set_volume(self, level: int) -> None:
        """Sets the general volume level on camera. Requires camera to have speakers"""
        if not self.feature_flags.has_speaker:
            raise BadRequest("Camera does not have speaker")

        def callback() -> None:
            self.speaker_settings.volume = PercentInt(level)

        await self.queue_update(callback)

    async def set_ring_volume(self, level: int) -> None:
        """Sets the doorbell ring volume. Requires camera to be a doorbell"""
        if not self.feature_flags.is_doorbell:
            raise BadRequest("Camera is not a doorbell")

        def callback() -> None:
            self.speaker_settings.ring_volume = PercentInt(level)

        await self.queue_update(callback)

    async def set_chime_type(self, chime_type: ChimeType) -> None:
        """Sets chime type for doorbell. Requires camera to be a doorbell"""
        await self.set_chime_duration(timedelta(milliseconds=chime_type.value))

    async def set_chime_duration(self, duration: timedelta | float) -> None:
        """Sets chime duration for doorbell. Requires camera to be a doorbell"""
        if not self.feature_flags.has_chime:
            raise BadRequest("Camera does not have a chime")

        if isinstance(duration, (float, int)):
            if duration < 0:
                raise BadRequest("Chime duration must be a positive number of seconds")
            duration_td = timedelta(seconds=duration)
        else:
            duration_td = duration

        if duration_td.total_seconds() > 10:
            raise BadRequest("Chime duration is too long")

        def callback() -> None:
            self.chime_duration = duration_td

        await self.queue_update(callback)

    async def set_system_sounds(self, enabled: bool) -> None:
        """Sets system sound playback through speakers. Requires camera to have speakers"""
        if not self.feature_flags.has_speaker:
            raise BadRequest("Camera does not have speaker")

        def callback() -> None:
            self.speaker_settings.are_system_sounds_enabled = enabled

        await self.queue_update(callback)

    async def set_privacy(
        self,
        enabled: bool,
        mic_level: int | None = None,
        recording_mode: RecordingMode | None = None,
        reenable_global: bool = False,
    ) -> None:
        """Adds/removes a privacy zone that blacks out the whole camera."""
        if not self.feature_flags.has_privacy_mask:
            raise BadRequest("Camera does not allow privacy zones")

        def callback() -> None:
            if enabled:
                self.use_global = False
                self.add_privacy_zone()
            else:
                if reenable_global:
                    self.use_global = True
                self.remove_privacy_zone()

            if not reenable_global:
                if mic_level is not None:
                    self.mic_volume = PercentInt(mic_level)

                if recording_mode is not None:
                    self.recording_settings.mode = recording_mode

        await self.queue_update(callback)

    async def set_person_track(self, enabled: bool) -> None:
        """Sets person tracking on camera"""
        if not self.feature_flags.is_ptz:
            raise BadRequest("Camera does not support person tracking")

        if self.use_global:
            raise BadRequest("Camera is using global recording settings.")

        def callback() -> None:
            self.smart_detect_settings.auto_tracking_object_types = (
                [SmartDetectObjectType.PERSON] if enabled else []
            )

        await self.queue_update(callback)

    async def create_talkback_stream(
        self,
        content_url: str,
        ffmpeg_path: Path | None = None,  # Deprecated: no longer used
        *,
        use_public_api: bool = True,
    ) -> TalkbackStream:
        """
        Creates a stream to play audio to a camera through its speaker.

        Uses PyAV (libav) for audio encoding - compatible with Home Assistant.

        Args:
        ----
            content_url: Either a URL accessible by python or a path to a file
            ffmpeg_path: Deprecated, no longer used (PyAV handles encoding)
            use_public_api: Use the public API to get talkback session (default: True)

        Use either `await stream.run_until_complete()` or `await stream.start()` to start streaming
        after getting the stream.

        `.play_audio()` is a helper that wraps this method and automatically runs the stream as well

        """
        if ffmpeg_path is not None:
            _LOGGER.warning(
                "ffmpeg_path is deprecated and ignored, PyAV is used instead"
            )
        if self.talkback_stream is not None and self.talkback_stream.is_running:
            raise BadRequest("Camera is already playing audio")

        session: TalkbackSession | None = None
        if use_public_api:
            if self._api._api_key is None:
                raise NotAuthorized(
                    "Cannot create talkback session without an API key."
                )
            session = await self._api.create_talkback_session_public(self.id)

        self.talkback_stream = TalkbackStream(self, content_url, session)
        return self.talkback_stream

    async def play_audio(
        self,
        content_url: str,
        ffmpeg_path: Path | None = None,  # Deprecated: no longer used
        blocking: bool = True,
        *,
        use_public_api: bool = True,
    ) -> None:
        """
        Plays audio to a camera through its speaker.

        Uses PyAV (libav) for audio encoding - compatible with Home Assistant.

        Args:
        ----
            content_url: Either a URL accessible by python or a path to a file
            ffmpeg_path: Deprecated, no longer used (PyAV handles encoding)
            blocking: Awaits stream completion
            use_public_api: Use the public API to get talkback session (default: True)

        """
        stream = await self.create_talkback_stream(
            content_url, ffmpeg_path, use_public_api=use_public_api
        )
        await stream.start()

        if blocking:
            await self.wait_until_audio_completes()

    async def wait_until_audio_completes(self) -> None:
        """Awaits stream completion of audio."""
        stream = self.talkback_stream
        if stream is None:
            raise StreamError("No audio playing to wait for")

        await stream.run_until_complete()

    async def stop_audio(self) -> None:
        """Stop currently playing audio."""
        if (stream := self.talkback_stream) is None:
            raise StreamError("No audio playing to stop")
        await stream.stop()

    def can_read_media(self, user: User) -> bool:
        if self.model is None:
            return True
        return user.can(self.model, PermissionNode.READ_MEDIA, self)

    async def get_ptz_presets(self) -> list[PTZPreset]:
        """Get PTZ Presets for camera."""
        if not self.feature_flags.is_ptz:
            raise BadRequest("Camera does not support PTZ features.")

        return await self._api.get_presets_ptz_camera(self.id)

    async def get_ptz_patrols(self) -> list[PTZPatrol]:
        """Get PTZ Patrols for camera."""
        if not self.feature_flags.is_ptz:
            raise BadRequest("Camera does not support PTZ features.")

        return await self._api.get_patrols_ptz_camera(self.id)

    def _check_ptz_public_api(self) -> None:
        """Check prerequisites for PTZ public API calls."""
        if not self.feature_flags.is_ptz:
            raise BadRequest("Camera does not support PTZ features.")

    async def ptz_goto_preset_public(self, *, slot: int) -> None:
        """Move PTZ camera to preset position using public API."""
        self._check_ptz_public_api()
        await self._api.ptz_goto_preset_public(self.id, slot=slot)

    async def ptz_patrol_start_public(self, *, slot: int) -> None:
        """Start a PTZ patrol using public API."""
        self._check_ptz_public_api()
        await self._api.ptz_patrol_start_public(self.id, slot=slot)

    async def ptz_patrol_stop_public(self) -> None:
        """Stop the active PTZ patrol using public API."""
        self._check_ptz_public_api()
        await self._api.ptz_patrol_stop_public(self.id)

    async def set_hdr_mode_public(self, mode: PublicHdrMode) -> None:
        """Set HDR mode via public API."""
        if not self.feature_flags.has_hdr:
            raise BadRequest("Camera does not have HDR")
        await self._api.update_camera_public(self.id, hdr_type=mode)
        # The public API response uses 'hdrType', not 'hdrMode'/'ispSettings',
        # so we derive the local state update directly from the mode we sent.
        hdr_on = mode != PublicHdrMode.OFF
        if hasattr(self, "hdr_mode"):
            self.hdr_mode = hdr_on
        isp = getattr(self, "isp_settings", None)
        if isp is not None:
            isp_hdr = getattr(isp, "hdr_mode", None)
            if isp_hdr is not None:
                isp.hdr_mode = (
                    HDRMode.ALWAYS_ON if mode == PublicHdrMode.ON else HDRMode.NORMAL
                )

    async def set_lcd_message_public(
        self,
        text_type: DoorbellMessageType | None,
        text: str | None = None,
        reset_at: datetime | DEFAULT_TYPE | None = DEFAULT,
    ) -> None:
        """
        Set doorbell LCD message via public API.

        Pass ``None`` for ``text_type`` to clear the message, with ``text`` and
        ``reset_at`` omitted.  ``text`` is required for CUSTOM_MESSAGE and
        IMAGE, and must be omitted for DO_NOT_DISTURB and
        LEAVE_PACKAGE_AT_DOOR.  ``reset_at`` controls when the message is
        cleared: omit for the NVR default, pass ``None`` for "forever", or pass
        a specific datetime.
        """
        if not self.feature_flags.has_lcd_screen:
            raise BadRequest("Camera does not have an LCD screen")
        message = _build_public_lcd_message(text_type, text, reset_at)
        updated = await self._api.update_camera_public(self.id, lcd_message=message)
        if text_type is None:
            # The response is not read back: the console only runs its sweep for
            # a provisioned, connected camera, so an offline one echoes the
            # request straight back and would rebuild the message just cleared.
            # The faked frame below only reaches an instance the bootstrap owns,
            # so set the local state here.
            self.lcd_message = None
            # UniFi Protect bug: clearing the LCD message does _not_ emit a WS
            # message, so fake one. A reset time in the past is how the console
            # signals a wiped message.
            reset = to_js_time(utc_now() - timedelta(seconds=10))
            await self.emit_message({"lcdMessage": {"resetAt": reset}})
            return
        pub = updated.lcd_message
        # The public response carries a ``PublicLcdMessage``; rebuild the private
        # ``LCDMessage`` from it (``None`` when the message was cleared).
        self.lcd_message = (
            None
            if pub is None or pub.type is None
            else LCDMessage.from_unifi_dict(
                type=pub.type,
                text=pub.text or "",
                resetAt=pub.reset_at,
                api=self._api,
            )
        )


class Viewer(ProtectAdoptableDeviceModel):
    liveview_id: str

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "liveview": "liveviewId"}

    @property
    def liveview(self) -> Liveview | None:
        # user may not have permission to see the liveview
        return self._api.bootstrap.liveviews.get(self.liveview_id)

    async def set_liveview(self, liveview: Liveview) -> None:
        """
        Set the liveview for this viewer.

        .. deprecated::
            Use :meth:`ProtectApiClient.update_viewer_public` instead; the
            public-API counterpart is feature-complete for renaming and
            liveview assignment.
        """
        warnings.warn(
            "Viewer.set_liveview is deprecated; use "
            "ProtectApiClient.update_viewer_public(viewer_id, liveview=...) "
            "instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if self._api is not None and liveview.id not in self._api.bootstrap.liveviews:
            raise BadRequest("Unknown liveview")

        async with self._update_sync.lock:
            # yield to the event loop once we have the lock to process any pending updates
            await asyncio.sleep(0)
            data_before_changes = self.dict_with_excludes()
            self.liveview_id = liveview.id
            # UniFi Protect bug: changing the liveview does _not_ emit a WS message
            await self.save_device(data_before_changes, force_emit=True)


class Bridge(ProtectAdoptableDeviceModel):
    platform: str


class SensorSettingsBase(ProtectBaseObject):
    is_enabled: bool


class SensorThresholdSettings(SensorSettingsBase):
    margin: float  # read only
    # "safe" thresholds for alerting
    # anything below/above will trigger alert
    low_threshold: float | None = None
    high_threshold: float | None = None


class SensorSensitivitySettings(SensorSettingsBase):
    sensitivity: PercentInt
    # Armed-mode sensitivity override. Absent on older firmware / not carried by
    # every console, so it is optional and dropped from the wire dict when unset.
    sensitivity_when_armed: PercentInt | None = None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"sensitivityWhenArmed"})
        return data


class SensorBatteryStatus(ProtectBaseObject):
    percentage: PercentInt | None = None
    is_low: bool


class SensorStat(ProtectBaseObject):
    value: float | None = None
    status: SensorStatusType


class SensorStats(ProtectBaseObject):
    light: SensorStat
    humidity: SensorStat
    temperature: SensorStat


class Sensor(ProtectAdoptableDeviceModel):
    alarm_settings: SensorSettingsBase
    alarm_triggered_at: datetime | None = None
    battery_status: SensorBatteryStatus
    camera_id: str | None = None
    humidity_settings: SensorThresholdSettings
    is_motion_detected: bool
    is_opened: bool
    leak_detected_at: datetime | None = None
    led_settings: LEDSettings
    light_settings: SensorThresholdSettings
    motion_detected_at: datetime | None = None
    motion_settings: SensorSensitivitySettings
    open_status_changed_at: datetime | None = None
    stats: SensorStats
    tampering_detected_at: datetime | None = None
    temperature_settings: SensorThresholdSettings
    mount_type: MountType

    # not directly from UniFi
    last_motion_event_id: str | None = None
    last_contact_event_id: str | None = None
    last_value_event_id: str | None = None
    last_alarm_event_id: str | None = None
    extreme_value_detected_at: datetime | None = None
    _tamper_timeout: datetime | None = PrivateAttr(None)
    _alarm_timeout: datetime | None = PrivateAttr(None)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "batteryStatus",
            "isMotionDetected",
            "leakDetectedAt",
            "tamperingDetectedAt",
            "isOpened",
            "openStatusChangedAt",
            "alarmTriggeredAt",
            "motionDetectedAt",
            "stats",
        }

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_tuple(
            data,
            (
                "lastMotionEventId",
                "lastContactEventId",
                "lastValueEventId",
                "lastAlarmEventId",
                "extremeValueDetectedAt",
            ),
        )
        return data

    @property
    def camera(self) -> Camera | None:
        """Paired Camera will always be none if no camera is paired"""
        if (camera_id := self.camera_id) is None:
            return None
        return self._api.bootstrap.cameras[camera_id]

    @property
    def is_tampering_detected(self) -> bool:
        return self.tampering_detected_at is not None

    @property
    def is_alarm_detected(self) -> bool:
        if self._alarm_timeout is None:
            return False
        return utc_now() < self._alarm_timeout

    @property
    def is_alarm_sensor_enabled(self) -> bool:
        return self.mount_type is not MountType.LEAK and self.alarm_settings.is_enabled

    def set_alarm_timeout(self) -> None:
        self._alarm_timeout = utc_now() + EVENT_PING_INTERVAL
        self._event_callback_ping()

    @property
    def last_alarm_event(self) -> Event | None:
        if (last_alarm_event_id := self.last_alarm_event_id) is None:
            return None
        return self._api.bootstrap.events.get(last_alarm_event_id)

    @property
    def is_leak_detected(self) -> bool:
        return self.leak_detected_at is not None

    async def set_status_light(self, enabled: bool) -> None:
        """Sets the status indicator light for the sensor"""

        def callback() -> None:
            self.led_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_mount_type(self, mount_type: MountType) -> None:
        """Sets current mount type for sensor"""

        def callback() -> None:
            self.mount_type = mount_type

        await self.queue_update(callback)

    async def set_paired_camera(self, camera: Camera | None) -> None:
        """Sets the camera paired with the sensor"""

        def callback() -> None:
            if camera is None:
                self.camera_id = None
            else:
                self.camera_id = camera.id

        await self.queue_update(callback)

    async def clear_tamper(self) -> None:
        """Clears tamper status for sensor"""
        if not self._api.bootstrap.auth_user.can(
            ModelType.SENSOR,
            PermissionNode.WRITE,
            self,
        ):
            raise NotAuthorized(
                f"Do not have permission to clear tamper for sensor: {self.id}",
            )
        await self._api.clear_tamper_sensor(self.id)


class ChimeFeatureFlags(ProtectBaseObject):
    pass


class RingSetting(ProtectBaseObject):
    """Ring settings for a paired doorbell camera."""

    camera_id: str
    repeat_times: RepeatTimes
    ringtone_id: str | None = None
    track_no: int | None = None  # deprecated: use ringtone_id
    volume: int

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    def to_api_dict(
        self, volume: int | None = None, repeat_times: int | None = None
    ) -> PublicApiChimeRingSettingRequest:
        """
        Convert to API dict format for Public API requests.

        Args:
        ----
            volume: Override volume value. If None, uses current volume.
            repeat_times: Override repeat-times value. If None, uses current
                repeat_times.

        Returns:
        -------
            Dict with cameraId, volume, repeatTimes, and ringtoneId keys.

        Raises:
        ------
            ChimeRingtoneNotSetError: If no ringtone is set for this camera.

        """
        if not self.ringtone_id:
            raise ChimeRingtoneNotSetError(self.camera_id)
        return {
            "cameraId": self.camera_id,
            "ringtoneId": self.ringtone_id,
            "volume": volume if volume is not None else self.volume,
            "repeatTimes": repeat_times
            if repeat_times is not None
            else self.repeat_times,
        }

    @property
    def camera(self) -> Camera | None:
        """Paired Camera will always be none if no camera is paired."""
        if self.camera_id is None:
            return None  # type: ignore[unreachable]

        return self._api.bootstrap.cameras[self.camera_id]


class Chime(ProtectAdoptableDeviceModel):
    volume: PercentInt
    last_ring: datetime | None = None
    camera_ids: list[str]
    # requires 2.7.15+
    feature_flags: ChimeFeatureFlags | None = None
    # requires 3.0.22+
    platform: str | None = None
    repeat_times: RepeatTimes | None = None
    ring_settings: list[RingSetting] = []

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {"lastRing"}

    @property
    def cameras(self) -> list[Camera]:
        """Paired Cameras for chime"""
        if len(self.camera_ids) == 0:
            return []
        return [self._api.bootstrap.cameras[c] for c in self.camera_ids]

    async def play(
        self,
        *,
        volume: int | None = None,
        repeat_times: int | None = None,
        ringtone_id: str | None = None,
        track_no: int | None = None,
    ) -> None:
        """
        Plays chime tone.

        Args:
        ----
            volume: Volume level for playback (0-100). Uses chime's current volume if None.
            repeat_times: Number of times to repeat the tone.
            ringtone_id: The ringtone ID (UUID) to play. If None, uses default tone.
            track_no: Legacy track number from speakerTrackList.
                .. deprecated::
                    Use ringtone_id instead.

        """
        if track_no is not None:
            warnings.warn(
                "track_no is deprecated, use ringtone_id instead",
                DeprecationWarning,
                stacklevel=2,
            )
        await self._api.play_speaker(
            self.id,
            volume=volume,
            repeat_times=repeat_times,
            ringtone_id=ringtone_id,
            track_no=track_no,
        )

    async def play_buzzer(self) -> None:
        """Plays chime buzzer"""
        await self._api.play_buzzer(self.id)

    async def set_ring_settings_public(
        self,
        ring_settings: list[PublicApiChimeRingSettingRequest],
    ) -> None:
        """
        Update ring settings using public API.

        This is the preferred method to change ring volume per camera as it uses
        the official public API.

        Args:
        ----
            ring_settings: List of ring settings per camera. Each dict should contain:
                - cameraId: The camera ID this setting applies to
                - volume: Ring volume (0-100)
                - repeatTimes: How many times to repeat (1-10)
                - ringtoneId: The ringtone ID to use; Protect rejects entries
                  without one

        Raises:
        ------
            ChimeRingtoneNotSetError: If an entry has no ``ringtoneId``.

        Example:
        -------
            >>> await chime.set_ring_settings_public([
            ...     {
            ...         "cameraId": "camera123",
            ...         "volume": 80,
            ...         "repeatTimes": 2,
            ...         "ringtoneId": "ringtone456"
            ...     }
            ... ])

        """
        updated = await self._api.update_chime_public(
            self.id,
            ring_settings=ring_settings,
        )
        self._api._write_through_public_twin(updated)
        # The public response carries ``PublicRingSettings`` (every field typed
        # optional); rebuild the strict private ``RingSetting`` list from it,
        # skipping entries the wire left incomplete so a partial response can't
        # raise ``ValidationError`` (``RingSetting`` requires camera_id /
        # repeat_times / volume).
        self.ring_settings = [
            RingSetting.from_unifi_dict(**rs.unifi_dict(), api=self._api)
            for rs in updated.ring_settings
            if rs.camera_id is not None
            and rs.repeat_times is not None
            and rs.volume is not None
        ]

    async def set_volume_for_camera_public(
        self,
        camera: Camera,
        level: int,
    ) -> None:
        """
        Set the ring volume for a specific camera using public API.

        This is the preferred method to change ring volume as it uses
        the official public API and properly updates the doorbell ring volume.

        Args:
        ----
            camera: The doorbell camera to set volume for
            level: Volume level (0-100)

        Raises:
        ------
            BadRequest: If the camera is not paired with this chime
            ValidationError: If level is not in range 0-100

        """
        # Validate level using PercentInt (raises ValidationError if invalid)
        PercentInt(level)

        # Hold the lock across the whole read-modify-write: two concurrent
        # callers must not each read the pre-mutation list and clobber each
        # other's change (last PATCH wins).
        async with self._update_sync.lock:
            # Find the current ring setting for this camera
            ring_setting = None
            for setting in self.ring_settings:
                if setting.camera_id == camera.id:
                    ring_setting = setting
                    break

            if ring_setting is None:
                raise BadRequest(f"Camera {camera.id} is not paired with chime")

            # Build the update payload preserving original order
            ring_settings_update: list[PublicApiChimeRingSettingRequest] = [
                setting.to_api_dict(volume=level)
                if setting.camera_id == camera.id
                else setting.to_api_dict()
                for setting in self.ring_settings
            ]

            await self.set_ring_settings_public(ring_settings_update)
