# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_CAMERA_EXISTS, TEST_LIGHT_EXISTS
from uiprotect.data.public_devices import (
    PublicLight,
    PublicLightDeviceSettings,
    PublicLightModeSettings,
)

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
@pytest.mark.asyncio()
async def test_light_concurrent_setters_send_one_patch(light_obj: Light) -> None:
    """A setter queued while another waits takes over and sends one PATCH."""
    light_obj.api.api_request.reset_mock()
    light_obj.is_ssh_enabled = False

    first = asyncio.create_task(light_obj.set_ssh(True))
    # land inside the first setter's 50 ms coalescing window
    await asyncio.sleep(0.01)
    await light_obj.set_name("Renamed")
    await first

    light_obj.api.api_request.assert_called_once_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"isSshEnabled": True, "name": "Renamed"},
    )


@pytest.mark.parametrize(
    ("pir_duration", "expected"),
    [(None, None), (60000, 60), (15000, 15), (30499, 30), (30500, 30), (30501, 31)],
)
def test_public_light_pir_duration_seconds(
    pir_duration: int | None, expected: int | None
) -> None:
    settings = PublicLightDeviceSettings.from_unifi_dict(
        isIndicatorEnabled=True, pirDuration=pir_duration
    )

    assert settings.pir_duration == pir_duration
    assert settings.pir_duration_seconds == expected
