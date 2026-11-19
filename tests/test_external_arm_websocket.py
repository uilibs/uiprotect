"""Tests for the ``subscribe/updates`` websocket of external arm profiles."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import aiohttp
import orjson
import pytest

from uiprotect import ProtectApiClient
from uiprotect.exceptions import NvrError
from uiprotect.websocket import Websocket, WebsocketState

from .test_api_public import _mock_update_public_endpoints
from .test_api_ws import (
    _CodeClosingWebsocket,
    _handshake_401,
    _QuietWebsocket,
    _wait_until,
)
from .test_public_external_arm_profiles_store import (
    PROFILE_ID,
    STORE,
    _mock_external_arm_websocket,
    _nvr,
    _prime,
    _profile,
    _raw,
    _tick,
    no_ws_connect,  # noqa: F401
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from uiprotect.data import PublicStoreChange

OTHER_ID = "6a1b2c3d4e5f60718293a4b6"
NEW_ID = "6a1b2c3d4e5f60718293a4c0"


class _FrameWebsocket(_QuietWebsocket):
    """WS that delivers the given frames, then blocks on receive."""

    def __init__(self, *frames: aiohttp.WSMessage) -> None:
        self.frames = list(frames)

    async def receive(self, timeout: float | None) -> Any:
        if self.frames:
            return self.frames.pop(0)
        return await super().receive(timeout)


def _frame(action: str, profile_id: str = PROFILE_ID, **item: Any) -> Any:
    payload = {
        "type": action,
        "item": {"id": profile_id, "modelKey": "externalArmProfile", **item},
    }
    return aiohttp.WSMessage(
        aiohttp.WSMsgType.TEXT, orjson.dumps(payload).decode(), None
    )


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def _update(client: ProtectApiClient, flag: bool | None = True) -> None:
    _mock_update_public_endpoints(
        client,
        get_nvr_public=AsyncMock(return_value=_nvr(client, flag)),
        _fetch_external_arm_profiles=AsyncMock(return_value=[_profile(client)]),
    )
    await client.update_public()


def _real_session(client: ProtectApiClient, *websockets: Any) -> AsyncMock:
    session = AsyncMock()
    if len(websockets) == 1:
        session.ws_connect = AsyncMock(return_value=websockets[0])
    else:
        session.ws_connect = AsyncMock(side_effect=list(websockets))
    client.get_public_api_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
    return session


def _real_websocket(client: ProtectApiClient, *websockets: Any) -> AsyncMock:
    session = _real_session(client, *websockets)
    client._get_external_arm_websocket().backoff = 0
    return session


def _refetch_mock(client: ProtectApiClient, **kwargs: Any) -> AsyncMock:
    refresh = AsyncMock(**kwargs)
    client.refresh_public_store = refresh  # type: ignore[method-assign]
    return refresh


@pytest.mark.asyncio()
async def test_no_socket_before_update_public(protect_client: ProtectApiClient) -> None:
    """Subscribing before the first ``update_public`` opens nothing."""
    protect_client.subscribe_public_store_changes(lambda _: None)
    await _settle()

    assert protect_client._external_arm_websocket is None


@pytest.mark.asyncio()
async def test_no_socket_after_raising_first_update_public(
    protect_client: ProtectApiClient,
) -> None:
    """A first ``update_public`` that raised does not enable the socket."""
    websocket = _mock_external_arm_websocket(protect_client)
    protect_client.subscribe_public_store_changes(lambda _: None)
    _mock_update_public_endpoints(
        protect_client,
        get_nvr_public=AsyncMock(return_value=_nvr(protect_client, True)),
        get_cameras_public=AsyncMock(side_effect=ValueError("boom")),
    )

    with pytest.raises(ValueError):
        await protect_client.update_public()
    await _settle()

    websocket.start.assert_not_called()
    assert protect_client._external_arm_ws_enabled is False


@pytest.mark.asyncio()
@pytest.mark.parametrize("flag", [False, None])
async def test_no_socket_without_external_alarm_manager(
    protect_client: ProtectApiClient, flag: bool | None
) -> None:
    """A console without the external alarm manager sees no attempt."""
    await _prime(protect_client, flag)
    await _settle()

    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    websocket.start.assert_not_called()


@pytest.mark.asyncio()
async def test_no_socket_without_store_subscriber(
    protect_client: ProtectApiClient,
) -> None:
    """Without a store subscriber the socket is not started."""
    websocket = _mock_external_arm_websocket(protect_client)
    await _update(protect_client)
    await _settle()

    websocket.start.assert_not_called()


def test_no_decision_without_running_loop() -> None:
    """A request outside an event loop does nothing."""
    client = ProtectApiClient.public_only("127.0.0.1", 443, api_key="key")
    unsub = client.subscribe_public_store_changes(lambda _: None)
    unsub()
    client.set_api_key("other")

    assert client._external_arm_ws_decision is None
    assert client._external_arm_websocket is None


@pytest.mark.asyncio()
async def test_start_after_update_public_with_subscriber(
    protect_client: ProtectApiClient,
) -> None:
    """A subscriber present before ``update_public`` gets the socket started."""
    websocket = _mock_external_arm_websocket(protect_client)
    protect_client.subscribe_public_store_changes(lambda _: None)
    await _settle()
    websocket.start.assert_not_called()

    await _update(protect_client)
    await _settle()

    websocket.start.assert_called_once()


@pytest.mark.asyncio()
@pytest.mark.parametrize("interval", [900.0, None])
async def test_start_after_subscribe(
    protect_client: ProtectApiClient, interval: float | None
) -> None:
    """Subscribing after ``update_public`` starts it, with or without the timer."""
    protect_client._public_refresh_interval = interval
    await _prime(protect_client, True)
    await _settle()

    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    websocket.start.assert_called_once()
    websocket.stop.assert_not_called()
    assert (protect_client._public_refresh_timer is None) is (interval is None)


@pytest.mark.asyncio()
async def test_last_unsubscribe_stops(protect_client: ProtectApiClient) -> None:
    """The socket stops when the last store subscriber leaves."""
    websocket = _mock_external_arm_websocket(protect_client)
    await _update(protect_client)
    first = protect_client.subscribe_public_store_changes(lambda _: None)
    second = protect_client.subscribe_public_store_changes(lambda _: None)
    await _settle()
    websocket.start.assert_called_once()

    first()
    await _settle()
    websocket.stop.assert_not_called()

    second()
    await _settle()
    websocket.stop.assert_called_once()


@pytest.mark.asyncio()
@pytest.mark.parametrize("overlap", [False, True], ids=["plain", "close-overlap"])
async def test_flag_turning_false_stops(
    protect_client: ProtectApiClient, overlap: bool
) -> None:
    """A later ``update_public`` reporting no external alarm manager stops it."""
    await _prime(protect_client, True)
    await _settle()
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    release = asyncio.Event()

    async def _nvr_later() -> Any:
        await release.wait()
        return _nvr(protect_client, False)

    _mock_update_public_endpoints(
        protect_client, get_nvr_public=AsyncMock(side_effect=_nvr_later)
    )
    update = asyncio.create_task(protect_client.update_public())
    await _settle()
    if overlap:
        await protect_client.close_public_api_session()
    release.set()
    await update
    await _settle()

    websocket.stop.assert_called_once()


@pytest.mark.asyncio()
async def test_raising_update_public_leaves_socket_running(
    protect_client: ProtectApiClient,
) -> None:
    """A later ``update_public`` that raises neither stops nor restarts it."""
    await _prime(protect_client, True)
    await _settle()
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    protect_client.get_cameras_public = AsyncMock(side_effect=ValueError("boom"))  # type: ignore[method-assign]

    with pytest.raises(ValueError):
        await protect_client.update_public()
    await _settle()

    websocket.start.assert_called_once()
    websocket.stop.assert_not_called()


@pytest.mark.parametrize(
    ("port", "expected"),
    [
        (
            443,
            (
                "https://127.0.0.1/proxy/protect/integration/v1/subscribe/updates"
                "?modelKeys=externalArmProfile"
            ),
        ),
        (
            7443,
            (
                "https://127.0.0.1:7443/proxy/protect/integration/v1/subscribe/updates"
                "?modelKeys=externalArmProfile"
            ),
        ),
    ],
)
def test_url_carries_model_key(port: int, expected: str) -> None:
    """The socket subscribes to ``externalArmProfile`` only."""
    client = ProtectApiClient.public_only(
        "127.0.0.1", port, api_key="key", ws_receive_timeout=5
    )

    websocket = client._get_external_arm_websocket()

    assert str(websocket.get_url()) == expected
    assert websocket.receive_timeout is None
    assert client._get_external_arm_websocket() is websocket


@pytest.mark.asyncio()
async def test_requests_are_deferred_and_coalesced(
    protect_client: ProtectApiClient,
) -> None:
    """Subscribe and unsubscribe decide later, once per loop turn."""
    websocket = _mock_external_arm_websocket(protect_client)
    await _update(protect_client)
    await _settle()
    websocket.reset_mock()

    first = protect_client.subscribe_public_store_changes(lambda _: None)
    protect_client.subscribe_public_store_changes(lambda _: None)
    first()
    websocket.start.assert_not_called()
    websocket.stop.assert_not_called()

    await _settle()
    websocket.start.assert_called_once()
    websocket.stop.assert_not_called()


async def _push_with_callback(
    client: ProtectApiClient,
    on_change: Callable[[Callable[[], None]], None],
) -> Websocket:
    """Prime with a real socket that pushes one frame to ``on_change``."""
    _real_session(client, _FrameWebsocket(_frame("update", title="pushed")))
    _refetch_mock(client)
    _mock_update_public_endpoints(
        client,
        get_nvr_public=AsyncMock(return_value=_nvr(client, True)),
        _fetch_external_arm_profiles=AsyncMock(return_value=[_profile(client)]),
    )
    await client.update_public()
    calls = 0
    unsub: Callable[[], None]

    def _callback(change: PublicStoreChange) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            on_change(unsub)

    unsub = client.subscribe_public_store_changes(_callback)
    await _settle()
    websocket = client._external_arm_websocket
    assert websocket is not None
    await _wait_until(lambda: calls > 0)
    return websocket


@pytest.mark.asyncio()
async def test_unsubscribe_in_pushed_frame_stops_after_frame(
    protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Unsubscribing the last subscriber from a frame stops the socket afterwards."""
    running_in_callback: list[bool] = []

    def _on_change(unsub: Callable[[], None]) -> None:
        unsub()
        websocket = protect_client._external_arm_websocket
        assert websocket is not None
        running_in_callback.append(websocket._running)

    with caplog.at_level(logging.ERROR):
        websocket = await _push_with_callback(protect_client, _on_change)
        await _wait_until(lambda: not websocket._running)
        await websocket.wait_closed()

    assert running_in_callback == [True]
    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored.title == "pushed"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.asyncio()
