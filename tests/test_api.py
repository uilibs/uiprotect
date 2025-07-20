"""Tests for uiprotect.unifi_protect_server."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import aiohttp
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
from uiprotect.api import ProtectApiClient
from uiprotect.data import (
    Camera,
    Event,
    EventType,
    ModelType,
    create_from_unifi_dict,
)
from uiprotect.data.types import Version, VideoMode
from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from uiprotect.utils import to_js_time

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


def test_connection_host_override():
    protect = ProtectApiClient(
        "127.0.0.1",
        443,
        "test",
        "test",
        override_connection_host=True,
        store_sessions=False,
    )

    expected = IPv4Address("127.0.0.1")
    assert protect._connection_host == expected


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
    expected_events = []
    for event in raw_events:
        if event["score"] >= 50 and event["type"] in EventType.device_events():
            expected_events.append(event)

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
        url="/v1/cameras/test_id/snapshot",
        params={
            "highQuality": True,
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
            "trackNo": chime.track_no,
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
    import aiohttp

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
