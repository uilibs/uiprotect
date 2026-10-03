# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_CAMERA_EXISTS, TEST_SENSOR_EXISTS
from uiprotect.data.types import MountType

if TYPE_CHECKING:
    from uiprotect.data import Camera, Light, Sensor


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_status_light(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.led_settings.is_enabled = not status

    await sensor_obj.set_status_light(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"ledSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mount_type", [MountType.DOOR, MountType.NONE])
@pytest.mark.asyncio()
async def test_sensor_set_mount_type(sensor_obj: Sensor, mount_type: MountType):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.mount_type = MountType.LEAK

    await sensor_obj.set_mount_type(mount_type)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"mountType": mount_type.value},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_paired_camera_none(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.camera_id = "bad_id"

    await sensor_obj.set_paired_camera(None)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"camera": None},
    )


@pytest.mark.skipif(
    not TEST_SENSOR_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_sensor_set_paired_camera(sensor_obj: Light, camera_obj: Camera):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.camera_id = None

    await sensor_obj.set_paired_camera(camera_obj)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"camera": camera_obj.id},
    )