async def test_resubscribe_in_pushed_frame_keeps_running(
    protect_client: ProtectApiClient,
) -> None:
    """Unsubscribing and subscribing again in one frame leaves it running."""

    def _on_change(unsub: Callable[[], None]) -> None:
        unsub()
        protect_client.subscribe_public_store_changes(lambda _: None)

    websocket = await _push_with_callback(protect_client, _on_change)
    await _settle()

    assert websocket._running is True
    assert websocket.state is WebsocketState.CONNECTED
    await protect_client.async_disconnect_ws()
    assert websocket._running is False


def _assert_torn_down(client: ProtectApiClient) -> None:
    assert client._external_arm_websocket is None
    assert client._external_arm_refetch_tasks == set()
    assert client._external_arm_ws_decision is None
    assert client._external_arm_ws_enabled is False


@pytest.mark.asyncio()
async def test_disconnect_with_update_public_in_flight(
    protect_client: ProtectApiClient,
) -> None:
    """An ``update_public`` overlapping the teardown does not bring it back."""
    await _prime(protect_client, True)
    await _settle()
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    release = asyncio.Event()

    async def _nvr_later() -> Any:
        await release.wait()
        return _nvr(protect_client, True)

    protect_client.get_nvr_public = AsyncMock(side_effect=_nvr_later)  # type: ignore[method-assign]
    update = asyncio.create_task(protect_client.update_public())
    await _settle()
    disconnect = asyncio.create_task(protect_client.async_disconnect_ws())
    await _settle()
    release.set()
    await update
    await disconnect
    await _settle()

    websocket.stop.assert_called_once()
    websocket.wait_closed.assert_awaited_once()
    _assert_torn_down(protect_client)


