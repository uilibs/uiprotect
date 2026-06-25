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

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from typing import Any, Literal, TypedDict

from pydantic import Field

from ..exceptions import BadRequest
from .base import ProtectBaseObject, ProtectModelWithId
from .types import (
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

# ---------------------------------------------------------------------------
# Write payloads (TypedDict — shape the client accepts and forwards)
# ---------------------------------------------------------------------------


class PublicArmScheduleDict(TypedDict):
    """Arm-profile schedule entry (write shape). Fields are cron expressions."""

    start: str
    end: str


class PublicSensorLightSettings(TypedDict, total=False):
    isEnabled: bool
    lowThreshold: int
    highThreshold: int
    margin: int


class PublicSensorHumiditySettings(TypedDict, total=False):
    isEnabled: bool
    lowThreshold: int
    highThreshold: int
    margin: int


class PublicSensorTemperatureSettings(TypedDict, total=False):
    isEnabled: bool
    # Temperature values are floats (degrees). Do not confuse with
    # ``PublicSensorHumiditySettings`` (which uses ``int`` percentages).
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


# ---------------------------------------------------------------------------
# Shared sub-models (read shape)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Camera (public) — leaf sub-models + device
# ---------------------------------------------------------------------------
#
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


class PublicSmartDetectSettings(ProtectBaseObject):
    object_types: list[SmartDetectObjectType] = Field(default_factory=list)
    audio_types: list[SmartDetectAudioType] = Field(default_factory=list)


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

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "type": "deviceType",
            "guid": "deviceGuid",
        }


class PublicDeviceModel(PublicIdentifiedModel):
    """Shared base for dedicated public device models carrying ``mac`` / ``state``."""

    state: DeviceState
    mac: str


class PublicCamera(PublicDeviceModel):
    """Public API camera device (``GET /v1/cameras``)."""

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

    def hardware_stream_qualities(self) -> list[ChannelQuality]:
        """Stream qualities the camera hardware supports (not the server's ``available`` list)."""
        qualities = [ChannelQuality.HIGH, ChannelQuality.MEDIUM, ChannelQuality.LOW]
        if self.has_package_camera:
            qualities.append(ChannelQuality.PACKAGE)
        return qualities

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Camera mutations must go through the dedicated public API helpers "
            "(update_camera_public)."
        )


# ---------------------------------------------------------------------------
# Light (public) — leaf sub-models + device
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Sensor (public) — leaf sub-models + device
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Chime (public) — leaf sub-model + device
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Siren
# ---------------------------------------------------------------------------


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


class Siren(ProtectModelWithId):
    """Public API siren device."""

    model: ModelType | None = ModelType.SIREN
    state: DeviceState
    name: str
    mac: str
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


# ---------------------------------------------------------------------------
# Relay
# ---------------------------------------------------------------------------


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


class Relay(ProtectModelWithId):
    """
    Public API relay device.

    Use :meth:`__getitem__` (``relay[output_id]``) for "fail loud" lookup or
    :meth:`get_output` for the ``None``-returning variant.
    """

    model: ModelType | None = ModelType.RELAY
    state: DeviceState
    name: str
    mac: str
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


# ---------------------------------------------------------------------------
# Fob
# ---------------------------------------------------------------------------


class PublicFobFeatureFlags(ProtectBaseObject):
    # ``FobButton`` carries an ``unknown`` member, so button kinds added by
    # newer firmware coerce to ``FobButton.UNKNOWN`` instead of raising.
    buttons: list[FobButton]


class Fob(ProtectModelWithId):
    """Public API key fob device."""

    model: ModelType | None = ModelType.FOB
    # ``DeviceState`` / ``FobAwayState`` carry an ``unknown`` member, so values
    # added by newer firmware coerce to the ``UNKNOWN`` member rather than
    # raising. ``wireless_connection_state`` (and the battery status it carries)
    # is required by the spec — a fob is always a wireless battery device.
    state: DeviceState
    # Nullable on the wire and in WS partial-updates.
    name: str | None = None
    mac: str
    away_state: FobAwayState
    feature_flags: PublicFobFeatureFlags
    wireless_connection_state: PublicWirelessConnectionState


