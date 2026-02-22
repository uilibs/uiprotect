"""UniFi Protect Data Conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from uiprotect.data.base import ProtectModelWithId

from ..exceptions import DataDecodeError
from .devices import (
    AiPort,
    Bridge,
    Camera,
    Chime,
    Doorlock,
    Light,
    Sensor,
    Viewer,
)
from .nvr import NVR, Event, Liveview
from .types import ModelType
from .user import CloudAccount, Group, Keyring, UlpUser, User, UserLocation

if TYPE_CHECKING:
    from ..api import ProtectApiClient
    from ..data.base import ProtectModel


MODEL_TO_CLASS: dict[str, type[ProtectModel]] = {
    ModelType.EVENT: Event,
    ModelType.GROUP: Group,
    ModelType.USER_LOCATION: UserLocation,
    ModelType.CLOUD_IDENTITY: CloudAccount,
    ModelType.USER: User,
    ModelType.NVR: NVR,
    ModelType.LIGHT: Light,
    ModelType.CAMERA: Camera,
    ModelType.LIVEVIEW: Liveview,
    ModelType.VIEWPORT: Viewer,
    ModelType.BRIDGE: Bridge,
    ModelType.SENSOR: Sensor,
    ModelType.DOORLOCK: Doorlock,
    ModelType.CHIME: Chime,
    ModelType.AIPORT: AiPort,
    ModelType.KEYRING: Keyring,
    ModelType.ULP_USER: UlpUser,
}


def get_klass_from_dict(data: dict[str, Any]) -> type[ProtectModel]:
    """
    Helper method to read the `modelKey` from a UFP JSON dict and get the correct Python class for conversion.
    Will raise `DataDecodeError` if the `modelKey` is for an unknown object.
    """
    if "modelKey" not in data:
        raise DataDecodeError("No modelKey")

    model = ModelType(data["modelKey"])

    klass = MODEL_TO_CLASS.get(model)

    if klass is None:
        raise DataDecodeError("Unknown modelKey")

    return klass


def create_from_unifi_dict(
    data: dict[str, Any],
    api: ProtectApiClient | None = None,
    klass: type[ProtectModel] | None = None,
    model_type: ModelType | None = None,
) -> ProtectModel:
    """
    Convert a UFP JSON dict to the correct Python class.

    When ``model_type`` is provided (e.g. from WS action headers), ``modelKey``
    will be synthesised if absent (Protect 7+).

    A shallow copy of *data* is created so the caller's dict is never mutated.

    Raises ``DataDecodeError`` if the model cannot be resolved.
    """
    # Work on a shallow copy so downstream conversions cannot mutate caller data.
    data = dict(data)

    if model_type is not None:
        if klass is None:
            klass = MODEL_TO_CLASS.get(model_type)
        # Protect 7+ may omit modelKey from WS data payloads; add it if missing.
        if "modelKey" not in data:
            data["modelKey"] = model_type.value

    if "modelKey" not in data:
        raise DataDecodeError("No modelKey")

    if klass is None:
        klass = get_klass_from_dict(data)

    return klass.from_unifi_dict(**data, api=api)


def list_from_unifi_list(
    api: ProtectApiClient, unifi_list: list[dict[str, ProtectModelWithId]]
) -> list[ProtectModelWithId]:
    return [
        cast(ProtectModelWithId, create_from_unifi_dict(obj_dict, api))
        for obj_dict in unifi_list
    ]
