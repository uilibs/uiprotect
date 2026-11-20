"""Tests for the liveness signal of the external arm profile store."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import aiohttp
import orjson
import pytest

from uiprotect.data import ExternalArmProfileState
from uiprotect.exceptions import NvrError
from uiprotect.websocket import WebsocketState

from .test_api_public import _mock_update_public_endpoints
from .test_api_ws import (
    _CodeClosingWebsocket,
    _handshake_401,
    _QuietWebsocket,
    _wait_until,
)
from .test_external_arm_websocket import (
    _frame,
    _real_websocket,
    _settle,
    _update,
)
from .test_public_external_arm_profiles_store import (
    PROFILE_ID,
    STORE,
    _nvr,
    _prime,
    _profile,
    _raw,
    no_ws_connect,  # noqa: F401
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from uiprotect import ProtectApiClient
    from uiprotect.data import PublicStoreChange

_ZERO = (0.0, 0.0, 0.0)
_SHORT = (0.01, 0.01, 0.01)


class _GatedCodeWebsocket(_QuietWebsocket):
    """WS that blocks on receive until released, then closes with ``code``."""

    def __init__(self, code: int = 1000) -> None:
        self.code = code
        self.release = asyncio.Event()

    async def receive(self, timeout: float | None) -> Any:
        await self.release.wait()
        self.is_closed = True
        return aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, self.code, None)


def _record(client: ProtectApiClient) -> list[tuple[bool, bool]]:
    """Subscribe to the live value, recording the argument and the property."""
    calls: list[tuple[bool, bool]] = []
    client.subscribe_external_arm_profiles_live(
        lambda live: calls.append((live, client.is_external_arm_profiles_live))
    )
    return calls


def _fetch(client: ProtectApiClient, *results: Any) -> AsyncMock:
    """Replace the list fetch; each result is a list, an exception or a callable."""
    queue = list(results)

    async def _next() -> Any:
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(result):
            result = await result()
        if isinstance(result, BaseException):
            raise result
        return result

    fetch = AsyncMock(side_effect=_next)
    client._fetch_external_arm_profiles = fetch  # type: ignore[method-assign]
    return fetch


def _gate(result: Any) -> tuple[asyncio.Event, Callable[[], Any]]:
    release = asyncio.Event()

    async def _wait() -> Any:
        await release.wait()
        return result

    return release, _wait


async def _connected(
    client: ProtectApiClient, *fetches: Any
) -> tuple[Mock, AsyncMock, list[tuple[bool, bool]]]:
    """Prime with a mocked socket and report a ``CONNECTED`` to the handler."""
    await _prime(client, True)
    websocket = client._external_arm_websocket
    assert isinstance(websocket, Mock)
    calls = _record(client)
    fetch = _fetch(client, *(fetches or ([_profile(client)],)))
    websocket.state = WebsocketState.CONNECTED
    client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
    return websocket, fetch, calls


async def _refetched(client: ProtectApiClient) -> None:
    await asyncio.gather(*client._external_arm_refetch_tasks)
    await _settle()


def _drop(client: ProtectApiClient, websocket: Mock) -> None:
    websocket.state = WebsocketState.DISCONNECTED
    client._on_external_arm_websocket_state_change(WebsocketState.DISCONNECTED)


@pytest.mark.asyncio()
async def test_false_before_update_public(protect_client: ProtectApiClient) -> None:
    """Nothing is live before ``update_public``."""
    assert protect_client.is_external_arm_profiles_live is False


@pytest.mark.asyncio()
@pytest.mark.parametrize("flag", [True, False], ids=["no-subscriber", "local"])
async def test_false_without_socket(
    protect_client: ProtectApiClient, flag: bool
) -> None:
    """Without the external alarm manager or a store subscriber nothing goes live."""
    session = _real_websocket(protect_client, _QuietWebsocket())
    calls = _record(protect_client)
    await _update(protect_client, flag)
    if not flag:
        protect_client.subscribe_public_store_changes(lambda _: None)
    await _settle()

    session.ws_connect.assert_not_called()
    assert calls == []
    assert protect_client.is_external_arm_profiles_live is False


@pytest.mark.asyncio()
async def test_first_connect(protect_client: ProtectApiClient) -> None:
    """``False`` until the refetch applied a list; its store change comes first."""
    _real_websocket(protect_client, _QuietWebsocket())
    calls = _record(protect_client)
    order: list[Any] = []
    protect_client.subscribe_external_arm_profiles_live(
        lambda live: order.append(("live", live))
    )
    await _update(protect_client)
    protect_client.subscribe_public_store_changes(
        lambda _: order.append(("store", protect_client.is_external_arm_profiles_live))
    )
    release, wait = _gate([_profile(protect_client, title="refetched")])
    fetch = _fetch(protect_client, wait)
    websocket = protect_client._external_arm_websocket
    assert websocket is not None
    await _wait_until(lambda: fetch.await_count == 1)

    assert websocket.state is WebsocketState.CONNECTED
    assert protect_client.is_external_arm_profiles_live is False
    release.set()
    await _wait_until(lambda: bool(calls))

    assert order == [("store", False), ("live", True)]
    assert calls == [(True, True)]
    assert protect_client.is_external_arm_profiles_live is True
    await protect_client.async_disconnect_ws()
    assert calls == [(True, True), (False, False)]


@pytest.mark.asyncio()
async def test_same_list_reports_true(protect_client: ProtectApiClient) -> None:
    """A refetch returning the stored list still turns the value ``True``."""
    _real_websocket(protect_client, _QuietWebsocket())
    calls = _record(protect_client)
    await _prime(protect_client, True, mock_websocket=False)
    await _wait_until(lambda: bool(calls))

    assert calls == [(True, True)]
    await protect_client.async_disconnect_ws()


@pytest.mark.asyncio()
async def test_drop_before_report(protect_client: ProtectApiClient) -> None:
    """A drop between the write and the report leaves it never ``True``."""
    _real_websocket(protect_client, _QuietWebsocket())
    calls = _record(protect_client)
    seen: list[bool] = []
    await _update(protect_client)

    def _on_change(_: PublicStoreChange) -> None:
        seen.append(protect_client.is_external_arm_profiles_live)
        websocket = protect_client._external_arm_websocket
        assert websocket is not None
        websocket.stop()

    protect_client.subscribe_public_store_changes(_on_change)
    fetch = _fetch(protect_client, [_profile(protect_client, title="refetched")])
    await _wait_until(lambda: fetch.await_count == 1)
    await _wait_until(lambda: bool(seen))
    await _settle()

    assert seen == [False]
    assert calls == []
    assert protect_client.is_external_arm_profiles_live is False
    await protect_client.async_disconnect_ws()


@pytest.mark.asyncio()
async def test_reconnect(protect_client: ProtectApiClient) -> None:
    """A reconnect reports ``False`` at the drop and ``True`` after its refetch."""
    first = _GatedCodeWebsocket()
    _real_websocket(protect_client, first, _QuietWebsocket())
    calls = _record(protect_client)
    states: list[Any] = []
    await _update(protect_client)
    protect_client.subscribe_public_store_changes(
        lambda _: states.append(
            protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID].state
        )
    )
    await _wait_until(lambda: bool(calls))
    release, wait = _gate([_profile(protect_client, state="breached")])
    fetch = _fetch(protect_client, wait)

    first.release.set()
    await _wait_until(lambda: len(calls) == 2)
    await _wait_until(lambda: fetch.await_count == 1)
    assert calls == [(True, True), (False, False)]
    release.set()
    await _wait_until(lambda: len(calls) == 3)

    assert calls[2] == (True, True)
    assert states == [ExternalArmProfileState.BREACHED]
    await protect_client.async_disconnect_ws()


@pytest.mark.asyncio()
@pytest.mark.parametrize("path", ["update_public", "periodic", "list_getter"])
async def test_list_in_flight_across_connect_is_dropped(
    protect_client: ProtectApiClient, path: str
) -> None:
    """A list fetched across a ``CONNECTED`` is not applied."""
    websocket, _, calls = await _connected(protect_client)
    await _refetched(protect_client)
    assert calls == [(True, True)]
    stale_release, stale = _gate([_profile(protect_client, title="stale")])
    fresh_release, fresh = _gate([_profile(protect_client, title="fresh")])
    _fetch(protect_client, stale, fresh)
    if path == "update_public":
        task = asyncio.create_task(protect_client.update_public())
    elif path == "periodic":
        timer = protect_client._public_refresh_timer
        assert timer is not None
        timer.cancel()
        protect_client._public_refresh_next = 3
        protect_client._run_public_refresh_tick()
        task = protect_client._public_refresh_tasks[STORE]
    else:
        task = asyncio.create_task(protect_client.get_external_arm_profiles_public())
    await _settle()

    _drop(protect_client, websocket)
    websocket.state = WebsocketState.CONNECTED
    protect_client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
    stale_release.set()
    await task
    await _settle()

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored.title == "test"
    assert protect_client.is_external_arm_profiles_live is False
    fresh_release.set()
    await _refetched(protect_client)

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored.title == "fresh"
    assert calls == [(True, True), (False, False), (True, True)]


@pytest.mark.asyncio()
@pytest.mark.parametrize("method", ["single_getter", "arm"])
async def test_response_across_connect_is_not_written(
    protect_client: ProtectApiClient, method: str
) -> None:
    """The single getter and arm write no response that spans a ``CONNECTED``."""
    websocket, _, calls = await _connected(protect_client)
    await _refetched(protect_client)
    release, fresh = _gate([_profile(protect_client, title="fresh")])
    _fetch(protect_client, fresh)

    async def _respond(**_: Any) -> dict[str, Any]:
        _drop(protect_client, websocket)
        websocket.state = WebsocketState.CONNECTED
        protect_client._on_external_arm_websocket_state_change(WebsocketState.CONNECTED)
        return _raw(state="armed", title="response")

    protect_client.api_request_obj = AsyncMock(side_effect=_respond)  # type: ignore[method-assign]
    if method == "arm":
        await protect_client.arm_external_arm_profile_public(PROFILE_ID)
    else:
        await protect_client.get_external_arm_profile_public(PROFILE_ID)
    await _settle()

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored.title == "test"
    release.set()
    await _refetched(protect_client)

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored.title == "fresh"
    assert calls == [(True, True), (False, False), (True, True)]


@pytest.mark.asyncio()
async def test_refetch_retried_after_failure(
    protect_client: ProtectApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed refetch is retried and then turns the value ``True``."""
    monkeypatch.setattr("uiprotect.api.PUBLIC_RESYNC_RETRY_DELAYS", _ZERO)
    _, fetch, calls = await _connected(
        protect_client, NvrError("down"), [_profile(protect_client)]
    )
    await _refetched(protect_client)

    assert fetch.await_count == 2
    assert calls == [(True, True)]


