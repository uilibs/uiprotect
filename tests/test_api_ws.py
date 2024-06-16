"""Tests for uiprotect.unifi_protect_server."""

from __future__ import annotations

import asyncio
import base64
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from tests.conftest import (
    TEST_CAMERA_EXISTS,
    TEST_SENSOR_EXISTS,
    MockDatetime,
    MockWebsocket,
)
from uiprotect.data import EventType, WSPacket
from uiprotect.data.base import ProtectModel
from uiprotect.data.devices import EVENT_PING_INTERVAL, Camera
from uiprotect.data.types import ModelType
from uiprotect.data.websocket import (
    WSAction,
    WSJSONPacketFrame,
    WSSubscriptionMessage,
)
from uiprotect.utils import print_ws_stat_summary, to_js_time, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_benchmark.fixture import BenchmarkFixture

    from uiprotect import ProtectApiClient

PACKET_RAW = "AQEBAAAAAHR4nCXMQQrCMBBA0auUWRvIpJOm8Qbi2gNMZiZQ0NRFqIh4dwluP7z/AZa+7Q3OE7AqnCZo9ro9lbtddFRPhCayuOorOyqYXfEJXcprEqQZ55UHe+xq96u9h7HDWh9x+y+UqeZAsUrQrCFajFQWgu8PBLYjMAIBAQAAAAC2eJxVjr0KwzAMhF8leO6QOLZDOrdT126lg2PLxRA7wVYKIeTdK1PoD2jQfTodtzFcZ2DHiiUfH+xQsYw6IYFGtbyplaKRnDhE+0u7N81mSuW9LnugzxMgGLxSaCZ8u//z8xMifg4BUFuNmvS2kzY6QCqKdaaXsrNOcSN1ywfbgXGtg1JwpjSPfopkjMs4EloypK/ypSirrRau50I6w21vuQQpxaBEiQiThfECa/FBqcT2F6ZyTac="


@pytest.fixture(name="packet")
def packet_fixture():
    return WSPacket(base64.b64decode(PACKET_RAW))


class SubscriptionTest:
    callback_count: int = 0
    unsub: Callable[[], None] | None = None

    def callback(self, msg: WSSubscriptionMessage):
        self.callback_count += 1

        assert isinstance(msg.new_obj, ProtectModel)

        if msg.action == WSAction.ADD:
            assert msg.old_obj is None
        else:
            assert isinstance(msg.old_obj, ProtectModel)
            assert msg.old_obj.update_from_dict(msg.changed_data) == msg.new_obj

        if self.callback_count == 2:
            raise Exception

        if self.callback_count >= 3 and self.unsub is not None:
            self.unsub()


@pytest.mark.benchmark(group="websockets")
@pytest.mark.asyncio()
@pytest.mark.timeout(0)
async def test_ws_all(
    protect_client_ws: ProtectApiClient,
    ws_messages: dict[str, dict[str, Any]],
    benchmark: BenchmarkFixture,
):
    protect_client = protect_client_ws
    sub = SubscriptionTest()
    sub.unsub = protect_client.subscribe_websocket(sub.callback)
    _orig = protect_client.bootstrap.process_ws_packet

    stats = benchmark._make_stats(1)

    def benchmark_process_ws_packet(*args, **kwargs):
        runner = benchmark._make_runner(_orig, args, kwargs)
        duration, result = runner(None)
        stats.update(duration)

        return result

    # bypass pydantic checks
    object.__setattr__(
        protect_client.bootstrap,
        "process_ws_packet",
        benchmark_process_ws_packet,
    )

    websocket = await protect_client.get_websocket()

    ws_connect: MockWebsocket | None = websocket._ws_connection  # type: ignore[assignment]
    assert ws_connect is not None

    while websocket.is_connected:
        await asyncio.sleep(0.1)

    assert ws_connect.count == len(ws_messages)
    assert ws_connect.now == float(list(ws_messages.keys())[-1])
    assert sub.callback_count == 3


