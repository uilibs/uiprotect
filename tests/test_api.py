"""Tests for uiprotect.unifi_protect_server."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import orjson
import pytest
from PIL import Image

from tests.conftest import (
    TEST_BRIDGE_EXISTS,
    TEST_CAMERA_EXISTS,
    TEST_HEATMAP_EXISTS,
    TEST_LIGHT_EXISTS,
    TEST_LIVEVIEW_EXISTS,
    TEST_PUBLIC_API_SNAPSHOT_EXISTS,
    TEST_SENSOR_EXISTS,
    TEST_SMART_TRACK_EXISTS,
    TEST_SNAPSHOT_EXISTS,
    TEST_THUMBNAIL_EXISTS,
    TEST_VIDEO_EXISTS,
    TEST_VIEWPORT_EXISTS,
    MockDatetime,
    compare_objs,
    get_time,
    validate_video_file,
)
from tests.sample_data.constants import CONSTANTS
from uiprotect.api import ProtectApiClient, RTSPSStreams, get_user_hash
from uiprotect.data import (
    Camera,
    Event,
    EventType,
    ModelType,
    PTZPatrol,
    PTZPreset,
    create_from_unifi_dict,
)
from uiprotect.data.devices import LEDSettings
from uiprotect.data.types import Version, VideoMode
from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from uiprotect.stream import TalkbackSession
from uiprotect.utils import decode_token_cookie, to_js_time

from .common import assert_equal_dump

OLD_VERSION = Version("1.2.3")
NFC_FINGERPRINT_SUPPORT_VERSION = Version("5.1.57")

if TYPE_CHECKING:
    from uiprotect.data.base import ProtectAdoptableDeviceModel
    from uiprotect.data.bootstrap import Bootstrap


async def check_motion_event(event: Event):
    data = await event.get_thumbnail()
    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}

    data = await event.get_heatmap()
    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


async def check_camera(camera: Camera):
    if camera.last_motion_event is not None:
        await check_motion_event(camera.last_motion_event)

    if camera.last_smart_detect_event is not None:
        await check_motion_event(camera.last_smart_detect_event)

    assert camera.last_nfc_card_scanned is None
    assert camera.last_fingerprint_identified is None

    for channel in camera.channels:
        assert channel._api is not None

    data = await camera.get_snapshot()
    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}

    pub_data = await camera.get_public_api_snapshot()
    assert pub_data is not None
    pub_img = Image.open(BytesIO(pub_data))
    assert pub_img.format in {"PNG", "JPEG"}

    camera.last_ring_event  # noqa: B018

    assert camera.timelapse_url == f"https://127.0.0.1:0/protect/timelapse/{camera.id}"
    check_device(camera)

    for channel in camera.channels:
        if channel.is_rtsp_enabled:
            for _ in range(2):
                assert (
                    channel.rtsp_url
                    == f"rtsp://{camera.api.connection_host}:7447/{channel.rtsp_alias}"
                )
                assert (
                    channel.rtsps_url
                    == f"rtsps://{camera.api.connection_host}:7441/{channel.rtsp_alias}?enableSrtp"
                )
                assert (
                    channel.rtsps_no_srtp_url
                    == f"rtsps://{camera.api.connection_host}:7441/{channel.rtsp_alias}"
                )

    if VideoMode.HIGH_FPS in camera.feature_flags.video_modes:
        assert camera.feature_flags.has_highfps
    else:
        assert not camera.feature_flags.has_highfps

    if camera.feature_flags.has_hdr:
        assert not camera.feature_flags.has_wdr
    else:
        assert camera.feature_flags.has_wdr


def check_device(device: ProtectAdoptableDeviceModel):
    assert device.protect_url == f"https://127.0.0.1:0/protect/devices/{device.id}"


async def check_bootstrap(bootstrap: Bootstrap):
    bootstrap.api._api_key = "test_api_key"
    assert bootstrap.auth_user
    assert (
        bootstrap.nvr.protect_url
        == f"https://127.0.0.1:0/protect/devices/{bootstrap.nvr.id}"
    )

    for light in bootstrap.lights.values():
        if light.camera is not None:
            await check_camera(light.camera)
        light.last_motion_event  # noqa: B018
        check_device(light)

    for camera in bootstrap.cameras.values():
        await check_camera(camera)

    for viewer in bootstrap.viewers.values():
        assert viewer.liveview
        check_device(viewer)

    for sensor in bootstrap.sensors.values():
        check_device(sensor)

    for liveview in bootstrap.liveviews.values():
        liveview.owner  # noqa: B018
        assert (
            liveview.protect_url
            == f"https://127.0.0.1:0/protect/liveview/{liveview.id}"
        )

        for slot in liveview.slots:
            expected_ids = set(slot.camera_ids).intersection(
                set(bootstrap.cameras.keys()),
            )
            assert len(expected_ids) == len(slot.cameras)

    for user in bootstrap.users.values():
        user.groups  # noqa: B018

        if user.cloud_account is not None:
            assert user.cloud_account.user == user

    for event in bootstrap.events.values():
        event.smart_detect_events  # noqa: B018

        if event.type.value in EventType.motion_events() and event.camera is not None:
            await check_motion_event(event)


def test_base_url(protect_client: ProtectApiClient):
    arg = f"{protect_client.private_ws_path}?lastUpdateId={protect_client.bootstrap.last_update_id}"

    assert protect_client.base_url == "https://127.0.0.1:0"
    assert protect_client.ws_url == f"wss://127.0.0.1:0{arg}"

    protect_client._port = 443
    protect_client._update_url()

    assert protect_client.base_url == "https://127.0.0.1"
    assert protect_client.ws_url == f"wss://127.0.0.1{arg}"


def test_api_client_creation():
    """Test we can create the object."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        debug=True,
        store_sessions=False,
    )
    assert client


def test_early_bootstrap():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        debug=True,
        store_sessions=False,
    )

    with pytest.raises(BadRequest):
        client.bootstrap  # noqa: B018


@pytest.mark.asyncio()
@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
async def test_get_is_prerelease_returns_false(protect_client: ProtectApiClient):
    protect_client._bootstrap = None

    await protect_client.update()

    assert await protect_client.bootstrap.get_is_prerelease() is False
    assert await protect_client.bootstrap.nvr.get_is_prerelease() is False


@pytest.mark.asyncio()
@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
async def test_bootstrap_get_device_from_mac(bootstrap):
    orig_bootstrap = deepcopy(bootstrap)
    mac = bootstrap["cameras"][0]["mac"]

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        debug=True,
        store_sessions=False,
    )
    client.api_request_obj = AsyncMock(side_effect=[bootstrap, orig_bootstrap])
    client.update_device = AsyncMock()

    bootstrap_obj = await client.get_bootstrap()
    camera = bootstrap_obj.get_device_from_mac(mac)

    assert camera is not None
    assert camera.mac == mac


@pytest.mark.asyncio()
@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
async def test_bootstrap_get_device_from_mac_bad_mac(bootstrap):
    orig_bootstrap = deepcopy(bootstrap)

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        debug=True,
        store_sessions=False,
    )
    client.api_request_obj = AsyncMock(side_effect=[bootstrap, orig_bootstrap])
    client.update_device = AsyncMock()

    bootstrap_obj = await client.get_bootstrap()
    camera = bootstrap_obj.get_device_from_mac("not_a_mac")

    assert camera is None


def test_connection_host(protect_client: ProtectApiClient):
    protect_client.bootstrap.nvr.hosts = [
        IPv4Address("192.168.1.1"),
        IPv4Address("192.168.2.1"),
        IPv4Address("192.168.3.1"),
        "se-gw.local",
    ]

    # mismatch between client IP and IP that NVR returns
    protect_client._connection_host = None
    protect_client._host = "192.168.10.1"
    assert protect_client.connection_host == IPv4Address("192.168.1.1")

    # same IP from client and NVR (first match)
    protect_client._connection_host = None
    protect_client._host = "192.168.1.1"
    assert protect_client.connection_host == IPv4Address("192.168.1.1")

    # same IP from client and NVR (not first match)
    protect_client._connection_host = None
    protect_client._host = "192.168.3.1"
    assert protect_client.connection_host == IPv4Address("192.168.3.1")

    # same IP from client and NVR (not first match, DNS host)
    protect_client._connection_host = None
    protect_client._host = "se-gw.local"
    assert protect_client.connection_host == "se-gw.local"


def test_connection_host_with_hostname_fallback(protect_client: ProtectApiClient):
    """Test connection_host property when host is a hostname (not IP)."""
    protect_client.bootstrap.nvr.hosts = [
        IPv4Address("192.168.1.1"),
        IPv4Address("192.168.2.1"),
        "hostname.local",
    ]

    # Hostname triggers ValueError, falls back to first host
    protect_client._connection_host = None
    protect_client._host = "unifi.local"
    assert protect_client.connection_host == IPv4Address("192.168.1.1")


@pytest.mark.parametrize(
    ("host",),
    [
        ("127.0.0.1",),
        ("2001:db8::1",),
        ("192.168.1.100",),
        ("fe80::1",),
        ("unifi.local",),
    ],
)
def test_connection_host_override(host: str):
    """Test override_connection_host stores host as-is (string)."""
    protect = ProtectApiClient(
        host,
        443,
        "test",
        "test",
        override_connection_host=True,
        store_sessions=False,
    )

    # Host is always stored as string, format_host_for_url handles formatting
    assert protect._connection_host == host
    assert isinstance(protect._connection_host, str)


@pytest.mark.asyncio()
async def test_connection_host_update_with_dns_resolution(
    protect_client: ProtectApiClient,
):
    """Test that update() resolves hostnames via ip_from_host."""
    # Setup: host is a hostname that will be resolved
    protect_client._connection_host = None
    protect_client._host = "unifi.local"

    # Create a new bootstrap object with specific hosts
    bootstrap = protect_client.bootstrap.model_copy()
    bootstrap.nvr.hosts = [
        IPv4Address("192.168.1.1"),
        IPv4Address("192.168.1.100"),
    ]

    # Mock get_bootstrap to return our custom bootstrap
    # Mock ip_from_host to return an IP that exists in nvr.hosts
    with (
        patch.object(
            protect_client, "get_bootstrap", new=AsyncMock(return_value=bootstrap)
        ),
        patch(
            "uiprotect.api.ip_from_host",
            new=AsyncMock(return_value=IPv4Address("192.168.1.100")),
        ),
    ):
        await protect_client.update()

    # Should have selected the resolved IP from nvr.hosts
    assert protect_client._connection_host == IPv4Address("192.168.1.100")


@pytest.mark.asyncio()
async def test_connection_host_update_fallback_to_first(
    protect_client: ProtectApiClient,
):
    """Test that update() falls back to first host if no match found."""
    # Setup: host won't match anything
    protect_client._connection_host = None
    protect_client._host = "unknown.local"

    # Create a new bootstrap object with specific hosts
    bootstrap = protect_client.bootstrap.model_copy()
    bootstrap.nvr.hosts = [
        IPv4Address("192.168.1.1"),
        IPv4Address("192.168.1.2"),
    ]

    # Mock get_bootstrap to return our custom bootstrap
    # Mock ip_from_host to return an IP that's NOT in nvr.hosts
    with (
        patch.object(
            protect_client, "get_bootstrap", new=AsyncMock(return_value=bootstrap)
        ),
        patch(
            "uiprotect.api.ip_from_host",
            new=AsyncMock(return_value=IPv4Address("10.0.0.1")),
        ),
    ):
        await protect_client.update()

    # Should fall back to first host
    assert protect_client._connection_host == IPv4Address("192.168.1.1")


def test_connection_host_ipv6(protect_client: ProtectApiClient):
    """Test that IPv6 addresses work correctly for connection_host."""
    protect_client.bootstrap.nvr.hosts = [
        IPv6Address("fe80::1ff:fe23:4567:890a"),
        IPv6Address("2001:db8::1"),
        IPv4Address("192.168.1.1"),
    ]

    # Test IPv6 address selection
    protect_client._connection_host = None
    protect_client._host = "192.168.10.1"
    assert protect_client.connection_host == IPv6Address("fe80::1ff:fe23:4567:890a")

    # Test matching IPv6 address
    protect_client._connection_host = None
    protect_client._host = "2001:db8::1"
    assert protect_client.connection_host == IPv6Address("2001:db8::1")


