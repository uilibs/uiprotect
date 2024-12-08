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
from uiprotect.data.user import Keyring, Keyrings, UlpUser, UlpUsers
from uiprotect.data.websocket import (
    WSAction,
    WSJSONPacketFrame,
    WSSubscriptionMessage,
)
from uiprotect.utils import print_ws_stat_summary, to_js_time, utc_now
from uiprotect.websocket import WebsocketState

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

    websocket = protect_client._get_websocket()

    while not websocket.is_connected:
        await asyncio.sleep(0.05)

    stats = benchmark._make_stats(1)
    processed_packets = 0

    def benchmark_process_ws_packet(*args, **kwargs):
        nonlocal processed_packets
        processed_packets += 1
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

    ws_connect: MockWebsocket | None = websocket._ws_connection  # type: ignore[assignment]
    assert ws_connect is not None

    while websocket.is_connected:
        await asyncio.sleep(0.05)

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

    websocket = protect_client._get_websocket()
    while not websocket.is_connected:
        await asyncio.sleep(0.05)

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

    ws_connect: MockWebsocket | None = websocket._ws_connection  # type: ignore[assignment]
    assert ws_connect is not None

    while websocket.is_connected:
        await asyncio.sleep(0.05)

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
async def test_ws_event_nfc_card_scanned(
    protect_client_no_debug: ProtectApiClient,
    now,
    camera,
    packet: WSPacket,
):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b03-b071-7987c143138a"
    expected_event_id = "6730b5af01029603e4003bdb"
    expected_nfc_id = "66B2A649"
    expected_user_id = "672b570000f79603e400049d"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "id": expected_event_id,
        "modelKey": "event",
        "type": "nfcCardScanned",
        "start": to_js_time(now - timedelta(seconds=30)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": [],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "metadata": {
            "nfc": {"nfcId": expected_nfc_id, "userId": expected_user_id},
            "ramDescription": "",
            "ramClassifications": [],
        },
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
    }

    camera = get_camera()

    assert camera.last_nfc_card_scanned_event is None
    assert camera.feature_flags.support_nfc is True

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    event = camera.last_nfc_card_scanned_event
    camera_before.last_nfc_card_scanned_event_id = None
    camera.last_nfc_card_scanned_event_id = None

    assert camera.last_nfc_card_scanned == event.start
    camera_before.last_nfc_card_scanned = None
    camera.last_nfc_card_scanned = None

    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.NFC_CARD_SCANNED
    assert event.metadata.nfc.nfc_id == expected_nfc_id
    assert event.metadata.nfc.user_id == expected_user_id
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"
    assert event.start == (now - timedelta(seconds=30))
    assert event.end == now

    for channel in camera.channels:
        assert channel._api is not None


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_ws_event_fingerprint_identified(
    protect_client_no_debug: ProtectApiClient,
    now,
    camera,
    packet: WSPacket,
):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b03-b071-7987c143138a"
    expected_event_id = "6730b5af01029603e4003bdb"
    expected_ulp_id = "0ef32f12-f291-123d-ab12-30e373e12345"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "id": expected_event_id,
        "modelKey": "event",
        "type": "fingerprintIdentified",
        "start": to_js_time(now - timedelta(seconds=30)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": [],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "metadata": {
            "fingerprint": {"ulpId": expected_ulp_id},
            "ramDescription": "",
            "ramClassifications": [],
        },
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
    }

    camera = get_camera()

    assert camera.last_fingerprint_identified_event is None
    assert camera.feature_flags.has_fingerprint_sensor is True

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    event = camera.last_fingerprint_identified_event
    camera_before.last_fingerprint_identified_event_id = None
    camera.last_fingerprint_identified_event_id = None

    assert camera.last_fingerprint_identified == event.start
    camera_before.last_fingerprint_identified = None
    camera.last_fingerprint_identified = None

    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.FINGERPRINT_IDENTIFIED
    assert event.metadata.fingerprint.ulp_id == expected_ulp_id
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"
    assert event.start == (now - timedelta(seconds=30))
    assert event.end == now

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


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@patch("uiprotect.data.devices.utc_now")
@patch("uiprotect.data.base.EVENT_PING_INTERVAL_SECONDS", 0)
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

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"alarmTriggeredAt": to_js_time(now)}

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

    # The event message should be emitted
    assert protect_client.emit_message.call_count == 1

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # An empty messages should be emitted
    assert protect_client.emit_message.call_count == 2

    message: WSSubscriptionMessage = protect_client.emit_message.call_args[0][0]
    assert message.changed_data == {}

    assert not obj.is_alarm_detected


