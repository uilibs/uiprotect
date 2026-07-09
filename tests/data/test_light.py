# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tests.conftest import TEST_CAMERA_EXISTS, TEST_LIGHT_EXISTS
from uiprotect.data.public_devices import (
    PublicLight,
    PublicLightDeviceSettings,
    PublicLightModeSettings,
)
from uiprotect.data.types import LightModeEnableType, LightModeType
from uiprotect.exceptions import BadRequest
from uiprotect.utils import to_ms

if TYPE_CHECKING:
    from uiprotect.data import Camera, Light


def _public_light_response(
    *,
    is_light_force_enabled: bool = False,
    light_device_settings: PublicLightDeviceSettings | None = None,
    light_mode_settings: PublicLightModeSettings | None = None,
    name: str | None = None,
) -> PublicLight:
    """Build a minimal ``PublicLight`` for mocking ``update_light_public`` returns."""
    return PublicLight.model_construct(
        is_light_force_enabled=is_light_force_enabled,
        light_device_settings=light_device_settings,
        light_mode_settings=light_mode_settings,
        name=name,
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_light_set_paired_camera_none(light_obj: Light):
    light_obj.api.api_request.reset_mock()

    light_obj.camera_id = "bad_id"

    await light_obj.set_paired_camera(None)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"camera": None},
    )


@pytest.mark.skipif(
    not TEST_LIGHT_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_light_set_paired_camera(light_obj: Light, camera_obj: Camera):
    light_obj.api.api_request.reset_mock()

    light_obj.camera_id = None

    await light_obj.set_paired_camera(camera_obj)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"camera": camera_obj.id},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_light_set_flood_light(light_obj: Light, status: bool) -> None:
    light_obj.api.api_request.reset_mock()

    light_obj.light_on_settings.is_led_force_on = not status

    await light_obj.set_flood_light(status)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"lightOnSettings": {"isLedForceOn": status}},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_light_set_status_light(light_obj: Light, status: bool) -> None:
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.is_indicator_enabled = not status

    await light_obj.set_status_light(status)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"lightDeviceSettings": {"isIndicatorEnabled": status}},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 1, 3, 6, 7])