def test_rtsp_urls_with_ipv6(protect_client: ProtectApiClient):
    """Test that RTSP URLs are correctly formatted with IPv6 addresses (with brackets)."""
    # Set an IPv6 address as connection_host
    ipv6_addr = IPv6Address("fe80::1ff:fe23:4567:890a")
    protect_client._connection_host = ipv6_addr

    camera = next(iter(protect_client.bootstrap.cameras.values()))
    # Set camera's connectionHost to None so it falls back to NVR's connection_host
    camera.connection_host = None

    for channel in camera.channels:
        if channel.is_rtsp_enabled:
            # IPv6 addresses should be wrapped in brackets in URLs
            expected_host = "[fe80::1ff:fe23:4567:890a]"

            assert (
                channel.rtsp_url == f"rtsp://{expected_host}:7447/{channel.rtsp_alias}"
            )
            assert (
                channel.rtsps_url
                == f"rtsps://{expected_host}:7441/{channel.rtsp_alias}?enableSrtp"
            )
            assert (
                channel.rtsps_no_srtp_url
                == f"rtsps://{expected_host}:7441/{channel.rtsp_alias}"
            )
            break


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
def test_rtsp_urls_with_stacked_nvr(protect_client: ProtectApiClient, camera):
    """Test that RTSP URLs use camera's connectionHost in stacked NVR scenario."""
    # Simulate stacked NVR: NVR at 192.168.1.1, but camera connected via 192.168.2.100
    protect_client._connection_host = IPv4Address("192.168.1.1")
    camera["connectionHost"] = IPv4Address("192.168.2.100")

    camera_obj = Camera.from_unifi_dict(api=protect_client, **camera)

    # Verify setup
    assert camera_obj.connection_host == IPv4Address("192.168.2.100")
    assert protect_client.connection_host == IPv4Address("192.168.1.1")

    # Test all RTSP-enabled channels use camera's connectionHost
    rtsp_channels = [ch for ch in camera_obj.channels if ch.is_rtsp_enabled]
    assert rtsp_channels, "No RTSP-enabled channels found"

    for channel in rtsp_channels:
        if channel.rtsp_alias:
            assert channel.rtsp_url == f"rtsp://192.168.2.100:7447/{channel.rtsp_alias}"
            assert (
                channel.rtsps_url
                == f"rtsps://192.168.2.100:7441/{channel.rtsp_alias}?enableSrtp"
            )
            assert (
                channel.rtsps_no_srtp_url
                == f"rtsps://192.168.2.100:7441/{channel.rtsp_alias}"
            )


def test_api_client_with_ipv6():
    """Test that ProtectApiClient handles IPv6 addresses correctly in URLs."""
    # Test with IPv6 address
    protect = ProtectApiClient(
        "fe80::1",
        443,
        "test",
        "test",
        store_sessions=False,
    )

    # Check that URLs are formatted with brackets for IPv6
    assert "[fe80::1]" in str(protect._url)
    assert "[fe80::1]" in str(protect._ws_url)

    # Test with IPv6 and custom port
    protect_port = ProtectApiClient(
        "2001:db8::1",
        7443,
        "test",
        "test",
        store_sessions=False,
    )

    assert "[2001:db8::1]:7443" in str(protect_port._url)
    assert "[2001:db8::1]:7443" in str(protect_port._ws_url)


@pytest.mark.asyncio()
async def test_force_update_with_old_Version(protect_client: ProtectApiClient):
    protect_client._bootstrap = None

    await protect_client.update()

    assert protect_client.bootstrap
    original_bootstrap = protect_client.bootstrap
    protect_client._bootstrap = None
    with patch(
        "uiprotect.api.ProtectApiClient.get_bootstrap",
        AsyncMock(return_value=AsyncMock(nvr=AsyncMock(version=OLD_VERSION))),
    ) as mock:
        await protect_client.update()
        assert mock.called

    assert protect_client.bootstrap
    assert original_bootstrap != protect_client.bootstrap


@pytest.mark.asyncio()
async def test_force_update_with_nfc_fingerprint_version(
    protect_client: ProtectApiClient,
):
    protect_client._bootstrap = None

    await protect_client.update()

    assert protect_client.bootstrap
    original_bootstrap = protect_client.bootstrap
    protect_client._bootstrap = None
    with (
        patch(
            "uiprotect.api.ProtectApiClient.get_bootstrap",
            return_value=AsyncMock(
                nvr=AsyncMock(version=NFC_FINGERPRINT_SUPPORT_VERSION)
            ),
        ) as get_bootstrap_mock,
        patch(
            "uiprotect.api.ProtectApiClient.api_request_list",
            side_effect=lambda endpoint: {
                "keyrings": [
                    {
                        "deviceType": "camera",
                        "deviceId": "new_device_id_1",
                        "registryType": "fingerprint",
                        "registryId": "new_registry_id_1",
                        "lastActivity": 1733432893331,
                        "metadata": {},
                        "ulpUser": "new_ulp_user_id_1",
                        "id": "new_keyring_id_1",
                        "modelKey": "keyring",
                    }
                ],
                "ulp-users": [
                    {
                        "ulpId": "new_ulp_id_1",
                        "firstName": "localadmin",
                        "lastName": "",
                        "fullName": "localadmin",
                        "avatar": "",
                        "status": "ACTIVE",
                        "id": "new_ulp_user_id_1",
                        "modelKey": "ulpUser",
                    }
                ],
            }.get(endpoint, []),
        ) as api_request_list_mock,
    ):
        await protect_client.update()
        assert get_bootstrap_mock.called
        assert api_request_list_mock.called
        api_request_list_mock.assert_any_call("keyrings")
        api_request_list_mock.assert_any_call("ulp-users")
        assert api_request_list_mock.call_count == 2

    assert protect_client.bootstrap
    assert original_bootstrap != protect_client.bootstrap
    assert len(protect_client.bootstrap.keyrings)
    assert len(protect_client.bootstrap.ulp_users)


@pytest.mark.asyncio()
async def test_force_update_no_user_keyring_access(protect_client: ProtectApiClient):
    protect_client._bootstrap = None

    await protect_client.update()

    assert protect_client.bootstrap
    original_bootstrap = protect_client.bootstrap
    protect_client._bootstrap = None
    with (
        patch(
            "uiprotect.api.ProtectApiClient.get_bootstrap",
            return_value=AsyncMock(
                nvr=AsyncMock(version=NFC_FINGERPRINT_SUPPORT_VERSION)
            ),
        ) as get_bootstrap_mock,
        patch(
            "uiprotect.api.ProtectApiClient.api_request_list",
            side_effect=NotAuthorized,
        ) as api_request_list_mock,
    ):
        await protect_client.update()
        assert get_bootstrap_mock.called
        assert api_request_list_mock.called
        api_request_list_mock.assert_any_call("keyrings")
        api_request_list_mock.assert_any_call("ulp-users")
        assert api_request_list_mock.call_count == 2

    assert protect_client.bootstrap
    assert original_bootstrap != protect_client.bootstrap
    assert not len(protect_client.bootstrap.keyrings)
    assert not len(protect_client.bootstrap.ulp_users)


@pytest.mark.asyncio()
async def test_force_update_user_keyring_internal_error(
    protect_client: ProtectApiClient,
):
    protect_client._bootstrap = None

    await protect_client.update()

    assert protect_client.bootstrap
    protect_client._bootstrap = None
    with (
        pytest.raises(BadRequest),
        patch(
            "uiprotect.api.ProtectApiClient.get_bootstrap",
            return_value=AsyncMock(
                nvr=AsyncMock(version=NFC_FINGERPRINT_SUPPORT_VERSION)
            ),
        ),
        patch(
            "uiprotect.api.ProtectApiClient.api_request_list",
            side_effect=BadRequest,
        ),
    ):
        await protect_client.update()


@pytest.mark.asyncio()
async def test_get_nvr(protect_client: ProtectApiClient, nvr):
    """Verifies the `get_nvr` method"""
    nvr_obj = await protect_client.get_nvr()
    nvr_dict = nvr_obj.unifi_dict()

    compare_objs(ModelType.NVR.value, nvr, nvr_dict)


@pytest.mark.asyncio()
async def test_bootstrap(protect_client: ProtectApiClient):
    """Verifies lookup of all object via ID"""
    await check_bootstrap(protect_client.bootstrap)


@pytest.mark.asyncio()
async def test_bootstrap_cached_property(protect_client: ProtectApiClient):
    """Test cached property works with bootstrap."""
    bootstrap = protect_client.bootstrap

    assert bootstrap.has_doorbell is True
    bootstrap.cameras = {}
    assert bootstrap.has_doorbell is True
    bootstrap._has_doorbell = None
    assert bootstrap.has_doorbell is False


@pytest.mark.asyncio()
async def test_bootstrap_construct(protect_client_no_debug: ProtectApiClient):
    """Verifies lookup of all object via ID"""
    await check_bootstrap(protect_client_no_debug.bootstrap)


@pytest.mark.asyncio()
@patch("uiprotect.utils.datetime", MockDatetime)
async def test_get_events_raw_default(protect_client: ProtectApiClient, now: datetime):
    events = await protect_client.get_events_raw(_allow_manual_paginate=False)

    end = now + timedelta(seconds=10)

    protect_client.api_request.assert_called_with(  # type: ignore[attr-defined]
        url="events",
        method="get",
        require_auth=True,
        raise_exception=True,
        public_api=False,
        params={
            "orderDirection": "ASC",
            "withoutDescriptions": "false",
            "start": to_js_time(end - timedelta(hours=1)),
            "end": to_js_time(end),
        },
    )
    assert len(events) == CONSTANTS["event_count"]
    for event in events:
        assert event["type"] in EventType.values()
        assert event["modelKey"] in ModelType.values()


@pytest.mark.asyncio()
async def test_get_events_raw_limit(protect_client: ProtectApiClient):
    await protect_client.get_events_raw(limit=10)

    protect_client.api_request.assert_called_with(  # type: ignore[attr-defined]
        url="events",
        method="get",
        require_auth=True,
        raise_exception=True,
        public_api=False,
        params={"orderDirection": "ASC", "withoutDescriptions": "false", "limit": 10},
    )


@pytest.mark.asyncio()
async def test_get_events_raw_types(protect_client: ProtectApiClient):
    await protect_client.get_events_raw(
        limit=10,
        types=[EventType.MOTION, EventType.SMART_DETECT],
    )

    protect_client.api_request.assert_called_with(  # type: ignore[attr-defined]
        url="events",
        method="get",
        require_auth=True,
        raise_exception=True,
        public_api=False,
        params={
            "orderDirection": "ASC",
            "withoutDescriptions": "false",
            "limit": 10,
            "types": ["motion", "smartDetectZone"],
        },
    )


# test has a scaling "expected time to complete" based on the number of
# events in the last 24 hours
@pytest.mark.timeout(CONSTANTS["event_count"] * 0.1)  # type: ignore[misc]
@pytest.mark.asyncio()
async def test_get_events(protect_client: ProtectApiClient, raw_events):
    expected_events = [
        event
        for event in raw_events
        if event["score"] >= 50 and event["type"] in EventType.device_events()
    ]

    protect_client._minimum_score = 50

    events = await protect_client.get_events(_allow_manual_paginate=False)

    assert len(events) == len(expected_events)
    for index, event in enumerate(events):
        compare_objs(event.model.value, expected_events[index], event.unifi_dict())

        if event.type.value in EventType.motion_events():
            await check_motion_event(event)


@pytest.mark.asyncio()
async def test_get_events_not_event(protect_client: ProtectApiClient, camera):
    protect_client.get_events_raw = AsyncMock(return_value=[camera])  # type: ignore[method-assign]

    assert await protect_client.get_events() == []


@pytest.mark.asyncio()
async def test_get_events_not_event_with_type(protect_client: ProtectApiClient, camera):
    camera["type"] = EventType.MOTION.value

    protect_client.get_events_raw = AsyncMock(return_value=[camera])  # type: ignore[method-assign]

    assert await protect_client.get_events() == []


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_device_mismatch(protect_client: ProtectApiClient, camera):
    protect_client.api_request_obj = AsyncMock(return_value=camera)  # type: ignore[method-assign]

    with pytest.raises(NvrError):
        await protect_client.get_bridge("test_id")


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_device_not_adopted(protect_client: ProtectApiClient, camera):
    camera["isAdopted"] = False
    protect_client.api_request_obj = AsyncMock(return_value=camera)  # type: ignore[method-assign]

    with pytest.raises(NvrError):
        await protect_client.get_camera("test_id")


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_device_not_adopted_enabled(protect_client: ProtectApiClient, camera):
    camera["isAdopted"] = False
    protect_client.ignore_unadopted = False
    protect_client.api_request_obj = AsyncMock(return_value=camera)  # type: ignore[method-assign]

    obj = create_from_unifi_dict(camera)
    assert_equal_dump(obj, await protect_client.get_camera("test_id"))


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_camera(protect_client: ProtectApiClient, camera):
    obj = create_from_unifi_dict(camera)

    assert_equal_dump(obj, await protect_client.get_camera("test_id"))


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_light(protect_client: ProtectApiClient, light):
    obj = create_from_unifi_dict(light)

    assert_equal_dump(obj, await protect_client.get_light("test_id"))


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_sensor(protect_client: ProtectApiClient, sensor):
    obj = create_from_unifi_dict(sensor)

    assert_equal_dump(obj, await protect_client.get_sensor("test_id"))


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_viewer(protect_client: ProtectApiClient, viewport):
    obj = create_from_unifi_dict(viewport)

    assert_equal_dump(obj, await protect_client.get_viewer("test_id"))


