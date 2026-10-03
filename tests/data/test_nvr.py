# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr, arg-type, list-item"

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address
from unittest.mock import Mock

import pytest

from uiprotect.data import (
    NVR,
    AnalyticsOption,
    DoorbellMessage,
    DoorbellMessageType,
    Event,
    EventType,
)
from uiprotect.data.nvr import StorageDevice
from uiprotect.data.types import SmartDetectObjectType
from uiprotect.exceptions import BadRequest


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, {"model": None, "size": None, "healthy": None}),  # empty slot
        (
            {"model": "ST4000VN008", "size": 4000787030016, "healthy": True},
            {"model": "ST4000VN008", "size": 4000787030016, "healthy": True},
        ),
        ({"healthy": "OK"}, {"healthy": "OK"}),  # string healthy value
        ({"model": "TestModel"}, {"model": "TestModel", "size": None}),  # partial
    ],
)
def test_storage_device(data: dict, expected: dict):
    """Test StorageDevice handles empty slots and various field types (Protect 6.x+)."""
    device = StorageDevice.from_unifi_dict(**data)
    for key, value in expected.items():
        assert getattr(device, key) == value


def test_event_unknown_smart_detect_type_dropped() -> None:
    """An unknown ``smartDetectTypes`` entry is dropped rather than aborting parsing."""
    event = Event.from_unifi_dict(
        api=Mock(),
        id="evt-1",
        modelKey="event",
        type=EventType.SMART_DETECT.value,
        start=1735689600000,
        score=0,
        smartDetectTypes=["person", "linecrossing_basic"],
    )
    assert event.smart_detect_types == [SmartDetectObjectType.PERSON]


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