class _ReleasingWebsocket(_QuietWebsocket):
    """WS whose close sets ``release`` and then takes several loop turns."""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def close(self) -> None:
        self.release.set()
        await asyncio.sleep(0.05)
        await super().close()


def _websocket_loop_tasks() -> list[asyncio.Task[Any]]:
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_coro().__qualname__ == "Websocket._websocket_loop"  # type: ignore[union-attr]
    ]


@pytest.mark.asyncio()
async def test_disconnect_detaches_after_refresh_cancel(
    protect_client: ProtectApiClient,
) -> None:
    """An ``update_public`` released while the socket closes leaves nothing running."""
    connection = _ReleasingWebsocket()
    _real_websocket(protect_client, connection)
    _refetch_mock(protect_client)
    await _prime(protect_client, True, mock_websocket=False)
    websocket = protect_client._external_arm_websocket
    assert websocket is not None
    await _wait_until(lambda: websocket.state is WebsocketState.CONNECTED)

    async def _nvr_later() -> Any:
        await connection.release.wait()
        return _nvr(protect_client, True)

    protect_client.get_nvr_public = AsyncMock(side_effect=_nvr_later)  # type: ignore[method-assign]
    update = asyncio.create_task(protect_client.update_public())
    await _settle()

    await protect_client.async_disconnect_ws()
    await update
    await _settle()

    assert websocket._running is False
    assert _websocket_loop_tasks() == []
    _assert_torn_down(protect_client)


