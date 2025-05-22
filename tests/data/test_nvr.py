# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr, arg-type, list-item"

from __future__ import annotations

from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address

import pytest
from pydantic import ValidationError

from uiprotect.data import (
    NVR,
    AnalyticsOption,
    DoorbellMessage,
    DoorbellMessageType,
    RecordingMode,
)
from uiprotect.data.nvr import NVRSmartDetection
from uiprotect.data.types import SmartDetectObjectType
from uiprotect.exceptions import BadRequest
from uiprotect.utils import to_ms


@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio()
async def test_nvr_set_insights(nvr_obj: NVR, status: bool):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.is_insights_enabled = not status

    await nvr_obj.set_insights(status)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"isInsightsEnabled": status},
    )


@pytest.mark.asyncio()
async def test_nvr_set_anonymous_analytics(nvr_obj: NVR):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.analytics_data = AnalyticsOption.ANONYMOUS

    await nvr_obj.set_anonymous_analytics(False)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"analyticsData": "none"},
    )


@pytest.mark.asyncio()
async def test_nvr_set_default_reset_timeout(nvr_obj: NVR):
    nvr_obj.api.api_request.reset_mock()

    duration = timedelta(seconds=10)
    await nvr_obj.set_default_reset_timeout(duration)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"doorbellSettings": {"defaultMessageResetTimeoutMs": to_ms(duration)}},
    )


@pytest.mark.parametrize("message", ["Test", "fqthpqBgVMKXp9jXX2VeuGeXYfx2mMjB"])
@pytest.mark.asyncio()
async def test_nvr_set_default_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    if len(message) > 30:
        with pytest.raises(ValidationError):
            await nvr_obj.set_default_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.set_default_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr",
            method="patch",
            json={"doorbellSettings": {"defaultMessageText": message}},
        )


@pytest.mark.parametrize(
    "message",
    ["Welcome", "Test", "fqthpqBgVMKXp9jXX2VeuGeXYfx2mMjB"],
)
@pytest.mark.asyncio()
async def test_nvr_add_custom_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.doorbell_settings.custom_messages = ["Welcome"]

    if message != "Test":
        with pytest.raises(BadRequest):
            await nvr_obj.add_custom_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.add_custom_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr",
            method="patch",
            json={"doorbellSettings": {"customMessages": ["Welcome", "Test"]}},
        )

        assert nvr_obj.doorbell_settings.all_messages == [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.CUSTOM_MESSAGE,
                text="Welcome",
            ),
            DoorbellMessage(
                type=DoorbellMessageType.CUSTOM_MESSAGE,
                text="Test",
            ),
        ]


@pytest.mark.parametrize("message", ["Welcome", "Test"])
@pytest.mark.asyncio()
async def test_nvr_remove_custom_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.doorbell_settings.custom_messages = ["Welcome"]

    if message == "Test":
        with pytest.raises(BadRequest):
            await nvr_obj.remove_custom_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.remove_custom_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr",
            method="patch",
            json={"doorbellSettings": {"customMessages": []}},
        )

        assert nvr_obj.doorbell_settings.all_messages == [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
            ),
        ]


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("192.168.1.1", IPv4Address("192.168.1.1")),
        ("fe80::1ff:fe23:4567:890a", IPv6Address("fe80::1ff:fe23:4567:890a")),
    ],
)
@pytest.mark.asyncio()
async def test_nvr_wan_ip(nvr_obj: NVR, ip: str, expected: IPv4Address | IPv6Address):
    nvr_dict = nvr_obj.unifi_dict()
    nvr_dict["wanIp"] = ip

    nvr = NVR.from_unifi_dict(**nvr_dict)
    assert nvr.wan_ip == expected
    assert nvr.unifi_dict()["wanIp"] == ip


@pytest.mark.asyncio()
async def test_nvr_set_smart_detections(nvr_obj: NVR):
    nvr_obj.smart_detection = NVRSmartDetection(
        enable=False,
        face_recognition=False,
        license_plate_recognition=False,
    )
    nvr_obj.api.api_request.reset_mock()

    await nvr_obj.set_smart_detections(True)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"smartDetection": {"enable": True}},
    )


@pytest.mark.asyncio()
async def test_nvr_set_face_recognition(nvr_obj: NVR):
    nvr_obj.smart_detection = NVRSmartDetection(
        enable=True,
        face_recognition=False,
        license_plate_recognition=False,
    )
    nvr_obj.api.api_request.reset_mock()

    await nvr_obj.set_face_recognition(True)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"smartDetection": {"faceRecognition": True}},
    )


@pytest.mark.asyncio()
async def test_nvr_set_face_recognition_no_smart(nvr_obj: NVR):
    nvr_obj.smart_detection = NVRSmartDetection(
        enable=False,
        face_recognition=False,
        license_plate_recognition=False,
    )
    nvr_obj.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await nvr_obj.set_face_recognition(True)

    assert not nvr_obj.api.api_request.called


@pytest.mark.asyncio()
async def test_nvr_set_license_plate_recognition(nvr_obj: NVR):
    nvr_obj.smart_detection = NVRSmartDetection(
        enable=True,
        face_recognition=False,
        license_plate_recognition=False,
    )
    nvr_obj.api.api_request.reset_mock()

    await nvr_obj.set_license_plate_recognition(True)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"smartDetection": {"licensePlateRecognition": True}},
    )


@pytest.mark.asyncio()
async def test_nvr_set_license_plate_recognition_no_smart(nvr_obj: NVR):
    nvr_obj.smart_detection = NVRSmartDetection(
        enable=False,
        face_recognition=False,
        license_plate_recognition=False,
    )
    nvr_obj.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await nvr_obj.set_license_plate_recognition(True)

    assert not nvr_obj.api.api_request.called


def test_nvr_is_global_face_detection_on(nvr_obj: NVR) -> None:
    from unittest.mock import Mock

    # Temporarily disable validation for NVR model
    original_validate_assignment = NVR.model_config.get("validate_assignment", True)
    NVR.model_config["validate_assignment"] = False

    try:
        # Create mock global camera settings if they don't exist
        if nvr_obj.global_camera_settings is None:
            nvr_obj.global_camera_settings = Mock()
            nvr_obj.global_camera_settings.recording_settings = Mock()
            nvr_obj.global_camera_settings.smart_detect_settings = Mock()

        # Test when global face detection is enabled
        nvr_obj.global_camera_settings.recording_settings.mode = RecordingMode.ALWAYS
        nvr_obj.global_camera_settings.smart_detect_settings.object_types = [
            SmartDetectObjectType.FACE
        ]
        assert nvr_obj.is_global_face_detection_on is True

        # Test when global face detection is disabled
        nvr_obj.global_camera_settings.smart_detect_settings.object_types = []
        assert nvr_obj.is_global_face_detection_on is False

        # Test when global recording is disabled
        nvr_obj.global_camera_settings.recording_settings.mode = RecordingMode.NEVER
        nvr_obj.global_camera_settings.smart_detect_settings.object_types = [
            SmartDetectObjectType.FACE
        ]
        assert nvr_obj.is_global_face_detection_on is False

        # Test with mixed object types
        nvr_obj.global_camera_settings.recording_settings.mode = RecordingMode.ALWAYS
        nvr_obj.global_camera_settings.smart_detect_settings.object_types = [
            SmartDetectObjectType.PERSON,
            SmartDetectObjectType.FACE,
            SmartDetectObjectType.VEHICLE,
        ]
        assert nvr_obj.is_global_face_detection_on is True
    finally:
        # Restore original validation setting
        NVR.model_config["validate_assignment"] = original_validate_assignment
