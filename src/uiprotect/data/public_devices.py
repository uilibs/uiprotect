"""
UniFi Protect Public API (Integration) data models.

These models represent resources that are exposed only through the Public
Integration API. They live in a separate module so
that the existing private-API data models (in :mod:`uiprotect.data.devices`)
are not affected and older Protect installations remain unaffected.

Fields the NVR is contractually required to return are modelled as required;
only fields that are genuinely optional on the wire (bridge link, battery
status on mains-powered devices, siren activation metadata while idle, ...)
are ``Optional``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypedDict

from pydantic import Field
from pydantic.fields import PrivateAttr

from ..exceptions import BadRequest
from ..utils import (
    convert_smart_audio_types,
    convert_smart_types,
    convert_to_datetime,
    convert_video_modes,
    to_js_time,
)
from .base import ProtectBaseObject, ProtectModelWithId
from .types import (
    DEFAULT,
    DEFAULT_TYPE,
    AlarmHubBatteryStatus,
    AlarmHubConnectionState,
    AlarmHubCoverStatus,
    AlarmHubInputContactType,
    AlarmHubInputStatus,
    AlarmHubInputType,
    AlarmHubOutputStatus,
    AssetFileType,
    ChannelQuality,
    DeviceState,
    DoorbellMessageType,
    EventType,
    FobAwayState,
    FobButton,
    LightModeEnableType,
    LightModeType,
    LiveviewCycleMode,
    ModelType,
    MountType,
    NvrArmModeStatus,
    OnOffState,
    OsdOverlayLocation,
    PublicHdrMode,
    RelayInputActionTrigger,
    RelayInputActionType,
    RelayInputState,
    RelayOutputRebootState,
    RelayOutputState,
    RelayOutputType,
    SensorScheduleMode,
    SensorStatusType,
    SirenConnectionType,
    SirenDuration,
    SmartDetectAudioType,
    SmartDetectObjectType,
    SpeakerMode,
    SpeakerStatus,
    UlpUserStatus,
    VideoMode,
)

if TYPE_CHECKING:
    from ..api import CameraPublicApiLcdMessageRequest, PublicApiChimeRingSettingRequest
    from .public_event import PublicEvent

# Public Integration API numeric bounds, taken from the OpenAPI spec. The
# public schema is the source of truth for these and they differ from the
# private/UI limits (e.g. ``PercentInt`` allows 101). The sensor
# ``highThreshold`` fields are spec-unbounded, so they are not range-checked.
_PUBLIC_SENSITIVITY_RANGE: tuple[float, float] = (0, 100)
_PUBLIC_LED_LEVEL_RANGE: tuple[float, float] = (1, 6)
_PUBLIC_MIC_VOLUME_RANGE: tuple[float, float] = (1, 100)
_PUBLIC_TEMPERATURE_LOW_RANGE: tuple[float, float] = (-39, 124)
_PUBLIC_HUMIDITY_LOW_RANGE: tuple[float, float] = (1, 99)
_PUBLIC_LIGHT_LUX_LOW_RANGE: tuple[float, float] = (1, 503192)
_PUBLIC_RING_VOLUME_RANGE: tuple[float, float] = (0, 100)
_PUBLIC_RING_REPEAT_RANGE: tuple[float, float] = (1, 6)


def _validate_public_range(
    name: str,
    value: float,
    bounds: tuple[float, float],
) -> None:
    """Range-check a public-API number against the spec bounds."""
    if not math.isfinite(value):
        raise BadRequest(f"{name} must be a finite number, got {value}")
    minimum, maximum = bounds
    if value < minimum or value > maximum:
        raise BadRequest(f"{name} must be between {minimum} and {maximum}, got {value}")


def _coerce_public_int(
    name: str,
    value: float,
    bounds: tuple[float, float],
) -> int:
    """Validate a public-API number against the spec bounds and coerce it to ``int``."""
    _validate_public_range(name, value, bounds)
    return int(value)


# Doorbell LCD message types that require accompanying ``text``; the rest must
# omit it.
_LCD_TYPES_REQUIRING_TEXT: frozenset[DoorbellMessageType] = frozenset(
    {DoorbellMessageType.CUSTOM_MESSAGE, DoorbellMessageType.IMAGE}
)


# Smart-detect object events. Protect 7.x emits overlapping ``smartDetectZone``
# and ``smartDetectLine`` frames for the same detection, so both drive the smart
# flags — mirroring the private ``Camera`` model (see ``CAMERA_EVENT_ATTR_MAP``
# in ``bootstrap.py``, which maps both to the same ``last_smart_detect`` state).
_SMART_DETECT_EVENT_TYPES = frozenset(
    {EventType.SMART_DETECT, EventType.SMART_DETECT_LINE}
)
_MOTION_EVENT_TYPES = frozenset({EventType.MOTION})
_SMART_AUDIO_EVENT_TYPES = frozenset({EventType.SMART_AUDIO_DETECT})

# Public events-WS event types that drive the derived detection-state booleans
# on :class:`PublicCamera`. Other event types are ignored by that machinery.
_DETECTION_EVENT_TYPES = (
    _MOTION_EVENT_TYPES | _SMART_AUDIO_EVENT_TYPES | _SMART_DETECT_EVENT_TYPES
)

# Derived detection-state boolean property names on :class:`PublicCamera`. A
# transition in any of these (after an events-WS frame is folded into the active
# set) is surfaced as a synthetic devices-WS update — see
# :meth:`PublicCamera._detection_state` and the events-WS handler.
_DETECTION_STATE_FIELDS = (
    "is_motion_detected",
    "is_smart_currently_detected",
    "is_person_currently_detected",
    "is_vehicle_currently_detected",
    "is_animal_currently_detected",
    "is_audio_currently_detected",
    "is_smoke_currently_detected",
    "is_cmonx_currently_detected",
    "is_siren_currently_detected",
    "is_baby_cry_currently_detected",
    "is_speaking_currently_detected",
    "is_bark_currently_detected",
    "is_car_alarm_currently_detected",
    "is_car_horn_currently_detected",
    "is_glass_break_currently_detected",
)


class PublicArmScheduleDict(TypedDict):
    """Arm-profile schedule entry (write shape). Fields are cron expressions."""

    start: str
    end: str


class PublicSensorLightSettings(TypedDict, total=False):
    isEnabled: bool
    lowThreshold: float
    highThreshold: float
    margin: int


class PublicSensorHumiditySettings(TypedDict, total=False):
    isEnabled: bool
    lowThreshold: float
    highThreshold: float
    margin: int


class PublicSensorTemperatureSettings(TypedDict, total=False):
    isEnabled: bool
    lowThreshold: float
    highThreshold: float
    margin: float


class PublicSensorMotionSettings(TypedDict, total=False):
    isEnabled: bool
    sensitivity: int
    sensitivityWhenArmed: int


class PublicSensorGlassBreakSettingsWrite(TypedDict, total=False):
    # Write shape for ``glassBreakSettings``; the read model is
    # ``PublicSensorGlassBreakSettings``.
    isEnabled: bool
    sensitivity: int
    sensitivityWhenArmed: int


class PublicSensorAlarmSettings(TypedDict, total=False):
    isEnabled: bool


class PublicLiveviewSlotDict(TypedDict):
    """Liveview slot (write shape)."""

    cameras: list[str]
    cycleMode: LiveviewCycleMode
    cycleInterval: int


class PublicSignalState(ProtectBaseObject):
    # Nullable on the wire: a freshly-paired wireless device (e.g. a key fob)
    # has not yet reported its Bluetooth signal.
    signal_quality: int | None = None
    signal_strength: int | None = None


class PublicWirelessBatteryStatus(ProtectBaseObject):
    # Nullable on the wire until the device first reports its battery level.
    percentage: int | None = None
    is_low: bool


class PublicWirelessConnectionState(ProtectBaseObject):
    # ``signal_state`` is only present while the device is online; battery
    # status is absent on mains-powered devices; bridge may be unset.
    signal_state: PublicSignalState | None = None
    battery_status: PublicWirelessBatteryStatus | None = None
    bridge: str | None = None


class PublicLedSettings(ProtectBaseObject):
    is_enabled: bool


# Sub-object internals are not ``required`` in the spec, so every leaf field
# carries a default; that keeps partial WS update diffs (which omit unchanged
# nested keys) parseable without strict-validation failures.


class PublicOsdSettings(ProtectBaseObject):
    is_name_enabled: bool = False
    is_date_enabled: bool = False
    is_logo_enabled: bool = False
    is_debug_enabled: bool = False
    overlay_location: OsdOverlayLocation | None = None


class PublicCameraLedSettings(ProtectBaseObject):
    # Distinct from the single-field :class:`PublicLedSettings` used by
    # siren/relay. ``welcome_led`` / ``flood_led`` are ``None`` on cameras
    # without a doorbell/floodlight.
    is_enabled: bool = False
    welcome_led: bool | None = None
    flood_led: bool | None = None


class PublicLcdMessage(ProtectBaseObject):
    # Spec marks ``type``/``text`` required, but the PATCH endpoint accepts
    # (and a cleared message returns) ``{}`` — so every field is optional.
    type: DoorbellMessageType | None = None
    reset_at: int | None = None
    text: str | None = None


class PublicCameraFeatureFlags(ProtectBaseObject):
    support_full_hd_snapshot: bool = False
    has_hdr: bool = False
    smart_detect_types: list[SmartDetectObjectType] = Field(default_factory=list)
    smart_detect_audio_types: list[SmartDetectAudioType] = Field(default_factory=list)
    video_modes: list[VideoMode] = Field(default_factory=list)
    has_mic: bool = False
    has_led_status: bool = False
    has_speaker: bool = False

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "smartDetectTypes": convert_smart_types,
            "smartDetectAudioTypes": convert_smart_audio_types,
            "videoModes": convert_video_modes,
        } | super().unifi_dict_conversions()


class PublicSmartDetectSettings(ProtectBaseObject):
    object_types: list[SmartDetectObjectType] = Field(default_factory=list)
    audio_types: list[SmartDetectAudioType] = Field(default_factory=list)

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "objectTypes": convert_smart_types,
            "audioTypes": convert_smart_audio_types,
        } | super().unifi_dict_conversions()


class RTSPSStreams(ProtectBaseObject):
    """RTSPS stream URLs for a camera."""

    model_config = {"extra": "allow"}
    # Intentionally no variables like 'high', 'medium', 'low' are defined here.
    # The API naming appears inconsistent - what's called "quality" might actually be "channels".
    # Besides standard qualities (high/medium/low), there are special cases like "package" for doorbells
    # and unclear implementation for 180° cameras with dual sensors. Dynamic handling via __pydantic_extra__ is safer.

    def get_stream_url(self, quality: str, srtp: bool = True) -> str | None:
        """Get stream URL for a quality level; ``srtp=False`` strips ``?enableSrtp``."""
        url = getattr(self, quality, None)
        if srtp or not isinstance(url, str):
            return url
        # Strip only the exact ?enableSrtp suffix the server appends (mirrors the
        # private rtsps_url construction); go2rtc rejects the SRTP variant. A
        # generic query strip would be wrong if Protect ever adds other params.
        return url.removesuffix("?enableSrtp")

    def get_available_stream_qualities(self) -> list[str]:
        """
        List available RTSPS quality keys from the server.

        Returns raw strings; may include values not in :class:`ChannelQuality`.
        """
        if self.__pydantic_extra__ is None:
            return []
        return list(self.__pydantic_extra__.keys())

    def get_active_stream_qualities(self) -> list[str]:
        """Get list of currently active RTSPS stream quality levels (only those with stream URLs)."""
        if self.__pydantic_extra__ is None:
            return []
        return [
            key
            for key, value in self.__pydantic_extra__.items()
            if isinstance(value, str) and value is not None
        ]

    def get_inactive_stream_qualities(self) -> list[str]:
        """Get list of inactive RTSPS stream quality levels (supported but not currently active)."""
        if self.__pydantic_extra__ is None:
            return []
        return [
            key
            for key, value in self.__pydantic_extra__.items()
            if not (isinstance(value, str) and value is not None)
        ]


class PublicIdentifiedModel(ProtectModelWithId):
    """Public model carrying the optional device self-description (``type`` / ``guid``)."""

    # Present on newer firmware; older consoles omit both, so they default to
    # ``None`` and ``from_unifi_dict`` must not raise on the old shape.
    # ``device_type`` is the human model name (wire ``type``), distinct from
    # ``model`` (the modelKey enum); ``device_guid`` (wire ``guid``) is a stable
    # identifier.
    device_type: str | None = None
    device_guid: str | None = None
    name: str | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "type": "deviceType",
            "guid": "deviceGuid",
        }

    @property
    def type(self) -> str | None:
        """Alias for ``device_type`` mirroring the private tree's ``type`` field."""
        return self.device_type

    @property
    def display_name(self) -> str:
        """Human-facing name, falling back ``name -> type`` (no ``market_name`` here)."""
        return self.name or self.type or ""