@pytest.mark.asyncio()
async def test_disconnect_with_refetch_in_flight(
    protect_client: ProtectApiClient,
) -> None:
    """A refetch in flight is cancelled by the teardown."""
    await _prime(protect_client, True)
    await _settle()
    started = asyncio.Event()

    async def _blocked(_: str) -> None:
        started.set()
        await asyncio.Event().wait()

    _refetch_mock(protect_client, side_effect=_blocked)
    protect_client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
    (task,) = protect_client._external_arm_refetch_tasks
    await started.wait()

    await protect_client.async_disconnect_ws()

    assert task.cancelled()
    _assert_torn_down(protect_client)


@pytest.mark.asyncio()
async def test_disconnect_with_decision_pending(
    protect_client: ProtectApiClient,
) -> None:
    """A pending decision is cancelled and the client stays off afterwards."""
    await _prime(protect_client, True)
    await _settle()
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    keep = protect_client.subscribe_public_store_changes(lambda _: None)
    assert protect_client._external_arm_ws_decision is not None

    await protect_client.async_disconnect_ws()
    assert protect_client._external_arm_ws_decision is None
    await _settle()

    websocket.start.assert_called_once()
    _assert_torn_down(protect_client)

    after = _mock_external_arm_websocket(protect_client)
    keep()
    protect_client.subscribe_public_store_changes(lambda _: None)
    protect_client.set_api_key("new-key")
    await _settle()
    after.start.assert_not_called()

    await _update(protect_client)
    await _settle()
    after.start.assert_called_once()


@pytest.mark.asyncio()
@pytest.mark.parametrize("method", ["close_session", "close_public_api_session"])
async def test_close_keeps_socket_and_cancels_refetch(
    protect_client: ProtectApiClient, method: str
) -> None:
    """Closing the sessions leaves the socket and cancels a refetch."""
    await _prime(protect_client, True)
    await _settle()
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)

    async def _blocked(_: str) -> None:
        await asyncio.Event().wait()

    _refetch_mock(protect_client, side_effect=_blocked)
    protect_client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
    (task,) = protect_client._external_arm_refetch_tasks
    await _settle()

    await getattr(protect_client, method)()

    assert task.cancelled()
    assert protect_client._external_arm_refetch_tasks == set()
    assert protect_client._external_arm_websocket is websocket
    websocket.stop.assert_not_called()


class _GatedClosingWebsocket(_QuietWebsocket):
    """WS that blocks on receive until released, then delivers a CLOSE frame."""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def receive(self, timeout: float | None) -> Any:
        await self.release.wait()
        self.is_closed = True
        return aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, 1000, None)


