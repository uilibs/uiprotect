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

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from ..exceptions import BadRequest
from .base import ProtectBaseObject, ProtectModelWithId
from .types import ModelType

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
    signal_quality: int
    signal_strength: int


class PublicWirelessBatteryStatus(ProtectBaseObject):
    percentage: int
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
        """Whether the siren is currently playing."""
        return self.siren_status.is_active

    async def play(self, duration: int | None = None) -> None:
        """Play the siren. ``duration`` is in seconds; ``None`` uses the server default."""
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
    name: str
    type: str
    delay: int
    pulse_duration: int
    state: str
    reboot_state: str


class PublicRelayInput(ProtectBaseObject):
    id: int
    name: str
    state: str
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
        for out in self.outputs:
            if out.id == output_id:
                return out
        raise KeyError(output_id)

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


class ArmManagerSettings(ProtectBaseObject):
    """
    Current arm-manager state from ``GET /v1/arm-profiles/settings``.

    Both fields are ``Optional`` because the endpoint may be absent on
    installations where the local alarm manager is not provisioned, and
    forward-compatibility with future fields is preserved by not enforcing
    presence here.
    """

    arm_profile_id: str | None = None
    is_enabled: bool | None = None