class PublicDeviceModel(PublicIdentifiedModel):
    """Shared base for dedicated public device models carrying ``mac`` / ``state``."""

    state: DeviceState
    mac: str

    # Fields a write-through merge must never overwrite from a PATCH response:
    # stable identity plus any library-owned out-of-band state. Subclasses
    # extend this (see :class:`PublicCamera`). ``_update_sync.lock`` (inherited
    # from :class:`~uiprotect.data.base.ProtectModelWithId`) is what serializes
    # the read-modify-write setters below — no separate lock is introduced.
    _WRITE_THROUGH_SKIP: ClassVar[frozenset[str]] = frozenset({"id"})

    def _apply_from_response(self, response: Self) -> None:
        """
        Merge a fresh PATCH-response model into this cached instance in place.

        Lock-free by design: it performs a run of plain attribute assignments
        with no ``await`` in between, so it is atomic with respect to the event
        loop. Read-modify-write setters take ``self._update_sync.lock`` around
        their read+patch+apply themselves; this helper must not, or a setter
        holding that lock would deadlock on the non-reentrant ``asyncio.Lock``.
        Private ``PrivateAttr`` state (detection caches, ...) is not part of
        ``model_fields`` and is therefore preserved untouched.
        """
        skip = type(self)._WRITE_THROUGH_SKIP
        for name in type(self).model_fields:
            if name in skip:
                continue
            setattr(self, name, getattr(response, name))


