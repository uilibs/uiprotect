"""UniFi Protect Data Conversion."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from uiprotect.data.base import ProtectModelWithId

from ..exceptions import DataDecodeError
from .devices import (
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
) -> ProtectModelWithId:
    """
    Helper method to read the `modelKey` from a UFP JSON dict and convert to currect Python class.
    Will raise `DataDecodeError` if the `modelKey` is for an unknown object.
    """
    if "modelKey" not in data:
        raise DataDecodeError("No modelKey")

    if model_type is not None and klass is None:
        klass = MODEL_TO_CLASS.get(model_type)

    if klass is None:
        klass = get_klass_from_dict(data)

    return klass.from_unifi_dict(**data, api=api)


def dict_from_unifi_list(
    api: ProtectApiClient, unifi_list: list[dict[str, ProtectModelWithId]]
) -> dict[str, ProtectModelWithId]:
    return_dict: dict[str, Any] = {}
    for obj_dict in unifi_list:
        obj = create_from_unifi_dict(obj_dict, api)
        return_dict[obj.id] = obj
    return return_dict
