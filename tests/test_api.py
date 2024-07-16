"""Tests for uiprotect.unifi_protect_server."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
from ipaddress import IPv4Address
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from tests.conftest import (
    TEST_BRIDGE_EXISTS,
    TEST_CAMERA_EXISTS,
    TEST_HEATMAP_EXISTS,
    TEST_LIGHT_EXISTS,
    TEST_LIVEVIEW_EXISTS,
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
from uiprotect.data.types import VideoMode
from uiprotect.exceptions import BadRequest, NvrError
from uiprotect.utils import to_js_time

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

    for channel in camera.channels:
        assert channel._api is not None

    data = await camera.get_snapshot()
    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.format in {"PNG", "JPEG"}

    camera.last_ring_event  # noqa: B018

    assert camera.timelapse_url == f"https://127.0.0.1:0/protect/timelapse/{camera.id}"
    check_device(camera)

    for channel in camera.channels:
        if channel.is_rtsp_enabled:
            assert (
                channel.rtsp_url
                == f"rtsp://{camera.api.connection_host}:7447/{channel.rtsp_alias}"
            )
            assert (
                channel.rtsps_url
                == f"rtsps://{camera.api.connection_host}:7441/{channel.rtsp_alias}?enableSrtp"
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
    arg = f"{protect_client.ws_path}?lastUpdateId={protect_client.bootstrap.last_update_id}"

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
async def test_force_update(protect_client: ProtectApiClient):
    protect_client._bootstrap = None

    await protect_client.update()

    assert protect_client.bootstrap
    original_bootstrap = protect_client.bootstrap
    protect_client._bootstrap = None
    with patch("uiprotect.api.ProtectApiClient.get_bootstrap", AsyncMock()) as mock:
        await protect_client.update()
        assert mock.called

    assert protect_client.bootstrap
    assert original_bootstrap != protect_client.bootstrap


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
    assert obj == await protect_client.get_camera("test_id")


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_camera(protect_client: ProtectApiClient, camera):
    obj = create_from_unifi_dict(camera)

    assert obj == await protect_client.get_camera("test_id")


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_light(protect_client: ProtectApiClient, light):
    obj = create_from_unifi_dict(light)

    assert obj == await protect_client.get_light("test_id")


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_sensor(protect_client: ProtectApiClient, sensor):
    obj = create_from_unifi_dict(sensor)

    assert obj == await protect_client.get_sensor("test_id")


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_viewer(protect_client: ProtectApiClient, viewport):
    obj = create_from_unifi_dict(viewport)

    assert obj == await protect_client.get_viewer("test_id")


@pytest.mark.skipif(not TEST_BRIDGE_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_bridge(protect_client: ProtectApiClient, bridge):
    obj = create_from_unifi_dict(bridge)

    assert obj == await protect_client.get_bridge("test_id")


@pytest.mark.skipif(not TEST_LIVEVIEW_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_liveview(protect_client: ProtectApiClient, liveview):
    obj = create_from_unifi_dict(liveview)

    assert obj == await protect_client.get_liveview("test_id")


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

    assert objs == await protect_client.get_cameras()


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_lights(protect_client: ProtectApiClient, lights):
    objs = [create_from_unifi_dict(d) for d in lights]

    assert objs == await protect_client.get_lights()


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_sensors(protect_client: ProtectApiClient, sensors):
    objs = [create_from_unifi_dict(d) for d in sensors]

    assert objs == await protect_client.get_sensors()


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_viewers(protect_client: ProtectApiClient, viewports):
    objs = [create_from_unifi_dict(d) for d in viewports]

    assert objs == await protect_client.get_viewers()


@pytest.mark.skipif(not TEST_BRIDGE_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_bridges(protect_client: ProtectApiClient, bridges):
    objs = [create_from_unifi_dict(d) for d in bridges]

    assert objs == await protect_client.get_bridges()


@pytest.mark.skipif(not TEST_LIVEVIEW_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_get_liveviews(protect_client: ProtectApiClient, liveviews):
    objs = [create_from_unifi_dict(d) for d in liveviews]

    assert objs == await protect_client.get_liveviews()


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
    )