@pytest.mark.skipif(not TEST_BRIDGE_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_bridge(protect_client: ProtectApiClient, bridge):
    obj = create_from_unifi_dict(bridge)

    assert_equal_dump(obj, await protect_client.get_bridge("test_id"))


@pytest.mark.skipif(not TEST_LIVEVIEW_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_liveview(protect_client: ProtectApiClient, liveview):
    obj = create_from_unifi_dict(liveview)

    assert_equal_dump(obj, (await protect_client.get_liveview("test_id")))


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_devices_mismatch(protect_client: ProtectApiClient, cameras):
    protect_client.api_request_list = AsyncMock(return_value=cameras)  # type: ignore[method-assign]

    with pytest.raises(NvrError):
        await protect_client.get_bridges()


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_devices_not_adopted(protect_client: ProtectApiClient, cameras):
    cameras[0]["isAdopted"] = False
    protect_client.api_request_list = AsyncMock(return_value=cameras)  # type: ignore[method-assign]

    assert len(await protect_client.get_cameras()) == len(cameras) - 1


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_devices_not_adopted_enabled(
    protect_client: ProtectApiClient,
    cameras,
):
    cameras[0]["isAdopted"] = False
    protect_client.ignore_unadopted = False
    protect_client.api_request_list = AsyncMock(return_value=cameras)  # type: ignore[method-assign]

    assert len(await protect_client.get_cameras()) == len(cameras)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_cameras(protect_client: ProtectApiClient, cameras):
    objs = [create_from_unifi_dict(d) for d in cameras]

    assert_equal_dump(objs, await protect_client.get_cameras())


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_lights(protect_client: ProtectApiClient, lights):
    objs = [create_from_unifi_dict(d) for d in lights]

    assert_equal_dump(objs, await protect_client.get_lights())


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_sensors(protect_client: ProtectApiClient, sensors):
    objs = [create_from_unifi_dict(d) for d in sensors]

    assert_equal_dump(objs, await protect_client.get_sensors())


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_viewers(protect_client: ProtectApiClient, viewports):
    objs = [create_from_unifi_dict(d) for d in viewports]

    assert_equal_dump(objs, await protect_client.get_viewers())


@pytest.mark.skipif(not TEST_BRIDGE_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_bridges(protect_client: ProtectApiClient, bridges):
    objs = [create_from_unifi_dict(d) for d in bridges]

    assert_equal_dump(objs, await protect_client.get_bridges())


@pytest.mark.skipif(not TEST_LIVEVIEW_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_liveviews(protect_client: ProtectApiClient, liveviews):
    objs = [create_from_unifi_dict(d) for d in liveviews]

    assert_equal_dump(objs, await protect_client.get_liveviews())


@pytest.mark.skipif(not TEST_SNAPSHOT_EXISTS, reason="Missing testdata")
@patch("uiprotect.utils.datetime", MockDatetime)
@patch("uiprotect.api.time.time", get_time)
@pytest.mark.asyncio()
async def test_get_camera_snapshot(protect_client: ProtectApiClient, now):
    data = await protect_client.get_camera_snapshot("test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "cameras/test_id/snapshot",
        params={
            "ts": to_js_time(now),
            "force": "true",
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_PUBLIC_API_SNAPSHOT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_public_api_camera_snapshot(protect_client: ProtectApiClient, now):
    data = await protect_client.get_public_api_camera_snapshot("test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        public_api=True,
        raise_exception=False,
        url="/v1/cameras/test_id/snapshot",
        params={
            "highQuality": "false",
        },
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_PUBLIC_API_SNAPSHOT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_public_api_camera_snapshot_hq_true(
    protect_client: ProtectApiClient, now
):
    data = await protect_client.get_public_api_camera_snapshot(
        "test_id", high_quality=True
    )
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        public_api=True,
        raise_exception=False,
        url="/v1/cameras/test_id/snapshot",
        params={
            "highQuality": "true",
        },
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_SNAPSHOT_EXISTS, reason="Missing testdata")
@patch("uiprotect.utils.datetime", MockDatetime)
@patch("uiprotect.api.time.time", get_time)
@pytest.mark.asyncio()
async def test_get_pacakge_camera_snapshot(protect_client: ProtectApiClient, now):
    data = await protect_client.get_package_camera_snapshot("test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "cameras/test_id/package-snapshot",
        params={
            "ts": to_js_time(now),
            "force": "true",
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_SNAPSHOT_EXISTS, reason="Missing testdata")
@patch("uiprotect.utils.datetime", MockDatetime)
@patch("uiprotect.api.time.time", get_time)
@pytest.mark.asyncio()
async def test_get_camera_snapshot_args(protect_client: ProtectApiClient, now):
    data = await protect_client.get_camera_snapshot("test_id", 1920, 1080)
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "cameras/test_id/snapshot",
        params={
            "ts": to_js_time(now),
            "force": "true",
            "w": 1920,
            "h": 1080,
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_SNAPSHOT_EXISTS, reason="Missing testdata")
@patch("uiprotect.utils.datetime", MockDatetime)
@patch("uiprotect.api.time.time", get_time)
@pytest.mark.asyncio()
async def test_get_package_camera_snapshot_args(protect_client: ProtectApiClient, now):
    data = await protect_client.get_package_camera_snapshot("test_id", 1920, 1080)
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "cameras/test_id/package-snapshot",
        params={
            "ts": to_js_time(now),
            "force": "true",
            "w": 1920,
            "h": 1080,
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_VIDEO_EXISTS, reason="Missing testdata")
@patch("uiprotect.api.datetime", MockDatetime)
@patch("uiprotect.api.time.time", get_time)
@pytest.mark.asyncio()
async def test_get_camera_video(protect_client: ProtectApiClient, now, tmp_binary_file):
    camera = next(iter(protect_client.bootstrap.cameras.values()))
    start = now - timedelta(seconds=CONSTANTS["camera_video_length"])

    data = await protect_client.get_camera_video(camera.id, start, now)
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "video/export",
        params={
            "camera": camera.id,
            "channel": 0,
            "start": to_js_time(start),
            "end": to_js_time(now),
        },
        raise_exception=False,
    )

    tmp_binary_file.write(data)
    tmp_binary_file.close()

    validate_video_file(tmp_binary_file.name, CONSTANTS["camera_video_length"])


@pytest.mark.asyncio()
async def test_get_camera_video_http_error(
    protect_client: ProtectApiClient, now: datetime
) -> None:
    """Test get_camera_video with HTTP error response."""
    camera = next(iter(protect_client.bootstrap.cameras.values()))
    start = now - timedelta(seconds=CONSTANTS["camera_video_length"])

    # Test the simple path (no output_file) which uses api_request_raw
    protect_client.api_request_raw = AsyncMock(
        side_effect=NotAuthorized("Access denied")
    )

    with pytest.raises(NotAuthorized):
        await protect_client.get_camera_video(camera.id, start, now)


@pytest.mark.asyncio()
async def test_get_camera_video_logging(
    protect_client: ProtectApiClient, now: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    """Test get_camera_video debug logging."""
    caplog.set_level(logging.DEBUG, logger="uiprotect.api")

    camera = next(iter(protect_client.bootstrap.cameras.values()))
    start = now - timedelta(seconds=CONSTANTS["camera_video_length"])

    # Create a simple async context manager class for the file mock
    class MockAsyncFile:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def write(self, data):
            pass

    # Mock the response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.close = AsyncMock()

    # Create a mock content with iter_chunked method
    class MockContent:
        def iter_chunked(self, chunk_size):
            return MockAsyncIterator()

    class MockAsyncIterator:
        def __init__(self):
            self.items = [b"test_chunk"]
            self.index = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.index >= len(self.items):
                raise StopAsyncIteration
            item = self.items[self.index]
            self.index += 1
            return item

    mock_response.content = MockContent()

    # Mock aiofiles.open to return our mock file
    with patch("aiofiles.open", return_value=MockAsyncFile()):
        protect_client.request = AsyncMock(return_value=mock_response)

        await protect_client.get_camera_video(
            camera.id,
            start,
            now,
            output_file="/tmp/test.mp4",  # noqa: S108
        )

    # Check that debug log was written
    assert any(
        "Requesting camera video:" in record.message for record in caplog.records
    )


@pytest.mark.skipif(not TEST_THUMBNAIL_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_event_thumbnail(protect_client: ProtectApiClient):
    data = await protect_client.get_event_thumbnail("e-test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "events/test_id/thumbnail",
        params={},
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_THUMBNAIL_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_event_thumbnail_args(protect_client: ProtectApiClient):
    data = await protect_client.get_event_thumbnail("test_id", 1920, 1080)
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "events/test_id/thumbnail",
        params={
            "w": 1920,
            "h": 1080,
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_HEATMAP_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_event_heatmap(protect_client: ProtectApiClient):
    data = await protect_client.get_event_heatmap("e-test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore[attr-defined]
        "events/test_id/heatmap",
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}


@pytest.mark.skipif(not TEST_SMART_TRACK_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_event_smart_detect_track(protect_client: ProtectApiClient):
    data = await protect_client.get_event_smart_detect_track("test_id")
    assert data.camera

    protect_client.api_request.assert_called_with(  # type: ignore[attr-defined]
        url="events/test_id/smartDetectTrack",
        method="get",
        require_auth=True,
        raise_exception=True,
        public_api=False,
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_aiport(protect_client: ProtectApiClient, aiport):
    obj = create_from_unifi_dict(aiport)

    assert_equal_dump(obj, await protect_client.get_aiport("test_id"))


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_aiport_not_adopted(protect_client: ProtectApiClient, aiport):
    aiport["isAdopted"] = False
    protect_client.api_request_obj = AsyncMock(return_value=aiport)

    with pytest.raises(NvrError):
        await protect_client.get_aiport("test_id")


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_aiport_not_adopted_enabled(protect_client: ProtectApiClient, aiport):
    aiport["isAdopted"] = False
    protect_client.ignore_unadopted = False
    protect_client.api_request_obj = AsyncMock(return_value=aiport)

    obj = create_from_unifi_dict(aiport)
    assert_equal_dump(obj, await protect_client.get_aiport("test_id"))


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_chime(protect_client: ProtectApiClient, chime):
    obj = create_from_unifi_dict(chime)

    assert_equal_dump(obj, await protect_client.get_chime("test_id"))


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_chime_not_adopted(protect_client: ProtectApiClient, chime):
    chime["isAdopted"] = False
    protect_client.api_request_obj = AsyncMock(return_value=chime)

    with pytest.raises(NvrError):
        await protect_client.get_chime("test_id")


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_chime_not_adopted_enabled(protect_client: ProtectApiClient, chime):
    chime["isAdopted"] = False
    protect_client.ignore_unadopted = False
    protect_client.api_request_obj = AsyncMock(return_value=chime)

    obj = create_from_unifi_dict(chime)
    assert_equal_dump(obj, await protect_client.get_chime("test_id"))


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_aiports(protect_client: ProtectApiClient, aiports):
    objs = [create_from_unifi_dict(d) for d in aiports]

    assert_equal_dump(objs, await protect_client.get_aiports())


@pytest.mark.asyncio()
async def test_play_speaker(protect_client: ProtectApiClient):
    """Test play_speaker with default parameters."""
    device_id = "cf1a330397c08f919d02bd7c"
    protect_client.api_request = AsyncMock()

    await protect_client.play_speaker(device_id)

    protect_client.api_request.assert_called_with(
        f"chimes/{device_id}/play-speaker",
        method="post",
        json=None,
    )


@pytest.mark.asyncio()
async def test_play_speaker_with_volume(protect_client: ProtectApiClient):
    """Test play_speaker with volume parameter."""
    device_id = "cf1a330397c08f919d02bd7c"
    volume = 5
    chime = protect_client.bootstrap.chimes[device_id]
    protect_client.api_request = AsyncMock()

    await protect_client.play_speaker(device_id, volume=volume)

    protect_client.api_request.assert_called_with(
        f"chimes/{device_id}/play-speaker",
        method="post",
        json={
            "volume": volume,
            "repeatTimes": chime.repeat_times,
        },
    )


@pytest.mark.asyncio()
async def test_play_speaker_with_ringtone_id(protect_client: ProtectApiClient):
    """Test play_speaker with ringtone_id parameter."""
    device_id = "cf1a330397c08f919d02bd7c"
    ringtone_id = "ringtone_1"
    chime = protect_client.bootstrap.chimes[device_id]
    protect_client.api_request = AsyncMock()

    await protect_client.play_speaker(device_id, ringtone_id=ringtone_id)

    protect_client.api_request.assert_called_with(
        f"chimes/{device_id}/play-speaker",
        method="post",
        json={
            "volume": chime.volume,
            "repeatTimes": chime.repeat_times,
            "ringtoneId": ringtone_id,
        },
    )


@pytest.mark.asyncio()
async def test_play_speaker_invalid_chime_id(protect_client: ProtectApiClient):
    """Test play_speaker with invalid chime ID."""
    device_id = "invalid_id"
    protect_client.api_request = AsyncMock()

    with pytest.raises(BadRequest):
        await protect_client.play_speaker(device_id, volume=5)


@pytest.mark.asyncio()
async def test_play_speaker_with_all_parameters(protect_client: ProtectApiClient):
    """Test play_speaker with all parameters."""
    device_id = "cf1a330397c08f919d02bd7c"
    volume = 5
    repeat_times = 3
    ringtone_id = "ringtone_1"
    track_no = 2
    protect_client.api_request = AsyncMock()

    await protect_client.play_speaker(
        device_id,
        volume=volume,
        repeat_times=repeat_times,
        ringtone_id=ringtone_id,
        track_no=track_no,
    )

    protect_client.api_request.assert_called_with(
        f"chimes/{device_id}/play-speaker",
        method="post",
        json={
            "volume": volume,
            "repeatTimes": repeat_times,
            "ringtoneId": ringtone_id,
        },
    )


@pytest.mark.asyncio()
async def test_set_light_is_led_force_on(protect_client: ProtectApiClient):
    """Test set_light_is_led_force_on with valid parameters."""
    device_id = "test_light_id"
    is_led_force_on = True
    protect_client.api_request = AsyncMock()

    await protect_client.set_light_is_led_force_on(device_id, is_led_force_on)

    protect_client.api_request.assert_called_with(
        f"lights/{device_id}",
        method="patch",
        json={"lightOnSettings": {"isLedForceOn": is_led_force_on}},
    )


@pytest.mark.asyncio()
async def test_set_light_is_led_force_on_false(protect_client: ProtectApiClient):
    """Test set_light_is_led_force_on with is_led_force_on set to False."""
    device_id = "test_light_id"
    is_led_force_on = False
    protect_client.api_request = AsyncMock()

    await protect_client.set_light_is_led_force_on(device_id, is_led_force_on)

    protect_client.api_request.assert_called_with(
        f"lights/{device_id}",
        method="patch",
        json={"lightOnSettings": {"isLedForceOn": is_led_force_on}},
    )


@pytest.mark.asyncio()
async def test_set_light_is_led_force_on_invalid_device_id(
    protect_client: ProtectApiClient,
):
    """Test set_light_is_led_force_on with invalid device ID."""
    device_id = "invalid_id"
    is_led_force_on = True
    protect_client.api_request = AsyncMock(side_effect=BadRequest)

    with pytest.raises(BadRequest):
        await protect_client.set_light_is_led_force_on(device_id, is_led_force_on)


@pytest.mark.asyncio()
async def test_create_api_key_success(protect_client: ProtectApiClient):
    protect_client.api_request = AsyncMock(
        return_value={"data": {"full_api_key": "test_api_key"}}
    )
    result = await protect_client.create_api_key("test")
    assert result == "test_api_key"
    protect_client.api_request.assert_called_with(
        api_path="/proxy/users/api/v2",
        url="/user/self/keys",
        method="post",
        json={"name": "test"},
    )


@pytest.mark.asyncio()
async def test_create_api_key_empty_name(protect_client: ProtectApiClient):
    protect_client._last_token_cookie_decode = {"userId": "test_user_id"}
    with pytest.raises(BadRequest, match="API key name cannot be empty"):
        await protect_client.create_api_key("")


@pytest.mark.asyncio()
async def test_create_api_key_failure(protect_client: ProtectApiClient):
    protect_client.api_request = AsyncMock(return_value={})
    protect_client._last_token_cookie_decode = {"userId": "test_user_id"}
    with pytest.raises(BadRequest, match="Failed to create API key"):
        await protect_client.create_api_key("test")


@pytest.mark.asyncio()
async def test_api_request_raw_with_custom_api_path() -> None:
    """Test api_request_raw uses custom api_path when provided"""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test",
        "test",
        verify_ssl=False,
    )

    # Mock the request method to verify the path
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=b"test_response")
    mock_response.close = AsyncMock()

    client.request = AsyncMock(return_value=mock_response)

    result = await client.api_request_raw("/test/endpoint", api_path="/custom/api/path")

    assert result == b"test_response"
    client.request.assert_called_with(
        "get",
        "/custom/api/path/test/endpoint",
        require_auth=True,
        auto_close=False,
        public_api=False,
    )


@pytest.mark.asyncio()
async def test_api_request_raw_with_default_api_path() -> None:
    """Test api_request_raw uses default api_path when not provided"""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test",
        "test",
        verify_ssl=False,
    )

    # Mock the request method to verify the path
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=b"test_response")
    mock_response.close = AsyncMock()

    client.request = AsyncMock(return_value=mock_response)

    result = await client.api_request_raw("/test/endpoint")

    assert result == b"test_response"
    client.request.assert_called_with(
        "get",
        f"{client.private_api_path}/test/endpoint",
        require_auth=True,
        auto_close=False,
        public_api=False,
    )


@pytest.mark.asyncio
async def test_read_auth_config_file_not_found():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test",
        "test",
        verify_ssl=False,
    )
    with patch("aiofiles.open", side_effect=FileNotFoundError):
        result = await client._read_auth_config()
        assert result is None


class AsyncMockOpen:
    def __init__(self, read_data: bytes):
        self._read_data = read_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def read(self):
        return self._read_data


@pytest.mark.asyncio
async def test_read_auth_config_empty_file():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test",
        "test",
        verify_ssl=False,
    )
    with patch("aiofiles.open", return_value=AsyncMockOpen(b"")):
        result = await client._read_auth_config()
        assert result is None


@pytest.mark.asyncio
async def test_read_auth_config_invalid_json():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test",
        "test",
        verify_ssl=False,
    )
    with patch("aiofiles.open", return_value=AsyncMockOpen(b"{invalid json")):
        result = await client._read_auth_config()
        assert result is None


@pytest.mark.asyncio
async def test_read_auth_config_no_session():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test",
        "test",
        verify_ssl=False,
    )
    with patch("aiofiles.open", return_value=AsyncMockOpen(b"{}")):
        result = await client._read_auth_config()
        assert result is None


def test_api_key_init():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )
    assert hasattr(client, "_api_key")
    assert client._api_key == "my_key"


@pytest.mark.asyncio()
@patch("uiprotect.api.ProtectApiClient.request")
async def test_authenticate_sets_csrf_token(mock_request: AsyncMock) -> None:
    """Test that authenticate() extracts and sets the x-csrf-token header."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {
        "set-cookie": "TOKEN=test_token_value; path=/",
        "x-csrf-token": "test-csrf-token-12345",
    }
    mock_response.cookies = {}
    mock_request.return_value = mock_response

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=False,
    )

    await client.authenticate()

    assert client.headers is not None
    assert client.headers.get("x-csrf-token") == "test-csrf-token-12345"
    assert client._is_authenticated is True

    mock_request.assert_called_once_with(
        "post",
        url="/api/auth/login",
        json={
            "username": "test_user",
            "password": "test_pass",
            "rememberMe": False,
        },
    )


@pytest.mark.asyncio()
@patch("uiprotect.api.ProtectApiClient.request")
async def test_authenticate_without_csrf_token(mock_request: AsyncMock) -> None:
    """Test that authenticate() works even if no x-csrf-token is returned."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {
        "set-cookie": "TOKEN=test_token_value; path=/",
    }
    mock_response.cookies = {}
    mock_request.return_value = mock_response

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=False,
    )

    await client.authenticate()

    assert client.headers is None or client.headers.get("x-csrf-token") is None
    assert client._is_authenticated is True


@pytest.mark.asyncio()
async def test_load_session_rejects_missing_csrf_token(tmp_path: Path) -> None:
    """Test that _read_auth_config rejects sessions without CSRF token."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    # Create a config file with a session but no CSRF token (simulating old session)
    session_hash = get_user_hash(str(client._url), "test_user")
    config = {
        "sessions": {
            session_hash: {
                "metadata": {"path": "/", "expires": "Sun, 21 Dec 2025 13:44:52 GMT"},
                "cookiename": "TOKEN",
                "value": "old_token_without_csrf",
                "csrf": None,  # Old session without CSRF token
            }
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(config))

    # Try to load the session
    cookie = await client._read_auth_config()

    # Should return None because CSRF token is missing
    assert cookie is None
    assert client._is_authenticated is False


@pytest.mark.asyncio()
async def test_load_session_accepts_valid_csrf_token(tmp_path: Path) -> None:
    """Test that _read_auth_config accepts sessions with valid CSRF token."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    # Create a config file with a session including CSRF token
    session_hash = get_user_hash(str(client._url), "test_user")
    config = {
        "sessions": {
            session_hash: {
                "metadata": {"path": "/", "expires": "Sun, 21 Dec 2025 13:44:52 GMT"},
                "cookiename": "TOKEN",
                "value": "valid_token_with_csrf",
                "csrf": "valid-csrf-token-12345",
            }
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(config))

    # Try to load the session
    cookie = await client._read_auth_config()

    # Should successfully load the session
    assert cookie is not None
    assert client._is_authenticated is True
    assert client.headers is not None
    assert client.headers.get("x-csrf-token") == "valid-csrf-token-12345"


@pytest.mark.asyncio()
async def test_load_session_with_invalid_token(tmp_path: Path) -> None:
    """Test that loading a session with an invalid token (not enough segments) handles gracefully."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    # Create a config file with a session containing an invalid token
    # (not a valid JWT format - should have 3 segments separated by dots)
    session_hash = get_user_hash(str(client._url), "test_user")
    config = {
        "sessions": {
            session_hash: {
                "metadata": {"path": "/", "expires": "Sun, 21 Dec 2025 13:44:52 GMT"},
                "cookiename": "TOKEN",
                "value": "invalid_token_not_jwt",  # Invalid: only 1 segment, not 3
                "csrf": "valid-csrf-token-12345",
            }
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(config))

    # Load the session
    cookie = await client._read_auth_config()

    # Should successfully load the cookie even if token is invalid
    assert cookie is not None
    assert client._is_authenticated is True
    assert client._last_token_cookie is not None

    # The decode should fail gracefully and return None
    # This simulates the "Authentication token decode error: Not enough segments" from the issue
    decoded = decode_token_cookie(client._last_token_cookie)
    assert decoded is None

    # Verify is_authenticated returns False for invalid token
    assert client.is_authenticated() is False


@pytest.mark.asyncio()
async def test_load_session_with_token_two_segments(tmp_path: Path) -> None:
    """Test that loading a session with a token having only 2 segments handles gracefully."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    # Create a config file with a token that has 2 segments instead of 3
    session_hash = get_user_hash(str(client._url), "test_user")
    config = {
        "sessions": {
            session_hash: {
                "metadata": {"path": "/", "expires": "Sun, 21 Dec 2025 13:44:52 GMT"},
                "cookiename": "TOKEN",
                "value": "segment1.segment2",  # Invalid: only 2 segments instead of 3
                "csrf": "valid-csrf-token-12345",
            }
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(config))

    # Load the session
    cookie = await client._read_auth_config()

    # Should successfully load the cookie even if token is invalid
    assert cookie is not None
    assert client._is_authenticated is True
    assert client._last_token_cookie is not None

    # The decode should fail gracefully and return None
    decoded = decode_token_cookie(client._last_token_cookie)
    assert decoded is None

    # Verify is_authenticated returns False for invalid token
    assert client.is_authenticated() is False


@pytest.mark.asyncio()
@patch("uiprotect.api.ProtectApiClient.request")
async def test_invalid_token_triggers_reauthentication(
    mock_request: AsyncMock, tmp_path: Path
) -> None:
    """Test that an invalid token in session triggers re-authentication and updates the session file."""
    # Create a config file with an invalid token (like from the GitHub issue)
    session_hash = get_user_hash("https://127.0.0.1:0", "test_user")
    invalid_config = {
        "sessions": {
            session_hash: {
                "metadata": {"path": "/", "expires": "Sun, 21 Dec 2025 13:44:52 GMT"},
                "cookiename": "TOKEN",
                "value": "invalid_token",  # Not a valid JWT
                "csrf": "old-csrf-token",
            }
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(invalid_config))

    # Setup mock for authentication
    mock_auth_response = AsyncMock()
    mock_auth_response.status = 200
    mock_auth_response.headers = {
        "set-cookie": "TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0IiwiZXhwIjoxNzMzMDAwMDAwfQ.test; path=/",
        "x-csrf-token": "new-csrf-token-12345",
    }
    mock_auth_response.cookies = {}
    mock_request.return_value = mock_auth_response

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    # Ensure authentication is triggered (which loads the session first)
    await client.ensure_authenticated()

    # Should have called authenticate() due to invalid token
    assert mock_request.called
    assert client._is_authenticated is True

    # Verify the session file was updated with the new valid token
    updated_config = orjson.loads(config_file.read_bytes())
    session_data = updated_config["sessions"][session_hash]
    assert session_data["csrf"] == "new-csrf-token-12345"
    # The new token should be a valid JWT format (3 segments)
    assert session_data["value"].count(".") == 2


@pytest.mark.asyncio()
async def test_clear_session_removes_specific_session(tmp_path: Path) -> None:
    """Test that clear_session removes only the specific user/host session."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    session_hash = get_user_hash(str(client._url), "test_user")
    config = {
        "sessions": {
            session_hash: {
                "metadata": {"path": "/", "expires": "Sun, 21 Dec 2025 13:44:52 GMT"},
                "cookiename": "TOKEN",
                "value": "some_token_value",
                "csrf": "some-csrf-token",
            },
            "other_session_hash": {
                "metadata": {"path": "/"},
                "cookiename": "TOKEN",
                "value": "other_token",
                "csrf": "other-csrf",
            },
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(config))

    await client.clear_session()

    # File should still exist with the other session intact
    updated_config = orjson.loads(config_file.read_bytes())
    assert session_hash not in updated_config["sessions"]
    assert "other_session_hash" in updated_config["sessions"]
    assert client._is_authenticated is False


@pytest.mark.asyncio()
@patch("uiprotect.api._LOGGER")
async def test_clear_all_sessions_removes_file(
    mock_logger: Mock, tmp_path: Path
) -> None:
    """Test that clear_all_sessions removes the config file and logs debug message."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    config = {
        "sessions": {
            "hash1": {
                "metadata": {"path": "/"},
                "cookiename": "TOKEN",
                "value": "token1",
                "csrf": "csrf1",
            },
            "hash2": {
                "metadata": {"path": "/"},
                "cookiename": "TOKEN",
                "value": "token2",
                "csrf": "csrf2",
            },
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(config))

    await client.clear_all_sessions()

    assert not config_file.exists()
    assert client._is_authenticated is False
    assert client._last_token_cookie is None
    assert client._last_token_cookie_decode is None
    mock_logger.debug.assert_called_once_with("Cleared all sessions from config file")


@pytest.mark.asyncio()
@pytest.mark.parametrize("clear_method", ["clear_session", "clear_all_sessions"])
async def test_clear_methods_do_nothing_when_sessions_disabled(
    tmp_path: Path, clear_method: str
) -> None:
    """Test that clear methods do nothing when store_sessions=False."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=False,
        config_dir=tmp_path,
    )

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps({"sessions": {}}))

    await getattr(client, clear_method)()

    # File should still exist since sessions are disabled
    assert config_file.exists()
    config = orjson.loads(config_file.read_bytes())
    assert config == {"sessions": {}}


@pytest.mark.asyncio()
async def test_clear_session_with_invalid_config_file(tmp_path: Path) -> None:
    """Test that clear_session handles invalid config file gracefully."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )

    # Create a config file with invalid JSON
    config_file = tmp_path / "unifi_protect.json"
    config_file.write_text("invalid json content {{{")

    # Call clear_session - should handle the exception gracefully
    await client.clear_session()

    # File should still exist
    assert config_file.exists()


@pytest.mark.asyncio()
@pytest.mark.parametrize("clear_method", ["clear_session", "clear_all_sessions"])
async def test_clear_methods_handle_missing_file(
    tmp_path: Path, clear_method: str
) -> None:
    """Test that clear methods handle missing config file gracefully."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )
    # Set auth state to simulate authenticated client
    client._is_authenticated = True
    client._last_token_cookie = "some_token"  # noqa: S105

    # Don't create the config file
    await getattr(client, clear_method)()

    # No file should exist and no error should be raised
    config_file = tmp_path / "unifi_protect.json"
    assert not config_file.exists()
    # Client state should NOT be reset since no file was found
    assert client._is_authenticated is True
    assert client._last_token_cookie == "some_token"  # noqa: S105


@pytest.mark.asyncio()
async def test_clear_session_when_session_not_in_config(tmp_path: Path) -> None:
    """Test that clear_session handles missing session hash gracefully."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
        config_dir=tmp_path,
    )
    # Set auth state to simulate authenticated client
    client._is_authenticated = True
    client._last_token_cookie = "some_token"  # noqa: S105

    config = {
        "sessions": {
            "different_hash": {
                "metadata": {"path": "/"},
                "cookiename": "TOKEN",
                "value": "token1",
                "csrf": "csrf1",
            }
        }
    }

    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps(config))

    await client.clear_session()

    # File should still have the original session
    updated_config = orjson.loads(config_file.read_bytes())
    assert "different_hash" in updated_config["sessions"]
    # Client state should NOT be reset since no session was actually removed
    assert client._is_authenticated is True
    assert client._last_token_cookie == "some_token"  # noqa: S105


@pytest.mark.asyncio()
@patch("uiprotect.api.aos.remove")
async def test_clear_all_sessions_handles_file_disappearing(
    mock_remove: AsyncMock, tmp_path: Path
) -> None:
    """Test that clear_all_sessions handles FileNotFoundError if file disappears during removal."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
    )
    client.config_dir = tmp_path
    # Set auth state to simulate authenticated client
    client._is_authenticated = True
    client._last_token_cookie = "some_token"  # noqa: S105

    # Create config file so path.exists() check passes
    config_file = tmp_path / "unifi_protect.json"
    config_file.write_bytes(orjson.dumps({"sessions": {}}))

    # Mock aos.remove to raise FileNotFoundError (race condition simulation)
    mock_remove.side_effect = FileNotFoundError(
        "File disappeared between exists() and remove()"
    )

    # Should not raise exception even though remove() fails
    await client.clear_all_sessions()

    # Should have attempted to remove the file
    mock_remove.assert_called_once()
    # Client state should NOT be reset since file removal failed
    assert client._is_authenticated is True
    assert client._last_token_cookie == "some_token"  # noqa: S105


@pytest.mark.asyncio()
@patch("uiprotect.api.ProtectApiClient.request")
async def test_authenticate_with_session_storage(
    mock_request: AsyncMock, tmp_path: Path
) -> None:
    """Test that authenticate() stores session with CSRF token when store_sessions=True."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {
        "set-cookie": "TOKEN=stored_token_value; path=/; Secure; HttpOnly",
        "x-csrf-token": "stored-csrf-token-67890",
    }
    mock_response.cookies = {}
    mock_request.return_value = mock_response

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=True,
    )
    client.config_dir = tmp_path

    await client.authenticate()

    # Verify authentication succeeded
    assert client._is_authenticated is True
    assert client.headers is not None
    assert client.headers.get("x-csrf-token") == "stored-csrf-token-67890"

    # Verify session was saved to file
    config_file = tmp_path / "unifi_protect.json"
    assert config_file.exists()

    config = orjson.loads(config_file.read_bytes())
    assert "sessions" in config
    sessions = config["sessions"]
    assert len(sessions) == 1

    # Get the session (there's only one)
    session = next(iter(sessions.values()))
    assert session["csrf"] == "stored-csrf-token-67890"
    assert "TOKEN" in session["cookiename"]


