"""UniFi Protect Websockets."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from http import HTTPStatus
from typing import Any, Optional

from aiohttp import (
    ClientError,
    ClientSession,
    ClientWebSocketResponse,
    WSMessage,
    WSMsgType,
    WSServerHandshakeError,
)

_LOGGER = logging.getLogger(__name__)
AuthCallbackType = Callable[..., Coroutine[Any, Any, Optional[dict[str, str]]]]
GetSessionCallbackType = Callable[[], Awaitable[ClientSession]]
UpdateBootstrapCallbackType = Callable[[], None]
_CLOSE_MESSAGE_TYPES = {WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED}


class Websocket:
    """UniFi Protect Websocket manager."""

    _running = False
    _headers: dict[str, str] | None = None
    _websocket_loop_task: asyncio.Task[None] | None = None
    _stop_task: asyncio.Task[None] | None = None
    _ws_connection: ClientWebSocketResponse | None = None

    def __init__(
        self,
        get_url: Callable[[], str],
        auth_callback: AuthCallbackType,
        update_bootstrap_callback: UpdateBootstrapCallbackType,
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
        self._update_bootstrap_callback = update_bootstrap_callback
        self._connect_lock = asyncio.Lock()
        self._subscription = subscription
        self._last_ws_connect_ok = False

    @property
    def is_connected(self) -> bool:
        """Return if the websocket is connected."""
        return self._ws_connection is not None and not self._ws_connection.closed

    async def _websocket_reconnect_loop(self) -> None:
        """Reconnect loop for websocket."""
        await self.wait_closed()
        backoff = self.backoff

        while True:
            try:
                await self._websocket_loop()
            except ClientError:
                _LOGGER.debug("Error in websocket reconnect loop, backoff: %s", backoff)
            except Exception:
                _LOGGER.debug(
                    "Error in websocket reconnect loop, backoff: %s",
                    backoff,
                    exc_info=True,
                )

            if self._running is False:
                break
            await asyncio.sleep(self.backoff)

    async def _websocket_loop(self) -> None:
        url = self.get_url()
        _LOGGER.debug("Connecting WS to %s", url)
        self._headers = await self._auth(False)
        ssl = None if self.verify else False
        msg: WSMessage | None = None
        seen_non_close_message = False
        # catch any and all errors for Websocket so we can clean up correctly
        try:
            session = await self._get_session()
            self._ws_connection = await session.ws_connect(
                url, ssl=ssl, headers=self._headers, timeout=self.timeout
            )
            self._last_ws_connect_ok = True
            while True:
                msg = await self._ws_connection.receive(self.timeout)
                msg_type = msg.type
                if msg_type is WSMsgType.ERROR:
                    _LOGGER.exception("Error from Websocket: %s", msg.data)
                    break
                elif msg_type in _CLOSE_MESSAGE_TYPES:
                    _LOGGER.debug("Websocket closed: %s", msg)
                    break

                seen_non_close_message = True
                try:
                    self._subscription(msg)
                except Exception:
                    _LOGGER.exception("Error processing websocket message")
        except asyncio.TimeoutError:
            _LOGGER.debug("Websocket timeout: %s", url)
        except WSServerHandshakeError as ex:
            level = logging.ERROR if self._last_ws_connect_ok else logging.DEBUG
            self._last_ws_connect_ok = False
            if ex.status == HTTPStatus.UNAUTHORIZED.value:
                _LOGGER.log(level, "Websocket authentication error: %s", url)
                self._headers = await self._auth(True)
            else:
                _LOGGER.log(level, "Websocket handshake error: %s", url, exc_info=True)
            raise
        except ClientError:
            level = logging.ERROR if self._last_ws_connect_ok else logging.DEBUG
            self._last_ws_connect_ok = False
            _LOGGER.log(level, "Websocket disconnect error: %s", url, exc_info=True)
            raise
        finally:
            if (
                msg is not None
                and msg.type is WSMsgType.CLOSE
                # If it closes right away or lastUpdateId is in the extra
                # its an indication that we should update the bootstrap
                # since lastUpdateId is invalid
                and (
                    not seen_non_close_message
                    or (msg.extra and "lastUpdateId" in msg.extra)
                )
            ):
                self._update_bootstrap_callback()
            _LOGGER.debug("Websocket disconnected: last message: %s", msg)
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