class PublicCamera(PublicDeviceModel):
    """Public API camera device (``GET /v1/cameras``)."""

    # ``rtsps_streams`` is primed out-of-band by the library (see the field
    # docstring below) and is never carried on a PATCH response, so a
    # write-through merge must skip it or a setter call would null it.
    _WRITE_THROUGH_SKIP: ClassVar[frozenset[str]] = frozenset({"id", "rtsps_streams"})
    model: ModelType | None = ModelType.CAMERA
    # Nullable on the wire (spec: ``oneOf [string, null]``).
    name: str | None = None
    is_mic_enabled: bool
    osd_settings: PublicOsdSettings
    led_settings: PublicCameraLedSettings
    lcd_message: PublicLcdMessage | None = None
    mic_volume: int
    # ``null`` when no patrol is running.
    active_patrol_slot: int | None = None
    video_mode: VideoMode
    hdr_type: PublicHdrMode
    feature_flags: PublicCameraFeatureFlags
    smart_detect_settings: PublicSmartDetectSettings
    has_package_camera: bool
    # RTSPS stream URLs for this camera. Owned and primed entirely by the
    # library: filled by ``ProtectApiClient.update_public`` (and kept fresh by
    # the WS-reconnect refresh + create/delete write-through). The Public
    # Integration API does not yet carry these on the camera payload, so the
    # field defaults to ``None`` and is populated out-of-band. Consumers read
    # it synchronously.
    rtsps_streams: RTSPSStreams | None = None

    # Open (not-yet-ended) detection events keyed by event id, maintained from
    # the public events websocket. Per-instance (one process may drive several
    # clients against different consoles), so it is a ``PrivateAttr`` with a
    # per-instance default factory rather than a shared class attribute.
    _active_detection_events: dict[str, PublicEvent] = PrivateAttr(default_factory=dict)

    # Memoized derived detection booleans. ``None`` means "stale"; the next
    # ``_detection_state`` call rebuilds a fresh dict and caches it. The two
    # mutators of ``_active_detection_events`` invalidate by setting this back to
    # ``None`` rather than mutating the dict in place, so a snapshot already
    # captured by the events-WS diff stays a distinct object from the rebuild.
    _detection_state_cache: dict[str, bool] | None = PrivateAttr(default=None)

    def hardware_stream_qualities(self) -> list[ChannelQuality]:
        """Stream qualities the camera hardware supports (not the server's ``available`` list)."""
        qualities = [ChannelQuality.HIGH, ChannelQuality.MEDIUM, ChannelQuality.LOW]
        if self.has_package_camera:
            qualities.append(ChannelQuality.PACKAGE)
        return qualities

    # The Public Integration API does not carry live detection booleans on the
    # camera payload; they are derived here from the public events websocket,
    # mirroring the private :class:`~uiprotect.data.devices.Camera` accessor
    # names. An event turns the matching flag(s) on at start (``end is None``)
    # and off once it ends, so overlapping detections of the same kind are
    # handled by the per-id active-event set.

    @property
    def is_motion_detected(self) -> bool:
        """Is a motion event currently active."""
        return self._detection_state()["is_motion_detected"]

    @property
    def is_smart_currently_detected(self) -> bool:
        """Is a smart-detect event currently active."""
        return self._detection_state()["is_smart_currently_detected"]

    @property
    def is_person_currently_detected(self) -> bool:
        """Is a person currently being detected."""
        return self._detection_state()["is_person_currently_detected"]

    @property
    def is_vehicle_currently_detected(self) -> bool:
        """Is a vehicle currently being detected."""
        return self._detection_state()["is_vehicle_currently_detected"]

    @property
    def is_animal_currently_detected(self) -> bool:
        """Is an animal currently being detected."""
        return self._detection_state()["is_animal_currently_detected"]

    @property
    def is_audio_currently_detected(self) -> bool:
        """Is an audio smart-detect event currently active."""
        return self._detection_state()["is_audio_currently_detected"]

    @property
    def is_smoke_currently_detected(self) -> bool:
        """Is a smoke alarm currently being detected."""
        return self._detection_state()["is_smoke_currently_detected"]

    @property
    def is_cmonx_currently_detected(self) -> bool:
        """Is a CO alarm currently being detected."""
        return self._detection_state()["is_cmonx_currently_detected"]

    @property
    def is_siren_currently_detected(self) -> bool:
        """Is a siren currently being detected."""
        return self._detection_state()["is_siren_currently_detected"]

    @property
    def is_baby_cry_currently_detected(self) -> bool:
        """Is a baby cry currently being detected."""
        return self._detection_state()["is_baby_cry_currently_detected"]

    @property
    def is_speaking_currently_detected(self) -> bool:
        """Is speaking currently being detected."""
        return self._detection_state()["is_speaking_currently_detected"]

    @property
    def is_bark_currently_detected(self) -> bool:
        """Is a bark currently being detected."""
        return self._detection_state()["is_bark_currently_detected"]

    @property
    def is_car_alarm_currently_detected(self) -> bool:
        """Is a car alarm currently being detected."""
        return self._detection_state()["is_car_alarm_currently_detected"]

    @property
    def is_car_horn_currently_detected(self) -> bool:
        """Is a car horn currently being detected."""
        return self._detection_state()["is_car_horn_currently_detected"]

    @property
    def is_glass_break_currently_detected(self) -> bool:
        """Is glass breaking currently being detected."""
        return self._detection_state()["is_glass_break_currently_detected"]

    # Config-derived parity accessors mirroring the private
    # :class:`~uiprotect.data.devices.Camera` names. Unlike the private model,
    # the public payload has no per-type feature-flag/global-settings
    # indirection, so each ``is_*_detection_on`` is a plain membership test over
    # ``smart_detect_settings`` — object types against ``object_types``, audio
    # types against ``audio_types``. ``is_motion_detection_on`` is deliberately
    # absent: its private semantics depend on ``recording_settings``, which the
    # public payload does not expose.

    @property
    def is_person_detection_on(self) -> bool:
        """Is person smart detection enabled."""
        return SmartDetectObjectType.PERSON in self.smart_detect_settings.object_types

    @property
    def is_vehicle_detection_on(self) -> bool:
        """Is vehicle smart detection enabled."""
        return SmartDetectObjectType.VEHICLE in self.smart_detect_settings.object_types

    @property
    def is_face_detection_on(self) -> bool:
        """Is face smart detection enabled."""
        return SmartDetectObjectType.FACE in self.smart_detect_settings.object_types

    @property
    def is_license_plate_detection_on(self) -> bool:
        """Is license plate smart detection enabled."""
        return (
            SmartDetectObjectType.LICENSE_PLATE
            in self.smart_detect_settings.object_types
        )

    @property
    def is_package_detection_on(self) -> bool:
        """Is package smart detection enabled."""
        return SmartDetectObjectType.PACKAGE in self.smart_detect_settings.object_types

    @property
    def is_animal_detection_on(self) -> bool:
        """Is animal smart detection enabled."""
        return SmartDetectObjectType.ANIMAL in self.smart_detect_settings.object_types

    @property
    def is_smoke_detection_on(self) -> bool:
        """Is smoke alarm smart detection enabled."""
        return SmartDetectAudioType.SMOKE in self.smart_detect_settings.audio_types

    @property
    def is_co_detection_on(self) -> bool:
        """Is CO alarm smart detection enabled."""
        return SmartDetectAudioType.CMONX in self.smart_detect_settings.audio_types

    @property
    def is_siren_detection_on(self) -> bool:
        """Is siren smart detection enabled."""
        return SmartDetectAudioType.SIREN in self.smart_detect_settings.audio_types

    @property
    def is_baby_cry_detection_on(self) -> bool:
        """Is baby cry smart detection enabled."""
        return SmartDetectAudioType.BABY_CRY in self.smart_detect_settings.audio_types

    @property
    def is_speaking_detection_on(self) -> bool:
        """Is speaking smart detection enabled."""
        return SmartDetectAudioType.SPEAK in self.smart_detect_settings.audio_types

    @property
    def is_bark_detection_on(self) -> bool:
        """Is bark smart detection enabled."""
        return SmartDetectAudioType.BARK in self.smart_detect_settings.audio_types

    @property
    def is_car_alarm_detection_on(self) -> bool:
        """Is car alarm smart detection enabled."""
        return SmartDetectAudioType.BURGLAR in self.smart_detect_settings.audio_types

    @property
    def is_car_horn_detection_on(self) -> bool:
        """Is car horn smart detection enabled."""
        return SmartDetectAudioType.CAR_HORN in self.smart_detect_settings.audio_types

    @property
    def is_glass_break_detection_on(self) -> bool:
        """Is glass break smart detection enabled."""
        return (
            SmartDetectAudioType.GLASS_BREAK in self.smart_detect_settings.audio_types
        )

    @property
    def is_high_fps_enabled(self) -> bool:
        """Is the camera running in high-FPS video mode."""
        return self.video_mode is VideoMode.HIGH_FPS

    @property
    def hdr_mode_display(self) -> Literal["auto", "off", "always"]:
        """HDR mode as shown in the Protect interface (inverse of ``hdr_type``)."""
        if self.hdr_type is PublicHdrMode.OFF:
            return "off"
        if self.hdr_type is PublicHdrMode.ON:
            return "always"
        return "auto"

    def _apply_detection_event(self, event: PublicEvent) -> None:
        """Add/remove a detection event from the active set based on its ``end``."""
        if event.type not in _DETECTION_EVENT_TYPES:
            return
        if event.end is None:
            self._active_detection_events[event.id] = event
        else:
            self._active_detection_events.pop(event.id, None)
        self._detection_state_cache = None

    def _clear_detection_event(self, event_id: str) -> None:
        """Drop an event from the active set (eviction / server ``remove`` frame)."""
        self._active_detection_events.pop(event_id, None)
        self._detection_state_cache = None

    def _detection_state(self) -> dict[str, bool]:
        """
        Snapshot every derived detection boolean in one pass over the active set.

        Single source of truth for the per-type predicates: the nine public
        ``is_*`` properties read their value out of this dict, so they and the
        snapshot used for transition diffing can never drift apart. The result
        is memoized until the active set mutates, so a single-property read is an
        O(1) cache lookup rather than a fresh pass over every active event.
        """
        cached = self._detection_state_cache
        if cached is not None:
            return cached
        motion = smart = person = vehicle = animal = False
        audio = smoke = cmonx = siren = False
        baby_cry = speaking = bark = car_alarm = car_horn = glass_break = False
        for event in self._active_detection_events.values():
            event_type = event.type
            if event_type in _MOTION_EVENT_TYPES:
                motion = True
            elif event_type in _SMART_DETECT_EVENT_TYPES:
                smart = True
                smart_types = event.smart_detect_types
                person = person or SmartDetectObjectType.PERSON in smart_types
                vehicle = vehicle or SmartDetectObjectType.VEHICLE in smart_types
                animal = animal or SmartDetectObjectType.ANIMAL in smart_types
            elif event_type in _SMART_AUDIO_EVENT_TYPES:
                audio = True
                smart_types = event.smart_detect_types
                smoke = smoke or SmartDetectObjectType.SMOKE in smart_types
                cmonx = cmonx or SmartDetectObjectType.CMONX in smart_types
                siren = siren or SmartDetectObjectType.SIREN in smart_types
                baby_cry = baby_cry or SmartDetectObjectType.BABY_CRY in smart_types
                speaking = speaking or SmartDetectObjectType.SPEAK in smart_types
                bark = bark or SmartDetectObjectType.BARK in smart_types
                car_alarm = car_alarm or SmartDetectObjectType.BURGLAR in smart_types
                car_horn = car_horn or SmartDetectObjectType.CAR_HORN in smart_types
                glass_break = (
                    glass_break or SmartDetectObjectType.GLASS_BREAK in smart_types
                )
        state = dict(
            zip(
                _DETECTION_STATE_FIELDS,
                (
                    motion,
                    smart,
                    person,
                    vehicle,
                    animal,
                    audio,
                    smoke,
                    cmonx,
                    siren,
                    baby_cry,
                    speaking,
                    bark,
                    car_alarm,
                    car_horn,
                    glass_break,
                ),
                strict=True,
            )
        )
        self._detection_state_cache = state
        return state

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Camera mutations must go through the dedicated public API helpers "
            "(update_camera_public)."
        )

    async def set_status_light(self, enabled: bool) -> PublicCamera:
        """Set the status LED via the public API."""
        if not self.feature_flags.has_led_status:
            raise BadRequest("Camera does not have status light")
        updated = await self._api.update_camera_public(self.id, led_is_enabled=enabled)
        self._apply_from_response(updated)
        return self

    async def set_welcome_led(self, enabled: bool) -> PublicCamera:
        """Set the welcome LED via the public API."""
        if not self.feature_flags.has_led_status:
            raise BadRequest("Camera does not have status light")
        if self.led_settings.welcome_led is None:
            raise BadRequest("Camera does not have welcome LED")
        updated = await self._api.update_camera_public(self.id, led_welcome_led=enabled)
        self._apply_from_response(updated)
        return self

    async def set_flood_led(self, enabled: bool) -> PublicCamera:
        """Set the flood LED via the public API."""
        if not self.feature_flags.has_led_status:
            raise BadRequest("Camera does not have status light")
        if self.led_settings.flood_led is None:
            raise BadRequest("Camera does not have flood LED")
        updated = await self._api.update_camera_public(self.id, led_flood_led=enabled)
        self._apply_from_response(updated)
        return self

    async def set_hdr_mode(self, mode: PublicHdrMode) -> PublicCamera:
        """Set HDR mode via the public API."""
        if not self.feature_flags.has_hdr:
            raise BadRequest("Camera does not have HDR")
        updated = await self._api.update_camera_public(self.id, hdr_type=mode)
        self._apply_from_response(updated)
        return self

    async def set_video_mode(self, mode: VideoMode) -> PublicCamera:
        """Set the video mode via the public API."""
        if mode not in self.feature_flags.video_modes:
            raise BadRequest(f"Camera does not have {mode}")
        updated = await self._api.update_camera_public(self.id, video_mode=mode)
        self._apply_from_response(updated)
        return self

    async def set_mic_volume(self, level: int) -> PublicCamera:
        """Set microphone volume (1-100) via the public API."""
        if not self.feature_flags.has_mic:
            raise BadRequest("Camera does not have mic")
        level = _coerce_public_int("mic_volume", level, _PUBLIC_MIC_VOLUME_RANGE)
        updated = await self._api.update_camera_public(self.id, mic_volume=level)
        self._apply_from_response(updated)
        return self

    async def set_lcd_message(
        self,
        text_type: DoorbellMessageType,
        text: str | None = None,
        reset_at: datetime | None | DEFAULT_TYPE = DEFAULT,
    ) -> PublicCamera:
        """
        Set the doorbell LCD message via the public API.

        ``text`` is required for CUSTOM_MESSAGE and IMAGE and must be omitted
        otherwise. ``reset_at`` controls when the message clears: omit for the
        NVR default, pass ``None`` for "forever", or a specific datetime.
        """
        if text_type in _LCD_TYPES_REQUIRING_TEXT:
            if text is None:
                raise BadRequest(f"{text_type} requires text")
        elif text is not None:
            raise BadRequest(f"{text_type} does not accept text")
        message: CameraPublicApiLcdMessageRequest = {"type": text_type}
        if text is not None:
            message["text"] = text
        if isinstance(reset_at, datetime):
            message["resetAt"] = to_js_time(reset_at)
        elif reset_at is None:
            message["resetAt"] = None
        updated = await self._api.update_camera_public(self.id, lcd_message=message)
        self._apply_from_response(updated)
        return self

    async def set_osd_name(self, enabled: bool) -> PublicCamera:
        """Toggle the name overlay (OSD) via the public API."""
        updated = await self._api.update_camera_public(
            self.id, osd_name_enabled=enabled
        )
        self._apply_from_response(updated)
        return self

    async def set_osd_date(self, enabled: bool) -> PublicCamera:
        """Toggle the date overlay (OSD) via the public API."""
        updated = await self._api.update_camera_public(
            self.id, osd_date_enabled=enabled
        )
        self._apply_from_response(updated)
        return self

    async def set_osd_logo(self, enabled: bool) -> PublicCamera:
        """Toggle the logo overlay (OSD) via the public API."""
        updated = await self._api.update_camera_public(
            self.id, osd_logo_enabled=enabled
        )
        self._apply_from_response(updated)
        return self

    async def set_osd_nerd_mode(self, enabled: bool) -> PublicCamera:
        """Toggle the bitrate/debug overlay (OSD) via the public API."""
        updated = await self._api.update_camera_public(
            self.id, osd_nerd_mode_enabled=enabled
        )
        self._apply_from_response(updated)
        return self

    async def set_osd_overlay_location(
        self, location: OsdOverlayLocation
    ) -> PublicCamera:
        """Set the OSD overlay location via the public API."""
        updated = await self._api.update_camera_public(
            self.id, osd_overlay_location=location
        )
        self._apply_from_response(updated)
        return self

    async def set_person_detection(self, enabled: bool) -> PublicCamera:
        """Toggle person smart detection via the public API."""
        return await self._set_smart_detect_object(
            SmartDetectObjectType.PERSON, enabled
        )

    async def set_vehicle_detection(self, enabled: bool) -> PublicCamera:
        """Toggle vehicle smart detection via the public API."""
        return await self._set_smart_detect_object(
            SmartDetectObjectType.VEHICLE, enabled
        )

    async def set_package_detection(self, enabled: bool) -> PublicCamera:
        """Toggle package smart detection via the public API."""
        return await self._set_smart_detect_object(
            SmartDetectObjectType.PACKAGE, enabled
        )

    async def set_license_plate_detection(self, enabled: bool) -> PublicCamera:
        """Toggle license plate smart detection via the public API."""
        return await self._set_smart_detect_object(
            SmartDetectObjectType.LICENSE_PLATE, enabled
        )

    async def set_animal_detection(self, enabled: bool) -> PublicCamera:
        """Toggle animal smart detection via the public API."""
        return await self._set_smart_detect_object(
            SmartDetectObjectType.ANIMAL, enabled
        )

    async def set_face_detection(self, enabled: bool) -> PublicCamera:
        """Toggle face smart detection via the public API."""
        return await self._set_smart_detect_object(SmartDetectObjectType.FACE, enabled)

    async def set_smoke_detection(self, enabled: bool) -> PublicCamera:
        """Toggle smoke audio detection via the public API."""
        return await self._set_smart_detect_audio(SmartDetectAudioType.SMOKE, enabled)

    async def set_co_detection(self, enabled: bool) -> PublicCamera:
        """Toggle CO audio detection via the public API."""
        return await self._set_smart_detect_audio(SmartDetectAudioType.CMONX, enabled)

    async def set_siren_detection(self, enabled: bool) -> PublicCamera:
        """Toggle siren audio detection via the public API."""
        return await self._set_smart_detect_audio(SmartDetectAudioType.SIREN, enabled)

    async def set_baby_cry_detection(self, enabled: bool) -> PublicCamera:
        """Toggle baby cry audio detection via the public API."""
        return await self._set_smart_detect_audio(
            SmartDetectAudioType.BABY_CRY, enabled
        )

    async def set_speaking_detection(self, enabled: bool) -> PublicCamera:
        """Toggle speaking audio detection via the public API."""
        return await self._set_smart_detect_audio(SmartDetectAudioType.SPEAK, enabled)

    async def set_bark_detection(self, enabled: bool) -> PublicCamera:
        """Toggle bark audio detection via the public API."""
        return await self._set_smart_detect_audio(SmartDetectAudioType.BARK, enabled)

    async def set_burglar_detection(self, enabled: bool) -> PublicCamera:
        """Toggle burglar audio detection via the public API."""
        return await self._set_smart_detect_audio(SmartDetectAudioType.BURGLAR, enabled)

    async def set_car_horn_detection(self, enabled: bool) -> PublicCamera:
        """Toggle car horn audio detection via the public API."""
        return await self._set_smart_detect_audio(
            SmartDetectAudioType.CAR_HORN, enabled
        )

    async def set_glass_break_detection(self, enabled: bool) -> PublicCamera:
        """Toggle glass break audio detection via the public API."""
        return await self._set_smart_detect_audio(
            SmartDetectAudioType.GLASS_BREAK, enabled
        )

    async def _set_smart_detect_object(
        self, obj_type: SmartDetectObjectType, enabled: bool
    ) -> PublicCamera:
        if obj_type not in self.feature_flags.smart_detect_types:
            raise BadRequest(f"Camera does not support {obj_type} detection")
        async with self._update_sync.lock:
            types = list(self.smart_detect_settings.object_types)
            if enabled and obj_type not in types:
                types.append(obj_type)
            elif not enabled and obj_type in types:
                types.remove(obj_type)
            updated = await self._api.update_camera_public(
                self.id, smart_detect_object_types=types
            )
            self._apply_from_response(updated)
        return self

    async def _set_smart_detect_audio(
        self, audio_type: SmartDetectAudioType, enabled: bool
    ) -> PublicCamera:
        if audio_type not in self.feature_flags.smart_detect_audio_types:
            raise BadRequest(f"Camera does not support {audio_type} detection")
        async with self._update_sync.lock:
            types = list(self.smart_detect_settings.audio_types)
            if enabled and audio_type not in types:
                types.append(audio_type)
            elif not enabled and audio_type in types:
                types.remove(audio_type)
            updated = await self._api.update_camera_public(
                self.id, smart_detect_audio_types=types
            )
            self._apply_from_response(updated)
        return self