# ---------------------------------------------------------------------------
# Speaker
# ---------------------------------------------------------------------------


class PublicSpeakerFeatureFlags(ProtectBaseObject):
    has_mic: bool


class PublicSpeakerState(ProtectBaseObject):
    # ``SpeakerStatus`` / ``SpeakerMode`` carry an ``unknown`` member, so values
    # added by newer firmware coerce to ``UNKNOWN`` instead of raising.
    status: SpeakerStatus
    mode: SpeakerMode


class Speaker(ProtectModelWithId):
    """Public API speaker device."""

    model: ModelType | None = ModelType.SPEAKER
    state: DeviceState
    # Nullable on the wire and in WS partial-updates.
    name: str | None = None
    mac: str
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


# ---------------------------------------------------------------------------
# Link Station / Alarm Hub
# ---------------------------------------------------------------------------


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


class LinkStation(ProtectModelWithId):
    """
    Public API link station / alarm hub.

    A single wire schema (``modelKey: "linkstation"``) covers both the
    ``/v1/link-stations`` and ``/v1/alarm-hubs`` endpoints. The
    :attr:`is_alarm_hub` flag distinguishes the two; ``alarm_hub`` is only
    populated when :attr:`is_alarm_hub` is ``True``.
    """

    model: ModelType | None = ModelType.LINK_STATION
    state: DeviceState
    # Nullable on the wire (spec: ``oneOf [string, null]``).
    name: str | None = None
    mac: str
    is_alarm_hub: bool
    led_settings: PublicLedSettings
    # Top-level nullable epoch-ms timestamp of the last event, NOT an Event object.
    last_event: int | None = None
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

    # ------------------------------------------------------------------
    # Typed alarm-hub accessors
    # ------------------------------------------------------------------
    #
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


# ---------------------------------------------------------------------------
# Arm profile (NOT a device — has no ``modelKey``)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Public NVR
# ---------------------------------------------------------------------------


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
    """

    default_message_text: str = ""
    default_message_reset_timeout_ms: int = 0
    custom_messages: list[str] = Field(default_factory=list)
    custom_images: list[PublicDoorbellCustomImage] = Field(default_factory=list)


class PublicNVR(PublicIdentifiedModel):
    """
    NVR device as exposed by the Public Integration API (``GET /v1/nvrs``).

    This model reflects the public schema: ``id``, ``modelKey``, ``name``,
    ``doorbellSettings``, and optionally ``armMode``.

    ``name`` is nullable — the API schema declares it as ``oneOf: [string, null]``.

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
    doorbell_settings: PublicDoorbellSettings | None = None
    arm_mode: NvrArmMode | None = None


# ---------------------------------------------------------------------------
# Liveview
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class PublicBridge(ProtectModelWithId):
    """
    Public API bridge device.

    ``ModelType.BRIDGE`` is already owned by the private :class:`Bridge` class in
    ``MODEL_TO_CLASS``; this public counterpart is routed via a dedicated factory
    on :class:`~uiprotect.data.public_bootstrap.PublicBootstrap` instead.
    """

    model: ModelType | None = ModelType.BRIDGE
    state: DeviceState
    name: str | None = None
    mac: str
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


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------


class PublicViewer(ProtectModelWithId):
    """
    Public API viewer device.

    ``ModelType.VIEWPORT`` is already owned by the private :class:`Viewer` class
    in ``MODEL_TO_CLASS``; this public counterpart is routed via a dedicated
    factory on :class:`~uiprotect.data.public_bootstrap.PublicBootstrap` instead.

    The wire field ``liveview`` is a flat ``liveviewId`` string (nullable);
    snake-cased to :attr:`liveview_id` via :meth:`_get_unifi_remaps`.
    """

    model: ModelType | None = ModelType.VIEWPORT
    state: DeviceState
    name: str | None = None
    mac: str
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


# ---------------------------------------------------------------------------
# User / ULP user (read-only)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Files (device assets)
# ---------------------------------------------------------------------------


class PublicFile(ProtectBaseObject):
    """Public API device asset file (``/v1/files/{fileType}``)."""

    name: str
    type: AssetFileType
    path: str
    original_name: str | None = None
