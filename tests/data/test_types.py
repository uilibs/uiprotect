from __future__ import annotations

import typing

import pytest

from uiprotect.data.types import (
    AudioStyle,
    HDRMode,
    IRLEDMode,
    ModelType,
    MountPosition,
    MountType,
    PermissionNode,
    SensorStatusType,
    SensorType,
    StorageType,
    get_field_type,
)


@pytest.mark.asyncio()
async def test_model_type_from_string():
    assert ModelType.from_string("camera") is ModelType.CAMERA
    assert ModelType.from_string("invalid") is ModelType.UNKNOWN


@pytest.mark.parametrize(
    ("enum_cls", "known_value", "known_member"),
    [
        (AudioStyle, "nature", AudioStyle.NATURE),
        (HDRMode, "normal", HDRMode.NORMAL),
        (IRLEDMode, "auto", IRLEDMode.AUTO),
        (MountType, "door", MountType.DOOR),
        (SensorType, "temperature", SensorType.TEMPERATURE),
        (SensorStatusType, "safe", SensorStatusType.SAFE),
        (MountPosition, "ceiling", MountPosition.CEILING),
        (StorageType, "hdd", StorageType.DISK),
        (PermissionNode, "read", PermissionNode.READ),
    ],
)
def test_unknown_values_enum_known_value(enum_cls, known_value, known_member):
    """Known values resolve to their correct enum member."""
    assert enum_cls(known_value) is known_member


@pytest.mark.parametrize(
    "enum_cls",
    [
        AudioStyle,
        HDRMode,
        IRLEDMode,
        MountType,
        SensorType,
        SensorStatusType,
        MountPosition,
        StorageType,
        PermissionNode,
    ],
)
def test_unknown_values_enum_falls_back_to_unknown(enum_cls):
    """Unknown values fall back to UNKNOWN instead of raising ValueError."""
    result = enum_cls("completely_new_firmware_value")
    assert result.name == "UNKNOWN"


@pytest.mark.parametrize(
    ("annotation", "origin", "type_"),
    [
        (bytearray, None, bytearray),
        (typing.get_origin(dict[str, int]), None, dict),
        (dict, None, dict),
        # Extract value type from list, set, dict
        (list[int], list, int),
        (set[int], set, int),
        (dict[str, int], dict, int),
        # Extract type from Annotated
        (typing.Annotated[int, "Hello World"], None, int),
        # Remove '| None' from Union and extract remaining value type
        (int | None, None, int),
        (list[int] | None, list, int),
        (typing.Annotated[int, "Hello World"] | None, None, int),
        # Leave 'normal' unions as is
        (int | str, None, int | str),
        (int | str | bytes, None, int | str | bytes),
    ],
)
def test_get_field_type(annotation, origin, type_):
    res = get_field_type(annotation)
    assert origin == res[0]
    assert type_ == res[1]


def test_get_field_type_error():
    with pytest.raises(ValueError, match="Type annotation cannot be None"):
        get_field_type(None)