class PublicLightModeSettings(ProtectBaseObject):
    mode: LightModeType | None = None
    enable_at: LightModeEnableType | None = None


class PublicLightDeviceSettings(ProtectBaseObject):
    is_indicator_enabled: bool = False
    pir_duration: int | None = None
    pir_sensitivity: int | None = None
    led_level: int | None = None


class PublicLight(PublicDeviceModel):
    """Public API light device (``GET /v1/lights``)."""

    model: ModelType | None = ModelType.LIGHT
    # Nullable on the wire (spec: ``oneOf [string, null]``).
    name: str | None = None
    light_mode_settings: PublicLightModeSettings
    light_device_settings: PublicLightDeviceSettings
    is_dark: bool
    is_light_on: bool
    is_light_force_enabled: bool
    last_motion: int | None = None
    is_pir_motion_detected: bool
    # Flat ``cameraId`` string of the paired camera, or ``null``.
    camera: str | None = None

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Light mutations must go through the dedicated public API helpers "
            "(update_light_public)."
        )

    async def set_name(self, name: str) -> PublicLight:
        """Set the light name via the public API."""
        updated = await self._api.update_light_public(self.id, name=name)
        self._apply_from_response(updated)
        return self

    async def set_flood_light(self, enabled: bool) -> PublicLight:
        """Force the flood light on/off via the public API."""
        updated = await self._api.update_light_public(
            self.id, is_light_force_enabled=enabled
        )
        self._apply_from_response(updated)
        return self

    async def set_status_light(self, enabled: bool) -> PublicLight:
        """Toggle the status indicator LED via the public API."""
        async with self._update_sync.lock:
            settings = self.light_device_settings.model_copy()
            settings.is_indicator_enabled = enabled
            updated = await self._api.update_light_public(
                self.id, light_device_settings=settings
            )
            self._apply_from_response(updated)
        return self

    async def set_led_level(self, led_level: int) -> PublicLight:
        """Set the indicator LED brightness (1-6) via the public API."""
        led_level = _coerce_public_int("led_level", led_level, _PUBLIC_LED_LEVEL_RANGE)
        async with self._update_sync.lock:
            settings = self.light_device_settings.model_copy()
            settings.led_level = led_level
            updated = await self._api.update_light_public(
                self.id, light_device_settings=settings
            )
            self._apply_from_response(updated)
        return self

    async def set_light(
        self, enabled: bool, led_level: float | None = None
    ) -> PublicLight:
        """Force the light on/off, optionally setting LED brightness (1-6), in one call."""
        if led_level is None:
            updated = await self._api.update_light_public(
                self.id, is_light_force_enabled=enabled
            )
            self._apply_from_response(updated)
            return self
        led_level = _coerce_public_int("led_level", led_level, _PUBLIC_LED_LEVEL_RANGE)
        async with self._update_sync.lock:
            settings = self.light_device_settings.model_copy()
            settings.led_level = led_level
            updated = await self._api.update_light_public(
                self.id,
                is_light_force_enabled=enabled,
                light_device_settings=settings,
            )
            self._apply_from_response(updated)
        return self

    async def set_sensitivity(self, sensitivity: int) -> PublicLight:
        """Set PIR motion sensitivity (0-100) via the public API."""
        sensitivity = _coerce_public_int(
            "sensitivity", sensitivity, _PUBLIC_SENSITIVITY_RANGE
        )
        async with self._update_sync.lock:
            settings = self.light_device_settings.model_copy()
            settings.pir_sensitivity = sensitivity
            updated = await self._api.update_light_public(
                self.id, light_device_settings=settings
            )
            self._apply_from_response(updated)
        return self

    async def set_duration(self, duration: timedelta) -> PublicLight:
        """Set how long the light stays on after motion (15s-900s) via the public API."""
        if duration.total_seconds() < 15 or duration.total_seconds() > 900:
            raise BadRequest("Duration outside of 15s to 900s range")
        async with self._update_sync.lock:
            settings = self.light_device_settings.model_copy()
            settings.pir_duration = int(duration.total_seconds() * 1000)
            updated = await self._api.update_light_public(
                self.id, light_device_settings=settings
            )
            self._apply_from_response(updated)
        return self

    async def set_light_mode(
        self,
        mode: LightModeType,
        enable_at: LightModeEnableType | None = None,
    ) -> PublicLight:
        """Set the lighting trigger mode (and optional schedule) via the public API."""
        async with self._update_sync.lock:
            settings = self.light_mode_settings.model_copy()
            settings.mode = mode
            if enable_at is not None:
                settings.enable_at = enable_at
            updated = await self._api.update_light_public(
                self.id, light_mode_settings=settings
            )
            self._apply_from_response(updated)
        return self

    async def set_light_settings(
        self,
        mode: LightModeType,
        enable_at: LightModeEnableType | None = None,
        duration: timedelta | None = None,
        sensitivity: int | None = None,
    ) -> PublicLight:
        """Update mode, schedule, duration and PIR sensitivity via the public API."""
        if duration is not None and (
            duration.total_seconds() < 15 or duration.total_seconds() > 900
        ):
            raise BadRequest("Duration outside of 15s to 900s range")
        async with self._update_sync.lock:
            mode_settings = self.light_mode_settings.model_copy()
            mode_settings.mode = mode
            if enable_at is not None:
                mode_settings.enable_at = enable_at
            device_settings: PublicLightDeviceSettings | None = None
            if duration is not None or sensitivity is not None:
                device_settings = self.light_device_settings.model_copy()
                if duration is not None:
                    device_settings.pir_duration = int(duration.total_seconds() * 1000)
                if sensitivity is not None:
                    device_settings.pir_sensitivity = _coerce_public_int(
                        "sensitivity", sensitivity, _PUBLIC_SENSITIVITY_RANGE
                    )
            updated = await self._api.update_light_public(
                self.id,
                light_mode_settings=mode_settings,
                light_device_settings=device_settings,
            )
            self._apply_from_response(updated)
        return self


