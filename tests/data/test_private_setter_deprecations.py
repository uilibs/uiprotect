# mypy: disable-error-code="attr-defined, union-attr"

from __future__ import annotations

import warnings
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from tests.conftest import TEST_CAMERA_EXISTS, TEST_LIGHT_EXISTS, TEST_SENSOR_EXISTS
from uiprotect.data.types import LightModeType, VideoMode
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.data import Camera, Light, Sensor

LIGHT_SETTERS: list[tuple[str, tuple[Any, ...]]] = [
    ("set_flood_light", (True,)),
    ("set_led_level", (3,)),
    ("set_light", (True,)),
    ("set_sensitivity", (50,)),
    ("set_duration", (timedelta(seconds=60),)),
    ("set_light_settings", (LightModeType.MOTION,)),
]

CAMERA_SETTERS: list[tuple[str, tuple[Any, ...]]] = [
    ("set_person_detection", (True,)),
    ("set_vehicle_detection", (True,)),
    ("set_face_detection", (True,)),
    ("set_license_plate_detection", (True,)),
    ("set_package_detection", (True,)),
    ("set_animal_detection", (True,)),
    ("set_smoke_detection", (True,)),
    ("set_siren_detection", (True,)),
    ("set_baby_cry_detection", (True,)),
    ("set_speaking_detection", (True,)),
    ("set_bark_detection", (True,)),
    ("set_car_horn_detection", (True,)),
    ("set_glass_break_detection", (True,)),
    ("set_hdr_mode", ("auto",)),
    ("set_video_mode", (VideoMode.DEFAULT,)),
    ("set_mic_volume", (50,)),
    ("set_osd_name", (True,)),
    ("set_osd_date", (True,)),
    ("set_osd_logo", (True,)),
]

SENSOR_SETTERS: list[tuple[str, tuple[Any, ...]]] = [
    ("set_motion_sensitivity", (50,)),
]


async def _assert_deprecated(obj: Any, name: str, args: tuple[Any, ...]) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # the warning fires before any feature-flag validation
        with suppress(BadRequest):
            await getattr(obj, name)(*args)

    messages = [
        str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert f"{name} is deprecated, use {name}_public instead" in messages


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(("name", "args"), LIGHT_SETTERS)
@pytest.mark.asyncio()
async def test_light_private_setter_deprecated(
    light_obj: Light | None,
    name: str,
    args: tuple[Any, ...],
) -> None:
    """Each private Light setter with a public twin warns."""
    if light_obj is None:
        pytest.skip("No light_obj found")

    await _assert_deprecated(light_obj, name, args)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(("name", "args"), CAMERA_SETTERS)
@pytest.mark.asyncio()
async def test_camera_private_setter_deprecated(
    camera_obj: Camera | None,
    name: str,
    args: tuple[Any, ...],
) -> None:
    """Each private Camera setter with a public twin warns."""
    if camera_obj is None:
        pytest.skip("No camera_obj found")

    await _assert_deprecated(camera_obj, name, args)


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(("name", "args"), SENSOR_SETTERS)
@pytest.mark.asyncio()
async def test_sensor_private_setter_deprecated(
    sensor_obj: Sensor | None,
    name: str,
    args: tuple[Any, ...],
) -> None:
    """Each private Sensor setter with a public twin warns."""
    if sensor_obj is None:
        pytest.skip("No sensor_obj found")

    await _assert_deprecated(sensor_obj, name, args)