@pytest.mark.asyncio()
async def test_csrf_token_rotation() -> None:
    """Test that _update_last_token_cookie updates CSRF token when server sends new one."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "test_user",
        "test_pass",
        verify_ssl=False,
        store_sessions=False,
    )

    # Set initial CSRF token
    client.set_header("x-csrf-token", "initial-csrf-token")

    # Simulate API response with new CSRF token
    mock_response = AsyncMock()
    mock_response.headers = {
        "x-csrf-token": "rotated-csrf-token",
    }
    mock_response.cookies = {}

    # Call the method that updates CSRF token
    await client._update_last_token_cookie(mock_response)

    # Verify CSRF token was updated
    assert client.headers is not None
    assert client.headers.get("x-csrf-token") == "rotated-csrf-token"


@pytest.mark.asyncio()
async def test_get_meta_info_calls_public_api():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )
    client.api_request = AsyncMock(return_value={"applicationVersion": "1.0.0"})
    result = await client.get_meta_info()
    assert result.applicationVersion == "1.0.0"
    client.api_request.assert_called_with(url="/v1/meta/info", public_api=True)


@pytest.mark.asyncio()
async def test_api_request_raw_public_api_sets_path_and_header():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=b"public_response")
    mock_response.close = AsyncMock()
    client.request = AsyncMock(return_value=mock_response)

    result = await client.api_request_raw(
        "/v1/meta/info",
        public_api=True,
    )
    assert result == b"public_response"
    client.request.assert_called_with(
        "get",
        f"{client.public_api_path}/v1/meta/info",
        require_auth=True,
        auto_close=False,
        public_api=True,
    )


@pytest.mark.asyncio()
async def test_api_request_raw_public_api_requires_api_key():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key=None,
        verify_ssl=False,
    )
    # Patch get_session to avoid aiohttp session creation
    client.get_session = AsyncMock()
    with pytest.raises(
        NotAuthorized, match="API key is required for public API requests"
    ):
        await client.api_request_raw(
            "/v1/meta/info",
            public_api=True,
        )


@pytest.mark.asyncio()
async def test_get_meta_info_invalid_response_type():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )
    # Mock api_request to return a non-dict value
    client.api_request = AsyncMock(return_value=None)
    with pytest.raises(NvrError, match="Failed to retrieve meta info from public API"):
        await client.get_meta_info()


@pytest.mark.asyncio()
async def test_public_api_sets_x_api_key_header() -> None:
    """Test that X-API-KEY header is set when using public API."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_api_key_123",
        verify_ssl=False,
        store_sessions=False,  # Disable session storage to avoid auth cookie updates
    )

    # Create a mock session and response
    mock_session = AsyncMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.read = AsyncMock(return_value=b'{"test": "data"}')
    mock_response.release = AsyncMock()
    mock_response.close = AsyncMock()
    mock_response.url = "https://127.0.0.1:0/proxy/protect/integration/v1/test"
    mock_response.cookies = {}  # Empty cookies to avoid cookie processing

    # Track headers passed to session.request
    actual_headers: dict[str, str] | None = None

    # Create async context manager for the request
    class MockRequestContext:
        async def __aenter__(self) -> AsyncMock:
            return mock_response

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: Any,
        ) -> None:
            return None

    def mock_session_request(
        method: str, url: str, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> MockRequestContext:
        nonlocal actual_headers
        actual_headers = headers
        return MockRequestContext()

    mock_session.request = mock_session_request
    client.get_public_api_session = AsyncMock(return_value=mock_session)

    # Make a public API request
    await client.api_request_raw("/v1/test", public_api=True)

    # Verify the X-API-KEY header was set
    assert actual_headers == {"X-API-KEY": "test_api_key_123"}


@pytest.mark.asyncio
async def test_get_public_api_session_creates_and_reuses_session():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        verify_ssl=False,
    )
    session1 = await client.get_public_api_session()
    assert isinstance(session1, aiohttp.ClientSession)
    session2 = await client.get_public_api_session()
    assert session1 is session2
    await session1.close()
    session3 = await client.get_public_api_session()
    assert session3 is not session1
    assert isinstance(session3, aiohttp.ClientSession)
    await session3.close()


