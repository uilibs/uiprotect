"""UniFi Protect Websockets."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Optional

from aiohttp import (
    ClientError,
    ClientSession,
    ClientWebSocketResponse,
    WSMessage,
    WSMsgType,
)

from .utils import asyncio_timeout

_LOGGER = logging.getLogger(__name__)
AuthCallbackType = Callable[..., Coroutine[Any, Any, Optional[dict[str, str]]]]
GetSessionCallbackType = Callable[[], Awaitable[ClientSession]]
_CLOSE_MESSAGE_TYPES = {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}


class Websocket:
    """UniFi Protect Websocket manager."""

    url: str
    verify: bool
    timeout: float
    backoff: int
    _auth: AuthCallbackType
    _connect_lock: asyncio.Lock
    _running = False

    _headers: dict[str, str] | None = None
    _websocket_loop_task: asyncio.Task[None] | None = None
    _stop_task: asyncio.Task[None] | None = None
    _ws_connection: ClientWebSocketResponse | None = None

    def __init__(
        self,
        get_url: Callable[[], str],
        auth_callback: AuthCallbackType,
        get_session: GetSessionCallbackType,
        subscription: Callable[[WSMessage], None],
        *,
        timeout: float = 30.0,
        backoff: int = 10,
        verify: bool = True,
    ) -> None:
        """Init Websocket."""
        self.get_url = get_url
        self.timeout = timeout
        self.backoff = backoff
        self.verify = verify
        self._get_session = get_session
        self._auth = auth_callback
        self._connect_lock = asyncio.Lock()
        self._subscription = subscription

    @property
    def is_connected(self) -> bool:
        """Return if the websocket is connected."""
        return self._ws_connection is not None and not self._ws_connection.closed

    def _process_message(self, msg: WSMessage) -> bool:
        """Process a message from the websocket."""
        if msg.type is WSMsgType.ERROR:
            _LOGGER.exception("Error from Websocket: %s", msg.data)
            return False
        elif msg.type in _CLOSE_MESSAGE_TYPES:
            _LOGGER.debug("Websocket closed")
            return False

        try:
            self._subscription(msg)
        except Exception:
            _LOGGER.exception("Error processing websocket message")

        return True

    async def _websocket_reconnect_loop(self) -> None:
        """Reconnect loop for websocket."""
        await self.wait_closed()

        while True:
            try:
                await self._websocket_loop()
            except Exception:
                _LOGGER.exception(
                    "Error in websocket reconnect loop, backoff: %s", self.backoff
                )
                await asyncio.sleep(self.backoff)

            if self._running is False:
                break

    async def _websocket_loop(self) -> None:
        url = self.get_url()
        _LOGGER.debug("Connecting WS to %s", url)
        self._headers = await self._auth(False)
        ssl = None if self.verify else False
        # catch any and all errors for Websocket so we can clean up correctly
        try:
            session = await self._get_session()
            async with asyncio_timeout(self.timeout):
                self._ws_connection = await session.ws_connect(
                    url,
                    ssl=ssl,
                    headers=self._headers,
                )

            while True:
                msg = await self._ws_connection.receive(self.timeout)
                if not self._process_message(msg):
                    break
        except asyncio.TimeoutError:
            _LOGGER.debug("Websocket timeout: %s", url)
        except ClientError:
            self._headers = await self._auth(True)
            _LOGGER.exception("Websocket disconnect error: %s", url)
        finally:
            _LOGGER.debug("Websocket disconnected")
            if self._ws_connection is not None and not self._ws_connection.closed:
                await self._ws_connection.close()
            self._ws_connection = None

    def start(self) -> None:
        """Start the websocket."""
        if self._running:
            return
        self._running = True
        self._websocket_loop_task = asyncio.create_task(
            self._websocket_reconnect_loop()
        )

    def stop(self) -> None:
        """Disconnect the websocket."""
        _LOGGER.debug("Disconnecting websocket...")
        if not self._running:
            return
        if self._websocket_loop_task:
            self._websocket_loop_task.cancel()
        self._running = False
        self._stop_task = asyncio.create_task(self._stop())

    async def wait_closed(self) -> None:
        """Wait for the websocket to close."""
        if self._stop_task:
            with contextlib.suppress(asyncio.CancelledError):
                await self._stop_task

    async def _stop(self) -> None:
        """Stop the websocket."""
        if self._ws_connection:
            await self._ws_connection.close()
            self._ws_connection = None
        if self._websocket_loop_task:
            with contextlib.suppress(asyncio.CancelledError):
                await self._websocket_loop_task
            self._websocket_loop_task = None