@pytest.mark.asyncio()
async def test_state_changes_stay_internal(protect_client: ProtectApiClient) -> None:
    """Its state reaches no public state channel and starts no resync."""
    seen: list[WebsocketState] = []
    protect_client.subscribe_devices_websocket_state(seen.append)
    protect_client.subscribe_events_websocket_state(seen.append)
    resyncs: list[bool] = []
    protect_client.subscribe_public_resync(resyncs.append)
    first = _GatedClosingWebsocket()
    session = _real_session(protect_client, first)
    session.ws_connect = AsyncMock(
        side_effect=[first, _handshake_401(), _handshake_401()]
    )
    protect_client._get_external_arm_websocket().backoff = 0
    refresh = _refetch_mock(protect_client)
    await _prime(protect_client, True, mock_websocket=False)
    websocket = protect_client._external_arm_websocket
    assert websocket is not None
    await _wait_until(lambda: websocket.state is WebsocketState.CONNECTED)
    await _wait_until(lambda: refresh.await_count == 1)
    assert protect_client.is_public_live is False

    first.release.set()
    await _wait_until(lambda: websocket.state is WebsocketState.AUTH_FAILED)
    assert protect_client.is_public_live is False

    await protect_client.async_disconnect_ws()

    assert session.ws_connect.await_count == 3
    refresh.assert_awaited_once_with(STORE)
    assert seen == []
    assert resyncs == []
    assert protect_client.is_public_live is False
    assert protect_client._public_resync_task is None


@pytest.mark.asyncio()
async def test_refetch_on_connect_and_reconnect(
    protect_client: ProtectApiClient,
) -> None:
    """Every ``CONNECTED`` refetches the store, the first one included."""
    session = _real_websocket(
        protect_client, _CodeClosingWebsocket(data=1000), _QuietWebsocket()
    )
    refresh = _refetch_mock(protect_client)
    await _prime(protect_client, True, mock_websocket=False)
    await _wait_until(lambda: refresh.await_count == 2)

    await protect_client.async_disconnect_ws()

    assert session.ws_connect.await_count == 2
    assert protect_client._external_arm_ws_rejected is False