@pytest.mark.asyncio()
async def test_check_ws_connected(
    protect_client_ws: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)
    unsub = protect_client_ws.subscribe_websocket(lambda _: None)
    while not protect_client_ws._websocket.is_connected:
        await asyncio.sleep(0.01)
    assert protect_client_ws._websocket.is_connected
    unsub()


@pytest.mark.asyncio()
async def test_check_ws_connected_state_callback(
    protect_client_ws: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
):
    websocket = protect_client_ws._websocket
    assert not websocket.is_connected

    caplog.set_level(logging.DEBUG)
    states: list[bool] = []

    def _on_state(state: bool):
        states.append(state)

    unsub_state = protect_client_ws.subscribe_websocket_state(_on_state)
    unsub = protect_client_ws.subscribe_websocket(lambda _: None)
    while websocket._current_state is not WebsocketState.CONNECTED:
        await asyncio.sleep(0.01)

    assert states == [WebsocketState.CONNECTED]
    await protect_client_ws.async_disconnect_ws()
    while websocket._current_state is not WebsocketState.DISCONNECTED:
        await asyncio.sleep(0.01)

    assert states == [WebsocketState.CONNECTED, WebsocketState.DISCONNECTED]
    unsub()
    unsub_state()


@pytest.mark.asyncio()
async def test_check_ws_no_ws_initial(
    protect_client: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)

    await protect_client.async_disconnect_ws()
    assert not protect_client._websocket


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


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_keyring_update(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    keyring_id = "some_id"
    old_ulp_user = "b45f9411-133d-400d-b92f-a434877123"
    new_ulp_user = "b45f9411-133d-400d-b92f-a434877321"

    keyring = Keyring(
        id=keyring_id,
        ulp_user=old_ulp_user,
        device_type="test",
        device_id="test",
        registry_type="test",
        registry_id="test",
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    protect_client.bootstrap.keyrings = Keyrings()
    protect_client.bootstrap.keyrings.add(keyring)

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "update",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "keyring",
        "id": "some_id",
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"ulpUser": new_ulp_user}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    assert protect_client.bootstrap.keyrings.by_id(keyring_id).ulp_user == old_ulp_user

    protect_client._process_ws_message(msg)

    assert protect_client.bootstrap.keyrings.by_id(keyring_id).ulp_user == new_ulp_user

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_keyring_remove(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    keyring_id = "some_id"
    ulp_user = "b45f9411-133d-400d-b92f-a434877123"

    keyring = Keyring(
        id=keyring_id,
        ulp_user=ulp_user,
        device_type="test",
        device_id="test",
        registry_type="test",
        registry_id="test",
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    protect_client.bootstrap.keyrings = Keyrings()
    protect_client.bootstrap.keyrings.add(keyring)

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "remove",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "keyring",
        "id": keyring_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    assert protect_client.bootstrap.keyrings.by_id(keyring_id) is not None

    protect_client._process_ws_message(msg)

    assert protect_client.bootstrap.keyrings.by_id(keyring_id) is None

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_keyring_add_nfc(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug
    protect_client.bootstrap.keyrings = Keyrings()

    keyring_id = "some_id"
    ulp_user = "b45f9411-133d-400d-b92f-a434877123"

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "add",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "keyring",
        "id": keyring_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "id": keyring_id,
        "modelKey": "keyring",
        "deviceType": "camera",
        "deviceId": "663d0aa400918803e4006454",
        "registryType": "nfc",
        "registryId": "046A5702E27548",
        "lastActivity": None,
        "metadata": {"nfc": {"isUACard": False}},
        "ulpUser": ulp_user,
        "createdAt": to_js_time(now),
        "updatedAt": to_js_time(now),
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    assert keyring_id not in protect_client.bootstrap.keyrings.as_list()

    protect_client._process_ws_message(msg)

    assert protect_client.bootstrap.keyrings.by_id(keyring_id) is not None
    assert protect_client.bootstrap.keyrings.by_id(keyring_id).ulp_user == ulp_user

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_keyring_add_fingerprint(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug
    protect_client.bootstrap.keyrings = Keyrings()

    keyring_id = "some_id"
    ulp_user = "b45f9411-133d-400d-b92f-a434877123"

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "add",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "keyring",
        "id": keyring_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "id": keyring_id,
        "modelKey": "keyring",
        "deviceType": "camera",
        "deviceId": "663d0aa400918803e4004578",
        "registryType": "fingerprint",
        "registryId": "2",
        "lastActivity": None,
        "ulpUser": ulp_user,
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    assert protect_client.bootstrap.keyrings.by_id(keyring_id) is None

    protect_client._process_ws_message(msg)

    assert protect_client.bootstrap.keyrings.by_id(keyring_id) is not None
    assert protect_client.bootstrap.keyrings.by_id(keyring_id).ulp_user == ulp_user

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_ulp_user_add(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug
    protect_client.bootstrap.ulp_users = UlpUsers()
    some_id = "some_id"
    some_ulp_id = "42313461-eaa0-45f6-b12d-a0783ed3d4s2"

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "add",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "ulpUser",
        "id": some_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {
        "ulpId": some_ulp_id,
        "firstName": "viewonly",
        "lastName": "",
        "fullName": "viewonly",
        "avatar": "",
        "status": "ACTIVE",
        "id": some_id,
        "modelKey": "ulpUser",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    assert protect_client.bootstrap.ulp_users.by_id(some_id) is None

    protect_client._process_ws_message(msg)

    assert protect_client.bootstrap.ulp_users.by_id(some_id) is not None

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_ulp_user_update(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    some_ulp_id = "42313461-eaa0-45f6-b12d-a0783ed3d4s2"

    ulp_usr = UlpUser(
        id=some_ulp_id,
        ulp_id=some_ulp_id,
        first_name="viewonly",
        last_name="",
        full_name="viewonly",
        avatar="",
        status="ACTIVE",
        model_key="ulpUser",
    )

    protect_client.bootstrap.ulp_users = UlpUsers()
    protect_client.bootstrap.ulp_users.add(ulp_usr)

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "update",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "ulpUser",
        "id": some_ulp_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"status": "DEACTIVATED"}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    assert protect_client.bootstrap.ulp_users.by_id(some_ulp_id).status == "ACTIVE"

    protect_client._process_ws_message(msg)

    assert protect_client.bootstrap.ulp_users.by_id(some_ulp_id).status == "DEACTIVATED"

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_ulp_user_remove(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    some_ulp_id = "42313461-eaa0-45f6-b12d-a0783ed3d4s2"

    ulp_usr = UlpUser(
        id=some_ulp_id,
        ulp_id=some_ulp_id,
        first_name="viewonly",
        last_name="",
        full_name="viewonly",
        avatar="",
        status="ACTIVE",
        model_key="ulpUser",
    )

    protect_client.bootstrap.ulp_users = UlpUsers()
    protect_client.bootstrap.ulp_users.add(ulp_usr)

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "remove",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "ulpUser",
        "id": some_ulp_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    assert protect_client.bootstrap.ulp_users.by_id(some_ulp_id) is not None

    protect_client._process_ws_message(msg)

    assert protect_client.bootstrap.ulp_users.by_id(some_ulp_id) is None

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_ulp_user_remove_user_not_exist(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    some_ulp_id = "42313461-eaa0-45f6-b12d-a0783ed3d4s2"

    protect_client.bootstrap.ulp_users = UlpUsers()

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "remove",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "ulpUser",
        "id": some_ulp_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    protect_client._process_ws_message(msg)

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_ulp_user_update_user_not_exist(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    some_ulp_id = "42313461-eaa0-45f6-b12d-a0783ed3d4s2"

    protect_client.bootstrap.ulp_users = UlpUsers()

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "update",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "ulpUser",
        "id": some_ulp_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"status": "DEACTIVATED"}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    protect_client._process_ws_message(msg)

    unsub()


@patch("uiprotect.data.devices.utc_now")
@pytest.mark.asyncio()
async def test_ws_ulp_user_unknown_action(
    mock_now,
    protect_client_no_debug: ProtectApiClient,
    now: datetime,
    packet: WSPacket,
):
    mock_now.return_value = now
    protect_client = protect_client_no_debug

    some_ulp_id = "42313461-eaa0-45f6-b12d-a0783ed3d4s2"

    protect_client.bootstrap.ulp_users = UlpUsers()

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_websocket(capture_ws)

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore[assignment]
    action_frame.data = {
        "action": "not_supported",
        "newUpdateId": "0441ecc6-f0fa-4b19-b071-7987c143138a",
        "modelKey": "ulpUser",
        "id": some_ulp_id,
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore[assignment]
    data_frame.data = {"status": "DEACTIVATED"}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    assert len(messages) == 0

    packet = WSPacket(msg.data)

    protect_client._process_ws_message(msg)

    unsub()