@pytest.mark.asyncio()
@pytest.mark.parametrize("recovery", ["periodic", "update_public"])
async def test_refetch_gives_up(
    protect_client: ProtectApiClient,
    monkeypatch: pytest.MonkeyPatch,
    recovery: str,
) -> None:
    """Retries end with the delays; the next applied list turns it ``True``."""
    monkeypatch.setattr("uiprotect.api.PUBLIC_RESYNC_RETRY_DELAYS", _ZERO)
    websocket, fetch, calls = await _connected(protect_client, NvrError("down"))
    await _refetched(protect_client)

    assert fetch.await_count == 4
    assert calls == []
    assert websocket.state is WebsocketState.CONNECTED
    assert protect_client.is_external_arm_profiles_live is False

    _fetch(protect_client, [_profile(protect_client)])
    if recovery == "periodic":
        timer = protect_client._public_refresh_timer
        assert timer is not None
        timer.cancel()
        protect_client._public_refresh_next = 3
        protect_client._run_public_refresh_tick()
        await protect_client._public_refresh_tasks[STORE]
    else:
        await protect_client.update_public()
    await _settle()

    assert calls == [(True, True)]


@pytest.mark.asyncio()
async def test_dropped_refresh_is_retried(
    protect_client: ProtectApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh whose fetches are both dropped reports nothing until the retry."""
    monkeypatch.setattr("uiprotect.api.PUBLIC_RESYNC_RETRY_DELAYS", _ZERO)
    seen: list[list[tuple[bool, bool]]] = []
    calls: list[tuple[bool, bool]] = []

    async def _pushed() -> Any:
        protect_client._process_external_arm_ws_message(_frame("update", title="p"))
        return [_profile(protect_client)]

    async def _retry() -> Any:
        seen.append(list(calls))
        return [_profile(protect_client, title="retry")]

    _, fetch, calls = await _connected(protect_client, _pushed, _pushed, _retry)
    await _refetched(protect_client)

    assert fetch.await_count == 3
    assert seen == [[]]
    assert calls == [(True, True)]


@pytest.mark.asyncio()
@pytest.mark.parametrize("delays", [_ZERO, _SHORT], ids=["zero", "short"])
@pytest.mark.parametrize("cause", ["dropped", "reconnected", "applied"])
async def test_no_retry_when_settled(
    protect_client: ProtectApiClient,
    monkeypatch: pytest.MonkeyPatch,
    delays: tuple[float, ...],
    cause: str,
) -> None:
    """No retry after a drop, a reconnect or a list applied by another path."""
    monkeypatch.setattr("uiprotect.api.PUBLIC_RESYNC_RETRY_DELAYS", delays)
    websocket: Mock | None = None

    async def _fail() -> Any:
        assert websocket is not None
        if cause == "dropped":
            _drop(protect_client, websocket)
        elif cause == "reconnected":
            protect_client._on_external_arm_websocket_state_change(
                WebsocketState.CONNECTED
            )
        else:
            await protect_client.get_external_arm_profiles_public()
        return NvrError("down")

    websocket, fetch, _ = await _connected(
        protect_client, _fail, [_profile(protect_client)]
    )
    while protect_client._external_arm_refetch_tasks:
        await _refetched(protect_client)

    assert fetch.await_count == (1 if cause == "dropped" else 2)
    assert protect_client.is_external_arm_profiles_live is (cause != "dropped")


@pytest.mark.asyncio()
async def test_refetch_ends_after_applied_attempt(
    protect_client: ProtectApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refetch that applied a list ends without waiting for a retry."""
    monkeypatch.setattr("uiprotect.api.PUBLIC_RESYNC_RETRY_DELAYS", (1000.0,))
    _, fetch, calls = await _connected(protect_client)
    (task,) = protect_client._external_arm_refetch_tasks
    await _wait_until(lambda: fetch.await_count == 1)
    await _settle()

    assert task.done()
    assert calls == [(True, True)]


@pytest.mark.asyncio()
async def test_no_retry_after_drop_during_wait(
    protect_client: ProtectApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drop during the wait ends the refetch without another request."""
    monkeypatch.setattr("uiprotect.api.PUBLIC_RESYNC_RETRY_DELAYS", (0.05,) * 3)
    websocket, fetch, calls = await _connected(protect_client, NvrError("down"))
    await _wait_until(lambda: fetch.await_count == 1)

    _drop(protect_client, websocket)
    await _refetched(protect_client)

    assert fetch.await_count == 1
    assert calls == []


@pytest.mark.asyncio()
@pytest.mark.parametrize("live", [True, False], ids=["was-live", "not-live"])
@pytest.mark.parametrize("ending", ["auth_failed", "rejected", "unsubscribe", "stop"])
async def test_false_when_socket_ends(
    protect_client: ProtectApiClient, live: bool, ending: str
) -> None:
    """Leaving ``CONNECTED`` reports ``False`` once, and only after ``True``."""
    first = _GatedCodeWebsocket(4404 if ending == "rejected" else 1000)
    connections: list[Any] = [first]
    if ending == "auth_failed":
        connections += [_handshake_401(), _handshake_401()]
    _real_websocket(protect_client, *connections)
    calls = _record(protect_client)
    await _update(protect_client)
    unsub = protect_client.subscribe_public_store_changes(lambda _: None)
    fetch = _fetch(
        protect_client,
        [_profile(protect_client)] if live else _gate([])[1],
    )
    websocket = protect_client._external_arm_websocket
    assert websocket is not None
    await _wait_until(lambda: fetch.await_count == 1)
    await _settle()
    assert calls == ([(True, True)] if live else [])

    if ending == "auth_failed":
        first.release.set()
        await _wait_until(lambda: websocket.state is WebsocketState.AUTH_FAILED)
    elif ending == "rejected":
        first.release.set()
        await _wait_until(lambda: protect_client._external_arm_ws_rejected)
        await _wait_until(lambda: not websocket._running)
    elif ending == "unsubscribe":
        unsub()
        await _wait_until(lambda: not websocket._running)
    else:
        await protect_client.async_disconnect_ws()

    assert calls == ([(True, True), (False, False)] if live else [])
    assert protect_client.is_external_arm_profiles_live is False
    await protect_client.async_disconnect_ws()


@pytest.mark.asyncio()
@pytest.mark.parametrize("fetched", [True, False], ids=["list", "failed"])
async def test_flag_turning_false_reports_nothing(
    protect_client: ProtectApiClient,
    monkeypatch: pytest.MonkeyPatch,
    fetched: bool,
) -> None:
    """Losing the external alarm manager while not live reports nothing."""
    monkeypatch.setattr("uiprotect.api.PUBLIC_RESYNC_RETRY_DELAYS", _ZERO)
    _, _, calls = await _connected(protect_client, NvrError("down"))
    await _refetched(protect_client)
    _mock_update_public_endpoints(
        protect_client,
        get_nvr_public=AsyncMock(return_value=_nvr(protect_client, False)),
    )
    _fetch(protect_client, [_profile(protect_client)] if fetched else NvrError("x"))

    await protect_client.update_public()
    await _settle()

    assert calls == []
    assert protect_client.is_external_arm_profiles_live is False


@pytest.mark.asyncio()
async def test_flag_turning_false_while_live(protect_client: ProtectApiClient) -> None:
    """Losing the external alarm manager reads ``False`` before the socket stops."""
    _real_websocket(protect_client, _QuietWebsocket())
    calls = _record(protect_client)
    await _update(protect_client)
    seen: list[bool] = []
    protect_client.subscribe_public_store_changes(
        lambda _: seen.append(protect_client.is_external_arm_profiles_live)
    )
    await _wait_until(lambda: bool(calls))
    seen.clear()
    _mock_update_public_endpoints(
        protect_client,
        get_nvr_public=AsyncMock(return_value=_nvr(protect_client, False)),
    )
    _fetch(protect_client, [_profile(protect_client, title="changed")])
    websocket = protect_client._external_arm_websocket
    assert websocket is not None

    await protect_client.update_public()

    assert websocket.state is WebsocketState.CONNECTED
    assert protect_client.is_external_arm_profiles_live is False
    assert True not in seen
    await _wait_until(lambda: len(calls) == 2)
    assert calls == [(True, True), (False, False)]
    await protect_client.async_disconnect_ws()


@pytest.mark.asyncio()
async def test_nvr_frame_turning_flag_false(protect_client: ProtectApiClient) -> None:
    """A devices websocket NVR frame dropping the flag reports ``False`` once."""
    await _connected(protect_client)
    await _refetched(protect_client)
    calls = _record(protect_client)
    assert protect_client.is_external_arm_profiles_live is True
    nvr = protect_client.public_bootstrap.nvr
    assert nvr is not None
    frame = {
        "type": "update",
        "item": {
            "id": nvr.id,
            "modelKey": "nvr",
            "featureFlags": {"useExternalAlarmManager": False},
        },
    }

    for _ in range(2):
        protect_client._process_devices_ws_message(
            aiohttp.WSMessage(
                aiohttp.WSMsgType.TEXT, orjson.dumps(frame).decode(), None
            )
        )

    assert calls == [(False, False)]


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "method", ["close_session", "close_public_api_session", "async_disconnect_ws"]
)
async def test_teardown_cancels_waiting_retry(
    protect_client: ProtectApiClient, method: str
) -> None:
    """A refetch waiting for a retry is cancelled by the teardown."""
    _, fetch, _ = await _connected(protect_client, NvrError("down"))
    (task,) = protect_client._external_arm_refetch_tasks
    await _wait_until(lambda: fetch.await_count == 1)
    await _settle()

    await getattr(protect_client, method)()
    await _settle()

    assert task.cancelled()
    assert fetch.await_count == 1


@pytest.mark.asyncio()
async def test_subscribers(
    protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Subscribers are called on changes only and survive each other."""
    first: list[bool] = []
    last: list[bool] = []
    unsub_first = protect_client.subscribe_external_arm_profiles_live(first.append)
    unsub_self: Callable[[], None]
    once: list[bool] = []

    def _self_unsubscribing(live: bool) -> None:
        once.append(live)
        unsub_self()

    raised: list[bool] = []

    def _raising(live: bool) -> None:
        raised.append(live)
        raise ValueError("boom")

    unsub_self = protect_client.subscribe_external_arm_profiles_live(
        _self_unsubscribing
    )
    protect_client.subscribe_external_arm_profiles_live(_raising)
    protect_client.subscribe_external_arm_profiles_live(last.append)

    with caplog.at_level(logging.ERROR):
        websocket, _, _ = await _connected(protect_client)
        await _refetched(protect_client)
    late: list[bool] = []
    protect_client.subscribe_external_arm_profiles_live(late.append)
    await _settle()
    unsub_first()
    _drop(protect_client, websocket)

    assert first == [True]
    assert once == [True]
    assert raised == [True, False]
    assert last == [True, False]
    assert late == [False]
    assert "external arm live handler" in caplog.text


@pytest.mark.asyncio()
async def test_rejection_close_code_reports_nothing(
    protect_client: ProtectApiClient,
) -> None:
    """A socket rejected right after the handshake never reports."""
    session = _real_websocket(protect_client, _CodeClosingWebsocket(data=4404))
    calls = _record(protect_client)
    await _prime(protect_client, True, mock_websocket=False)
    _fetch(protect_client, _gate([])[1])
    await _wait_until(lambda: protect_client._external_arm_ws_rejected)
    await _settle()

    session.ws_connect.assert_awaited_once()

    assert calls == []
    assert protect_client.is_external_arm_profiles_live is False
    await protect_client.async_disconnect_ws()