class PublicBatteryStatus(ProtectBaseObject):
    percentage: int | None = None
    is_low: bool = False


class PublicSensorMetric(ProtectBaseObject):
    # ``value`` is ``null`` until the sensor first reports the metric.
    value: float | None = None
    status: SensorStatusType | None = None


class PublicSensorStats(ProtectBaseObject):
    light: PublicSensorMetric | None = None
    humidity: PublicSensorMetric | None = None
    temperature: PublicSensorMetric | None = None


class PublicSensorThresholdSettings(ProtectBaseObject):
    # Shared read-shape for the ``lightSettings`` / ``humiditySettings`` /
    # ``temperatureSettings`` leaves — identical field set in the spec.
    is_enabled: bool = False
    margin: float | None = None
    low_threshold: float | None = None
    high_threshold: float | None = None


class PublicSensorMotionSettingsRead(ProtectBaseObject):
    is_enabled: bool = False
    sensitivity: int | None = None
    sensitivity_when_armed: int | None = None


class PublicSensorAlarmSettingsRead(ProtectBaseObject):
    is_enabled: bool = False


class PublicSensorGlassBreakSettings(ProtectBaseObject):
    is_enabled: bool = False
    sensitivity: int | None = None
    sensitivity_when_armed: int | None = None


class PublicSensorLeakSettings(ProtectBaseObject):
    is_internal_enabled: bool = False
    is_external_enabled: bool = False


class SensorFeatureCapability(StrEnum):
    """A capability a sensor can advertise in :class:`PublicSensorFeatureFlags`."""

    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    LIGHT = "light"
    MOTION = "motion"
    WATER_LEAK = "water_leak"
    OPEN = "open"
    TAMPER = "tamper"
    SMOKE = "smoke"


class PublicSensorFeatureCapability(ProtectBaseObject):
    """One capability slice; ``channel_count`` defaults to ``0`` when the wire omits it."""

    channel_count: int = 0


class PublicSensorFeatureFlags(ProtectBaseObject):
    """Per-sensor capability map. An absent key means the capability is unsupported."""

    temperature: PublicSensorFeatureCapability | None = None
    humidity: PublicSensorFeatureCapability | None = None
    light: PublicSensorFeatureCapability | None = None
    motion: PublicSensorFeatureCapability | None = None
    water_leak: PublicSensorFeatureCapability | None = None
    open: PublicSensorFeatureCapability | None = None
    tamper: PublicSensorFeatureCapability | None = None
    smoke: PublicSensorFeatureCapability | None = None


class PublicSensor(PublicDeviceModel):
    """Public API sensor device (``GET /v1/sensors``)."""

    model: ModelType | None = ModelType.SENSOR
    # Nullable on the wire (spec: ``oneOf [string, null]``).
    name: str | None = None
    mount_type: MountType
    battery_status: PublicBatteryStatus
    stats: PublicSensorStats
    light_settings: PublicSensorThresholdSettings
    humidity_settings: PublicSensorThresholdSettings
    temperature_settings: PublicSensorThresholdSettings
    is_opened: bool | None = None
    open_status_changed_at: int | None = None
    is_motion_detected: bool
    motion_detected_at: int | None = None
    motion_settings: PublicSensorMotionSettingsRead
    alarm_triggered_at: int | None = None
    alarm_settings: PublicSensorAlarmSettingsRead
    leak_detected_at: int | None = None
    external_leak_detected_at: int | None = None
    leak_settings: PublicSensorLeakSettings
    tampering_detected_at: int | None = None
    wireless_connection_state: PublicWirelessConnectionState
    # Firmware-new fields (Protect 7.1.76+): older consoles (e.g. 7.1.69) omit
    # them, so default them rather than require — the wire shape shifts across
    # releases and ``from_unifi_dict`` must not raise on the older shape.
    schedule_mode: SensorScheduleMode = SensorScheduleMode.UNKNOWN
    glass_break_settings: PublicSensorGlassBreakSettings = Field(
        default_factory=PublicSensorGlassBreakSettings
    )
    arm_profile_ids: list[str] | None = None
    has_custom_sensitivity_when_armed: bool = False
    # Capability map, present only on newer firmware (older consoles omit it).
    feature_flags: PublicSensorFeatureFlags | None = None

    @property
    def has_feature_flags(self) -> bool:
        """Whether a capability map was reported; ``False`` means unavailable, not empty."""
        return self.feature_flags is not None

    def supports(self, capability: SensorFeatureCapability) -> bool:
        """Whether the sensor advertises ``capability`` (``False`` without a feature map)."""
        if self.feature_flags is None:
            return False
        return getattr(self.feature_flags, capability.value, None) is not None

    @property
    def is_leak_detected(self) -> bool:
        """Whether a leak is detected on either the internal or external channel."""
        return (
            self.leak_detected_at is not None
            or self.external_leak_detected_at is not None
        )

    @property
    def is_tampering_detected(self) -> bool:
        """Whether the tamper switch is currently triggered."""
        return self.tampering_detected_at is not None

    # Environmental metrics are suppressed on leak mounts; the leak metric only
    # applies there.
    @property
    def is_temperature_sensor_enabled(self) -> bool:
        return (
            self.mount_type is not MountType.LEAK
            and self.temperature_settings.is_enabled
        )

    @property
    def is_humidity_sensor_enabled(self) -> bool:
        return (
            self.mount_type is not MountType.LEAK and self.humidity_settings.is_enabled
        )

    @property
    def is_light_sensor_enabled(self) -> bool:
        return self.mount_type is not MountType.LEAK and self.light_settings.is_enabled

    @property
    def is_motion_sensor_enabled(self) -> bool:
        return self.mount_type is not MountType.LEAK and self.motion_settings.is_enabled

    @property
    def is_alarm_sensor_enabled(self) -> bool:
        return self.mount_type is not MountType.LEAK and self.alarm_settings.is_enabled

    @property
    def is_leak_sensor_enabled(self) -> bool:
        return self.mount_type is MountType.LEAK

    @property
    def is_contact_sensor_enabled(self) -> bool:
        return self.mount_type in {MountType.DOOR, MountType.WINDOW, MountType.GARAGE}

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Sensor mutations must go through the dedicated public API helpers "
            "(update_sensor_public)."
        )

    async def set_name(self, name: str) -> PublicSensor:
        """Set the sensor name via the public API."""
        updated = await self._api.update_sensor_public(self.id, name=name)
        self._apply_from_response(updated)
        return self

    async def set_temperature_settings(
        self,
        *,
        is_enabled: bool | None = None,
        low_threshold: float | None = None,
        high_threshold: float | None = None,
        margin: float | None = None,
    ) -> PublicSensor:
        """Update temperature alert settings via the public API."""
        settings: PublicSensorTemperatureSettings = {}
        if is_enabled is not None:
            settings["isEnabled"] = is_enabled
        if low_threshold is not None:
            _validate_public_range(
                "low_threshold", low_threshold, _PUBLIC_TEMPERATURE_LOW_RANGE
            )
            settings["lowThreshold"] = low_threshold
        if high_threshold is not None:
            settings["highThreshold"] = high_threshold
        if margin is not None:
            settings["margin"] = margin
        if not settings:
            raise BadRequest("At least one parameter must be provided")
        updated = await self._api.update_sensor_public(
            self.id, temperature_settings=settings
        )
        self._apply_from_response(updated)
        return self

    async def set_humidity_settings(
        self,
        *,
        is_enabled: bool | None = None,
        low_threshold: float | None = None,
        high_threshold: float | None = None,
        margin: int | None = None,
    ) -> PublicSensor:
        """Update humidity alert settings via the public API."""
        settings: PublicSensorHumiditySettings = {}
        if is_enabled is not None:
            settings["isEnabled"] = is_enabled
        if low_threshold is not None:
            _validate_public_range(
                "low_threshold", low_threshold, _PUBLIC_HUMIDITY_LOW_RANGE
            )
            settings["lowThreshold"] = low_threshold
        if high_threshold is not None:
            settings["highThreshold"] = high_threshold
        if margin is not None:
            settings["margin"] = margin
        if not settings:
            raise BadRequest("At least one parameter must be provided")
        updated = await self._api.update_sensor_public(
            self.id, humidity_settings=settings
        )
        self._apply_from_response(updated)
        return self

    async def set_light_settings(
        self,
        *,
        is_enabled: bool | None = None,
        low_threshold: float | None = None,
        high_threshold: float | None = None,
        margin: int | None = None,
    ) -> PublicSensor:
        """Update light (lux) alert settings via the public API."""
        settings: PublicSensorLightSettings = {}
        if is_enabled is not None:
            settings["isEnabled"] = is_enabled
        if low_threshold is not None:
            _validate_public_range(
                "low_threshold", low_threshold, _PUBLIC_LIGHT_LUX_LOW_RANGE
            )
            settings["lowThreshold"] = low_threshold
        if high_threshold is not None:
            settings["highThreshold"] = high_threshold
        if margin is not None:
            settings["margin"] = margin
        if not settings:
            raise BadRequest("At least one parameter must be provided")
        updated = await self._api.update_sensor_public(self.id, light_settings=settings)
        self._apply_from_response(updated)
        return self

    async def set_motion_settings(
        self,
        *,
        is_enabled: bool | None = None,
        sensitivity: float | None = None,
        sensitivity_when_armed: float | None = None,
    ) -> PublicSensor:
        """Update motion detection settings via the public API."""
        settings: PublicSensorMotionSettings = {}
        if is_enabled is not None:
            settings["isEnabled"] = is_enabled
        if sensitivity is not None:
            settings["sensitivity"] = _coerce_public_int(
                "sensitivity", sensitivity, _PUBLIC_SENSITIVITY_RANGE
            )
        if sensitivity_when_armed is not None:
            settings["sensitivityWhenArmed"] = _coerce_public_int(
                "sensitivity_when_armed",
                sensitivity_when_armed,
                _PUBLIC_SENSITIVITY_RANGE,
            )
        if not settings:
            raise BadRequest("At least one parameter must be provided")
        updated = await self._api.update_sensor_public(
            self.id, motion_settings=settings
        )
        self._apply_from_response(updated)
        return self

    async def set_glass_break_settings(
        self,
        *,
        is_enabled: bool | None = None,
        sensitivity: float | None = None,
        sensitivity_when_armed: float | None = None,
    ) -> PublicSensor:
        """Update glass-break detection settings via the public API."""
        settings: PublicSensorGlassBreakSettingsWrite = {}
        if is_enabled is not None:
            settings["isEnabled"] = is_enabled
        if sensitivity is not None:
            settings["sensitivity"] = _coerce_public_int(
                "sensitivity", sensitivity, _PUBLIC_SENSITIVITY_RANGE
            )
        if sensitivity_when_armed is not None:
            settings["sensitivityWhenArmed"] = _coerce_public_int(
                "sensitivity_when_armed",
                sensitivity_when_armed,
                _PUBLIC_SENSITIVITY_RANGE,
            )
        if not settings:
            raise BadRequest("At least one parameter must be provided")
        updated = await self._api.update_sensor_public(
            self.id, glass_break_settings=settings
        )
        self._apply_from_response(updated)
        return self

    async def set_alarm(self, enabled: bool) -> PublicSensor:
        """Toggle the (audio) alarm detection setting via the public API."""
        alarm_settings: PublicSensorAlarmSettings = {"isEnabled": enabled}
        updated = await self._api.update_sensor_public(
            self.id, alarm_settings=alarm_settings
        )
        self._apply_from_response(updated)
        return self

    async def set_schedule_mode(self, mode: SensorScheduleMode) -> PublicSensor:
        """Set the arm-schedule mode via the public API."""
        updated = await self._api.update_sensor_public(self.id, schedule_mode=mode)
        self._apply_from_response(updated)
        return self

    async def set_arm_profile_ids(self, arm_profile_ids: list[str]) -> PublicSensor:
        """Set the arm-profile ids associated with the sensor via the public API."""
        updated = await self._api.update_sensor_public(
            self.id, arm_profile_ids=arm_profile_ids
        )
        self._apply_from_response(updated)
        return self

    async def set_custom_sensitivity_when_armed(self, enabled: bool) -> PublicSensor:
        """Toggle custom armed sensitivity via the public API."""
        updated = await self._api.update_sensor_public(
            self.id, has_custom_sensitivity_when_armed=enabled
        )
        self._apply_from_response(updated)
        return self

    async def set_motion_status(self, enabled: bool) -> PublicSensor:
        """Toggle motion detection via the public API."""
        return await self.set_motion_settings(is_enabled=enabled)

    async def set_motion_sensitivity(self, sensitivity: float) -> PublicSensor:
        """Set motion detection sensitivity via the public API."""
        return await self.set_motion_settings(sensitivity=sensitivity)

    async def set_temperature_status(self, enabled: bool) -> PublicSensor:
        """Toggle temperature alerts via the public API."""
        return await self.set_temperature_settings(is_enabled=enabled)

    async def set_humidity_status(self, enabled: bool) -> PublicSensor:
        """Toggle humidity alerts via the public API."""
        return await self.set_humidity_settings(is_enabled=enabled)

    async def set_light_status(self, enabled: bool) -> PublicSensor:
        """Toggle light (lux) alerts via the public API."""
        return await self.set_light_settings(is_enabled=enabled)

    async def set_glass_break_status(self, enabled: bool) -> PublicSensor:
        """Toggle glass-break detection via the public API."""
        return await self.set_glass_break_settings(is_enabled=enabled)


