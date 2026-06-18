# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from tests.conftest import (
    TEST_AIR_QUALITY_SENSOR_EXISTS,
    TEST_CAMERA_EXISTS,
    TEST_SENSOR_EXISTS,
    read_json_file,
)
from uiprotect.data import create_from_unifi_dict
from uiprotect.data.types import MountType, SensorRingLedMetric, SensorStatusType
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.data import Camera, Light, Sensor


@pytest.mark.skipif(
    not TEST_AIR_QUALITY_SENSOR_EXISTS,
    reason="Missing air quality sensor testdata",
)
def test_air_quality_sensor_from_private_payload():
    sensor = create_from_unifi_dict(read_json_file("sample_up_airquality_sensor"))

    assert sensor.air_quality is not None
    assert sensor.air_quality.co2 is not None
    assert sensor.air_quality.co2.value == 670
    assert sensor.air_quality.co2.status is SensorStatusType.NEUTRAL
    assert sensor.air_quality.pm25 is not None
    assert sensor.air_quality.pm25.value == 3
    assert sensor.air_quality.pm10 is not None
    assert sensor.air_quality.pm10.value == 5
    assert sensor.air_quality.temperature is not None
    assert sensor.air_quality.temperature.value == 21.4
    assert sensor.air_quality.humidity is not None
    assert sensor.air_quality.humidity.value == 42

    assert sensor.air_quality_settings is not None
    assert sensor.air_quality_settings.ring_led_brightness == 75
    assert sensor.air_quality_settings.ring_led_metric is SensorRingLedMetric.CO2
    assert sensor.air_quality_settings.night_mode_enabled is True
    assert sensor.air_quality_settings.night_mode_start_time == "22:00"
    assert sensor.air_quality_settings.night_mode_end_time == "06:00"
    assert sensor.air_quality_settings.reading_interval == 15
    assert sensor.air_quality_settings.co2 is not None
    assert sensor.air_quality_settings.co2.is_enabled is True
    assert sensor.air_quality_settings.co2.high_threshold == 1000
    assert sensor.air_quality_settings.pm25 is not None
    assert sensor.air_quality_settings.pm25.high_threshold == 25
    assert sensor.air_quality_settings.vape_sensitivity_settings is not None
    assert sensor.air_quality_settings.vape_sensitivity_settings.is_enabled is True
    assert sensor.air_quality_settings.vape_sensitivity_settings.sensitivity == 50
    assert sensor.air_quality_settings.temperature is not None
    assert sensor.air_quality_settings.temperature.low_threshold == 15

    sensor_dict = sensor.unifi_dict()
    assert sensor_dict["airQuality"]["co2"] == {
        "value": 670,
        "status": "neutral",
    }
    assert sensor_dict["airQuality"]["pm2p5"] == {
        "value": 3,
        "status": "neutral",
    }
    assert sensor_dict["airQualitySettings"]["ringLedBrightness"] == 75
    assert sensor_dict["airQualitySettings"]["co2Settings"] == {
        "isEnabled": True,
        "lowThreshold": None,
        "highThreshold": 1000,
    }
    assert sensor_dict["airQualitySettings"]["pm2p5Settings"] == {
        "isEnabled": True,
        "lowThreshold": None,
        "highThreshold": 25,
    }
    assert sensor_dict["airQualitySettings"]["vapeSensitivitySettings"] == {
        "isEnabled": True,
        "sensitivity": 50,
    }


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
def test_legacy_sensor_without_air_quality_fields(sensor):
    sensor_obj = create_from_unifi_dict(deepcopy(sensor))

    assert sensor_obj.air_quality is None
    assert sensor_obj.air_quality_settings is None

    # Existing (non-air-quality) sensors must serialize without the new keys so
    # their wire payload is unchanged.
    sensor_dict = sensor_obj.unifi_dict()
    assert "airQuality" not in sensor_dict
    assert "airQualitySettings" not in sensor_dict


@pytest.mark.skipif(
    not TEST_AIR_QUALITY_SENSOR_EXISTS,
    reason="Missing air quality sensor testdata",
)
def test_air_quality_ring_led_metric_unknown_value():
    data = read_json_file("sample_up_airquality_sensor")
    data["airQualitySettings"]["ringLedMetric"] = 7

    sensor = create_from_unifi_dict(data)

    assert sensor.air_quality_settings is not None
    assert sensor.air_quality_settings.ring_led_metric is SensorRingLedMetric.UNKNOWN


@pytest.mark.skipif(
    not TEST_AIR_QUALITY_SENSOR_EXISTS,
    reason="Missing air quality sensor testdata",
)
@pytest.mark.asyncio()
async def test_sensor_set_ring_led_brightness(air_quality_sensor_obj: Sensor):
    air_quality_sensor_obj.api.api_request.reset_mock()
    air_quality_sensor_obj.air_quality_settings.ring_led_brightness = 50

    await air_quality_sensor_obj.set_ring_led_brightness(80)

    air_quality_sensor_obj.api.api_request.assert_called_with(
        f"sensors/{air_quality_sensor_obj.id}",
        method="patch",
        json={"airQualitySettings": {"ringLedBrightness": 80}},
    )


@pytest.mark.skipif(
    not TEST_AIR_QUALITY_SENSOR_EXISTS,
    reason="Missing air quality sensor testdata",
)
@pytest.mark.asyncio()
async def test_sensor_set_ring_led_metric(air_quality_sensor_obj: Sensor):
    air_quality_sensor_obj.api.api_request.reset_mock()
    air_quality_sensor_obj.air_quality_settings.ring_led_metric = (
        SensorRingLedMetric.CO2
    )

    await air_quality_sensor_obj.set_ring_led_metric(SensorRingLedMetric.AIR_QUALITY)

    air_quality_sensor_obj.api.api_request.assert_called_with(
        f"sensors/{air_quality_sensor_obj.id}",
        method="patch",
        json={"airQualitySettings": {"ringLedMetric": 1}},
    )


@pytest.mark.skipif(
    not TEST_AIR_QUALITY_SENSOR_EXISTS,
    reason="Missing air quality sensor testdata",
)
@pytest.mark.asyncio()
async def test_sensor_set_night_mode(air_quality_sensor_obj: Sensor):
    air_quality_sensor_obj.api.api_request.reset_mock()
    air_quality_sensor_obj.air_quality_settings.night_mode_enabled = True

    await air_quality_sensor_obj.set_night_mode(False)

    air_quality_sensor_obj.api.api_request.assert_called_with(
        f"sensors/{air_quality_sensor_obj.id}",
        method="patch",
        json={"airQualitySettings": {"nightModeEnabled": False}},
    )


@pytest.mark.skipif(
    not TEST_AIR_QUALITY_SENSOR_EXISTS,
    reason="Missing air quality sensor testdata",
)
@pytest.mark.asyncio()
async def test_sensor_set_night_mode_brightness(air_quality_sensor_obj: Sensor):
    air_quality_sensor_obj.api.api_request.reset_mock()
    air_quality_sensor_obj.air_quality_settings.night_mode_brightness = 50

    await air_quality_sensor_obj.set_night_mode_brightness(30)

    air_quality_sensor_obj.api.api_request.assert_called_with(
        f"sensors/{air_quality_sensor_obj.id}",
        method="patch",
        json={"airQualitySettings": {"nightModeBrightness": 30}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_sensor_air_quality_setters_require_air_quality(sensor_obj: Sensor):
    assert sensor_obj.air_quality_settings is None

    with pytest.raises(BadRequest):
        await sensor_obj.set_ring_led_brightness(80)


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