@pytest.mark.asyncio
async def test_public_api_session_constructor_assignment():
    async with aiohttp.ClientSession() as session:
        client = ProtectApiClient(
            "127.0.0.1",
            0,
            "user",
            "pass",
            public_api_session=session,
            verify_ssl=False,
        )
        assert client._public_api_session is session


@pytest.mark.asyncio()
async def test_request_uses_get_session_for_private_api():
    """Test that request uses get_session (not get_public_api_session) for private API calls."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        verify_ssl=False,
    )
    # Patch get_session to return a mock session
    mock_session = AsyncMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content_type = "application/json"
    mock_response.read = AsyncMock(return_value=b"{}")
    mock_response.release = AsyncMock()
    mock_response.close = AsyncMock()
    mock_response.headers = {}
    mock_response.cookies = {}

    # __aenter__ returns the response
    class MockRequestContext:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session.request = lambda *args, **kwargs: MockRequestContext()
    client.get_session = AsyncMock(return_value=mock_session)
    client.ensure_authenticated = AsyncMock()
    # Should use get_session, not get_public_api_session
    client.get_public_api_session = AsyncMock()
    # Call request with public_api=False
    result = await client.request("get", "/test/endpoint", public_api=False)
    assert result is mock_response
    client.get_session.assert_awaited()
    client.get_public_api_session.assert_not_called()


@pytest.mark.asyncio
async def test_close_public_api_session():
    async with aiohttp.ClientSession() as session:
        client = ProtectApiClient(
            "127.0.0.1",
            0,
            "user",
            "pass",
            public_api_session=session,
            verify_ssl=False,
        )
        # Should be the same session
        assert client._public_api_session is session
        # Close the session
        await client.close_public_api_session()
        # Should be None after closing
        assert client._public_api_session is None
        # Should be idempotent (no error if called again)
        await client.close_public_api_session()


@pytest.mark.asyncio
async def test_close_session_closes_public_api_session():
    """Test that close_session also closes the public API session."""
    mock_session = AsyncMock()
    mock_public_session = AsyncMock()

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        verify_ssl=False,
    )
    client._session = mock_session
    client._loaded_session = True
    client._public_api_session = mock_public_session

    await client.close_session()

    # Both sessions should be closed
    mock_session.close.assert_called_once()
    mock_public_session.close.assert_called_once()
    assert client._session is None
    assert client._public_api_session is None
    assert client._loaded_session is False


def test_set_api_key_sets_value():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key=None,
        verify_ssl=False,
    )
    client.set_api_key("test_key")
    assert client._api_key == "test_key"


def test_set_api_key_empty_raises():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key=None,
        verify_ssl=False,
    )

    with pytest.raises(BadRequest, match="API key cannot be empty"):
        client.set_api_key("")


def test_is_api_key_set_true():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )
    assert client.is_api_key_set() is True


def test_is_api_key_set_false():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key=None,
        verify_ssl=False,
    )
    assert client.is_api_key_set() is False


@pytest.mark.asyncio
async def test_create_camera_rtsps_streams_with_list_qualities():
    """Test creating RTSPS streams with a list of qualities."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    mock_response = (
        b'{"high": "rtsps://example.com/high", "medium": "rtsps://example.com/medium"}'
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=mock_response)
    ) as mock_request:
        result = await client.create_camera_rtsps_streams(
            "camera123", ["high", "medium"]
        )

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="POST",
            json={"qualities": ["high", "medium"]},
        )

        assert result is not None
        assert result.get_stream_url("high") == "rtsps://example.com/high"
        assert result.get_stream_url("medium") == "rtsps://example.com/medium"


