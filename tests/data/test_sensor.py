# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from tests.conftest import TEST_CAMERA_EXISTS, TEST_SENSOR_EXISTS
from uiprotect.data.types import MountType, SensorScheduleMode
from uiprotect.exceptions import BadRequest

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
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_motion_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.motion_settings.is_enabled = not status

    await sensor_obj.set_motion_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"motionSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_temperature_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.is_enabled = not status

    await sensor_obj.set_temperature_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"temperatureSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_humidity_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.is_enabled = not status

    await sensor_obj.set_humidity_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"humiditySettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_light_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.is_enabled = not status

    await sensor_obj.set_light_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"lightSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_alarm_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.alarm_settings.is_enabled = not status

    await sensor_obj.set_alarm_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"alarmSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("sensitivity", [1, 100, -10])
@pytest.mark.asyncio()
async def test_sensor_set_motion_sensitivity(
    sensor_obj: Sensor,
    sensitivity: int,
):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.motion_settings.sensitivity = 50

    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await sensor_obj.set_motion_sensitivity(sensitivity)

        assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_motion_sensitivity(sensitivity)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"motionSettings": {"sensitivity": sensitivity}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [-1.0, 0.0, 25.0])
@pytest.mark.parametrize("high", [20.0, 45.0, 50.0])
@pytest.mark.asyncio()
async def test_sensor_set_temperature_safe_range(
    sensor_obj: Sensor,
    low: float,
    high: float,
):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.low_threshold = None
    sensor_obj.temperature_settings.high_threshold = None

    if low == -1.0 or high == 50.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_temperature_safe_range(low, high)

        assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_temperature_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"temperatureSettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [0.0, 1.0, 50.0])
@pytest.mark.parametrize("high", [45.0, 99.0, 100.0])
@pytest.mark.asyncio()
async def test_sensor_set_humidity_safe_range(
    sensor_obj: Sensor,
    low: float,
    high: float,
):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.low_threshold = None
    sensor_obj.humidity_settings.high_threshold = None

    if low == 0.0 or high == 100.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_humidity_safe_range(low, high)

        assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_humidity_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"humiditySettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [0.0, 1.0, 500.0])