class PublicRingSettings(ProtectBaseObject):
    camera_id: str | None = None
    repeat_times: int | None = None
    ringtone_id: str | None = None
    volume: int | None = None


class PublicChime(PublicDeviceModel):
    """Public API chime device (``GET /v1/chimes``)."""

    model: ModelType | None = ModelType.CHIME
    # Nullable on the wire (spec: ``oneOf [string, null]``).
    name: str | None = None
    camera_ids: list[str] = Field(default_factory=list)
    ring_settings: list[PublicRingSettings] = Field(default_factory=list)

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Chime mutations must go through the dedicated public API helpers "
            "(update_chime_public)."
        )

    async def set_ring_settings(
        self,
        ring_settings: list[PublicApiChimeRingSettingRequest],
    ) -> PublicChime:
        """Replace the full per-camera ring settings via the public API."""
        updated = await self._api.update_chime_public(
            self.id, ring_settings=ring_settings
        )
        self._apply_from_response(updated)
        return self

    async def set_volume_for_camera(self, camera_id: str, level: int) -> PublicChime:
        """Set the ring volume for one paired camera via the public API."""
        level = _coerce_public_int("volume", level, _PUBLIC_RING_VOLUME_RANGE)
        # The whole read-modify-write is held under the lock: two concurrent
        # callers must not each read the pre-mutation list and clobber each
        # other (last PATCH wins).
        async with self._update_sync.lock:
            body = self._ring_settings_body(camera_id, volume=level)
            updated = await self._api.update_chime_public(self.id, ring_settings=body)
            self._apply_from_response(updated)
        return self

    async def set_repeat_times_for_camera(
        self, camera_id: str, value: int
    ) -> PublicChime:
        """Set the ring repeat count for one paired camera via the public API."""
        value = _coerce_public_int("repeat_times", value, _PUBLIC_RING_REPEAT_RANGE)
        async with self._update_sync.lock:
            body = self._ring_settings_body(camera_id, repeat_times=value)
            updated = await self._api.update_chime_public(self.id, ring_settings=body)
            self._apply_from_response(updated)
        return self

    def _ring_settings_body(
        self,
        camera_id: str,
        *,
        volume: int | None = None,
        repeat_times: int | None = None,
    ) -> list[PublicApiChimeRingSettingRequest]:
        """Build a full ring-settings PATCH body overriding one camera's entry."""
        if not any(rs.camera_id == camera_id for rs in self.ring_settings):
            raise BadRequest(f"Camera {camera_id} is not paired with chime")
        body: list[PublicApiChimeRingSettingRequest] = []
        for rs in self.ring_settings:
            override = rs.camera_id == camera_id
            entry: PublicApiChimeRingSettingRequest = {
                "cameraId": rs.camera_id or "",
                "volume": volume
                if override and volume is not None
                else (rs.volume or 0),
                "repeatTimes": (
                    repeat_times
                    if override and repeat_times is not None
                    else (rs.repeat_times or 1)
                ),
            }
            if rs.ringtone_id is not None:
                entry["ringtoneId"] = rs.ringtone_id
            body.append(entry)
        return body


class PublicSirenStatus(ProtectBaseObject):
    is_active: bool
    # Only populated while the siren is active.
    activated_at: int | None = None
    duration: int | None = None

    @property
    def turn_off_at(self) -> datetime | None:
        """
        When the siren is expected to stop playing.

        Returns ``None`` when the siren is idle — either because ``activated_at``
        / ``duration`` are not set, or because ``is_active`` is ``False`` (e.g.
        after a manual stop, where the server may leave the timing fields
        populated). Derived from the websocket payload so no extra API call is
        needed — HA can compare against ``datetime.now(UTC)`` instead of
        maintaining its own timer.
        """
        if not self.is_active or self.activated_at is None or self.duration is None:
            return None
        return datetime.fromtimestamp(self.activated_at / 1000, tz=UTC) + timedelta(
            seconds=self.duration
        )


class Siren(PublicDeviceModel):
    """Public API siren device."""

    model: ModelType | None = ModelType.SIREN
    name: str
    volume: int
    led_settings: PublicLedSettings
    siren_status: PublicSirenStatus
    connection_type: SirenConnectionType
    wireless_connection_state: PublicWirelessConnectionState | None = None

    async def _api_update(self, data: dict[str, Any]) -> None:
        # The generic private-API mutation path (``queue_update`` /
        # ``save_device``) does not know how to route patches to the Public
        # Integration endpoints; consumers must use the dedicated
        # ``update_siren_public`` / ``play`` / ``stop`` / ``test_sound``
        # helpers instead.
        raise BadRequest(
            "Siren mutations must go through the dedicated public API helpers "
            "(e.g. play/stop/set_name/set_volume/set_status_light)."
        )

    @property
    def is_active(self) -> bool:
        """
        Whether the siren is currently playing.

        The server does not emit a stop event when the siren finishes its
        timed run, so ``sirenStatus.isActive`` in the WS payload stays
        ``True`` until the next update. ``turn_off_at`` is only set while
        the server flag is true and the timing fields are populated, so a
        clock check against it catches the timed-expiry case. A manual stop
        clears the server flag and ``turn_off_at`` becomes ``None``,
        falling back to the (now-false) server flag.
        """
        turn_off_at = self.siren_status.turn_off_at
        if turn_off_at is not None:
            return datetime.now(UTC) < turn_off_at
        return self.siren_status.is_active

    async def play(self, duration: int | SirenDuration | None = None) -> None:
        """Play the siren. ``duration`` may be a supported integer or :class:`SirenDuration`; defaults to 5 seconds."""
        await self._api.play_siren_public(self.id, duration=duration)

    async def stop(self) -> None:
        """Stop an active siren."""
        await self._api.stop_siren_public(self.id)

    async def test_sound(self, volume: int | None = None) -> None:
        """Test the siren sound at the given volume."""
        await self._api.test_siren_sound_public(self.id, volume=volume)

    async def set_name(self, name: str) -> Siren:
        return await self._api.update_siren_public(self.id, name=name)

    async def set_volume(self, volume: int) -> Siren:
        return await self._api.update_siren_public(self.id, volume=volume)

    async def set_status_light(self, enabled: bool) -> Siren:
        return await self._api.update_siren_public(self.id, led_is_enabled=enabled)