@pytest.mark.asyncio
async def test_create_camera_rtsps_streams_with_string_quality():
    """Test creating RTSPS streams with a single quality string."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    mock_response = b'{"high": "rtsps://example.com/high"}'

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=mock_response)
    ) as mock_request:
        result = await client.create_camera_rtsps_streams("camera123", "high")

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="POST",
            json={"qualities": ["high"]},
        )

        assert result is not None
        assert result.get_stream_url("high") == "rtsps://example.com/high"


@pytest.mark.asyncio
async def test_create_camera_rtsps_streams_none_response():
    """Test creating RTSPS streams with None response."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=None)
    ) as mock_request:
        result = await client.create_camera_rtsps_streams("camera123", ["high"])

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="POST",
            json={"qualities": ["high"]},
        )

        assert result is None


@pytest.mark.asyncio
async def test_create_camera_rtsps_streams_invalid_json():
    """Test creating RTSPS streams with invalid JSON response."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=b"invalid json")
    ) as mock_request:
        result = await client.create_camera_rtsps_streams("camera123", ["high"])

        mock_request.assert_called_once()
        assert result is None


@pytest.mark.asyncio
async def test_get_camera_rtsps_streams():
    """Test getting existing RTSPS streams."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    mock_response = (
        b'{"high": "rtsps://example.com/high", "medium": "rtsps://example.com/medium"}'
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=mock_response)
    ) as mock_request:
        result = await client.get_camera_rtsps_streams("camera123")

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="GET",
        )

        assert result is not None
        assert result.get_stream_url("high") == "rtsps://example.com/high"
        assert result.get_stream_url("medium") == "rtsps://example.com/medium"
        assert set(result.get_available_stream_qualities()) == {"high", "medium"}


@pytest.mark.asyncio
async def test_get_camera_rtsps_streams_none_response():
    """Test getting RTSPS streams with None response."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=None)
    ) as mock_request:
        result = await client.get_camera_rtsps_streams("camera123")

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="GET",
        )

        assert result is None


@pytest.mark.asyncio
async def test_get_camera_rtsps_streams_invalid_json():
    """Test getting RTSPS streams with invalid JSON response."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=b"invalid json")
    ) as mock_request:
        result = await client.get_camera_rtsps_streams("camera123")

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="GET",
        )

        assert result is None


@pytest.mark.asyncio
async def test_delete_camera_rtsps_streams_success():
    """Test deleting RTSPS streams successfully."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=b"")
    ) as mock_request:
        result = await client.delete_camera_rtsps_streams(
            "camera123", ["high", "medium"]
        )

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="DELETE",
            params=[("qualities", "high"), ("qualities", "medium")],
        )

        assert result is True


@pytest.mark.asyncio
async def test_delete_camera_rtsps_streams_single_quality():
    """Test deleting RTSPS streams with single quality."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=b"")
    ) as mock_request:
        result = await client.delete_camera_rtsps_streams("camera123", "high")

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="DELETE",
            params=[("qualities", "high")],
        )

        assert result is True


@pytest.mark.asyncio
async def test_delete_camera_rtsps_streams_failure():
    """Test deleting RTSPS streams with failure."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="test_key",
        verify_ssl=False,
    )

    with patch.object(
        client, "api_request_raw", new=AsyncMock(return_value=None)
    ) as mock_request:
        result = await client.delete_camera_rtsps_streams("camera123", ["high"])

        mock_request.assert_called_once_with(
            public_api=True,
            url="/v1/cameras/camera123/rtsps-stream",
            method="DELETE",
            params=[("qualities", "high")],
        )

        assert result is False


def test_rtsps_streams_class():
    """Test RTSPSStreams class functionality."""
    # Test with multiple qualities
    streams = RTSPSStreams(
        high="rtsps://example.com/high",
        medium="rtsps://example.com/medium",
        low="rtsps://example.com/low",
    )

    assert streams.get_stream_url("high") == "rtsps://example.com/high"
    assert streams.get_stream_url("medium") == "rtsps://example.com/medium"
    assert streams.get_stream_url("low") == "rtsps://example.com/low"
    assert streams.get_stream_url("nonexistent") is None

    available_qualities = streams.get_available_stream_qualities()
    assert set(available_qualities) == {"high", "medium", "low"}

    # Test with single quality
    single_stream = RTSPSStreams(ultra="rtsps://example.com/ultra")
    assert single_stream.get_stream_url("ultra") == "rtsps://example.com/ultra"
    assert set(single_stream.get_available_stream_qualities()) == {"ultra"}

    # Test with empty streams
    empty_stream = RTSPSStreams()
    assert empty_stream.get_stream_url("any") is None
    assert empty_stream.get_available_stream_qualities() == []


def test_rtsps_streams_active_inactive():
    """Test RTSPSStreams active/inactive stream quality detection."""
    # Test with mixed active and inactive streams
    streams = RTSPSStreams(
        high="rtsps://example.com/high",
        medium=None,  # inactive
        low="rtsps://example.com/low",
        ultra=None,  # inactive
    )

    # All available qualities (active + inactive)
    available = streams.get_available_stream_qualities()
    assert set(available) == {"high", "medium", "low", "ultra"}

    # Only active streams (with URLs)
    active = streams.get_active_stream_qualities()
    assert set(active) == {"high", "low"}

    # Only inactive streams (without URLs)
    inactive = streams.get_inactive_stream_qualities()
    assert set(inactive) == {"medium", "ultra"}


def test_rtsps_streams_all_active():
    """Test RTSPSStreams when all streams are active."""
    streams = RTSPSStreams(
        high="rtsps://example.com/high",
        medium="rtsps://example.com/medium",
    )

    assert set(streams.get_available_stream_qualities()) == {"high", "medium"}
    assert set(streams.get_active_stream_qualities()) == {"high", "medium"}
    assert streams.get_inactive_stream_qualities() == []


def test_rtsps_streams_all_inactive():
    """Test RTSPSStreams when all streams are inactive."""
    streams = RTSPSStreams(
        high=None,
        medium=None,
    )

    assert set(streams.get_available_stream_qualities()) == {"high", "medium"}
    assert streams.get_active_stream_qualities() == []
    assert set(streams.get_inactive_stream_qualities()) == {"high", "medium"}


def test_rtsps_streams_active_inactive_qualities():
    """Test RTSPSStreams active and inactive quality methods."""
    # Test with mixed active (URLs) and inactive (None) streams
    streams = RTSPSStreams(
        high="rtsps://example.com/high",
        medium=None,  # inactive stream
        low="rtsps://example.com/low",
        ultra=None,  # inactive stream
    )

    # Test active streams (those with valid RTSPS URLs)
    active_qualities = streams.get_active_stream_qualities()
    assert set(active_qualities) == {"high", "low"}

    # Test inactive streams (those with None values)
    inactive_qualities = streams.get_inactive_stream_qualities()
    assert set(inactive_qualities) == {"medium", "ultra"}

    # Test all available streams (both active and inactive)
    available_qualities = streams.get_available_stream_qualities()
    assert set(available_qualities) == {"high", "medium", "low", "ultra"}

    # Test that active + inactive equals available
    assert set(active_qualities + inactive_qualities) == set(available_qualities)


def test_rtsps_streams_only_active():
    """Test RTSPSStreams with only active streams."""
    streams = RTSPSStreams(
        high="rtsps://example.com/high",
        medium="rtsps://example.com/medium",
    )

    active_qualities = streams.get_active_stream_qualities()
    assert set(active_qualities) == {"high", "medium"}

    inactive_qualities = streams.get_inactive_stream_qualities()
    assert inactive_qualities == []

    available_qualities = streams.get_available_stream_qualities()
    assert set(available_qualities) == {"high", "medium"}


def test_rtsps_streams_only_inactive():
    """Test RTSPSStreams with only inactive streams."""
    streams = RTSPSStreams(
        high=None,
        medium=None,
        low=None,
    )

    active_qualities = streams.get_active_stream_qualities()
    assert active_qualities == []

    inactive_qualities = streams.get_inactive_stream_qualities()
    assert set(inactive_qualities) == {"high", "medium", "low"}

    available_qualities = streams.get_available_stream_qualities()
    assert set(available_qualities) == {"high", "medium", "low"}


def test_rtsps_streams_empty():
    """Test RTSPSStreams with no streams."""
    streams = RTSPSStreams()

    assert streams.get_active_stream_qualities() == []
    assert streams.get_inactive_stream_qualities() == []
    assert streams.get_available_stream_qualities() == []


def test_rtsps_streams_edge_cases():
    """Test RTSPSStreams edge cases and string validation."""
    # Test with empty strings and various URL formats
    streams = RTSPSStreams(
        high="rtsps://valid.com/stream",
        medium="",  # empty string - still a string, so active
        low="http://invalid.com/stream",  # still a string, so active
        ultra="invalid_url",  # still a string, so active
    )

    # All string values are considered active (including empty strings)
    active_qualities = streams.get_active_stream_qualities()
    assert set(active_qualities) == {"high", "medium", "low", "ultra"}

    # Test with None values (should be inactive)
    streams_with_none = RTSPSStreams(
        high="rtsps://valid.com/stream",
        medium=None,  # None value - inactive
    )

    active_qualities = streams_with_none.get_active_stream_qualities()
    assert active_qualities == ["high"]

    inactive_qualities = streams_with_none.get_inactive_stream_qualities()
    assert inactive_qualities == ["medium"]

    available_qualities = streams.get_available_stream_qualities()
    assert set(available_qualities) == {"high", "medium", "low", "ultra"}


def test_rtsps_streams_none_pydantic_extra():
    """Test RTSPSStreams when __pydantic_extra__ is None."""
    # Create an RTSPSStreams instance and manually set __pydantic_extra__ to None
    # This simulates edge cases where pydantic might not initialize extra fields
    streams = RTSPSStreams()

    # Manually set __pydantic_extra__ to None to test the None check
    streams.__pydantic_extra__ = None

    # All methods should return empty lists when __pydantic_extra__ is None
    assert streams.get_available_stream_qualities() == []
    assert streams.get_active_stream_qualities() == []
    assert streams.get_inactive_stream_qualities() == []

    # get_stream_url should still work (uses getattr, not __pydantic_extra__)
    assert streams.get_stream_url("any") is None


@pytest.mark.asyncio
async def test_camera_create_rtsps_streams():
    """Test Camera.create_rtsps_streams method."""
    # Mock camera and API
    camera = AsyncMock(spec=Camera)
    camera.id = "test_camera_id"
    camera._api = AsyncMock()
    camera._api._api_key = "test_api_key"
    camera._api.create_camera_rtsps_streams = AsyncMock(
        return_value=RTSPSStreams(high="rtsps://example.com/high")
    )

    # Bind the actual method to the mock
    camera.create_rtsps_streams = Camera.create_rtsps_streams.__get__(camera, Camera)

    # Test successful creation
    result = await camera.create_rtsps_streams(["high"])
    assert result is not None
    assert result.get_stream_url("high") == "rtsps://example.com/high"
    camera._api.create_camera_rtsps_streams.assert_called_once_with(
        "test_camera_id", ["high"]
    )


@pytest.mark.asyncio
async def test_camera_create_rtsps_streams_no_api_key():
    """Test Camera.create_rtsps_streams method without API key."""
    # Mock camera and API without key
    camera = AsyncMock(spec=Camera)
    camera.id = "test_camera_id"
    camera._api = AsyncMock()
    camera._api._api_key = None

    # Bind the actual method to the mock
    camera.create_rtsps_streams = Camera.create_rtsps_streams.__get__(camera, Camera)

    # Test that it raises NotAuthorized
    with pytest.raises(
        NotAuthorized, match="Cannot create RTSPS streams without an API key"
    ):
        await camera.create_rtsps_streams(["high"])


@pytest.mark.asyncio
async def test_camera_get_rtsps_streams():
    """Test Camera.get_rtsps_streams method."""
    # Mock camera and API
    camera = AsyncMock(spec=Camera)
    camera.id = "test_camera_id"
    camera._api = AsyncMock()
    camera._api._api_key = "test_api_key"
    camera._api.get_camera_rtsps_streams = AsyncMock(
        return_value=RTSPSStreams(
            high="rtsps://example.com/high", medium="rtsps://example.com/medium"
        )
    )

    # Bind the actual method to the mock
    camera.get_rtsps_streams = Camera.get_rtsps_streams.__get__(camera, Camera)

    # Test successful retrieval
    result = await camera.get_rtsps_streams()
    assert result is not None
    assert result.get_stream_url("high") == "rtsps://example.com/high"
    assert result.get_stream_url("medium") == "rtsps://example.com/medium"
    camera._api.get_camera_rtsps_streams.assert_called_once_with("test_camera_id")


@pytest.mark.asyncio
async def test_camera_get_rtsps_streams_no_api_key():
    """Test Camera.get_rtsps_streams method without API key."""
    # Mock camera and API without key
    camera = AsyncMock(spec=Camera)
    camera.id = "test_camera_id"
    camera._api = AsyncMock()
    camera._api._api_key = None

    # Bind the actual method to the mock
    camera.get_rtsps_streams = Camera.get_rtsps_streams.__get__(camera, Camera)

    # Test that it raises NotAuthorized
    with pytest.raises(
        NotAuthorized, match="Cannot get RTSPS streams without an API key"
    ):
        await camera.get_rtsps_streams()


@pytest.mark.asyncio
async def test_camera_delete_rtsps_streams():
    """Test Camera.delete_rtsps_streams method."""
    # Mock camera and API
    camera = AsyncMock(spec=Camera)
    camera.id = "test_camera_id"
    camera._api = AsyncMock()
    camera._api._api_key = "test_api_key"
    camera._api.delete_camera_rtsps_streams = AsyncMock(return_value=True)

    # Bind the actual method to the mock
    camera.delete_rtsps_streams = Camera.delete_rtsps_streams.__get__(camera, Camera)

    # Test successful deletion
    result = await camera.delete_rtsps_streams(["high", "medium"])
    assert result is True
    camera._api.delete_camera_rtsps_streams.assert_called_once_with(
        "test_camera_id", ["high", "medium"]
    )


@pytest.mark.asyncio
async def test_camera_delete_rtsps_streams_no_api_key():
    """Test Camera.delete_rtsps_streams method without API key."""
    # Mock camera and API without key
    camera = AsyncMock(spec=Camera)
    camera.id = "test_camera_id"
    camera._api = AsyncMock()
    camera._api._api_key = None

    # Bind the actual method to the mock
    camera.delete_rtsps_streams = Camera.delete_rtsps_streams.__get__(camera, Camera)

    # Test that it raises NotAuthorized
    with pytest.raises(
        NotAuthorized, match="Cannot delete RTSPS streams without an API key"
    ):
        await camera.delete_rtsps_streams(["high"])


@pytest.mark.asyncio
async def test_raise_for_status_status_codes():
    """Test _raise_for_status with different HTTP status codes."""
    # Create API client
    api = ProtectApiClient("test.com", 443, "username", "password")

    # Test success codes (2xx) - should not raise
    success_tests = [
        (199, True, NvrError),  # Just below 2xx range
        (200, False, None),  # Start of 2xx range
        (201, False, None),  # Common success code
        (299, False, None),  # End of 2xx range
        (300, True, NvrError),  # Just above 2xx range
    ]

    for status_code, should_raise, expected_exception in success_tests:
        response = Mock()
        response.status = status_code
        response.url = "https://test.com/api/test"

        with patch("uiprotect.api.get_response_reason", return_value="Test"):
            if should_raise:
                with pytest.raises(expected_exception):
                    await api._raise_for_status(response, raise_exception=True)
            else:
                # Should not raise any exception
                await api._raise_for_status(response, raise_exception=True)
                await api._raise_for_status(response, raise_exception=False)

    # Test specific error codes
    error_tests = [
        (400, BadRequest),
        (401, NotAuthorized),
        (403, NotAuthorized),
        (404, BadRequest),
        (429, NvrError),
        (500, NvrError),
    ]

    for status_code, expected_exception in error_tests:
        response = Mock()
        response.status = status_code
        response.url = "https://test.com/api/test"

        with patch("uiprotect.api.get_response_reason", return_value="Error"):
            # Should raise with raise_exception=True
            with pytest.raises(expected_exception):
                await api._raise_for_status(response, raise_exception=True)

            # Should not raise with raise_exception=False
            await api._raise_for_status(response, raise_exception=False)


@pytest.mark.asyncio
async def test_api_request_raw_error_handling():
    """Test api_request_raw error handling with raise_exception parameter."""
    # Create API client
    api = ProtectApiClient("test.com", 443, "username", "password")

    # Mock the request method to return a response with error status
    mock_response = AsyncMock()
    mock_response.status = 404
    mock_response.url = "https://test.com/api/test"
    mock_response.read = AsyncMock(return_value=b'{"error": "not found"}')
    mock_response.release = AsyncMock()

    api.request = AsyncMock(return_value=mock_response)

    # Mock get_response_reason
    with patch("uiprotect.api.get_response_reason", return_value="Not Found"):
        # Test with raise_exception=False - should return None
        result = await api.api_request_raw("/test", raise_exception=False)
        assert result is None

        # Verify that response.read() was NOT called since we return early
        mock_response.read.assert_not_called()

        # Reset mock for next test
        mock_response.reset_mock()
        api.request.reset_mock()

        # Test with raise_exception=True - should raise exception
        with pytest.raises(BadRequest):
            await api.api_request_raw("/test", raise_exception=True)

        # Verify that response.release() was called in the exception handler
        mock_response.release.assert_called_once()


@pytest.mark.asyncio
async def test_api_request_raw_success():
    """Test api_request_raw with successful response."""
    # Create API client
    api = ProtectApiClient("test.com", 443, "username", "password")

    # Mock the request method to return a response with success status
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.url = "https://test.com/api/test"
    mock_response.read = AsyncMock(return_value=b'{"success": true}')
    mock_response.release = AsyncMock()

    api.request = AsyncMock(return_value=mock_response)

    # Test with success status - should return data
    result = await api.api_request_raw("/test", raise_exception=True)
    assert result == b'{"success": true}'

    # Verify that response.read() was called
    mock_response.read.assert_called_once()
    # Verify that response.release() was called
    mock_response.release.assert_called_once()


# Public API Tests


@pytest.mark.asyncio()
async def test_get_nvr_public_success():
    """Test successful NVR retrieval from public API."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    # Mock a simple valid object instead of trying to create full NVR
    mock_nvr = Mock()
    mock_nvr.id = "663d0a9d001d8803e40003ea"
    mock_nvr.name = "Test NVR"

    # Mock the NVR.from_unifi_dict method to return our mock
    with patch("uiprotect.data.nvr.NVR.from_unifi_dict", return_value=mock_nvr):
        client.api_request_obj = AsyncMock(return_value={"id": "test"})

        result = await client.get_nvr_public()

        assert result is not None
        assert result.id == "663d0a9d001d8803e40003ea"
        assert result.name == "Test NVR"
        client.api_request_obj.assert_called_with(url="/v1/nvrs", public_api=True)


