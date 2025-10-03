"""Tests for Public API Websockets (Events and Devices)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.websocket import WebsocketState

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient


@pytest.mark.asyncio()
async def test_subscribe_events_websocket(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test subscribing to events websocket."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    # Subscribe
    unsub = protect_client.subscribe_events_websocket(capture_ws)

    assert len(protect_client._events_ws_subscriptions) == 1
    assert protect_client._events_ws_subscriptions[0] == capture_ws

    # Unsubscribe
    unsub()

    assert len(protect_client._events_ws_subscriptions) == 0


@pytest.mark.asyncio()
async def test_subscribe_devices_websocket(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test subscribing to devices websocket."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    # Subscribe
    unsub = protect_client.subscribe_devices_websocket(capture_ws)

    assert len(protect_client._devices_ws_subscriptions) == 1
    assert protect_client._devices_ws_subscriptions[0] == capture_ws

    # Unsubscribe
    unsub()

    assert len(protect_client._devices_ws_subscriptions) == 0


@pytest.mark.asyncio()
async def test_subscribe_events_websocket_state(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test subscribing to events websocket state changes."""
    protect_client = protect_client_no_debug

    states: list[WebsocketState] = []

    def capture_state(state: WebsocketState) -> None:
        states.append(state)

    # Subscribe
    unsub = protect_client.subscribe_events_websocket_state(capture_state)

    assert len(protect_client._events_ws_state_subscriptions) == 1
    assert protect_client._events_ws_state_subscriptions[0] == capture_state

    # Unsubscribe
    unsub()

    assert len(protect_client._events_ws_state_subscriptions) == 0


@pytest.mark.asyncio()
async def test_subscribe_devices_websocket_state(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test subscribing to devices websocket state changes."""
    protect_client = protect_client_no_debug

    states: list[WebsocketState] = []

    def capture_state(state: WebsocketState) -> None:
        states.append(state)

    # Subscribe
    unsub = protect_client.subscribe_devices_websocket_state(capture_state)

    assert len(protect_client._devices_ws_state_subscriptions) == 1
    assert protect_client._devices_ws_state_subscriptions[0] == capture_state

    # Unsubscribe
    unsub()

    assert len(protect_client._devices_ws_state_subscriptions) == 0


@pytest.mark.asyncio()
async def test_process_events_ws_message_add(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing events websocket message with ADD action."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_events_websocket(capture_ws)

    # Create a mock websocket message (JSON format for public API)
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = '{"type":"add","item":{"id":"test-event-123","modelKey":"event","type":"motion","start":1234567890}}'

    protect_client._process_events_ws_message(msg)

    assert len(messages) == 1
    assert messages[0].action == WSAction.ADD
    assert messages[0].changed_data["id"] == "test-event-123"
    assert messages[0].changed_data["modelKey"] == "event"

    unsub()


@pytest.mark.asyncio()
async def test_process_events_ws_message_update(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing events websocket message with UPDATE action."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_events_websocket(capture_ws)

    # Create a mock websocket message
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = '{"type":"update","item":{"id":"test-event-123","modelKey":"event","end":1234567900}}'

    protect_client._process_events_ws_message(msg)

    assert len(messages) == 1
    assert messages[0].action == WSAction.UPDATE
    assert messages[0].changed_data["id"] == "test-event-123"
    assert messages[0].changed_data["end"] == 1234567900

    unsub()


@pytest.mark.asyncio()
async def test_process_devices_ws_message_update(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing devices websocket message with UPDATE action."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_devices_websocket(capture_ws)

    # Create a mock websocket message
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = '{"type":"update","item":{"id":"test-sensor-123","modelKey":"sensor","leakDetectedAt":null}}'

    protect_client._process_devices_ws_message(msg)

    assert len(messages) == 1
    assert messages[0].action == WSAction.UPDATE
    assert messages[0].changed_data["id"] == "test-sensor-123"
    assert messages[0].changed_data["modelKey"] == "sensor"

    unsub()


@pytest.mark.asyncio()
async def test_process_events_ws_message_remove(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing events websocket message with REMOVE action."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_events_websocket(capture_ws)

    # Create a mock websocket message
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = '{"type":"remove","item":{"id":"test-event-123","modelKey":"event"}}'

    protect_client._process_events_ws_message(msg)

    assert len(messages) == 1
    assert messages[0].action == WSAction.REMOVE
    assert messages[0].changed_data["id"] == "test-event-123"

    unsub()


@pytest.mark.asyncio()
async def test_process_events_ws_message_invalid_json(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing events websocket message with invalid JSON."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_events_websocket(capture_ws)

    # Create a mock websocket message with invalid JSON
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = "invalid json"

    # Should not raise exception, just log error
    protect_client._process_events_ws_message(msg)

    assert len(messages) == 0

    unsub()


@pytest.mark.asyncio()
async def test_process_events_ws_message_missing_type(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing events websocket message with missing type."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_events_websocket(capture_ws)

    # Create a mock websocket message without type
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = '{"item":{"id":"test-event-123","modelKey":"event"}}'

    protect_client._process_events_ws_message(msg)

    assert len(messages) == 0

    unsub()


@pytest.mark.asyncio()
async def test_process_events_ws_message_unknown_model(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing events websocket message with unknown model type."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_events_websocket(capture_ws)

    # Create a mock websocket message with unknown model
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = '{"type":"add","item":{"id":"test-123","modelKey":"unknownModel"}}'

    protect_client._process_events_ws_message(msg)

    assert len(messages) == 0

    unsub()


@pytest.mark.asyncio()
async def test_process_events_ws_message_non_text(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing events websocket message with non-text type."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_events_websocket(capture_ws)

    # Create a mock websocket message with binary type
    msg = MagicMock()
    msg.type = 2  # WSMsgType.BINARY
    msg.data = b"binary data"

    protect_client._process_events_ws_message(msg)

    assert len(messages) == 0

    unsub()


@pytest.mark.asyncio()
async def test_emit_events_message(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test emitting events messages to multiple subscribers."""
    protect_client = protect_client_no_debug

    messages1: list[WSSubscriptionMessage] = []
    messages2: list[WSSubscriptionMessage] = []

    def capture_ws1(message: WSSubscriptionMessage) -> None:
        messages1.append(message)

    def capture_ws2(message: WSSubscriptionMessage) -> None:
        messages2.append(message)

    unsub1 = protect_client.subscribe_events_websocket(capture_ws1)
    unsub2 = protect_client.subscribe_events_websocket(capture_ws2)

    # Create a test message
    test_msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id="test-123",
        changed_data={"id": "test-event", "modelKey": "event"},
    )

    protect_client.emit_events_message(test_msg)

    assert len(messages1) == 1
    assert len(messages2) == 1
    assert messages1[0] == test_msg
    assert messages2[0] == test_msg

    unsub1()
    unsub2()