class PublicRelayOutput(ProtectBaseObject):
    id: int
    name: str | None = None
    type: RelayOutputType | None = None
    delay: int | None = None
    pulse_duration: int | None = None
    state: RelayOutputState | None = None
    reboot_state: RelayOutputRebootState | None = None


class PublicRelayInput(ProtectBaseObject):
    id: int
    name: str | None = None
    state: RelayInputState | None = None
    action_trigger: RelayInputActionTrigger | None = None
    action_type: RelayInputActionType | None = None
    action_output_id: int | None = None


class Relay(PublicDeviceModel):
    """
    Public API relay device.

    Use :meth:`__getitem__` (``relay[output_id]``) for "fail loud" lookup or
    :meth:`get_output` for the ``None``-returning variant.
    """

    model: ModelType | None = ModelType.RELAY
    name: str
    led_settings: PublicLedSettings
    outputs: list[PublicRelayOutput]
    inputs: list[PublicRelayInput]
    wireless_connection_state: PublicWirelessConnectionState | None = None

    async def _api_update(self, data: dict[str, Any]) -> None:
        # See :meth:`Siren._api_update` — consumers must use
        # ``update_relay_public`` / ``activate_relay_output_public`` (or the
        # helper methods on this class).
        raise BadRequest(
            "Relay mutations must go through the dedicated public API helpers "
            "(e.g. activate_output/set_name/set_status_light)."
        )

    def get_output(self, output_id: int) -> PublicRelayOutput | None:
        """Return the output with the given id, or ``None`` if not found."""
        for out in self.outputs:
            if out.id == output_id:
                return out
        return None

    def __getitem__(self, output_id: int) -> PublicRelayOutput:
        """Return the output with the given id; raises :class:`KeyError` if unknown."""
        if (out := self.get_output(output_id)) is None:
            raise KeyError(output_id)
        return out

    async def activate_output(
        self,
        output_id: int,
        state: Literal["on", "off"] | None = None,
        pulse_duration_ms: int | None = None,
    ) -> None:
        """Activate / toggle a relay output channel."""
        await self._api.activate_relay_output_public(
            self.id,
            output_id,
            state=state,
            pulse_duration_ms=pulse_duration_ms,
        )

    async def set_name(self, name: str) -> Relay:
        return await self._api.update_relay_public(self.id, name=name)

    async def set_status_light(self, enabled: bool) -> Relay:
        return await self._api.update_relay_public(self.id, led_is_enabled=enabled)


class PublicFobFeatureFlags(ProtectBaseObject):
    # ``FobButton`` carries an ``unknown`` member, so button kinds added by
    # newer firmware coerce to ``FobButton.UNKNOWN`` instead of raising.
    buttons: list[FobButton]


class Fob(PublicDeviceModel):
    """Public API key fob device."""

    model: ModelType | None = ModelType.FOB
    # Nullable on the wire and in WS partial-updates.
    name: str | None = None
    # ``FobAwayState`` carries an ``unknown`` member, so values added by newer
    # firmware coerce to the ``UNKNOWN`` member rather than raising.
    away_state: FobAwayState
    feature_flags: PublicFobFeatureFlags
    # Required by the spec — a fob is always a wireless battery device.
    wireless_connection_state: PublicWirelessConnectionState


class PublicSpeakerFeatureFlags(ProtectBaseObject):
    has_mic: bool


class PublicSpeakerState(ProtectBaseObject):
    # ``SpeakerStatus`` / ``SpeakerMode`` carry an ``unknown`` member, so values
    # added by newer firmware coerce to ``UNKNOWN`` instead of raising.
    status: SpeakerStatus
    mode: SpeakerMode


class Speaker(PublicDeviceModel):
    """Public API speaker device."""

    model: ModelType | None = ModelType.SPEAKER
    # Nullable on the wire and in WS partial-updates.
    name: str | None = None
    volume: int
    mic_volume: int
    is_mic_enabled: bool
    speaker_state: PublicSpeakerState
    feature_flags: PublicSpeakerFeatureFlags

    async def _api_update(self, data: dict[str, Any]) -> None:
        # See :meth:`Siren._api_update` — consumers must use
        # ``update_speaker_public`` / ``test_speaker_sound_public`` (or the
        # helper methods on this class).
        raise BadRequest(
            "Speaker mutations must go through the dedicated public API helpers "
            "(e.g. set_name/set_volume/set_mic_volume/set_mic_enabled/test_sound)."
        )

    async def set_name(self, name: str) -> Speaker:
        return await self._api.update_speaker_public(self.id, name=name)

    async def set_volume(self, volume: int) -> Speaker:
        return await self._api.update_speaker_public(self.id, volume=volume)

    async def set_mic_volume(self, mic_volume: int) -> Speaker:
        return await self._api.update_speaker_public(self.id, mic_volume=mic_volume)

    async def set_mic_enabled(self, enabled: bool) -> Speaker:
        return await self._api.update_speaker_public(self.id, is_mic_enabled=enabled)

    async def test_sound(self, volume: int | None = None) -> None:
        """Test the speaker sound at the given volume."""
        await self._api.test_speaker_sound_public(self.id, volume=volume)


class AlarmHubBattery(ProtectBaseObject):
    """
    Backup battery status of an alarm hub (``alarmHub.battery`` sub-schema).

    The ``battery`` object declares no ``required`` array in the OpenAPI spec,
    and a real hub with the backup battery disconnected emits only
    ``connection`` (omitting ``charging``/``voltage``/``batteryStatus``), so
    every field is optional.
    """

    charging: OnOffState | None = None
    connection: AlarmHubConnectionState | None = None
    voltage: float | None = None
    battery_status: AlarmHubBatteryStatus | None = None


class AlarmHubCover(ProtectBaseObject):
    """
    Tamper cover status of an alarm hub (``alarmHub.cover`` sub-schema).

    The ``cover`` object declares no ``required`` array in the OpenAPI spec, so
    both fields are optional.
    """

    status: AlarmHubCoverStatus | None = None
    distance: int | None = None


class AlarmHubInput(ProtectBaseObject):
    """A single alarm-hub input zone (``alarmHub.input[<id>]`` sub-schema)."""

    enable: OnOffState
    type: AlarmHubInputContactType
    status: AlarmHubInputStatus
    name: str | None = None
    # ``inputType`` is the categorical zone kind (motion/entry/smoke/...).
    # ``AlarmHubInputType`` carries an ``UNKNOWN`` member, so values added
    # by newer firmware coerce to ``UNKNOWN`` instead of raising.
    input_type: AlarmHubInputType | None = None
    last_triggered_at: int | None = None
    camera_id: str | None = None


class AlarmHubOutput(ProtectBaseObject):
    """A single alarm-hub output channel (``alarmHub.output[<id>]`` sub-schema)."""

    active: OnOffState
    enable: OnOffState
    status: AlarmHubOutputStatus
    name: str | None = None
    delay: int | None = None
    duration: int | None = None


