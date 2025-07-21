"""UniFi Protect Websockets."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from enum import Enum
from http import HTTPStatus
from typing import Any

import aiohttp
from aiohttp import (
    ClientError,
    ClientSession,
    ClientWebSocketResponse,
    WSMessage,
    WSMsgType,
    WSServerHandshakeError,
)
from yarl import URL

from .exceptions import NotAuthorized, NvrError

_LOGGER = logging.getLogger(__name__)
AuthCallbackType = Callable[..., Coroutine[Any, Any, dict[str, str] | None]]
GetSessionCallbackType = Callable[[], Awaitable[ClientSession]]
UpdateBootstrapCallbackType = Callable[[], None]
_CLOSE_MESSAGE_TYPES = {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}


class WebsocketState(Enum):
    CONNECTED = True
    DISCONNECTED = False


class Websocket:
    """UniFi Protect Websocket manager."""

    _running = False
    _headers: dict[str, str] | None = None
    _websocket_loop_task: asyncio.Task[None] | None = None
    _stop_task: asyncio.Task[None] | None = None
    _ws_connection: ClientWebSocketResponse | None = None

    def __init__(
        self,
        get_url: Callable[[], URL],
        auth_callback: AuthCallbackType,
        update_bootstrap: UpdateBootstrapCallbackType,
        get_session: GetSessionCallbackType,
        subscription: Callable[[WSMessage], None],
        state_callback: Callable[[WebsocketState], None],
        *,
        timeout: float = 30.0,
        backoff: int = 10,
        verify: bool = True,
        receive_timeout: float | None = None,
    ) -> None:
        """Init Websocket."""
        self.get_url = get_url
        self.timeout = timeout
        self.receive_timeout = receive_timeout
        self.backoff = backoff
        self.verify = verify
        self._get_session = get_session
        self._auth = auth_callback
        self._update_bootstrap = update_bootstrap
        self._subscription = subscription
        self._seen_non_close_message = False
        self._websocket_state = state_callback
        self._current_state: WebsocketState = WebsocketState.DISCONNECTED

    @property
    def is_connected(self) -> bool:
        """Return if the websocket is connected and has received a valid message."""
        return self._ws_connection is not None and not self._ws_connection.closed

    async def _websocket_loop(self) -> None:
        """Running loop for websocket."""
        await self.wait_closed()
        backoff = self.backoff

        while True:
            url = self.get_url()
            try:
                await self._websocket_inner_loop(url)
            except ClientError as ex:
                level = logging.ERROR if self._seen_non_close_message else logging.DEBUG
                if isinstance(ex, WSServerHandshakeError):
                    if ex.status == HTTPStatus.UNAUTHORIZED.value:
                        _LOGGER.log(
                            level, "Websocket authentication error: %s: %s", url, ex
                        )
                        await self._attempt_auth(True)
                    else:
                        _LOGGER.log(level, "Websocket handshake error: %s: %s", url, ex)
                else:
                    _LOGGER.log(level, "Websocket disconnect error: %s: %s", url, ex)
            except asyncio.TimeoutError:
                level = logging.ERROR if self._seen_non_close_message else logging.DEBUG
                _LOGGER.log(level, "Websocket timeout: %s", url)
            except Exception:
                _LOGGER.exception("Unexpected error in websocket loop")

            self._state_changed(WebsocketState.DISCONNECTED)
            if self._running is False:
                break
            _LOGGER.debug("Reconnecting websocket in %s seconds", backoff)
            await asyncio.sleep(self.backoff)

    def _state_changed(self, state: WebsocketState) -> None:
        """State changed."""
        if self._current_state is state:
            return
        self._current_state = state
        self._websocket_state(state)

    async def _websocket_inner_loop(self, url: URL) -> None:
        _LOGGER.debug("Connecting WS to %s", url)
        await self._attempt_auth(False)
        msg: WSMessage | None = None
        self._seen_non_close_message = False
        session = await self._get_session()
        # catch any and all errors for Websocket so we can clean up correctly
        try:
            self._ws_connection = await session.ws_connect(
                url,
                ssl=self.verify,
                headers=self._headers,
                timeout=aiohttp.ClientWSTimeout(ws_close=self.timeout),
            )
            while True:
                msg = await self._ws_connection.receive(self.receive_timeout)
                msg_type = msg.type
                if msg_type is WSMsgType.ERROR:
                    _LOGGER.exception("Error from Websocket: %s", msg.data)
                    break
                elif msg_type in _CLOSE_MESSAGE_TYPES:
                    _LOGGER.debug("Websocket closed: %s", msg)
                    break

                if not self._seen_non_close_message:
                    self._seen_non_close_message = True
                    self._state_changed(WebsocketState.CONNECTED)
                try:
                    self._subscription(msg)
                except Exception:
                    _LOGGER.exception("Error processing websocket message")
        finally:
            if (
                msg is not None
                and msg.type is WSMsgType.CLOSE
                # If it closes right away or lastUpdateId is in the extra
                # its an indication that we should update the bootstrap
                # since lastUpdateId is invalid
                and (
                    not self._seen_non_close_message
                    or (msg.extra and "lastUpdateId" in msg.extra)
                )
            ):
                self._update_bootstrap()
            _LOGGER.debug("Websocket disconnected: last message: %s", msg)
            if self._ws_connection is not None and not self._ws_connection.closed:
                await self._ws_connection.close()
            self._ws_connection = None

    async def _attempt_auth(self, force: bool) -> None:
        """Attempt to authenticate."""
        try:
            self._headers = await self._auth(force)
        except (NotAuthorized, NvrError) as ex:
            _LOGGER.debug("Error authenticating websocket: %s", ex)
        except Exception:
            _LOGGER.exception("Unknown error authenticating websocket")

    def start(self) -> None:
        """Start the websocket."""
        if self._running:
            return
        self._running = True
        self._websocket_loop_task = asyncio.create_task(self._websocket_loop())

    def stop(self) -> None:
        """Disconnect the websocket."""
        _LOGGER.debug("Disconnecting websocket...")
        if not self._running:
            return
        if self._websocket_loop_task:
            self._websocket_loop_task.cancel()
        self._running = False
        ws_connection = self._ws_connection
        websocket_loop_task = self._websocket_loop_task
        self._ws_connection = None
        self._websocket_loop_task = None
        self._stop_task = asyncio.create_task(
            self._stop(ws_connection, websocket_loop_task)
        )
        self._state_changed(WebsocketState.DISCONNECTED)

    async def wait_closed(self) -> None:
        """Wait for the websocket to close."""
        if self._stop_task and not self._stop_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await self._stop_task
            self._stop_task = None

    async def _stop(
        self,
        ws_connection: ClientWebSocketResponse | None,
        websocket_loop_task: asyncio.Task[None] | None,
    ) -> None:
        """Stop the websocket."""
        if ws_connection:
            await ws_connection.close()
        if websocket_loop_task:
            with contextlib.suppress(asyncio.CancelledError):
                await websocket_loop_task