@pytest.mark.benchmark(group="websockets")
@pytest.mark.asyncio()
@pytest.mark.timeout(0)
async def test_ws_filtered(
    protect_client_ws: ProtectApiClient,
    benchmark: BenchmarkFixture,
):
    protect_client = protect_client_ws
    protect_client.bootstrap.capture_ws_stats = True
    protect_client._ignore_stats = True
    protect_client._subscribed_models = {
        ModelType.EVENT,
        ModelType.CAMERA,
        ModelType.LIGHT,
        ModelType.VIEWPORT,
        ModelType.SENSOR,
        ModelType.LIVEVIEW,
    }
    sub = SubscriptionTest()
    sub.unsub = protect_client.subscribe_websocket(sub.callback)
    _orig = protect_client.bootstrap.process_ws_packet

    stats = benchmark._make_stats(1)

    def benchmark_process_ws_packet(*args, **kwargs):
        runner = benchmark._make_runner(_orig, args, kwargs)
        duration, result = runner(None)
        stats.update(duration)

        return result

    # bypass pydantic checks
    object.__setattr__(
        protect_client.bootstrap,
        "process_ws_packet",
        benchmark_process_ws_packet,
    )

    websocket = await protect_client.get_websocket()

    ws_connect: MockWebsocket | None = websocket._ws_connection  # type: ignore[assignment]
    assert ws_connect is not None

    while websocket.is_connected:
        await asyncio.sleep(0.1)

    print_ws_stat_summary(protect_client.bootstrap.ws_stats)


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_ws_event_ring(
    protect_client_no_debug: ProtectApiClient,
    now,
    camera,
    packet: WSPacket,
):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"
    expected_event_id = "bf9a241afe74821ceffffd05"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "id": expected_event_id,
        "type": "ring",
        "start": to_js_time(now - timedelta(seconds=1)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": [],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "partition": None,
        "user": None,
        "metadata": {},
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
        "modelKey": "event",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera = get_camera()

    event = camera.last_ring_event
    camera_before.last_ring_event_id = None
    camera.last_ring_event_id = None

    assert camera.last_ring == event.start
    camera.last_ring = None
    camera_before.last_ring = None

    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.RING
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"

    for channel in camera.channels:
        assert channel._api is not None


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_ws_event_motion(
    protect_client_no_debug: ProtectApiClient,
    now,
    camera,
    packet: WSPacket,
):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"
    expected_event_id = "bf9a241afe74821ceffffd05"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "id": expected_event_id,
        "type": "motion",
        "start": to_js_time(now - timedelta(seconds=30)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": [],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "partition": None,
        "user": None,
        "metadata": {},
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
        "modelKey": "event",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera = get_camera()

    event = camera.last_motion_event
    camera_before.last_motion_event_id = None
    camera.last_motion_event_id = None

    assert camera.last_motion == event.start
    camera_before.last_motion = None
    camera.last_motion = None

    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.MOTION
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"
    assert event.start == (now - timedelta(seconds=30))

    for channel in camera.channels:
        assert channel._api is not None


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_ws_event_smart(
    protect_client_no_debug: ProtectApiClient,
    now,
    camera,
    packet: WSPacket,
):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"
    expected_event_id = "bf9a241afe74821ceffffd05"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "id": expected_event_id,
        "type": "smartDetectZone",
        "start": to_js_time(now - timedelta(seconds=30)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": ["person"],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "partition": None,
        "user": None,
        "metadata": {},
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
        "modelKey": "event",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()
    camera = get_camera()

    smart_event = camera.last_smart_detect_event
    camera.last_smart_detect_event_id = None
    camera.last_smart_detect = None
    camera_before.last_smart_detect_event_id = None
    camera_before.last_smart_detect = None

    assert bootstrap == bootstrap_before
    assert camera.dict() == camera_before.dict()
    assert smart_event.id == expected_event_id
    assert smart_event.type == EventType.SMART_DETECT
    assert smart_event.thumbnail_id == f"e-{expected_event_id}"
    assert smart_event.heatmap_id == f"e-{expected_event_id}"
    assert smart_event.start == (now - timedelta(seconds=30))
    assert smart_event.end == now

    for channel in camera.channels:
        assert channel._api is not None


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_ws_event_update(
    protect_client_no_debug: ProtectApiClient,
    now,
    camera,
    packet: WSPacket,
):
    protect_client = protect_client_no_debug

    def get_camera() -> Camera:
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    new_stats = camera_before.stats.unifi_dict()
    new_stats["rxBytes"] += 100
    new_stats["txBytes"] += 100
    new_stats["video"]["recordingEnd"] = to_js_time(now)
    new_stats_unifi = camera_before.unifi_dict(data={"stats": deepcopy(new_stats)})

    del new_stats_unifi["stats"]["wifiQuality"]
    del new_stats_unifi["stats"]["wifiStrength"]

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "update",
        "newUpdateId": expected_updated_id,
        "modelKey": "camera",
        "id": camera["id"],
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = new_stats_unifi

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera_index = -1
    for index, camera_dict in enumerate(bootstrap_before["cameras"]):
        if camera_dict["id"] == camera["id"]:
            camera_index = index
            break

    bootstrap_before["cameras"][camera_index]["stats"] = new_stats
    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()

    assert bootstrap == bootstrap_before


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@patch("uiprotect.data.devices.utc_now")
@patch("uiprotect.data.base.EVENT_PING_INTERVAL_SECONDS", 0)
@pytest.mark.asyncio()
async def test_ws_emit_ring_callback(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    camera,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug
    protect_client.emit_message = Mock()  # type: ignore[method-assign]

    obj = protect_client.bootstrap.cameras[camera["id"]]

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "update",
        "newUpdateId": expected_updated_id,
        "modelKey": "camera",
        "id": camera["id"],
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"lastRing": to_js_time(now)}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert not obj.is_ringing
    with patch("uiprotect.data.bootstrap.utc_now", mock_now):
        protect_client._process_ws_message(msg)
    assert obj.is_ringing
    mock_now.return_value = utc_now() + EVENT_PING_INTERVAL
    assert not obj.is_ringing

    # The event message should be emitted
    assert protect_client.emit_message.call_count == 1

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # An empty messages should be emitted
    assert protect_client.emit_message.call_count == 2

    message: WSSubscriptionMessage = protect_client.emit_message.call_args[0][0]
    assert message.changed_data == {}


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_emit_alarm_callback(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    sensor,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug
    protect_client.emit_message = Mock()  # type: ignore[method-assign]

    obj = protect_client.bootstrap.sensors[sensor["id"]]

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "update",
        "newUpdateId": expected_updated_id,
        "modelKey": "sensor",
        "id": sensor["id"],
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"alarmTriggeredAt": to_js_time(now)}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert not obj.is_alarm_detected
    with patch("uiprotect.data.bootstrap.utc_now", mock_now):
        protect_client._process_ws_message(msg)
    assert obj.is_alarm_detected
    mock_now.return_value = utc_now() + EVENT_PING_INTERVAL
    assert not obj.is_alarm_detected


@pytest.mark.asyncio()
async def test_check_ws_connected(
    protect_client_ws: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)

    active_ws = protect_client_ws.check_ws()

    assert active_ws is True

    expected_logs: list[str] = []
    assert expected_logs == [rec.message for rec in caplog.records]


@pytest.mark.asyncio()
async def test_check_ws_no_ws_initial(
    protect_client: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)

    await protect_client.async_disconnect_ws()
    protect_client._last_ws_status = True

    active_ws = protect_client.check_ws()

    assert active_ws is False

    expected_logs = [
        "Disconnecting websocket...",
        "Websocket connection not active, failing back to polling",
    ]
    assert expected_logs == [rec.message for rec in caplog.records]
    assert caplog.records[1].levelname == "WARNING"


@pytest.mark.asyncio()
async def test_check_ws_no_ws(
    protect_client: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)

    await protect_client.async_disconnect_ws()
    protect_client._last_ws_status = False

    active_ws = protect_client.check_ws()

    assert active_ws is False

    expected_logs = [
        "Disconnecting websocket...",
        "Websocket connection not active, failing back to polling",
    ]
    assert expected_logs == [rec.message for rec in caplog.records]
    assert caplog.records[1].levelname == "DEBUG"


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_ignores_nvr_mac_and_guid(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    camera,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "update",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "camera",
        "id": camera["id"],
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"nvrMac": "any", "guid": "any", "isMotionDetected": True}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)
    protect_client._process_ws_message(msg)

    assert len(messages) == 1

    action_frame: WSJSONPacketFrame = packet.action_frame
    action_frame.data = {
        "action": "update",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138b",
        "modelKey": "camera",
        "id": camera["id"],
    }

    data_frame: WSJSONPacketFrame = packet.data_frame
    data_frame.data = {"nvrMac": "any", "guid": "any"}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    assert len(messages) == 1
    unsub()