class LinkStation(PublicDeviceModel):
    """
    Public API link station / alarm hub.

    A single wire schema (``modelKey: "linkstation"``) covers both the
    ``/v1/link-stations`` and ``/v1/alarm-hubs`` endpoints. The
    :attr:`is_alarm_hub` flag distinguishes the two; ``alarm_hub`` is only
    populated when :attr:`is_alarm_hub` is ``True``.
    """

    model: ModelType | None = ModelType.LINK_STATION
    # Nullable on the wire (spec: ``oneOf [string, null]``).
    name: str | None = None
    is_alarm_hub: bool
    led_settings: PublicLedSettings
    # Top-level nullable timestamp of the last event, NOT an Event object.
    # Sent on the wire as epoch-ms; converted to ``datetime`` via
    # ``unifi_dict_conversions`` to match every other Protect timestamp field.
    last_event: datetime | None = None
    # Retained as an opaque dict so the electrical sub-sections
    # (``connector``, ``*MeterStatus``, ``*TerminalStatus``, ``buckboost``,
    # ...) — whose keys are not valid Python identifiers (``"12v"``, ``"+"``,
    # ``"-"``) and which the OpenAPI spec itself models as
    # ``additionalProperties`` maps — survive untouched alongside any
    # unmodeled / future top-level keys. The well-formed slice
    # (``armed``/``battery``/``cover``/``input``/``output``) is exposed via
    # the typed accessors on this class (``alarm_hub_armed``,
    # ``alarm_hub_battery``, ``alarm_hub_cover``, ``alarm_hub_inputs``,
    # ``alarm_hub_outputs``).
    alarm_hub: dict[str, Any] | None = None

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        """Parse the ``lastEvent`` epoch-ms wire value into ``datetime``."""
        return {"lastEvent": convert_to_datetime} | super().unifi_dict_conversions()

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "LinkStation mutations must go through the dedicated public API helpers "
            "(update_link_station_public / update_alarm_hub_public / "
            "trigger_alarm_hub_output_public)."
        )

    async def set_name(self, name: str) -> LinkStation:
        """Rename via the matching endpoint for the device's role."""
        if self.is_alarm_hub:
            return await self._api.update_alarm_hub_public(self.id, name=name)
        return await self._api.update_link_station_public(self.id, name=name)

    async def trigger_output(
        self,
        output_id: int,
        *,
        enable: bool | None = None,
        delay: int | None = None,
        duration: int | None = None,
    ) -> None:
        """Trigger an alarm-hub output channel. Raises if this is not an alarm hub."""
        if not self.is_alarm_hub:
            raise BadRequest("Not an alarm hub")
        await self._api.trigger_alarm_hub_output_public(
            self.id,
            output_id,
            enable=enable,
            delay=delay,
            duration=duration,
        )

    # Re-derived from ``alarm_hub`` on every access so they stay live against
    # WS updates (which mutate the stored dict in place). The electrical
    # sub-sections (``connector``, ``*MeterStatus``, ``*TerminalStatus``,
    # ``buckboost``, ...) remain accessible via the raw ``alarm_hub`` dict.

    @property
    def alarm_hub_armed(self) -> OnOffState | None:
        """Return the typed armed flag, or ``None`` when the field is absent."""
        if not self.is_alarm_hub or self.alarm_hub is None:
            return None
        armed = self.alarm_hub.get("armed")
        if not isinstance(armed, str):
            return None
        return OnOffState(armed)

    @property
    def alarm_hub_battery(self) -> AlarmHubBattery | None:
        """Return the typed backup-battery status, or ``None`` when absent."""
        if not self.is_alarm_hub or self.alarm_hub is None:
            return None
        battery = self.alarm_hub.get("battery")
        if not isinstance(battery, dict):
            return None
        return AlarmHubBattery.from_unifi_dict(**battery)

    @property
    def alarm_hub_cover(self) -> AlarmHubCover | None:
        """Return the typed tamper-cover status, or ``None`` when absent."""
        if not self.is_alarm_hub or self.alarm_hub is None:
            return None
        cover = self.alarm_hub.get("cover")
        if not isinstance(cover, dict):
            return None
        return AlarmHubCover.from_unifi_dict(**cover)

    @property
    def alarm_hub_inputs(self) -> dict[int, AlarmHubInput]:
        """Return input zones keyed by numeric id; non-integer keys are skipped."""
        if not self.is_alarm_hub or self.alarm_hub is None:
            return {}
        raw = self.alarm_hub.get("input")
        if not isinstance(raw, dict):
            return {}
        return {
            int(key): AlarmHubInput.from_unifi_dict(**value)
            for key, value in raw.items()
            if isinstance(key, str) and key.isdigit() and isinstance(value, dict)
        }

    @property
    def alarm_hub_outputs(self) -> dict[int, AlarmHubOutput]:
        """Return output channels keyed by numeric id; non-integer keys are skipped."""
        if not self.is_alarm_hub or self.alarm_hub is None:
            return {}
        raw = self.alarm_hub.get("output")
        if not isinstance(raw, dict):
            return {}
        return {
            int(key): AlarmHubOutput.from_unifi_dict(**value)
            for key, value in raw.items()
            if isinstance(key, str) and key.isdigit() and isinstance(value, dict)
        }


class PublicArmSchedule(ProtectBaseObject):
    start: str
    end: str


class ArmProfile(ProtectBaseObject):
    """
    Public API arm profile (local alarm manager).

    Arm profiles are configuration objects, not devices — the
    ``/v1/arm-profiles`` payload has no ``modelKey``. The class therefore
    inherits directly from :class:`ProtectBaseObject` and carries its own
    ``id`` field.
    """

    id: str
    name: str
    automations: list[str]
    schedules: list[PublicArmSchedule]
    record_everything: bool
    activation_delay: int
    creator: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NvrArmMode(ProtectBaseObject):
    """
    Current arm-manager state embedded in the NVR object (``armMode`` field).

    Returned by ``GET /v1/nvrs`` as part of the NVR payload.  All fields
    that may legitimately be ``null`` on the wire are typed as ``Optional``
    for forward-compatibility.
    """

    status: NvrArmModeStatus
    arm_profile_id: str | None = None
    armed_at: int | None = None
    will_be_armed_at: int | None = None
    breach_detected_at: int | None = None
    breach_event_count: int = 0
    breach_trigger_event_id: str | None = None
    breach_event_id: str | None = None


class PublicDoorbellCustomImage(ProtectBaseObject):
    """A custom doorbell image entry (preview GIF + full sprite PNG)."""

    preview: str
    sprite: str


class PublicDoorbellSettings(ProtectBaseObject):
    """
    Doorbell settings exposed by the Public Integration API (``GET /v1/nvrs``).

    Intentionally separate from the private :class:`~uiprotect.data.nvr.DoorbellSettings`
    which carries additional private-API-only fields (``allMessages``, typed
    timedelta, etc.).

    All fields have defaults because the ``doorbellSettings`` OpenAPI schema
    declares no ``required`` array — fields may be absent on older firmware or
    in partial WS update diffs.

    Read-only: the Public Integration API exposes ``GET /v1/nvrs`` but no
    ``PATCH`` counterpart (nor a dedicated doorbell-message endpoint), so there
    is no public write path for these settings. Confirmed absent through
    Protect ``7.1.87``; changing the default message still requires the private
    API (:class:`~uiprotect.data.nvr.DoorbellSettings`).
    """

    default_message_text: str = ""
    default_message_reset_timeout_ms: int = 0
    custom_messages: list[str] = Field(default_factory=list)
    custom_images: list[PublicDoorbellCustomImage] = Field(default_factory=list)


class PublicNVR(PublicIdentifiedModel):
    """
    NVR device as exposed by the Public Integration API (``GET /v1/nvrs``).

    This model reflects the public schema: ``id``, ``modelKey``, ``name``,
    ``doorbellSettings``, and optionally ``armMode`` / ``mac``.

    ``name`` is nullable — the API schema declares it as ``oneOf: [string, null]``.

    ``mac`` is exposed on ``GET /v1/nvrs`` from Protect newer than 7.1 and is
    ``None`` on older firmware that omits the key (and absent from WS
    partial-update diffs).

    ``doorbell_settings`` is ``None`` on older firmware that does not yet
    expose the ``doorbellSettings`` key, and is absent from WS partial-update
    diffs (which only require ``id`` + ``modelKey``).

    ``arm_mode`` is ``None`` when the firmware does not yet expose the alarm
    manager (older releases) and also ``None`` when the alarm manager is set
    to global (server returns ``armMode: null``).  WS device-update diffs that
    include ``armMode`` are handled automatically by
    :meth:`~uiprotect.data.base.ProtectBaseObject.update_from_dict` without
    any manual extraction.
    """

    model: ModelType | None = ModelType.NVR
    name: str | None = None
    mac: str | None = None
    doorbell_settings: PublicDoorbellSettings | None = None
    arm_mode: NvrArmMode | None = None


class PublicLiveviewSlot(ProtectBaseObject):
    """One slot in a public-API liveview (read shape)."""

    camera_ids: list[str]
    # ``LiveviewCycleMode`` carries an ``unknown`` member, so values added by
    # newer firmware coerce to ``UNKNOWN`` instead of raising.
    cycle_mode: LiveviewCycleMode
    cycle_interval: int

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "cameras": "cameraIds"}


class PublicLiveview(ProtectModelWithId):
    """
    Public API liveview.

    ``owner`` is a flat ``userId`` string (the spec types it as ``$ref: userId``,
    which is ``type: string``) — not an embedded user object. ``layout`` is the
    number of slots the liveview contains (spec: number, 1..26); the field name
    matches the wire key exactly.
    """

    model: ModelType | None = ModelType.LIVEVIEW
    name: str
    is_default: bool
    is_global: bool
    owner: str
    layout: int
    slots: list[PublicLiveviewSlot]

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Liveview mutations must go through the dedicated public API helpers "
            "(create_liveview_public / update_liveview_public)."
        )


class PublicBridge(PublicDeviceModel):
    """
    Public API bridge device.

    ``ModelType.BRIDGE`` is already owned by the private :class:`Bridge` class in
    ``MODEL_TO_CLASS``; this public counterpart is routed via a dedicated factory
    on :class:`~uiprotect.data.public_bootstrap.PublicBootstrap` instead.
    """

    model: ModelType | None = ModelType.BRIDGE
    name: str | None = None
    # ``bridgePlatform`` is typed ``[string, null]`` in the spec.
    platform: str | None = None
    clients: list[str]
    max_clients: int

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Bridge mutations must go through the dedicated public API helpers "
            "(update_bridge_public)."
        )

    async def set_name(self, name: str) -> PublicBridge:
        return await self._api.update_bridge_public(self.id, name=name)


class PublicViewer(PublicDeviceModel):
    """
    Public API viewer device.

    ``ModelType.VIEWPORT`` is already owned by the private :class:`Viewer` class
    in ``MODEL_TO_CLASS``; this public counterpart is routed via a dedicated
    factory on :class:`~uiprotect.data.public_bootstrap.PublicBootstrap` instead.

    The wire field ``liveview`` is a flat ``liveviewId`` string (nullable);
    snake-cased to :attr:`liveview_id` via :meth:`_get_unifi_remaps`.
    """

    model: ModelType | None = ModelType.VIEWPORT
    name: str | None = None
    liveview_id: str | None = None
    stream_limit: int

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "liveview": "liveviewId"}

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Viewer mutations must go through the dedicated public API helpers "
            "(update_viewer_public)."
        )

    async def set_name(self, name: str) -> PublicViewer:
        return await self._api.update_viewer_public(self.id, name=name)

    async def set_liveview(self, liveview_id: str | None) -> PublicViewer:
        return await self._api.update_viewer_public(self.id, liveview=liveview_id)


class PublicUser(ProtectModelWithId):
    """Public API Protect user (read-only)."""

    model: ModelType | None = ModelType.USER
    name: str
    # ``firstName``/``lastName``/``email``/``ucoreUserId`` are spec-``required``
    # but typed ``oneOf [string, null]`` — the server returns the key but the
    # value may be ``null``. Pydantic field types are therefore ``str | None``.
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    ucore_user_id: str | None = None


class PublicUlpUser(ProtectModelWithId):
    """Public API UniFi Identity (ULP) user (read-only)."""

    model: ModelType | None = ModelType.ULP_USER
    first_name: str
    last_name: str
    full_name: str
    status: UlpUserStatus


class PublicFile(ProtectBaseObject):
    """Public API device asset file (``/v1/files/{fileType}``)."""

    name: str
    type: AssetFileType
    path: str
    original_name: str | None = None
