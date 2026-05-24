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
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from ..exceptions import BadRequest
from .base import ProtectBaseObject, ProtectModelWithId
from .types import (
    ModelType,
    NvrArmModeStatus,
    RelayInputState,
    RelayOutputRebootState,
    RelayOutputState,
    SirenDuration,
)

if TYPE_CHECKING:
    pass


# Public API connection state. Intentionally *not* ``StateType`` (which is the
# private-API enum with many values) — the public schema documents only these
# two values for sirens and relays, and treating it as a ``str`` keeps forward
# compatibility with future server additions without surprising callers.
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


# ---------------------------------------------------------------------------
# Shared sub-models (read shape)
# ---------------------------------------------------------------------------


class PublicSignalState(ProtectBaseObject):
    # Nullable on the wire for fobs (no recent heartbeat → no signal reading).
    signal_quality: int | None = None
    signal_strength: int | None = None


class PublicWirelessBatteryStatus(ProtectBaseObject):
    # ``percentage`` is nullable on the wire for fobs that have not reported.
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
    type: str | None = None
    delay: int | None = None
    pulse_duration: int | None = None
    state: RelayOutputState | None = None
    reboot_state: RelayOutputRebootState | None = None


class PublicRelayInput(ProtectBaseObject):
    id: int
    name: str | None = None
    state: RelayInputState | None = None
    action_trigger: str | None = None
    action_type: str | None = None
    action_output_id: int | None = None


class Relay(ProtectModelWithId):
    """
    Public API relay device.

    Use :meth:`__getitem__` (``relay[output_id]``) for "fail loud" lookup or
    :meth:`get_output` for the ``None``-returning variant.
    """

    model: ModelType | None = ModelType.RELAY
    state: str
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
# Speaker
# ---------------------------------------------------------------------------


class PublicSpeakerState(ProtectBaseObject):
    # ``status`` / ``mode`` are typed as ``str`` (not enums) so unknown server
    # values from future firmware don't raise — matching ``state`` elsewhere.
    status: str
    mode: str


class PublicSpeakerFeatureFlags(ProtectBaseObject):
    has_mic: bool


class Speaker(ProtectModelWithId):
    """Public API speaker device."""

    model: ModelType | None = ModelType.SPEAKER
    state: str
    name: str
    mac: str
    volume: int
    mic_volume: int
    is_mic_enabled: bool
    speaker_state: PublicSpeakerState
    feature_flags: PublicSpeakerFeatureFlags

    async def _api_update(self, data: dict[str, Any]) -> None:
        # See :meth:`Siren._api_update` — consumers must use the dedicated
        # public API helpers.
        raise BadRequest(
            "Speaker mutations must go through the dedicated public API helpers "
            "(e.g. test_sound/set_name/set_volume/set_mic_volume/set_mic_enabled)."
        )

    async def test_sound(self, volume: int | None = None) -> None:
        """Play the speaker test sound at the given volume."""
        await self._api.test_speaker_sound_public(self.id, volume=volume)

    async def set_name(self, name: str) -> Speaker:
        return await self._api.update_speaker_public(self.id, name=name)

    async def set_volume(self, volume: int) -> Speaker:
        return await self._api.update_speaker_public(self.id, volume=volume)

    async def set_mic_volume(self, mic_volume: int) -> Speaker:
        return await self._api.update_speaker_public(self.id, mic_volume=mic_volume)

    async def set_mic_enabled(self, enabled: bool) -> Speaker:
        return await self._api.update_speaker_public(self.id, is_mic_enabled=enabled)


# ---------------------------------------------------------------------------
# Fob (wireless key fob)
# ---------------------------------------------------------------------------


class PublicFobFeatureFlags(ProtectBaseObject):
    # ``buttons`` is the list of physical buttons the fob exposes; typed as
    # ``list[str]`` so unknown future button kinds don't raise.
    buttons: list[str]


class Fob(ProtectModelWithId):
    """Public API key-fob device."""

    model: ModelType | None = ModelType.FOB
    state: str
    name: str
    mac: str
    away_state: str
    feature_flags: PublicFobFeatureFlags
    wireless_connection_state: PublicWirelessConnectionState | None = None

    async def _api_update(self, data: dict[str, Any]) -> None:
        # See :meth:`Siren._api_update` — consumers must use the dedicated
        # public API helpers.
        raise BadRequest(
            "Fob mutations must go through the dedicated public API helpers "
            "(e.g. set_name)."
        )

    async def set_name(self, name: str) -> Fob:
        return await self._api.update_fob_public(self.id, name=name)


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class PublicBridge(ProtectModelWithId):
    """
    Public API bridge device.

    Distinct from the private :class:`~uiprotect.data.devices.Bridge` — the
    public schema exposes ``clients`` / ``maxClients`` (absent from the
    private model) and omits the adoption/firmware fields, so reusing the
    private model would silently drop those fields.
    """

    model: ModelType | None = ModelType.BRIDGE
    state: str
    name: str
    mac: str
    platform: str | None = None
    clients: list[str] = []
    max_clients: int

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Bridge mutations must go through the dedicated public API helpers "
            "(e.g. set_name)."
        )

    async def set_name(self, name: str) -> PublicBridge:
        return await self._api.update_bridge_public(self.id, name=name)


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------


class PublicViewer(ProtectModelWithId):
    """
    Public API viewer (Viewport) device.

    Distinct from the private :class:`~uiprotect.data.devices.Viewer` — the
    public schema names the assigned liveview ``liveview`` (the private model
    expects ``liveviewId``), so reusing the private model would drop the
    assignment.
    """

    model: ModelType | None = ModelType.VIEWPORT
    state: str
    name: str
    mac: str
    # The id of the liveview currently shown; ``None`` when unset.
    liveview: str | None = None
    stream_limit: int

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise BadRequest(
            "Viewer mutations must go through the dedicated public API helpers "
            "(e.g. set_name/set_liveview)."
        )

    async def set_name(self, name: str) -> PublicViewer:
        return await self._api.update_viewer_public(self.id, name=name)

    async def set_liveview(self, liveview_id: str) -> PublicViewer:
        return await self._api.update_viewer_public(self.id, liveview=liveview_id)


# ---------------------------------------------------------------------------
# Liveview
# ---------------------------------------------------------------------------


class PublicLiveviewSlot(ProtectBaseObject):
    cameras: list[str]
    # ``motion`` / ``time``; typed as ``str`` for forward compatibility.
    cycle_mode: str
    cycle_interval: int


class PublicLiveview(ProtectModelWithId):
    """
    Public API liveview.

    Distinct from the private :class:`~uiprotect.data.nvr.Liveview` — the
    public schema names the owner ``owner`` (the private model expects
    ``owner``→``owner_id``), so reusing the private model would drop it.
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
            "(e.g. set_name)."
        )

    async def set_name(self, name: str) -> PublicLiveview:
        return await self._api.update_liveview_public(self.id, name=name)


# ---------------------------------------------------------------------------
# Files (device asset uploads — NOT a device, has no ``modelKey``)
# ---------------------------------------------------------------------------


class PublicFile(ProtectBaseObject):
    """A device asset file entry returned by ``GET /v1/files/{fileType}``."""

    name: str
    # ``animations`` is the only documented asset file type; typed as ``str``
    # for forward compatibility.
    type: str
    path: str
    original_name: str | None = None


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
