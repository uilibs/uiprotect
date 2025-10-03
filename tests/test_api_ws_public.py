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
@pytest.mark.parametrize(
    ("new_obj", "old_obj", "use_debug"),
    [
        (None, None, False),  # Basic test without objects
        (MagicMock(model="event", id="test-1"), None, False),  # With new_obj
        (None, MagicMock(model="event", id="test-2"), False),  # With old_obj
        (
            MagicMock(model="event", id="test-3"),
            None,
            True,
        ),  # Debug logging with new_obj
        (
            None,
            MagicMock(model="event", id="test-4"),
            True,
        ),  # Debug logging with old_obj
        (None, None, True),  # Debug logging without objects
    ],
)
async def test_emit_events_message(
    protect_client_no_debug: ProtectApiClient,
    protect_client: ProtectApiClient,
    new_obj: MagicMock | None,
    old_obj: MagicMock | None,
    use_debug: bool,
) -> None:
    """Test emitting events messages with various configurations."""
    from unittest.mock import patch

    client = protect_client if use_debug else protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = client.subscribe_events_websocket(capture_ws)

    # Create a test message
    test_msg = WSSubscriptionMessage(
        action=WSAction.ADD
        if new_obj
        else WSAction.REMOVE
        if old_obj
        else WSAction.UPDATE,
        new_update_id="test-123",
        changed_data={"id": "test-event", "type": "motion"},
        new_obj=new_obj,
        old_obj=old_obj,
    )

    if use_debug:
        with patch("uiprotect.api._LOGGER") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            client.emit_events_message(test_msg)

            # Verify debug log was called
            assert mock_logger.debug.call_count >= 1
            call_args = mock_logger.debug.call_args[0]
            assert "emitting events message" in call_args[0]
    else:
        client.emit_events_message(test_msg)

    assert len(messages) == 1
    assert messages[0] == test_msg

    unsub()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("new_obj", "old_obj", "use_debug"),
    [
        (None, None, False),  # Basic test without objects
        (MagicMock(model="camera", id="test-1"), None, False),  # With new_obj
        (None, MagicMock(model="camera", id="test-2"), False),  # With old_obj
        (
            MagicMock(model="camera", id="test-3"),
            None,
            True,
        ),  # Debug logging with new_obj
        (
            None,
            MagicMock(model="camera", id="test-4"),
            True,
        ),  # Debug logging with old_obj
        (None, None, True),  # Debug logging without objects
    ],
)
async def test_emit_devices_message(
    protect_client_no_debug: ProtectApiClient,
    protect_client: ProtectApiClient,
    new_obj: MagicMock | None,
    old_obj: MagicMock | None,
    use_debug: bool,
) -> None:
    """Test emitting devices messages with various configurations."""
    from unittest.mock import patch

    client = protect_client if use_debug else protect_client_no_debug

    messages: list[WSSubscriptionMessage] = []

    def capture_ws(message: WSSubscriptionMessage) -> None:
        messages.append(message)

    unsub = client.subscribe_devices_websocket(capture_ws)

    # Create a test message
    test_msg = WSSubscriptionMessage(
        action=WSAction.UPDATE
        if new_obj
        else WSAction.REMOVE
        if old_obj
        else WSAction.ADD,
        new_update_id="test-456",
        changed_data={"id": "test-device", "name": "Test Camera"},
        new_obj=new_obj,
        old_obj=old_obj,
    )

    if use_debug:
        with patch("uiprotect.api._LOGGER") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            client.emit_devices_message(test_msg)

            # Verify debug log was called
            assert mock_logger.debug.call_count >= 1
            call_args = mock_logger.debug.call_args[0]
            assert "emitting devices message" in call_args[0]
    else:
        client.emit_devices_message(test_msg)

    assert len(messages) == 1
    assert messages[0] == test_msg

    unsub()


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
async def test_on_events_websocket_state_change(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test events websocket state change handler."""
    protect_client = protect_client_no_debug

    states: list[WebsocketState] = []

    def capture_state(state: WebsocketState) -> None:
        states.append(state)

    # Subscribe to state changes
    unsub = protect_client.subscribe_events_websocket_state(capture_state)

    # Simulate state changes
    protect_client._on_events_websocket_state_change(WebsocketState.CONNECTED)
    assert len(states) == 1
    assert states[0] == WebsocketState.CONNECTED

    protect_client._on_events_websocket_state_change(WebsocketState.DISCONNECTED)
    assert len(states) == 2
    assert states[1] == WebsocketState.DISCONNECTED

    unsub()


@pytest.mark.asyncio()
async def test_on_devices_websocket_state_change(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test devices websocket state change handler."""
    protect_client = protect_client_no_debug

    states: list[WebsocketState] = []

    def capture_state(state: WebsocketState) -> None:
        states.append(state)

    # Subscribe to state changes
    unsub = protect_client.subscribe_devices_websocket_state(capture_state)

    # Simulate state changes
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert len(states) == 1
    assert states[0] == WebsocketState.CONNECTED

    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    assert len(states) == 2
    assert states[1] == WebsocketState.DISCONNECTED

    unsub()


@pytest.mark.asyncio()
async def test_on_events_websocket_state_change_multiple_subscribers(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test events websocket state change with multiple subscribers."""
    protect_client = protect_client_no_debug

    states1: list[WebsocketState] = []
    states2: list[WebsocketState] = []

    def capture_state1(state: WebsocketState) -> None:
        states1.append(state)

    def capture_state2(state: WebsocketState) -> None:
        states2.append(state)

    # Subscribe both
    unsub1 = protect_client.subscribe_events_websocket_state(capture_state1)
    unsub2 = protect_client.subscribe_events_websocket_state(capture_state2)

    # Simulate state change
    protect_client._on_events_websocket_state_change(WebsocketState.CONNECTED)

    assert len(states1) == 1
    assert len(states2) == 1
    assert states1[0] == WebsocketState.CONNECTED
    assert states2[0] == WebsocketState.CONNECTED

    unsub1()
    unsub2()


@pytest.mark.asyncio()
async def test_on_devices_websocket_state_change_multiple_subscribers(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test devices websocket state change with multiple subscribers."""
    protect_client = protect_client_no_debug

    states1: list[WebsocketState] = []
    states2: list[WebsocketState] = []

    def capture_state1(state: WebsocketState) -> None:
        states1.append(state)

    def capture_state2(state: WebsocketState) -> None:
        states2.append(state)

    # Subscribe both
    unsub1 = protect_client.subscribe_devices_websocket_state(capture_state1)
    unsub2 = protect_client.subscribe_devices_websocket_state(capture_state2)

    # Simulate state change
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)

    assert len(states1) == 1
    assert len(states2) == 1
    assert states1[0] == WebsocketState.CONNECTED
    assert states2[0] == WebsocketState.CONNECTED

    unsub1()
    unsub2()


@pytest.mark.asyncio()
async def test_on_events_websocket_state_change_exception_handling(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test that exceptions in state change callbacks don't crash the system."""
    protect_client = protect_client_no_debug

    call_count = 0

    def raising_callback(state: WebsocketState) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Test exception")

    unsub = protect_client.subscribe_events_websocket_state(raising_callback)

    # Should not raise, just log the exception
    protect_client._on_events_websocket_state_change(WebsocketState.CONNECTED)

    assert call_count == 1

    unsub()


@pytest.mark.asyncio()
async def test_on_devices_websocket_state_change_exception_handling(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test that exceptions in state change callbacks don't crash the system."""
    protect_client = protect_client_no_debug

    call_count = 0

    def raising_callback(state: WebsocketState) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Test exception")

    unsub = protect_client.subscribe_devices_websocket_state(raising_callback)

    # Should not raise, just log the exception
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)

    assert call_count == 1

    unsub()


@pytest.mark.asyncio()
async def test_on_events_websocket_state_change_debug_logging(
    protect_client: ProtectApiClient,
) -> None:
    """Test events websocket state change with debug logging enabled."""
    states: list[WebsocketState] = []

    def capture_state(state: WebsocketState) -> None:
        states.append(state)

    # Subscribe to state changes
    unsub = protect_client.subscribe_events_websocket_state(capture_state)

    # Simulate different state changes with debug logging
    protect_client._on_events_websocket_state_change(WebsocketState.CONNECTED)
    assert len(states) == 1
    assert states[0] == WebsocketState.CONNECTED

    protect_client._on_events_websocket_state_change(WebsocketState.DISCONNECTED)
    assert len(states) == 2
    assert states[1] == WebsocketState.DISCONNECTED

    protect_client._on_events_websocket_state_change(WebsocketState.CONNECTED)
    assert len(states) == 3
    assert states[2] == WebsocketState.CONNECTED

    unsub()


@pytest.mark.asyncio()
async def test_on_devices_websocket_state_change_debug_logging(
    protect_client: ProtectApiClient,
) -> None:
    """Test devices websocket state change with debug logging enabled."""
    states: list[WebsocketState] = []

    def capture_state(state: WebsocketState) -> None:
        states.append(state)

    # Subscribe to state changes
    unsub = protect_client.subscribe_devices_websocket_state(capture_state)

    # Simulate different state changes with debug logging
    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert len(states) == 1
    assert states[0] == WebsocketState.CONNECTED

    protect_client._on_devices_websocket_state_change(WebsocketState.DISCONNECTED)
    assert len(states) == 2
    assert states[1] == WebsocketState.DISCONNECTED

    protect_client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert len(states) == 3
    assert states[2] == WebsocketState.CONNECTED

    unsub()


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


@pytest.mark.asyncio()
async def test_get_last_update_id_bootstrap_none(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test _get_last_update_id when bootstrap is None."""
    protect_client = protect_client_no_debug

    # Ensure bootstrap is None
    protect_client._bootstrap = None

    result = protect_client._get_last_update_id()

    assert result is None


@pytest.mark.asyncio()
async def test_process_devices_ws_message_exception_handling(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test exception handling in _process_devices_ws_message."""
    from unittest.mock import MagicMock, patch

    import aiohttp
    import orjson

    protect_client = protect_client_no_debug

    # Create valid data structure that will pass initial checks
    valid_data = {
        "type": "update",
        "item": {
            "modelKey": "camera",
            "id": "test-id",
        },
    }

    # Create a mock WSMessage
    mock_msg = MagicMock(spec=aiohttp.WSMessage)
    mock_msg.type = aiohttp.WSMsgType.TEXT
    mock_msg.data = orjson.dumps(valid_data)

    # Patch orjson.loads to raise an exception during processing
    with (
        patch(
            "uiprotect.api.orjson.loads",
            side_effect=Exception("Test JSON parsing exception"),
        ),
        patch("uiprotect.api._LOGGER") as mock_logger,
    ):
        # This should catch the exception and log it
        protect_client._process_devices_ws_message(mock_msg)

        # Verify that exception was logged
        mock_logger.exception.assert_called_once()
        call_args = mock_logger.exception.call_args
        assert (
            "Error processing public API devices websocket message" in call_args[0][0]
        )


@pytest.mark.asyncio()
async def test_base_api_client_events_websocket_state_change_debug(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test BaseApiClient._on_events_websocket_state_change debug logging."""
    from unittest.mock import patch

    from uiprotect.api import BaseApiClient

    protect_client = protect_client_no_debug

    # Call the BaseApiClient method directly (not the overridden one)
    with patch("uiprotect.api._LOGGER") as mock_logger:
        mock_logger.isEnabledFor.return_value = True

        # Call the base class method directly
        BaseApiClient._on_events_websocket_state_change(
            protect_client, WebsocketState.CONNECTED
        )

        # Verify debug log was called
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert "Events websocket state changed" in call_args[0][0]
        assert WebsocketState.CONNECTED in call_args[0]


@pytest.mark.asyncio()
async def test_base_api_client_devices_websocket_state_change_debug(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test BaseApiClient._on_devices_websocket_state_change debug logging."""
    from unittest.mock import patch

    from uiprotect.api import BaseApiClient

    protect_client = protect_client_no_debug

    # Call the BaseApiClient method directly (not the overridden one)
    with patch("uiprotect.api._LOGGER") as mock_logger:
        mock_logger.isEnabledFor.return_value = True

        # Call the base class method directly
        BaseApiClient._on_devices_websocket_state_change(
            protect_client, WebsocketState.DISCONNECTED
        )

        # Verify debug log was called
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert "Devices websocket state changed" in call_args[0][0]
        assert WebsocketState.DISCONNECTED in call_args[0]


@pytest.mark.asyncio()
async def test_process_devices_ws_message_non_text_debug(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test _process_devices_ws_message debug logging for non-text messages."""
    from unittest.mock import MagicMock, patch

    import aiohttp

    protect_client = protect_client_no_debug

    # Create a non-text WebSocket message (e.g., BINARY)
    mock_msg = MagicMock(spec=aiohttp.WSMessage)
    mock_msg.type = aiohttp.WSMsgType.BINARY

    with patch("uiprotect.api._LOGGER") as mock_logger:
        # Process the non-text message
        protect_client._process_devices_ws_message(mock_msg)

        # Verify debug log was called
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert "Ignoring non-text websocket message" in call_args[0][0]
        assert aiohttp.WSMsgType.BINARY in call_args[0]


@pytest.mark.asyncio()
async def test_process_devices_ws_message_invalid_data_debug(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test _process_devices_ws_message debug logging for invalid data."""
    from unittest.mock import MagicMock, patch

    import aiohttp
    import orjson

    protect_client = protect_client_no_debug

    # Create a message with missing required fields
    invalid_data = {
        "type": "update",
        # Missing "item" or "item.modelKey"
    }

    mock_msg = MagicMock(spec=aiohttp.WSMessage)
    mock_msg.type = aiohttp.WSMsgType.TEXT
    mock_msg.data = orjson.dumps(invalid_data)

    with patch("uiprotect.api._LOGGER") as mock_logger:
        # Process the invalid message
        protect_client._process_devices_ws_message(mock_msg)

        # Verify debug log was called
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert "Invalid public API websocket message" in call_args[0][0]


@pytest.mark.asyncio()
async def test_process_devices_ws_message_unknown_model_debug(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """Test _process_devices_ws_message debug logging for unknown model type."""
    from unittest.mock import MagicMock, patch

    import aiohttp
    import orjson

    protect_client = protect_client_no_debug

    # Create a message with an unknown model type
    unknown_model_data = {
        "type": "update",
        "item": {
            "modelKey": "unknown_model_type_xyz",
            "id": "test-id",
        },
    }

    mock_msg = MagicMock(spec=aiohttp.WSMessage)
    mock_msg.type = aiohttp.WSMsgType.TEXT
    mock_msg.data = orjson.dumps(unknown_model_data)

    with patch("uiprotect.api._LOGGER") as mock_logger:
        # Process the message with unknown model
        protect_client._process_devices_ws_message(mock_msg)

        # Verify debug log was called
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert "Unknown model type in public API message" in call_args[0][0]
        assert "unknown_model_type_xyz" in call_args[0]