@pytest.mark.asyncio()
async def test_get_nvr_public_error():
    """Test NVR retrieval error handling."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    client.api_request_obj = AsyncMock(side_effect=Exception("API Error"))

    with pytest.raises(Exception, match="API Error"):
        await client.get_nvr_public()

    client.api_request_obj.assert_called_with(url="/v1/nvrs", public_api=True)


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Camera.from_unifi_dict")
async def test_get_cameras_public_success(mock_create):
    """Test successful cameras retrieval from public API."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    mock_cameras_data = [
        {
            "id": "663d0aa400918803e4000445",
            "name": "Camera 1",
            "type": "UVC G4 Doorbell Pro PoE",
            "mac": "E438830EDA97",
            "modelKey": "camera",
            "firmwareVersion": "4.74.78",
        },
        {
            "id": "663d0aa400918803e4000446",
            "name": "Camera 2",
            "type": "UVC G4 Doorbell Pro PoE",
            "mac": "E438830EDA98",
            "modelKey": "camera",
            "firmwareVersion": "4.74.78",
        },
    ]

    # Mock the API request
    client.api_request_list = AsyncMock(return_value=mock_cameras_data)

    # Mock the Camera.from_unifi_dict method
    mock_camera = Mock()
    mock_create.return_value = mock_camera

    result = await client.get_cameras_public()

    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 2
    assert all(camera == mock_camera for camera in result)
    client.api_request_list.assert_called_with(url="/v1/cameras", public_api=True)
    assert mock_create.call_count == 2


@pytest.mark.asyncio()
async def test_get_cameras_public_error():
    """Test cameras retrieval error handling."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    client.api_request_list = AsyncMock(side_effect=Exception("API Error"))

    with pytest.raises(Exception, match="API Error"):
        await client.get_cameras_public()

    client.api_request_list.assert_called_with(url="/v1/cameras", public_api=True)


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Camera.from_unifi_dict")
async def test_get_camera_public_success(mock_create):
    """Test successful single camera retrieval from public API."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    mock_camera_data = {
        "id": "663d0aa400918803e4000445",
        "name": "Camera 1",
        "type": "UVC G4 Doorbell Pro PoE",
        "mac": "E438830EDA97",
        "modelKey": "camera",
        "firmwareVersion": "4.74.78",
    }

    # Mock the API request
    client.api_request_obj = AsyncMock(return_value=mock_camera_data)

    # Mock the Camera.from_unifi_dict method
    mock_camera = Mock()
    mock_camera.id = "663d0aa400918803e4000445"
    mock_camera.name = "Camera 1"
    mock_create.return_value = mock_camera

    result = await client.get_camera_public("663d0aa400918803e4000445")

    assert result is not None
    assert result.id == "663d0aa400918803e4000445"
    assert result.name == "Camera 1"
    client.api_request_obj.assert_called_with(
        url="/v1/cameras/663d0aa400918803e4000445", public_api=True
    )
    mock_create.assert_called_once_with(**mock_camera_data, api=client)


@pytest.mark.asyncio()
async def test_get_camera_public_error():
    """Test single camera retrieval error handling."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    client.api_request_obj = AsyncMock(side_effect=Exception("API Error"))

    with pytest.raises(Exception, match="API Error"):
        await client.get_camera_public("663d0aa400918803e4000445")

    client.api_request_obj.assert_called_with(
        url="/v1/cameras/663d0aa400918803e4000445", public_api=True
    )


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_get_chimes_public_success(mock_create):
    """Test successful chimes retrieval from public API."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    mock_chimes_data = [
        {
            "id": "663d0aa401108803e4000447",
            "name": "Chime 1",
            "type": "UP Chime PoE",
            "mac": "E438830ABC01",
            "modelKey": "chime",
            "firmwareVersion": "1.5.4",
        }
    ]

    # Mock the API request
    client.api_request_list = AsyncMock(return_value=mock_chimes_data)

    # Mock the Chime.from_unifi_dict method
    mock_chime = Mock()
    mock_chime.id = "663d0aa401108803e4000447"
    mock_chime.name = "Chime 1"
    mock_create.return_value = mock_chime

    result = await client.get_chimes_public()

    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].id == "663d0aa401108803e4000447"
    assert result[0].name == "Chime 1"
    client.api_request_list.assert_called_with(url="/v1/chimes", public_api=True)
    mock_create.assert_called_once_with(**mock_chimes_data[0], api=client)


@pytest.mark.asyncio()
async def test_get_chimes_public_error():
    """Test chimes retrieval error handling."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    client.api_request_list = AsyncMock(side_effect=Exception("API Error"))

    with pytest.raises(Exception, match="API Error"):
        await client.get_chimes_public()

    client.api_request_list.assert_called_with(url="/v1/chimes", public_api=True)


@pytest.mark.asyncio()
@patch("uiprotect.data.devices.Chime.from_unifi_dict")
async def test_get_chime_public_success(mock_create):
    """Test successful single chime retrieval from public API."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    mock_chime_data = {
        "id": "663d0aa401108803e4000447",
        "name": "Chime 1",
        "type": "UP Chime PoE",
        "mac": "E438830ABC01",
        "modelKey": "chime",
        "firmwareVersion": "1.5.4",
    }

    # Mock the API request
    client.api_request_obj = AsyncMock(return_value=mock_chime_data)

    # Mock the Chime.from_unifi_dict method
    mock_chime = Mock()
    mock_chime.id = "663d0aa401108803e4000447"
    mock_chime.name = "Chime 1"
    mock_create.return_value = mock_chime

    result = await client.get_chime_public("663d0aa401108803e4000447")

    assert result is not None
    assert result.id == "663d0aa401108803e4000447"
    assert result.name == "Chime 1"
    client.api_request_obj.assert_called_with(
        url="/v1/chimes/663d0aa401108803e4000447", public_api=True
    )
    mock_create.assert_called_once_with(**mock_chime_data, api=client)