@pytest.mark.asyncio()
async def test_emit_devices_message(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test emitting devices messages to multiple subscribers."""
    protect_client = protect_client_no_debug

    messages1: list[WSSubscriptionMessage] = []
    messages2: list[WSSubscriptionMessage] = []

    def capture_ws1(message: WSSubscriptionMessage) -> None:
        messages1.append(message)

    def capture_ws2(message: WSSubscriptionMessage) -> None:
        messages2.append(message)

    unsub1 = protect_client.subscribe_devices_websocket(capture_ws1)
    unsub2 = protect_client.subscribe_devices_websocket(capture_ws2)

    # Create a test message
    test_msg = WSSubscriptionMessage(
        action=WSAction.UPDATE,
        new_update_id="test-456",
        changed_data={"id": "test-sensor", "modelKey": "sensor"},
    )

    protect_client.emit_devices_message(test_msg)

    assert len(messages1) == 1
    assert len(messages2) == 1
    assert messages1[0] == test_msg
    assert messages2[0] == test_msg

    unsub1()
    unsub2()


@pytest.mark.asyncio()
async def test_events_websocket_multiple_subscriptions(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test multiple subscriptions and unsubscriptions for events websocket."""
    protect_client = protect_client_no_debug

    messages1: list[WSSubscriptionMessage] = []
    messages2: list[WSSubscriptionMessage] = []

    def capture_ws1(message: WSSubscriptionMessage) -> None:
        messages1.append(message)

    def capture_ws2(message: WSSubscriptionMessage) -> None:
        messages2.append(message)

    # Subscribe both
    unsub1 = protect_client.subscribe_events_websocket(capture_ws1)
    unsub2 = protect_client.subscribe_events_websocket(capture_ws2)

    assert len(protect_client._events_ws_subscriptions) == 2

    # Unsubscribe first
    unsub1()

    assert len(protect_client._events_ws_subscriptions) == 1
    assert protect_client._events_ws_subscriptions[0] == capture_ws2

    # Unsubscribe second
    unsub2()

    assert len(protect_client._events_ws_subscriptions) == 0


@pytest.mark.asyncio()
async def test_devices_websocket_multiple_subscriptions(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test multiple subscriptions and unsubscriptions for devices websocket."""
    protect_client = protect_client_no_debug

    messages1: list[WSSubscriptionMessage] = []
    messages2: list[WSSubscriptionMessage] = []

    def capture_ws1(message: WSSubscriptionMessage) -> None:
        messages1.append(message)

    def capture_ws2(message: WSSubscriptionMessage) -> None:
        messages2.append(message)

    # Subscribe both
    unsub1 = protect_client.subscribe_devices_websocket(capture_ws1)
    unsub2 = protect_client.subscribe_devices_websocket(capture_ws2)

    assert len(protect_client._devices_ws_subscriptions) == 2

    # Unsubscribe first
    unsub1()

    assert len(protect_client._devices_ws_subscriptions) == 1
    assert protect_client._devices_ws_subscriptions[0] == capture_ws2

    # Unsubscribe second
    unsub2()

    assert len(protect_client._devices_ws_subscriptions) == 0


@pytest.mark.asyncio()
async def test_process_devices_ws_message_add(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test processing devices websocket message with ADD action."""
    protect_client = protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = protect_client.subscribe_devices_websocket(capture_ws)

    # Create a mock websocket message
    msg = MagicMock()
    msg.type = 1  # WSMsgType.TEXT
    msg.data = '{"type":"add","item":{"id":"test-camera-123","modelKey":"camera","name":"Test Camera"}}'

    protect_client._process_devices_ws_message(msg)

    assert len(messages) == 1
    assert messages[0].action == WSAction.ADD
    assert messages[0].changed_data["id"] == "test-camera-123"
    assert messages[0].changed_data["modelKey"] == "camera"

    unsub()


@pytest.mark.asyncio()
async def test_events_websocket_exception_handling(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test that exceptions in event callbacks don't crash the system."""
    protect_client = protect_client_no_debug

    call_count = 0

    def raising_callback(message: WSSubscriptionMessage) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Test exception")

    unsub = protect_client.subscribe_events_websocket(raising_callback)

    # Create a test message
    test_msg = WSSubscriptionMessage(
        action=WSAction.ADD,
        new_update_id="test-123",
        changed_data={"id": "test-event", "modelKey": "event"},
    )

    # Should not raise, just log the exception
    protect_client.emit_events_message(test_msg)

    assert call_count == 1

    unsub()


@pytest.mark.asyncio()
async def test_devices_websocket_exception_handling(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test that exceptions in device callbacks don't crash the system."""
    protect_client = protect_client_no_debug

    call_count = 0

    def raising_callback(message: WSSubscriptionMessage) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Test exception")

    unsub = protect_client.subscribe_devices_websocket(raising_callback)

    # Create a test message
    test_msg = WSSubscriptionMessage(
        action=WSAction.UPDATE,
        new_update_id="test-456",
        changed_data={"id": "test-sensor", "modelKey": "sensor"},
    )

    # Should not raise, just log the exception
    protect_client.emit_devices_message(test_msg)

    assert call_count == 1

    unsub()


@pytest.mark.asyncio()
async def test_events_ws_url(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test events websocket URL property."""
    protect_client = protect_client_no_debug

    # Get the events websocket URL
    events_url = protect_client.events_ws_url

    # Verify it's a string and contains the expected path
    assert isinstance(events_url, str)
    assert "/proxy/protect/integration/v1/subscribe/events" in events_url
    assert events_url.startswith("https://")


@pytest.mark.asyncio()
async def test_devices_ws_url(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test devices websocket URL property."""
    protect_client = protect_client_no_debug

    # Get the devices websocket URL
    devices_url = protect_client.devices_ws_url

    # Verify it's a string and contains the expected path
    assert isinstance(devices_url, str)
    assert "/proxy/protect/integration/v1/subscribe/devices" in devices_url
    assert devices_url.startswith("https://")


@pytest.mark.asyncio()
async def test_get_events_websocket(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test getting events websocket instance."""
    protect_client = protect_client_no_debug

    # Get the websocket instance (should create it if not exists)
    ws = protect_client._get_events_websocket()

    # Verify it's the same instance when called again
    ws2 = protect_client._get_events_websocket()
    assert ws is ws2


@pytest.mark.asyncio()
async def test_get_devices_websocket(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test getting devices websocket instance."""
    protect_client = protect_client_no_debug

    # Get the websocket instance (should create it if not exists)
    ws = protect_client._get_devices_websocket()

    # Verify it's the same instance when called again
    ws2 = protect_client._get_devices_websocket()
    assert ws is ws2


@pytest.mark.asyncio()
async def test_auth_public_api_websocket_with_api_key(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test authentication for public API websocket with API key."""
    protect_client = protect_client_no_debug

    # Set an API key for testing
    protect_client._api_key = "test-api-key-12345"

    headers = await protect_client._auth_public_api_websocket()

    assert headers is not None
    assert "X-API-KEY" in headers
    assert headers["X-API-KEY"] == "test-api-key-12345"


@pytest.mark.asyncio()
async def test_auth_public_api_websocket_without_api_key(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test authentication for public API websocket without API key raises error."""
    from uiprotect.exceptions import NotAuthorized

    protect_client = protect_client_no_debug

    # Ensure API key is None
    protect_client._api_key = None

    with pytest.raises(NotAuthorized, match="API key is required"):
        await protect_client._auth_public_api_websocket()


@pytest.mark.asyncio()
async def test_auth_public_api_websocket_force_param(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test authentication for public API websocket with force parameter."""
    protect_client = protect_client_no_debug

    # Set an API key for testing
    protect_client._api_key = "test-api-key-force"

    # Test with force=True
    headers_forced = await protect_client._auth_public_api_websocket(force=True)

    assert headers_forced is not None
    assert "X-API-KEY" in headers_forced
    assert headers_forced["X-API-KEY"] == "test-api-key-force"

    # Test with force=False
    headers_not_forced = await protect_client._auth_public_api_websocket(force=False)

    assert headers_not_forced is not None
    assert "X-API-KEY" in headers_not_forced
    assert headers_not_forced["X-API-KEY"] == "test-api-key-force"