@pytest.mark.asyncio()
async def test_failing_refetch_logs_at_debug(
    protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed refetch is logged at debug level and raises nothing."""
    await _prime(protect_client, True)
    _refetch_mock(protect_client, side_effect=NvrError("down"))

    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        protect_client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
        (task,) = protect_client._external_arm_refetch_tasks
        await task

    (record,) = [r for r in caplog.records if "refetch failed" in r.message]
    assert record.levelno == logging.DEBUG
    assert protect_client._external_arm_refetch_tasks == set()


@pytest.mark.asyncio()
async def test_no_refetch_while_closing(protect_client: ProtectApiClient) -> None:
    """No refetch starts during a refresh teardown or before ``update_public``."""
    refresh = _refetch_mock(protect_client)
    protect_client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
    await _prime(protect_client, True)
    protect_client._public_refresh_closing = 1
    protect_client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
    protect_client._public_refresh_closing = 0

    assert protect_client._external_arm_refetch_tasks == set()
    refresh.assert_not_called()


_ACTIONS = [
    ("arm_external_arm_profile_public", "armed"),
    ("disarm_external_arm_profile_public", "disarmed"),
    ("create_external_arm_profile_public", "disarmed"),
    ("update_external_arm_profile_public", "armed"),
]


async def _call(client: ProtectApiClient, method: str) -> Any:
    if method == "create_external_arm_profile_public":
        return await client.create_external_arm_profile_public(title="new")
    if method == "update_external_arm_profile_public":
        return await client.update_external_arm_profile_public(PROFILE_ID, title="new")
    return await getattr(client, method)(PROFILE_ID)


async def _action(
    client: ProtectApiClient,
    method: str,
    state: str,
    *,
    connected: bool = True,
    frame: Any = None,
) -> tuple[Any, AsyncMock]:
    await _prime(client, True)
    websocket = client._external_arm_websocket
    assert isinstance(websocket, Mock)
    if connected:
        websocket.state = WebsocketState.CONNECTED
    refresh = _refetch_mock(client)

    async def _respond(**_: Any) -> dict[str, Any]:
        if frame is not None:
            client._process_external_arm_ws_message(frame)
        return _raw(state=state, title="response")

    client.api_request_obj = AsyncMock(side_effect=_respond)  # type: ignore[method-assign]
    profile = await _call(client, method)
    await _settle()
    assert profile.state == state
    assert profile.title == "response"
    return profile, refresh


@pytest.mark.asyncio()
@pytest.mark.parametrize(("method", "state"), _ACTIONS)
async def test_action_while_connected_without_write_is_written(
    protect_client: ProtectApiClient, method: str, state: str
) -> None:
    """With no store write during the request the response is written."""
    profile, refresh = await _action(protect_client, method, state)

    assert protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID] is profile
    refresh.assert_not_called()


@pytest.mark.asyncio()
@pytest.mark.parametrize(("method", "state"), _ACTIONS)
@pytest.mark.parametrize(
    "frame",
    [
        _frame("update", title="pushed"),
        _frame("add", OTHER_ID, **{**_raw(), "id": OTHER_ID}),
    ],
    ids=["same-profile", "other-profile"],
)
async def test_action_while_connected_after_push_refetches(
    protect_client: ProtectApiClient, method: str, state: str, frame: Any
) -> None:
    """A frame during the request leaves the write to a refetch."""
    profile, refresh = await _action(protect_client, method, state, frame=frame)

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored is not profile
    assert stored.title != "response"
    refresh.assert_awaited_once_with(STORE)


@pytest.mark.asyncio()
@pytest.mark.parametrize(("method", "state"), _ACTIONS)
async def test_action_while_closing_is_written(
    protect_client: ProtectApiClient, method: str, state: str
) -> None:
    """Without a possible refetch the response is written."""
    await _prime(protect_client, True)
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    websocket.state = WebsocketState.CONNECTED
    refresh = _refetch_mock(protect_client)

    async def _respond(**_: Any) -> dict[str, Any]:
        protect_client._process_external_arm_ws_message(_frame("update", title="p"))
        protect_client._public_refresh_closing = 1
        return _raw(state=state)

    protect_client.api_request_obj = AsyncMock(side_effect=_respond)  # type: ignore[method-assign]
    profile = await _call(protect_client, method)
    protect_client._public_refresh_closing = 0

    assert protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID] is profile
    refresh.assert_not_called()


@pytest.mark.asyncio()
@pytest.mark.parametrize(("method", "state"), _ACTIONS)
@pytest.mark.parametrize("frame", [None, _frame("update", title="pushed")])
async def test_action_while_not_connected_is_written(
    protect_client: ProtectApiClient, method: str, state: str, frame: Any
) -> None:
    """While not connected the response is written as before."""
    profile, refresh = await _action(
        protect_client, method, state, connected=False, frame=frame
    )

    assert protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID] is profile
    refresh.assert_not_called()


@pytest.mark.asyncio()
@pytest.mark.parametrize("connected", [True, False])
async def test_create_with_add_push_for_new_id(
    protect_client: ProtectApiClient, connected: bool
) -> None:
    """An ``add`` push for the created id defers to a refetch only while connected."""
    await _prime(protect_client, True)
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    if connected:
        websocket.state = WebsocketState.CONNECTED
    refresh = _refetch_mock(protect_client)

    async def _respond(**_: Any) -> dict[str, Any]:
        protect_client._process_external_arm_ws_message(
            _frame("add", NEW_ID, **{**_raw(title="pushed"), "id": NEW_ID})
        )
        return {**_raw(title="response"), "id": NEW_ID}

    protect_client.api_request_obj = AsyncMock(side_effect=_respond)  # type: ignore[method-assign]
    profile = await protect_client.create_external_arm_profile_public(title="new")
    await _settle()

    assert profile.id == NEW_ID
    stored = protect_client.public_bootstrap.external_arm_profiles[NEW_ID]
    if connected:
        assert stored is not profile
        assert stored.title == "pushed"
        refresh.assert_awaited_once_with(STORE)
    else:
        assert stored is profile
        refresh.assert_not_called()


@pytest.mark.asyncio()
@pytest.mark.parametrize("pushed", [False, True])
async def test_single_getter_unchanged_while_connected(
    protect_client: ProtectApiClient, pushed: bool
) -> None:
    """The single getter keeps its own write check and never refetches."""
    await _prime(protect_client, True)
    websocket = protect_client._external_arm_websocket
    assert isinstance(websocket, Mock)
    websocket.state = WebsocketState.CONNECTED
    refresh = _refetch_mock(protect_client)

    async def _respond(**_: Any) -> dict[str, Any]:
        if pushed:
            protect_client._process_external_arm_ws_message(_frame("update", title="p"))
        return _raw(state="armed")

    protect_client.api_request_obj = AsyncMock(side_effect=_respond)  # type: ignore[method-assign]
    profile = await protect_client.get_external_arm_profile_public(PROFILE_ID)
    await _settle()

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert (stored is profile) is not pushed
    refresh.assert_not_called()


@pytest.mark.parametrize(
    ("code", "reconnect"),
    [(4404, False), (4422, False), (4500, False), (1000, True), (None, True)],
)
def test_close_callback(code: int | None, reconnect: bool) -> None:
    """Only the rejection codes decline the reconnect."""
    client = ProtectApiClient.public_only("127.0.0.1", 443, api_key="key")

    assert client._on_external_arm_websocket_close(code) is reconnect
    assert client._external_arm_ws_rejected is not reconnect


@pytest.mark.asyncio()
async def test_rejected_socket_stops_and_retries_on_update_public(
    protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A rejection stops the socket; the first warns, a later one logs at debug."""
    session = _real_websocket(
        protect_client,
        _CodeClosingWebsocket(data=4404),
        _CodeClosingWebsocket(data=4500),
    )
    refresh = _refetch_mock(protect_client)
    websocket = protect_client._external_arm_websocket
    assert websocket is not None

    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        await _prime(protect_client, True, mock_websocket=False)
        await _wait_until(lambda: protect_client._external_arm_ws_rejected)
        await _wait_until(lambda: not websocket._running)

        unsub = protect_client.subscribe_public_store_changes(lambda _: None)
        unsub()
        await _settle()
        assert session.ws_connect.await_count == 1

        await protect_client.update_public()
        await _wait_until(lambda: session.ws_connect.await_count == 2)
        await _wait_until(lambda: not websocket._running)

    rejections = [r for r in caplog.records if "rejected" in r.message]
    assert [r.levelno for r in rejections] == [logging.WARNING, logging.DEBUG]
    assert protect_client._external_arm_ws_rejected is True
    assert protect_client._external_arm_websocket is websocket
    assert refresh.await_count == 2
    await protect_client.async_disconnect_ws()


async def _rejected(client: ProtectApiClient) -> Mock:
    await _prime(client, True)
    await _settle()
    websocket = client._external_arm_websocket
    assert isinstance(websocket, Mock)
    assert client._on_external_arm_websocket_close(4404) is False
    websocket.reset_mock()
    return websocket


@pytest.mark.asyncio()
async def test_retry_after_set_api_key(protect_client: ProtectApiClient) -> None:
    """``set_api_key`` clears the rejection, retries and resets the auth backoff."""
    websocket = await _rejected(protect_client)

    protect_client.set_api_key("new-key")
    await _settle()

    websocket.reset_auth_failure.assert_called_once()
    websocket.start.assert_called_once()
    assert protect_client._external_arm_ws_rejected is False


@pytest.mark.asyncio()
@pytest.mark.parametrize("busy", [False, True], ids=["fetches", "skips"])
async def test_retry_on_external_arm_refresh_turn(
    protect_client: ProtectApiClient, busy: bool
) -> None:
    """The refresh turn of ``external_arm_profiles`` retries, also when skipped."""
    websocket = await _rejected(protect_client)
    protect_client._public_refresh_next = 3
    blocker = asyncio.create_task(asyncio.Event().wait())
    if busy:
        protect_client._public_refresh_tasks[STORE] = blocker

    await _tick(protect_client)
    await _settle()

    websocket.start.assert_called_once()
    assert protect_client._external_arm_ws_rejected is False
    blocker.cancel()


@pytest.mark.asyncio()
async def test_no_retry_on_other_refresh_turn(
    protect_client: ProtectApiClient,
) -> None:
    """The turn of another store leaves a rejection in place."""
    websocket = await _rejected(protect_client)
    protect_client._public_refresh_next = 0

    await _tick(protect_client)
    await _settle()

    websocket.start.assert_not_called()
    assert protect_client._external_arm_ws_rejected is True


@pytest.mark.asyncio()
async def test_auth_failed_is_quiet(
    protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """``AUTH_FAILED`` logs no warning and starts no refetch."""
    await _prime(protect_client, True)
    refresh = _refetch_mock(protect_client)

    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        protect_client._on_external_arm_websocket_state_change(
            WebsocketState.AUTH_FAILED
        )

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert protect_client._external_arm_refetch_tasks == set()
    refresh.assert_not_called()