@pytest.mark.asyncio()
async def test_get_chime_public_error():
    """Test single chime retrieval error handling."""
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "user",
        "pass",
        api_key="my_key",
        verify_ssl=False,
    )

    client.api_request_obj = AsyncMock(side_effect=Exception("API Error"))

    with pytest.raises(Exception, match="API Error"):
        await client.get_chime_public("663d0aa401108803e4000447")

    client.api_request_obj.assert_called_with(
        url="/v1/chimes/663d0aa401108803e4000447", public_api=True
    )


def test_led_settings_deserialization_with_blink_rate():
    """Test that LEDSettings can be created with blink_rate field (older Protect versions)."""
    led_data = {
        "isEnabled": False,
        "blinkRate": 100,
    }
    led_settings = LEDSettings.from_unifi_dict(**led_data)

    assert led_settings.is_enabled is False
    assert led_settings.blink_rate == 100
    assert led_settings.welcome_led is None
    assert led_settings.flood_led is None


def test_led_settings_deserialization_without_blink_rate():
    """Test that LEDSettings can be created without blink_rate field (Protect 6.x+)."""
    led_data = {
        "isEnabled": True,
    }
    led_settings = LEDSettings.from_unifi_dict(**led_data)

    assert led_settings.is_enabled is True
    assert led_settings.blink_rate is None
    assert led_settings.welcome_led is None
    assert led_settings.flood_led is None


def test_led_settings_with_new_fields():
    """Test LED settings with welcome_led and flood_led fields (Protect 6.2+)."""
    led_data = {
        "isEnabled": True,
        "welcomeLed": True,
        "floodLed": False,
    }
    led_settings = LEDSettings.from_unifi_dict(**led_data)

    assert led_settings.is_enabled is True
    assert led_settings.blink_rate is None
    assert led_settings.welcome_led is True
    assert led_settings.flood_led is False


def test_led_settings_serialization_with_all_fields():
    """Test that LEDSettings serialization includes all fields when set."""
    led_settings = LEDSettings(
        is_enabled=True,
        blink_rate=0,
        welcome_led=True,
        flood_led=False,
    )

    # Test unifi_dict() serialization (for API)
    serialized = led_settings.unifi_dict()

    # All fields should be present in camelCase
    assert serialized["isEnabled"] is True
    assert serialized["blinkRate"] == 0
    assert serialized["welcomeLed"] is True
    assert serialized["floodLed"] is False


@pytest.mark.asyncio()
async def test_update_bootstrap_soon_creates_task_when_none_exists(
    protect_client: ProtectApiClient,
):
    """Test _update_bootstrap_soon creates a new task when none exists."""
    protect_client._update_task = None
    protect_client.update = AsyncMock()

    protect_client._update_bootstrap_soon()

    assert protect_client._update_task is not None
    await protect_client._update_task
    protect_client.update.assert_called_once()


@pytest.mark.asyncio()
async def test_update_bootstrap_soon_creates_task_when_previous_done(
    protect_client: ProtectApiClient,
):
    """Test _update_bootstrap_soon creates a new task when previous task is done."""
    completed_task = asyncio.create_task(asyncio.sleep(0))
    await completed_task
    protect_client._update_task = completed_task
    protect_client.update = AsyncMock()

    protect_client._update_bootstrap_soon()

    assert protect_client._update_task is not None
    await protect_client._update_task
    protect_client.update.assert_called_once()


@pytest.mark.asyncio()
async def test_update_bootstrap_soon_skips_when_task_running(
    protect_client: ProtectApiClient,
):
    """Test _update_bootstrap_soon does not create a new task when one is running."""
    task_event = asyncio.Event()
    running_task = asyncio.create_task(task_event.wait())
    protect_client._update_task = running_task
    protect_client.update = AsyncMock()

    protect_client._update_bootstrap_soon()

    assert protect_client._update_task is running_task
    protect_client.update.assert_not_called()

    task_event.set()
    await running_task


# Tests for JSON deserialization in api_request, api_request_obj, api_request_list


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_data,expected,expected_type",
    [
        (b'{"key": "value", "number": 42}', {"key": "value", "number": 42}, dict),
        (b'[{"id": 1}, {"id": 2}]', [{"id": 1}, {"id": 2}], list),
        (None, None, type(None)),
    ],
    ids=["dict_response", "list_response", "empty_response"],
)
async def test_api_request_success(
    simple_api_client, response_data, expected, expected_type
):
    """Test api_request successfully deserializes various JSON responses."""
    simple_api_client.api_request_raw = AsyncMock(return_value=response_data)

    result = await simple_api_client.api_request("/test")

    assert result == expected
    assert isinstance(result, expected_type)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_data",
    [
        pytest.param(b"invalid json {{{", id="invalid_syntax"),
        pytest.param(b'{"key": "value"', id="truncated"),
        pytest.param(b"\x00\x01\x02\x03\x04", id="binary_data"),
    ],
)
async def test_api_request_json_decode_error(simple_api_client, invalid_data):
    """Test api_request raises NvrError on JSONDecodeError."""
    simple_api_client.api_request_raw = AsyncMock(return_value=invalid_data)

    with pytest.raises(NvrError, match="Could not decode JSON from /test"):
        await simple_api_client.api_request("/test")


@pytest.mark.asyncio
async def test_api_request_complex_nested_json(simple_api_client):
    """Test api_request handles complex nested JSON structures."""
    complex_json = b'{"devices": [{"id": "cam1"}], "meta": {"nested": {"deep": true}}}'
    simple_api_client.api_request_raw = AsyncMock(return_value=complex_json)

    result = await simple_api_client.api_request("/test")

    assert result["devices"][0]["id"] == "cam1"
    assert result["meta"]["nested"]["deep"] is True


@pytest.mark.asyncio
async def test_api_request_unicode(simple_api_client):
    """Test api_request handles JSON with unicode characters."""
    simple_api_client.api_request_raw = AsyncMock(
        return_value='{"name": "Kamera Außen", "emoji": "📷"}'.encode()
    )

    result = await simple_api_client.api_request("/test")

    assert result["name"] == "Kamera Außen"
    assert result["emoji"] == "📷"


@pytest.mark.asyncio
async def test_api_request_obj_success(simple_api_client):
    """Test api_request_obj successfully returns dict."""
    simple_api_client.api_request_raw = AsyncMock(return_value=b'{"id": "test-id"}')

    result = await simple_api_client.api_request_obj("/test")

    assert result == {"id": "test-id"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_data",
    [pytest.param(b'[{"id": 1}]', id="list"), pytest.param(b"null", id="null")],
)
async def test_api_request_obj_invalid_type(simple_api_client, response_data):
    """Test api_request_obj raises NvrError when response is not a dict."""
    simple_api_client.api_request_raw = AsyncMock(return_value=response_data)

    with pytest.raises(NvrError, match="Could not decode object from /test"):
        await simple_api_client.api_request_obj("/test")


@pytest.mark.asyncio
async def test_api_request_list_success(simple_api_client):
    """Test api_request_list successfully returns list."""
    simple_api_client.api_request_raw = AsyncMock(
        return_value=b'[{"id": 1}, {"id": 2}]'
    )

    result = await simple_api_client.api_request_list("/test")

    assert result == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_data",
    [pytest.param(b'{"id": "test"}', id="dict"), pytest.param(b"null", id="null")],
)
async def test_api_request_list_invalid_type(simple_api_client, response_data):
    """Test api_request_list raises NvrError when response is not a list."""
    simple_api_client.api_request_raw = AsyncMock(return_value=response_data)

    with pytest.raises(NvrError, match="Could not decode list from /test"):
        await simple_api_client.api_request_list("/test")


# PTZ Private API Tests


@pytest.mark.asyncio
async def test_get_presets_ptz_camera(protect_client: ProtectApiClient):
    """Test get_presets_ptz_camera API method."""
    mock_response: list[dict[str, Any]] = [
        {
            "id": "preset1",
            "name": "Home",
            "slot": -1,
            "ptz": {"pan": 0.0, "tilt": 0.0, "zoom": 1.0},
        },
        {
            "id": "preset2",
            "name": "Front Door",
            "slot": 0,
            "ptz": {"pan": 45.0, "tilt": 10.0, "zoom": 2.0},
        },
    ]
    protect_client.api_request = AsyncMock(return_value=mock_response)

    presets = await protect_client.get_presets_ptz_camera("camera123")

    assert len(presets) == 2
    assert all(isinstance(p, PTZPreset) for p in presets)
    assert presets[0].name == "Home"
    assert presets[0].slot == -1
    assert presets[0].id == "preset1"
    assert presets[1].name == "Front Door"
    assert presets[1].slot == 0
    assert presets[1].id == "preset2"

    protect_client.api_request.assert_called_with("cameras/camera123/ptz/preset")


@pytest.mark.asyncio
async def test_get_patrols_ptz_camera(protect_client: ProtectApiClient):
    """Test get_patrols_ptz_camera API method."""
    mock_response: list[dict[str, Any]] = [
        {
            "name": "Patrol",
            "slot": 0,
            "presets": [0],
            "presetMovementSpeed": None,
            "presetDurationSeconds": 20,
            "camera": "camera123",
            "id": "patrol1",
            "modelKey": "ptzPatrol",
        },
        {
            "name": "Patrol 2",
            "slot": 1,
            "presets": [0, 2, 3],
            "presetMovementSpeed": 50,
            "presetDurationSeconds": 23,
            "camera": "camera123",
            "id": "patrol2",
            "modelKey": "ptzPatrol",
        },
    ]
    protect_client.api_request = AsyncMock(return_value=mock_response)

    patrols = await protect_client.get_patrols_ptz_camera("camera123")

    assert len(patrols) == 2
    assert all(isinstance(p, PTZPatrol) for p in patrols)
    assert patrols[0].name == "Patrol"
    assert patrols[0].slot == 0
    assert patrols[0].presets == [0]
    assert patrols[0].preset_movement_speed is None
    assert patrols[0].preset_duration_seconds == 20
    assert patrols[1].name == "Patrol 2"
    assert patrols[1].preset_movement_speed == 50
    assert patrols[1].presets == [0, 2, 3]

    protect_client.api_request.assert_called_with("cameras/camera123/ptz/patrol")


@pytest.mark.parametrize(
    ("method", "api_path"),
    [
        ("get_presets_ptz_camera", "cameras/camera123/ptz/preset"),
        ("get_patrols_ptz_camera", "cameras/camera123/ptz/patrol"),
    ],
)
@pytest.mark.parametrize("return_value", [[], None])
@pytest.mark.asyncio
async def test_ptz_get_methods_empty(
    protect_client: ProtectApiClient,
    method: str,
    api_path: str,
    return_value: list[Any] | None,
):
    """Test PTZ get methods return empty list when no data or None."""
    protect_client.api_request = AsyncMock(return_value=return_value)

    result = await getattr(protect_client, method)("camera123")

    assert result == []
    protect_client.api_request.assert_called_with(api_path)


# PTZ Public API Tests


@pytest.mark.parametrize(
    ("method", "args", "expected_path"),
    [
        ("ptz_goto_preset_public", {"slot": 2}, "/ptz/goto/2"),
        ("ptz_patrol_start_public", {"slot": 1}, "/ptz/patrol/start/1"),
        ("ptz_patrol_stop_public", {}, "/ptz/patrol/stop"),
    ],
)
@pytest.mark.asyncio()
async def test_ptz_public_api(
    protect_client: ProtectApiClient, method: str, args: dict, expected_path: str
):
    """Test PTZ public API methods."""
    protect_client.api_request_raw = AsyncMock(return_value=b"")

    await getattr(protect_client, method)("camera123", **args)

    protect_client.api_request_raw.assert_called_with(
        url=f"/v1/cameras/camera123{expected_path}",
        method="post",
        public_api=True,
    )


# Talkback Public API Tests


@pytest.mark.asyncio
async def test_create_talkback_session_public(protect_client: ProtectApiClient):
    """Test create_talkback_session_public API method."""
    mock_response: dict[str, Any] = {
        "url": "rtp://192.168.1.100:7004",
        "codec": "opus",
        "samplingRate": 24000,
    }
    protect_client.api_request_obj = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

    session = await protect_client.create_talkback_session_public("camera123")

    assert isinstance(session, TalkbackSession)
    assert session.url == "rtp://192.168.1.100:7004"
    assert session.codec == "opus"
    assert session.sampling_rate == 24000
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url="/v1/cameras/camera123/talkback-session",
        method="post",
        public_api=True,
    )