@pytest.mark.parametrize("high", [400.0, 1000.0, 1001.0])
@pytest.mark.asyncio()
async def test_sensor_set_light_safe_range(sensor_obj: Sensor, low: float, high: float):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.low_threshold = None
    sensor_obj.light_settings.high_threshold = None

    if low == 0.0 or high == 1001.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_light_safe_range(low, high)

        assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_light_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"lightSettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_remove_temperature_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.low_threshold = 10
    sensor_obj.temperature_settings.high_threshold = 20

    await sensor_obj.remove_temperature_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"temperatureSettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_remove_humidity_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.low_threshold = 10
    sensor_obj.humidity_settings.high_threshold = 20

    await sensor_obj.remove_humidity_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"humiditySettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_remove_light_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.low_threshold = 10
    sensor_obj.light_settings.high_threshold = 20

    await sensor_obj.remove_light_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"lightSettings": {"lowThreshold": None, "highThreshold": None}},
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


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_name_public(sensor_obj: Sensor):
    updated = Mock()
    updated.name = "Renamed"
    sensor_obj.api.update_sensor_public = AsyncMock(return_value=updated)

    await sensor_obj.set_name_public("Renamed")

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, name="Renamed"
    )
    assert sensor_obj.name == "Renamed"


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "attr",
    ["temperature", "humidity", "light"],
)
@pytest.mark.asyncio()
async def test_sensor_set_threshold_settings_public(sensor_obj: Sensor, attr: str):
    sensor_obj.api.update_sensor_public = AsyncMock()
    setter = getattr(sensor_obj, f"set_{attr}_settings_public")

    await setter(is_enabled=True, low_threshold=5, high_threshold=20, margin=2)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id,
        **{
            f"{attr}_settings": {
                "isEnabled": True,
                "lowThreshold": 5,
                "highThreshold": 20,
                "margin": 2,
            }
        },
    )
    local = getattr(sensor_obj, f"{attr}_settings")
    assert local.is_enabled is True
    assert local.low_threshold == 5
    assert local.high_threshold == 20
    assert local.margin == 2


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "attr",
    ["temperature", "humidity", "light"],
)
@pytest.mark.asyncio()
async def test_sensor_set_threshold_settings_public_requires_arg(
    sensor_obj: Sensor, attr: str
):
    sensor_obj.api.update_sensor_public = AsyncMock()
    setter = getattr(sensor_obj, f"set_{attr}_settings_public")

    with pytest.raises(BadRequest):
        await setter()

    assert not sensor_obj.api.update_sensor_public.called


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_motion_settings_public(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_motion_settings_public(
        is_enabled=True, sensitivity=70, sensitivity_when_armed=90
    )

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id,
        motion_settings={
            "isEnabled": True,
            "sensitivity": 70,
            "sensitivityWhenArmed": 90,
        },
    )
    assert sensor_obj.motion_settings.is_enabled is True
    assert sensor_obj.motion_settings.sensitivity == 70


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_motion_settings_public_requires_arg(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    with pytest.raises(BadRequest):
        await sensor_obj.set_motion_settings_public()

    assert not sensor_obj.api.update_sensor_public.called


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_glass_break_settings_public(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_glass_break_settings_public(
        is_enabled=True, sensitivity=55, sensitivity_when_armed=65
    )

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id,
        glass_break_settings={
            "isEnabled": True,
            "sensitivity": 55,
            "sensitivityWhenArmed": 65,
        },
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_glass_break_settings_public_requires_arg(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    with pytest.raises(BadRequest):
        await sensor_obj.set_glass_break_settings_public()

    assert not sensor_obj.api.update_sensor_public.called


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("field", ["sensitivity", "sensitivity_when_armed"])
@pytest.mark.parametrize("value", [-1, 101, 150])
@pytest.mark.asyncio()
async def test_sensor_set_motion_settings_public_rejects_out_of_range(
    sensor_obj: Sensor, field: str, value: int
):
    sensor_obj.api.update_sensor_public = AsyncMock()

    with pytest.raises(BadRequest):
        await sensor_obj.set_motion_settings_public(**{field: value})

    assert not sensor_obj.api.update_sensor_public.called


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_motion_settings_public_coerces_float(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_motion_settings_public(
        sensitivity=70.0, sensitivity_when_armed=90.0
    )

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id,
        motion_settings={"sensitivity": 70, "sensitivityWhenArmed": 90},
    )
    sent = sensor_obj.api.update_sensor_public.call_args.kwargs["motion_settings"]
    assert isinstance(sent["sensitivity"], int)
    assert isinstance(sent["sensitivityWhenArmed"], int)
    assert sensor_obj.motion_settings.sensitivity == 70


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("value", [-1, 101])
@pytest.mark.asyncio()
async def test_sensor_set_glass_break_settings_public_rejects_out_of_range(
    sensor_obj: Sensor, value: int
):
    sensor_obj.api.update_sensor_public = AsyncMock()

    with pytest.raises(BadRequest):
        await sensor_obj.set_glass_break_settings_public(sensitivity=value)

    assert not sensor_obj.api.update_sensor_public.called


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    ("attr", "low_bad", "low_ok", "high_bad"),
    [
        ("temperature", -40, -39, -40),
        ("temperature", 125, 124, None),
        ("humidity", 0, 1, 0),
        ("humidity", 100, 99, None),
        ("light", 0, 1, 0),
        ("light", 503193, 503192, None),
    ],
)
@pytest.mark.asyncio()
async def test_sensor_set_threshold_settings_public_rejects_out_of_range(
    sensor_obj: Sensor,
    attr: str,
    low_bad: float,
    low_ok: float,
    high_bad: float | None,
):
    sensor_obj.api.update_sensor_public = AsyncMock()
    setter = getattr(sensor_obj, f"set_{attr}_settings_public")

    with pytest.raises(BadRequest):
        await setter(low_threshold=low_bad)
    if high_bad is not None:
        with pytest.raises(BadRequest):
            await setter(high_threshold=high_bad)
    assert not sensor_obj.api.update_sensor_public.called

    # A boundary value passes, and highThreshold has no spec maximum.
    await setter(low_threshold=low_ok, high_threshold=10**9)
    assert sensor_obj.api.update_sensor_public.called


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("attr", ["humidity", "light"])
@pytest.mark.asyncio()
async def test_sensor_set_threshold_settings_public_coerces_float(
    sensor_obj: Sensor, attr: str
):
    sensor_obj.api.update_sensor_public = AsyncMock()
    setter = getattr(sensor_obj, f"set_{attr}_settings_public")

    await setter(low_threshold=30.7, high_threshold=80.9)

    sent = sensor_obj.api.update_sensor_public.call_args.kwargs[f"{attr}_settings"]
    assert sent == {"lowThreshold": 30, "highThreshold": 80}
    assert isinstance(sent["lowThreshold"], int)
    assert isinstance(sent["highThreshold"], int)
    # Local cache must match what was sent, not the un-coerced float.
    local = getattr(sensor_obj, f"{attr}_settings")
    assert local.low_threshold == 30
    assert local.high_threshold == 80


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_alarm_public(sensor_obj: Sensor, enabled: bool):
    sensor_obj.api.update_sensor_public = AsyncMock()
    sensor_obj.alarm_settings.is_enabled = not enabled

    await sensor_obj.set_alarm_public(enabled)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, alarm_settings={"isEnabled": enabled}
    )
    assert sensor_obj.alarm_settings.is_enabled is enabled


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_schedule_mode_public(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_schedule_mode_public(SensorScheduleMode.WHEN_ARMED)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, schedule_mode=SensorScheduleMode.WHEN_ARMED
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_arm_profile_ids_public(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_arm_profile_ids_public(["a", "b"])

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, arm_profile_ids=["a", "b"]
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_custom_sensitivity_when_armed_public(
    sensor_obj: Sensor, enabled: bool
):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_custom_sensitivity_when_armed_public(enabled)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, has_custom_sensitivity_when_armed=enabled
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_motion_status_public(sensor_obj: Sensor, enabled: bool):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_motion_status_public(enabled)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, motion_settings={"isEnabled": enabled}
    )
    assert sensor_obj.motion_settings.is_enabled is enabled


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_set_motion_sensitivity_public(sensor_obj: Sensor):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_motion_sensitivity_public(42)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, motion_settings={"sensitivity": 42}
    )
    assert sensor_obj.motion_settings.sensitivity == 42


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("attr", ["temperature", "humidity", "light"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_threshold_status_public(
    sensor_obj: Sensor, attr: str, enabled: bool
):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await getattr(sensor_obj, f"set_{attr}_status_public")(enabled)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, **{f"{attr}_settings": {"isEnabled": enabled}}
    )
    assert getattr(sensor_obj, f"{attr}_settings").is_enabled is enabled


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio()
async def test_sensor_set_glass_break_status_public(sensor_obj: Sensor, enabled: bool):
    sensor_obj.api.update_sensor_public = AsyncMock()

    await sensor_obj.set_glass_break_status_public(enabled)

    sensor_obj.api.update_sensor_public.assert_called_once_with(
        sensor_obj.id, glass_break_settings={"isEnabled": enabled}
    )
