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
from functools import cache
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from ..exceptions import BadRequest
from .base import ProtectBaseObject, ProtectModelWithId
from .types import (
    AlarmHubInputType,
    AssetFileType,
    DeviceState,
    FobAwayState,
    FobButton,
    LiveviewCycleMode,
    ModelType,
    NvrArmModeStatus,
    RelayInputActionTrigger,
    RelayInputActionType,
    RelayInputState,
    RelayOutputRebootState,
    RelayOutputState,
    RelayOutputType,
    SirenDuration,
    SpeakerMode,
    SpeakerStatus,
    UlpUserStatus,
)

if TYPE_CHECKING:
    pass


# Public API connection state. Intentionally *not* ``StateType`` (which is the
# private-API enum with many values) — the public schema documents only these
# two values for sirens, and treating it as a ``str`` keeps forward
# compatibility with future server additions without surprising callers.
# ``Relay.state`` uses the :class:`DeviceState` enum (same forward-compat
# semantics via ``UnknownValuesEnumMixin``); only ``Siren.state`` still uses
# the raw-``str`` treatment.
PublicConnectionState = Literal["CONNECTED", "DISCONNECTED"]


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
    # ``state`` uses :data:`PublicConnectionState` semantically but is typed as
    # ``str`` so unknown server values (future firmware) don't raise.
    state: str
    name: str
    mac: str
    volume: int
    led_settings: PublicLedSettings
    siren_status: PublicSirenStatus
    connection_type: str
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
    """Backup battery status of an alarm hub (``alarmHub.battery`` sub-schema)."""

    charging: str
    connection: str
    voltage: float | None = None
    battery_status: str


class AlarmHubCover(ProtectBaseObject):
    """Tamper cover status of an alarm hub (``alarmHub.cover`` sub-schema)."""

    status: str
    distance: int | None = None


class AlarmHubInput(ProtectBaseObject):
    """A single alarm-hub input zone (``alarmHub.input[<id>]`` sub-schema)."""

    enable: str
    type: str
    status: str
    name: str | None = None
    # ``inputType`` is the categorical zone kind (motion/entry/smoke/...).
    # ``AlarmHubInputType`` carries an ``UNKNOWN`` member, so values added
    # by newer firmware coerce to ``UNKNOWN`` instead of raising.
    input_type: AlarmHubInputType | None = None
    last_triggered_at: int | None = None
    camera_id: str | None = None


class AlarmHubOutput(ProtectBaseObject):
    """A single alarm-hub output channel (``alarmHub.output[<id>]`` sub-schema)."""

    active: str
    enable: str
    status: str
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
    def alarm_hub_armed(self) -> str | None:
        """Return the wire-level armed flag (``"on"``/``"off"``), or ``None``."""
        if not self.is_alarm_hub or self.alarm_hub is None:
            return None
        armed = self.alarm_hub.get("armed")
        return armed if isinstance(armed, str) else None

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
    custom_messages: list[str] = []
    custom_images: list[PublicDoorbellCustomImage] = []


class PublicNVR(ProtectModelWithId):
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
