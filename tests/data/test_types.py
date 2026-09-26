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
    OsdOverlayLocation,
    PermissionNode,
    SensorStatusType,
    SensorType,
    SmartDetectObjectType,
    StorageType,
    VideoMode,
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
        (IRLEDMode, "customFilterOnly", IRLEDMode.CUSTOM_FILTER_ONLY),
        (MountType, "door", MountType.DOOR),
        (SensorType, "temperature", SensorType.TEMPERATURE),
        (SensorStatusType, "safe", SensorStatusType.SAFE),
        (MountPosition, "ceiling", MountPosition.CEILING),
        (StorageType, "hdd", StorageType.DISK),
        (PermissionNode, "read", PermissionNode.READ),
        (OsdOverlayLocation, "topLeft", OsdOverlayLocation.TOP_LEFT),
        (OsdOverlayLocation, "bottomRight", OsdOverlayLocation.BOTTOM_RIGHT),
        (VideoMode, "default", VideoMode.DEFAULT),
        (VideoMode, "lprReflex", VideoMode.LPR_REFLEX),
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
        OsdOverlayLocation,
        VideoMode,
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


@pytest.mark.parametrize(
    ("value", "has_audio", "slug"),
    [
        (SmartDetectObjectType.PERSON, False, "person"),
        (SmartDetectObjectType.ANIMAL, False, "animal"),
        (SmartDetectObjectType.VEHICLE, False, "vehicle"),
        (SmartDetectObjectType.LICENSE_PLATE, False, "license_plate"),
        (SmartDetectObjectType.PACKAGE, False, "package"),
        (SmartDetectObjectType.SMOKE, True, "smoke"),
        (SmartDetectObjectType.CMONX, True, "cmonx"),
        (SmartDetectObjectType.SIREN, True, "siren"),
        (SmartDetectObjectType.BABY_CRY, True, "baby_cry"),
        (SmartDetectObjectType.SPEAK, True, "speak"),
        (SmartDetectObjectType.BARK, True, "bark"),
        (SmartDetectObjectType.BURGLAR, True, "burglar"),
        (SmartDetectObjectType.CAR_HORN, True, "car_horn"),
        (SmartDetectObjectType.GLASS_BREAK, True, "glass_break"),
        (SmartDetectObjectType.FACE, False, "face"),
        (SmartDetectObjectType.CAR, False, "car"),
        (SmartDetectObjectType.PET, False, "pet"),
    ],
)
def test_smart_detect_object_type_audio_type_and_slug(
    value: SmartDetectObjectType, has_audio: bool, slug: str
) -> None:
    assert (value.audio_type is not None) is has_audio
    assert value.slug == slug


def test_smart_detect_object_type_slugs_cover_all_members_uniquely() -> None:
    slugs = [member.slug for member in SmartDetectObjectType]
    assert len(slugs) == len(set(slugs)) == 17