@pytest.mark.asyncio()
async def test_light_set_led_level(light_obj: Light, level: int):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.led_level = 2

    if level in {-1, 7}:
        with pytest.raises(ValidationError):
            await light_obj.set_led_level(level)
        assert not light_obj.api.api_request.called
    else:
        await light_obj.set_led_level(level)

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json={"lightDeviceSettings": {"ledLevel": level}},
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.parametrize("level", [None, -1, 1, 3, 6, 7])
@pytest.mark.asyncio()
async def test_light_set_light(light_obj: Light, status: bool, level: int | None):
    light_obj.api.api_request.reset_mock()

    light_obj.light_on_settings.is_led_force_on = not status
    if level is not None:
        light_obj.light_device_settings.led_level = 2

    if level in {-1, 7}:
        with pytest.raises(ValidationError):
            await light_obj.set_light(status, level)
        assert not light_obj.api.api_request.called
    else:
        await light_obj.set_light(status, level)

        if level is None:
            expected = {"lightOnSettings": {"isLedForceOn": status}}
        else:
            expected = {
                "lightOnSettings": {"isLedForceOn": status},
                "lightDeviceSettings": {"ledLevel": level},
            }

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("sensitivity", [1, 100, -10])
@pytest.mark.asyncio()
async def test_light_set_sensitivity(
    light_obj: Light,
    sensitivity: int,
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.pir_sensitivity = 50

    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_sensitivity(sensitivity)
        assert not light_obj.api.api_request.called
    else:
        await light_obj.set_sensitivity(sensitivity)

        expected = {"lightDeviceSettings": {"pirSensitivity": sensitivity}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "duration",
    [
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.asyncio()
async def test_light_set_duration(
    light_obj: Light,
    duration: timedelta,
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.pir_duration = timedelta(seconds=30)

    duration_invalid = duration is not None and int(duration.total_seconds()) in {
        1,
        1000,
    }
    if duration_invalid:
        with pytest.raises(BadRequest):
            await light_obj.set_duration(duration)

        assert not light_obj.api.api_request.called
    else:
        await light_obj.set_duration(duration)

        expected = {"lightDeviceSettings": {"pirDuration": to_ms(duration)}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [LightModeType.MANUAL, LightModeType.WHEN_DARK])
@pytest.mark.parametrize("enable_at", [None, LightModeEnableType.ALWAYS])
@pytest.mark.parametrize(
    "duration",
    [
        None,
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.parametrize("sensitivity", [None, 1, 100, -10])
@pytest.mark.asyncio()
async def test_light_set_light_settings(
    light_obj: Light,
    mode: LightModeType,
    enable_at: LightModeEnableType | None,
    duration: timedelta | None,
    sensitivity: int | None,
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_mode_settings.mode = LightModeType.MOTION
    light_obj.light_mode_settings.enable_at = LightModeEnableType.DARK
    light_obj.light_device_settings.pir_duration = timedelta(seconds=30)
    light_obj.light_device_settings.pir_sensitivity = 50

    duration_invalid = duration is not None and int(duration.total_seconds()) in {
        1,
        1000,
    }
    if duration_invalid:
        with pytest.raises(BadRequest):
            await light_obj.set_light_settings(
                mode,
                enable_at=enable_at,
                duration=duration,
                sensitivity=sensitivity,
            )

        assert not light_obj.api.api_request.called
    elif sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_light_settings(
                mode,
                enable_at=enable_at,
                duration=duration,
                sensitivity=sensitivity,
            )

        assert not light_obj.api.api_request.called
    else:
        await light_obj.set_light_settings(
            mode,
            enable_at=enable_at,
            duration=duration,
            sensitivity=sensitivity,
        )

        expected = {"lightModeSettings": {"mode": mode.value}}
        if enable_at is not None:
            expected["lightModeSettings"].update({"enableAt": enable_at.value})
        if duration is not None:
            expected["lightDeviceSettings"] = expected.get("lightDeviceSettings", {})
            expected["lightDeviceSettings"].update({"pirDuration": to_ms(duration)})
        if sensitivity is not None:
            expected["lightDeviceSettings"] = expected.get("lightDeviceSettings", {})
            expected["lightDeviceSettings"].update({"pirSensitivity": sensitivity})

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_light_set_name_public(light_obj: Light) -> None:
    light_obj.api.update_light_public = AsyncMock(
        return_value=_public_light_response(name="Renamed"),
    )

    await light_obj.set_name_public("Renamed")

    light_obj.api.update_light_public.assert_called_once_with(
        light_obj.id,
        name="Renamed",
    )
    assert light_obj.name == "Renamed"


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_light_set_flood_light_public(light_obj: Light, status: bool) -> None:
    light_obj.api.update_light_public = AsyncMock(
        return_value=_public_light_response(is_light_force_enabled=status),
    )

    await light_obj.set_flood_light_public(status)

    light_obj.api.update_light_public.assert_called_once_with(
        light_obj.id,
        is_light_force_enabled=status,
    )
    assert light_obj.light_on_settings.is_led_force_on is status


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_light_set_status_light_public(light_obj: Light, status: bool) -> None:
    light_obj.api.update_light_public = AsyncMock(
        return_value=_public_light_response(
            light_device_settings=PublicLightDeviceSettings(
                is_indicator_enabled=status
            ),
        ),
    )

    await light_obj.set_status_light_public(status)

    call = light_obj.api.update_light_public.call_args
    assert call.args == (light_obj.id,)
    sent = call.kwargs["light_device_settings"]
    assert sent.is_indicator_enabled is status
    assert light_obj.light_device_settings.is_indicator_enabled is status


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 1, 6, 7])
@pytest.mark.asyncio()
async def test_light_set_led_level_public(light_obj: Light, level: int) -> None:
    light_obj.api.update_light_public = AsyncMock()

    if level in {-1, 7}:
        with pytest.raises(ValidationError):
            await light_obj.set_led_level_public(level)
        assert not light_obj.api.update_light_public.called
        return

    light_obj.api.update_light_public.return_value = _public_light_response(
        light_device_settings=PublicLightDeviceSettings(
            is_indicator_enabled=light_obj.light_device_settings.is_indicator_enabled,
            led_level=level,
        ),
    )

    await light_obj.set_led_level_public(level)

    sent = light_obj.api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.led_level == level
    assert light_obj.light_device_settings.led_level == level


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_light_set_led_level_public_coerces_float(light_obj: Light) -> None:
    light_obj.api.update_light_public = AsyncMock()
    light_obj.api.update_light_public.return_value = _public_light_response(
        light_device_settings=PublicLightDeviceSettings(
            is_indicator_enabled=light_obj.light_device_settings.is_indicator_enabled,
            led_level=3,
        ),
    )

    await light_obj.set_led_level_public(3.0)

    sent = light_obj.api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.led_level == 3


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("sensitivity", [1, 100, -10])
@pytest.mark.asyncio()
async def test_light_set_sensitivity_public(light_obj: Light, sensitivity: int) -> None:
    light_obj.api.update_light_public = AsyncMock()

    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_sensitivity_public(sensitivity)
        assert not light_obj.api.update_light_public.called
        return

    light_obj.api.update_light_public.return_value = _public_light_response(
        light_device_settings=PublicLightDeviceSettings(
            is_indicator_enabled=light_obj.light_device_settings.is_indicator_enabled,
            pir_sensitivity=sensitivity,
        ),
    )

    await light_obj.set_sensitivity_public(sensitivity)

    sent = light_obj.api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.pir_sensitivity == sensitivity
    assert light_obj.light_device_settings.pir_sensitivity == sensitivity


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "duration",
    [
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.asyncio()
async def test_light_set_duration_public(light_obj: Light, duration: timedelta) -> None:
    light_obj.api.update_light_public = AsyncMock()

    if int(duration.total_seconds()) in {1, 1000}:
        with pytest.raises(BadRequest):
            await light_obj.set_duration_public(duration)
        assert not light_obj.api.update_light_public.called
        return

    light_obj.api.update_light_public.return_value = _public_light_response(
        light_device_settings=PublicLightDeviceSettings(
            is_indicator_enabled=light_obj.light_device_settings.is_indicator_enabled,
            pir_duration=to_ms(duration),
        ),
    )

    await light_obj.set_duration_public(duration)

    sent = light_obj.api.update_light_public.call_args.kwargs["light_device_settings"]
    assert sent.pir_duration == duration
    assert light_obj.light_device_settings.pir_duration == duration


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [LightModeType.MANUAL, LightModeType.WHEN_DARK])
@pytest.mark.parametrize("enable_at", [None, LightModeEnableType.ALWAYS])
@pytest.mark.asyncio()
async def test_light_set_light_mode_public(
    light_obj: Light,
    mode: LightModeType,
    enable_at: LightModeEnableType | None,
) -> None:
    response_enable_at = (
        enable_at if enable_at is not None else light_obj.light_mode_settings.enable_at
    )
    light_obj.api.update_light_public = AsyncMock(
        return_value=_public_light_response(
            light_mode_settings=PublicLightModeSettings(
                mode=mode, enable_at=response_enable_at
            ),
        ),
    )

    original_enable_at = light_obj.light_mode_settings.enable_at

    await light_obj.set_light_mode_public(mode, enable_at=enable_at)

    sent = light_obj.api.update_light_public.call_args.kwargs["light_mode_settings"]
    assert sent.mode == mode
    if enable_at is not None:
        assert sent.enable_at == enable_at
    else:
        assert sent.enable_at == original_enable_at
    assert light_obj.light_mode_settings.mode == mode


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "duration",
    [
        None,
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=60),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.parametrize("sensitivity", [None, 1, 100, -10])
@pytest.mark.parametrize("enable_at", [None, LightModeEnableType.ALWAYS])
@pytest.mark.asyncio()
async def test_light_set_light_settings_public(
    light_obj: Light,
    duration: timedelta | None,
    sensitivity: int | None,
    enable_at: LightModeEnableType | None,
) -> None:
    light_obj.api.update_light_public = AsyncMock()

    duration_invalid = duration is not None and int(duration.total_seconds()) in {
        1,
        1000,
    }
    if duration_invalid:
        with pytest.raises(BadRequest):
            await light_obj.set_light_settings_public(
                LightModeType.MOTION,
                enable_at=enable_at,
                duration=duration,
                sensitivity=sensitivity,
            )
        assert not light_obj.api.update_light_public.called
        return
    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_light_settings_public(
                LightModeType.MOTION,
                enable_at=enable_at,
                duration=duration,
                sensitivity=sensitivity,
            )
        assert not light_obj.api.update_light_public.called
        return

    response_enable_at = (
        enable_at if enable_at is not None else light_obj.light_mode_settings.enable_at
    )
    updated_mode = PublicLightModeSettings(
        mode=LightModeType.MOTION, enable_at=response_enable_at
    )

    has_device_update = duration is not None or sensitivity is not None
    updated_device = (
        PublicLightDeviceSettings(
            is_indicator_enabled=light_obj.light_device_settings.is_indicator_enabled,
            pir_duration=to_ms(duration) if duration is not None else None,
            pir_sensitivity=sensitivity,
        )
        if has_device_update
        else None
    )

    light_obj.api.update_light_public.return_value = _public_light_response(
        light_mode_settings=updated_mode,
        light_device_settings=updated_device,
    )

    await light_obj.set_light_settings_public(
        LightModeType.MOTION,
        enable_at=enable_at,
        duration=duration,
        sensitivity=sensitivity,
    )

    kwargs = light_obj.api.update_light_public.call_args.kwargs
    assert kwargs["light_mode_settings"].mode == LightModeType.MOTION
    if enable_at is not None:
        assert kwargs["light_mode_settings"].enable_at == enable_at
    if has_device_update:
        assert kwargs["light_device_settings"] is not None
        if duration is not None:
            assert kwargs["light_device_settings"].pir_duration == duration
        if sensitivity is not None:
            assert kwargs["light_device_settings"].pir_sensitivity == sensitivity
    else:
        assert kwargs["light_device_settings"] is None
