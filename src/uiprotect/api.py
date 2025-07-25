"""UniFi Protect Server Wrapper."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from http import HTTPStatus, cookies
from http.cookies import Morsel, SimpleCookie
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import SplitResult

import aiofiles
import aiohttp
import orjson
from aiofiles import os as aos
from aiohttp import CookieJar, client_exceptions
from platformdirs import user_cache_dir, user_config_dir
from yarl import URL

from uiprotect.data.convert import list_from_unifi_list
from uiprotect.data.nvr import MetaInfo
from uiprotect.data.user import Keyring, Keyrings, UlpUser, UlpUsers

from ._compat import cached_property
from .data import (
    NVR,
    Bootstrap,
    Bridge,
    Camera,
    Doorlock,
    Event,
    EventCategories,
    EventType,
    Light,
    Liveview,
    ModelType,
    ProtectAdoptableDeviceModel,
    ProtectModel,
    PTZPosition,
    PTZPreset,
    Sensor,
    SmartDetectObjectType,
    SmartDetectTrack,
    Version,
    Viewer,
    WSPacket,
    WSSubscriptionMessage,
    create_from_unifi_dict,
)
from .data.base import ProtectModelWithId
from .data.devices import AiPort, Chime
from .data.types import IteratorCallback, ProgressCallback
from .exceptions import BadRequest, NotAuthorized, NvrError
from .utils import (
    decode_token_cookie,
    get_response_reason,
    ip_from_host,
    pybool_to_json_bool,
    set_debug,
    to_js_time,
    utc_now,
)
from .websocket import Websocket, WebsocketState

if "partitioned" not in cookies.Morsel._reserved:  # type: ignore[attr-defined]
    # See: https://github.com/python/cpython/issues/112713
    cookies.Morsel._reserved["partitioned"] = "partitioned"  # type: ignore[attr-defined]
    cookies.Morsel._flags.add("partitioned")  # type: ignore[attr-defined]

TOKEN_COOKIE_MAX_EXP_SECONDS = 60

# how many seconds before the bootstrap is refreshed from Protect
DEVICE_UPDATE_INTERVAL = 900
# retry timeout for thumbnails/heatmaps
RETRY_TIMEOUT = 10

TYPES_BUG_MESSAGE = """There is currently a bug in UniFi Protect that makes `start` / `end` not work if `types` is not provided. This means uiprotect has to iterate over all of the events matching the filters provided to return values.

If your Protect instance has a lot of events, this request will take much longer then expected. It is recommended adding additional filters to speed the request up."""


_LOGGER = logging.getLogger(__name__)
_COOKIE_RE = re.compile(r"^set-cookie: ", re.IGNORECASE)

NFC_FINGERPRINT_SUPPORT_VERSION = Version("5.1.57")

# TODO: Urls to still support
# Backups
# * GET /backups - list backends
# * POST /backups/import - import backup
# * POST /backups - create backup
# * GET /backups/{id} - download backup
# * POST /backups/{id}/restore - restore backup
# * DELETE /backups/{id} - delete backup
#
# Cameras
# * POST /cameras/{id}/reset - factory reset camera
# * POST /cameras/{id}/reset-isp - reset ISP settings
# * POST /cameras/{id}/reset-isp - reset ISP settings
# * POST /cameras/{id}/wake - battery powered cameras
# * POST /cameras/{id}/sleep
# * POST /cameras/{id}/homekit-talkback-speaker-muted
# * GET /cameras/{id}/live-heatmap - add live heatmap to WebRTC stream
# * GET /cameras/{id}/enable-control - PTZ controls
# * GET /cameras/{id}/disable-control
# * POST /cameras/{id}/move
# * POST /cameras/{id}/ptz/position
# * GET|POST /cameras/{id}/ptz/preset
# * GET /cameras/{id}/ptz/snapshot
# * POST /cameras/{id}/ptz/goto
# * GET /cameras/{id}/analytics-heatmap - analytics
# * GET /cameras/{id}/analytics-detections
# * GET /cameras/{id}/wifi-list - WiFi scan
# * POST /cameras/{id}/wifi-setup - Change WiFi settings
# * GET /cameras/{id}/playback-history
# * GET|POST|DELETE /cameras/{id}/sharedStream - stream sharing, unfinished?
#
# Device Groups
# * GET|POST|PUT|DELETE /device-groups
# * GET|PATCH|DELETE /device-groups/{id}
# * PATCH /device-groups/{id}/items
#
# Events
# POST /events/{id}/animated-thumbnail
#
# Lights
# POST /lights/{id}/locate
#
# NVR
# GET|PATCH /nvr/device-password
#
# Schedules
# GET|POST /recordingSchedules
# PATCH|DELETE /recordingSchedules/{id}
#
# Sensors
# POST /sensors/{id}/locate
#
# Timeline
# GET /timeline


def get_user_hash(host: str, username: str) -> str:
    session = hashlib.sha256()
    session.update(host.encode("utf8"))
    session.update(username.encode("utf8"))
    return session.hexdigest()


class BaseApiClient:
    _host: str
    _port: int
    _username: str
    _password: str
    _api_key: str | None = None
    _verify_ssl: bool
    _ws_timeout: int

    _is_authenticated: bool = False
    _last_token_cookie: Morsel[str] | None = None
    _last_token_cookie_decode: dict[str, Any] | None = None
    _session: aiohttp.ClientSession | None = None
    _public_api_session: aiohttp.ClientSession | None = None
    _loaded_session: bool = False
    _cookiename = "TOKEN"

    headers: dict[str, str] | None = None
    _private_websocket: Websocket | None = None

    private_api_path: str = "/proxy/protect/api/"
    public_api_path: str = "/proxy/protect/integration"
    private_ws_path: str = "/proxy/protect/ws/updates"

    cache_dir: Path
    config_dir: Path
    store_sessions: bool

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        api_key: str | None = None,
        verify_ssl: bool = True,
        session: aiohttp.ClientSession | None = None,
        public_api_session: aiohttp.ClientSession | None = None,
        ws_timeout: int = 30,
        cache_dir: Path | None = None,
        config_dir: Path | None = None,
        store_sessions: bool = True,
        ws_receive_timeout: int | None = None,
    ) -> None:
        self._auth_lock = asyncio.Lock()
        self._host = host
        self._port = port

        self._username = username
        self._password = password
        self._api_key = api_key
        self._verify_ssl = verify_ssl
        self._ws_timeout = ws_timeout
        self._ws_receive_timeout = ws_receive_timeout
        self._loaded_session = False
        self._update_task: asyncio.Task[Bootstrap | None] | None = None

        self.config_dir = config_dir or (Path(user_config_dir()) / "ufp")
        self.cache_dir = cache_dir or (Path(user_cache_dir()) / "ufp_cache")
        self.store_sessions = store_sessions

        if session is not None:
            self._session = session

        if public_api_session is not None:
            self._public_api_session = public_api_session

        self._update_url()

    def _update_cookiename(self, cookie: SimpleCookie) -> None:
        if "UOS_TOKEN" in cookie:
            self._cookiename = "UOS_TOKEN"

    def _update_url(self) -> None:
        """Updates the url after changing _host or _port."""
        if self._port != 443:
            self._url = URL(f"https://{self._host}:{self._port}")
            self._ws_url = URL(f"wss://{self._host}:{self._port}{self.private_ws_path}")
        else:
            self._url = URL(f"https://{self._host}")
            self._ws_url = URL(f"wss://{self._host}{self.private_ws_path}")

        self.base_url = str(self._url)

    @property
    def _ws_url_object(self) -> URL:
        """Get Websocket URL."""
        if last_update_id := self._get_last_update_id():
            return self._ws_url.with_query(lastUpdateId=last_update_id)
        return self._ws_url

    @property
    def ws_url(self) -> str:
        """Get Websocket URL."""
        return str(self._ws_url_object)

    @property
    def config_file(self) -> Path:
        return self.config_dir / "unifi_protect.json"

    async def get_session(self) -> aiohttp.ClientSession:
        """Gets or creates current client session"""
        if self._session is None or self._session.closed:
            if self._session is not None and self._session.closed:
                _LOGGER.debug("Session was closed, creating a new one")
            # need unsafe to access httponly cookies
            self._session = aiohttp.ClientSession(cookie_jar=CookieJar(unsafe=True))

        return self._session

    async def get_public_api_session(self) -> aiohttp.ClientSession:
        """Gets or creates current public API client session"""
        if self._public_api_session is None or self._public_api_session.closed:
            if self._public_api_session is not None and self._public_api_session.closed:
                _LOGGER.debug("Public API session was closed, creating a new one")
            self._public_api_session = aiohttp.ClientSession()

        return self._public_api_session

    async def _auth_websocket(self, force: bool) -> dict[str, str] | None:
        """Authenticate for Websocket."""
        if force:
            if self._session is not None:
                self._session.cookie_jar.clear()
            self.set_header("cookie", None)
            self.set_header("x-csrf-token", None)
            self._is_authenticated = False

        await self.ensure_authenticated()
        return self.headers

    def _get_websocket(self) -> Websocket:
        """Gets or creates current Websocket."""
        if self._private_websocket is None:
            self._private_websocket = Websocket(
                self._get_websocket_url,
                self._auth_websocket,
                self._update_bootstrap_soon,
                self.get_session,
                self._process_ws_message,
                self._on_websocket_state_change,
                verify=self._verify_ssl,
                timeout=self._ws_timeout,
                receive_timeout=self._ws_receive_timeout,
            )
        return self._private_websocket

    def _update_bootstrap_soon(self) -> None:
        """Update bootstrap soon."""
        _LOGGER.debug("Updating bootstrap soon")
        # Force the next bootstrap update
        # since the lastUpdateId is not valid anymore
        if self._update_task and not self._update_task.done():
            return
        self._update_task = asyncio.create_task(self.update())

    async def close_session(self) -> None:
        """Closing and deletes client session"""
        await self._cancel_update_task()
        if self._session is not None:
            await self._session.close()
            self._session = None
            self._loaded_session = False

    async def close_public_api_session(self) -> None:
        """Closing and deletes public API client session"""
        if self._public_api_session is not None:
            await self._public_api_session.close()
            self._public_api_session = None

    async def _cancel_update_task(self) -> None:
        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task
            self._update_task = None

    def set_header(self, key: str, value: str | None) -> None:
        """Set header."""
        self.headers = self.headers or {}
        if value is None:
            self.headers.pop(key, None)
        else:
            self.headers[key] = value

    async def request(
        self,
        method: str,
        url: str,
        require_auth: bool = False,
        auto_close: bool = True,
        public_api: bool = False,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Make a request to UniFi Protect"""
        if require_auth and not public_api:
            await self.ensure_authenticated()

        request_url = self._url.join(
            URL(SplitResult("", "", url, "", ""), encoded=True)
        )
        headers = kwargs.get("headers") or self.headers or {}
        if require_auth and public_api:
            if self._api_key is None:
                raise NotAuthorized("API key is required for public API requests")
            headers = {"X-API-KEY": self._api_key}
        _LOGGER.debug("Request url: %s", request_url)
        if not self._verify_ssl:
            kwargs["ssl"] = False

        if public_api:
            session = await self.get_public_api_session()
        else:
            session = await self.get_session()

        for attempt in range(2):
            try:
                req_context = session.request(
                    method,
                    request_url,
                    headers=headers,
                    **kwargs,
                )
                response = await req_context.__aenter__()

                await self._update_last_token_cookie(response)
                if auto_close:
                    try:
                        _LOGGER.debug(
                            "%s %s %s",
                            response.status,
                            response.content_type,
                            response,
                        )
                        response.release()
                    except Exception:
                        # make sure response is released
                        response.release()
                        # re-raise exception
                        raise

                return response
            except aiohttp.ServerDisconnectedError as err:
                # If the server disconnected, try again
                # since HTTP/1.1 allows the server to disconnect
                # at any time
                if attempt == 0:
                    continue
                raise NvrError(
                    f"Error requesting data from {self._host}: {err}",
                ) from err
            except client_exceptions.ClientError as err:
                raise NvrError(
                    f"Error requesting data from {self._host}: {err}",
                ) from err

        # should never happen
        raise NvrError(f"Error requesting data from {self._host}")

    async def api_request_raw(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        api_path: str | None = None,
        public_api: bool = False,
        **kwargs: Any,
    ) -> bytes | None:
        """Make a API request"""
        path = self.private_api_path
        if api_path is not None:
            path = api_path
        elif public_api:
            path = self.public_api_path

        response = await self.request(
            method,
            f"{path}{url}",
            require_auth=require_auth,
            auto_close=False,
            public_api=public_api,
            **kwargs,
        )

        try:
            if response.status != 200:
                await self._raise_for_status(response, raise_exception)
                return None

            data: bytes | None = await response.read()
            response.release()

            return data
        except Exception:
            # make sure response is released
            response.release()
            # re-raise exception
            raise

    async def _raise_for_status(
        self, response: aiohttp.ClientResponse, raise_exception: bool = True
    ) -> None:
        """Raise an exception based on the response status."""
        url = response.url
        reason = await get_response_reason(response)
        msg = "Request failed: %s - Status: %s - Reason: %s"
        status = response.status

        if raise_exception:
            if status in {
                HTTPStatus.UNAUTHORIZED.value,
                HTTPStatus.FORBIDDEN.value,
            }:
                raise NotAuthorized(msg % (url, status, reason))
            elif status == HTTPStatus.TOO_MANY_REQUESTS.value:
                _LOGGER.debug("Too many requests - Login is rate limited: %s", response)
                raise NvrError(msg % (url, status, reason))
            elif (
                status >= HTTPStatus.BAD_REQUEST.value
                and status < HTTPStatus.INTERNAL_SERVER_ERROR.value
            ):
                raise BadRequest(msg % (url, status, reason))
            raise NvrError(msg % (url, status, reason))

        _LOGGER.debug(msg, url, status, reason)

    async def api_request(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        api_path: str | None = None,
        public_api: bool = False,
        **kwargs: Any,
    ) -> list[Any] | dict[str, Any] | None:
        data = await self.api_request_raw(
            url=url,
            method=method,
            require_auth=require_auth,
            raise_exception=raise_exception,
            api_path=api_path,
            public_api=public_api,
            **kwargs,
        )

        if data is not None:
            json_data: list[Any] | dict[str, Any]
            try:
                json_data = orjson.loads(data)
                return json_data
            except orjson.JSONDecodeError as ex:
                _LOGGER.error("Could not decode JSON from %s", url)
                raise NvrError(f"Could not decode JSON from {url}") from ex
        return None

    async def api_request_obj(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        public_api: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        data = await self.api_request(
            url=url,
            method=method,
            require_auth=require_auth,
            raise_exception=raise_exception,
            public_api=public_api,
            **kwargs,
        )

        if not isinstance(data, dict):
            raise NvrError(f"Could not decode object from {url}")

        return data

    async def api_request_list(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        public_api: bool = False,
        **kwargs: Any,
    ) -> list[Any]:
        data = await self.api_request(
            url=url,
            method=method,
            require_auth=require_auth,
            raise_exception=raise_exception,
            public_api=public_api,
            **kwargs,
        )

        if not isinstance(data, list):
            raise NvrError(f"Could not decode list from {url}")

        return data

    async def ensure_authenticated(self) -> None:
        """Ensure we are authenticated."""
        await self._load_session()
        if self.is_authenticated() is False:
            await self.authenticate()

    async def authenticate(self) -> None:
        """Authenticate and get a token."""
        if self._auth_lock.locked():
            # If an auth is already in progress
            # do not start another one
            async with self._auth_lock:
                return

        async with self._auth_lock:
            url = "/api/auth/login"

            if self._session is not None:
                self._session.cookie_jar.clear()
                self.set_header("cookie", None)

            auth = {
                "username": self._username,
                "password": self._password,
                "rememberMe": self.store_sessions,
            }

            response = await self.request("post", url=url, json=auth)
            if response.status != 200:
                await self._raise_for_status(response, True)
            self.set_header("cookie", response.headers.get("set-cookie", ""))
            self._is_authenticated = True
            _LOGGER.debug("Authenticated successfully!")

    async def _update_last_token_cookie(self, response: aiohttp.ClientResponse) -> None:
        """Update the last token cookie."""
        csrf_token = response.headers.get("x-csrf-token")
        if (
            csrf_token is not None
            and self.headers
            and csrf_token != self.headers.get("x-csrf-token")
        ):
            self.set_header("x-csrf-token", csrf_token)
            await self._update_last_token_cookie(response)
            self._update_cookiename(response.cookies)

        if (
            token_cookie := response.cookies.get(self._cookiename)
        ) and token_cookie != self._last_token_cookie:
            self._last_token_cookie = token_cookie
            if self.store_sessions:
                await self._update_auth_config(self._last_token_cookie)
            self._last_token_cookie_decode = None

    async def _update_auth_config(self, cookie: Morsel[str]) -> None:
        """Updates auth cookie on disk for persistent sessions."""
        if self._last_token_cookie is None:
            return

        await aos.makedirs(self.config_dir, exist_ok=True)

        config: dict[str, Any] = {}
        session_hash = get_user_hash(str(self._url), self._username)
        try:
            async with aiofiles.open(self.config_file, "rb") as f:
                config_data = await f.read()
                if config_data:
                    try:
                        config = orjson.loads(config_data)
                    except Exception:
                        _LOGGER.warning("Invalid config file, ignoring.")
        except FileNotFoundError:
            pass

        config["sessions"] = config.get("sessions", {})
        config["sessions"][session_hash] = {
            "metadata": dict(cookie),
            "cookiename": self._cookiename,
            "value": cookie.value,
            "csrf": self.headers.get("x-csrf-token") if self.headers else None,
        }

        async with aiofiles.open(self.config_file, "wb") as f:
            await f.write(orjson.dumps(config, option=orjson.OPT_INDENT_2))

    async def _load_session(self) -> None:
        if self._session is None:
            await self.get_session()
            assert self._session is not None

        if not self._loaded_session and self.store_sessions:
            session_cookie = await self._read_auth_config()
            self._loaded_session = True
            if session_cookie:
                _LOGGER.debug("Successfully loaded session from config")
                self._session.cookie_jar.update_cookies(session_cookie)

    async def _read_auth_config(self) -> SimpleCookie | None:
        """Read auth cookie from config."""
        config: dict[str, Any] = {}
        try:
            async with aiofiles.open(self.config_file, "rb") as f:
                config_data = await f.read()
                if config_data:
                    try:
                        config = orjson.loads(config_data)
                    except Exception:
                        _LOGGER.warning("Invalid config file, ignoring.")
                        return None
        except FileNotFoundError:
            _LOGGER.debug("no config file, not loading session")
            return None

        session_hash = get_user_hash(str(self._url), self._username)
        session = config.get("sessions", {}).get(session_hash)
        if not session:
            _LOGGER.debug("No existing session for %s", session_hash)
            return None

        cookie = SimpleCookie()
        cookie_name = session.get("cookiename")
        if cookie_name is None:
            return None
        cookie[cookie_name] = session.get("value")
        for key, value in session.get("metadata", {}).items():
            cookie[cookie_name][key] = value

        cookie_value = _COOKIE_RE.sub("", str(cookie[cookie_name]))
        self._last_token_cookie = cookie[cookie_name]
        self._last_token_cookie_decode = None
        self._is_authenticated = True
        self.set_header("cookie", cookie_value)
        if session.get("csrf"):
            self.set_header("x-csrf-token", session["csrf"])
        return cookie

    def is_authenticated(self) -> bool:
        """Check to see if we are already authenticated."""
        if self._session is None:
            return False

        if self._is_authenticated is False:
            return False

        if self._last_token_cookie is None:
            return False

        # Lazy decode the token cookie
        if self._last_token_cookie and self._last_token_cookie_decode is None:
            self._last_token_cookie_decode = decode_token_cookie(
                self._last_token_cookie,
            )

        if (
            self._last_token_cookie_decode is None
            or "exp" not in self._last_token_cookie_decode
        ):
            return False

        token_expires_at = cast(int, self._last_token_cookie_decode["exp"])
        max_expire_time = time.time() + TOKEN_COOKIE_MAX_EXP_SECONDS

        return token_expires_at >= max_expire_time

    def _get_websocket_url(self) -> URL:
        """Get Websocket URL."""
        return self._ws_url_object

    async def async_disconnect_ws(self) -> None:
        """Disconnect from Websocket."""
        if self._private_websocket:
            websocket = self._get_websocket()
            websocket.stop()
            await websocket.wait_closed()
            self._private_websocket = None

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        raise NotImplementedError

    def _get_last_update_id(self) -> str | None:
        raise NotImplementedError

    async def update(self) -> Bootstrap:
        raise NotImplementedError

    def _on_websocket_state_change(self, state: WebsocketState) -> None:
        """Websocket state changed."""
        _LOGGER.debug("Websocket state changed: %s", state)


class ProtectApiClient(BaseApiClient):
    """
    Main UFP API Client

    UniFi Protect is a full async application. "normal" use of interacting with it is
    to call `.update()` which will initialize the `.bootstrap` and create a Websocket
    connection to UFP. This Websocket connection will emit messages that will automatically
    update the `.bootstrap` over time.

    You can use the `.get_` methods to one off pull devices from the UFP API, but should
    not be used for building an aplication on top of.

    All objects inside of `.bootstrap` have a refernce back to the API client so they can
    use `.save_device()` and update themselves using their own `.set_` methods on the object.

    Args:
    ----
        host: UFP hostname / IP address
        port: UFP HTTPS port
        username: UFP username
        password: UFP password
        api_key: API key for UFP
        verify_ssl: Verify HTTPS certificate (default: `True`)
        session: Optional aiohttp session to use (default: generate one)
        override_connection_host: Use `host` as your `connection_host` for RTSP stream instead of using the one provided by UniFi Protect.
        minimum_score: minimum score for events (default: `0`)
        subscribed_models: Model types you want to filter events for WS. You will need to manually check the bootstrap for updates for events that not subscibred.
        ignore_stats: Ignore storage, system, etc. stats/metrics from NVR and cameras (default: false)
        debug: Use full type validation (default: false)

    """

    _minimum_score: int
    _subscribed_models: set[ModelType]
    _ignore_stats: bool
    _ws_subscriptions: list[Callable[[WSSubscriptionMessage], None]]
    _ws_state_subscriptions: list[Callable[[WebsocketState], None]]
    _bootstrap: Bootstrap | None = None
    _last_update_dt: datetime | None = None
    _connection_host: IPv4Address | IPv6Address | str | None = None

    ignore_unadopted: bool

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        api_key: str | None = None,
        verify_ssl: bool = True,
        session: aiohttp.ClientSession | None = None,
        public_api_session: aiohttp.ClientSession | None = None,
        ws_timeout: int = 30,
        cache_dir: Path | None = None,
        config_dir: Path | None = None,
        store_sessions: bool = True,
        override_connection_host: bool = False,
        minimum_score: int = 0,
        subscribed_models: set[ModelType] | None = None,
        ignore_stats: bool = False,
        ignore_unadopted: bool = True,
        debug: bool = False,
        ws_receive_timeout: int | None = None,
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            api_key=api_key,
            verify_ssl=verify_ssl,
            session=session,
            public_api_session=public_api_session,
            ws_timeout=ws_timeout,
            ws_receive_timeout=ws_receive_timeout,
            cache_dir=cache_dir,
            config_dir=config_dir,
            store_sessions=store_sessions,
        )

        self._minimum_score = minimum_score
        self._subscribed_models = subscribed_models or set()
        self._ignore_stats = ignore_stats
        self._ws_subscriptions = []
        self._ws_state_subscriptions = []
        self.ignore_unadopted = ignore_unadopted
        self._update_lock = asyncio.Lock()

        if override_connection_host:
            self._connection_host = ip_from_host(self._host)

        if debug:
            set_debug()

    @cached_property
    def bootstrap(self) -> Bootstrap:
        if self._bootstrap is None:
            raise BadRequest("Client not initialized, run `update` first")

        return self._bootstrap

    @property
    def connection_host(self) -> IPv4Address | IPv6Address | str:
        """Connection host to use for generating RTSP URLs"""
        if self._connection_host is None:
            # fallback if cannot find user supplied host
            index = 0
            try:
                # check if user supplied host is avaiable
                index = self.bootstrap.nvr.hosts.index(self._host)
            except ValueError:
                # check if IP of user supplied host is avaiable
                host = ip_from_host(self._host)
                with contextlib.suppress(ValueError):
                    index = self.bootstrap.nvr.hosts.index(host)

            self._connection_host = self.bootstrap.nvr.hosts[index]

        return self._connection_host

    async def update(self) -> Bootstrap:
        """
        Updates the state of devices, initializes `.bootstrap`

        The websocket is auto connected once there are any
        subscriptions to it. update must be called at least
        once before subscribing to the websocket.

        You can use the various other `get_` methods if you need one off data from UFP
        """
        async with self._update_lock:
            bootstrap = await self.get_bootstrap()
            if bootstrap.nvr.version >= NFC_FINGERPRINT_SUPPORT_VERSION:
                try:
                    keyrings = await self.api_request_list("keyrings")
                except NotAuthorized as err:
                    _LOGGER.debug("No access to keyrings %s, skipping", err)
                    keyrings = []
                try:
                    ulp_users = await self.api_request_list("ulp-users")
                except NotAuthorized as err:
                    _LOGGER.debug("No access to ulp-users %s, skipping", err)
                    ulp_users = []
                bootstrap.keyrings = Keyrings.from_list(
                    cast(list[Keyring], list_from_unifi_list(self, keyrings))
                )
                bootstrap.ulp_users = UlpUsers.from_list(
                    cast(list[UlpUser], list_from_unifi_list(self, ulp_users))
                )
            self.__dict__.pop("bootstrap", None)
            self._bootstrap = bootstrap
            return bootstrap

    async def poll_events(self) -> None:
        """Poll for events."""
        now_dt = utc_now()
        max_event_dt = now_dt - timedelta(hours=1)
        events = await self.get_events(
            start=self._last_update_dt or max_event_dt,
            end=now_dt,
        )
        for event in events:
            self.bootstrap.process_event(event)
        self._last_update_dt = now_dt

    def emit_message(self, msg: WSSubscriptionMessage) -> None:
        """Emit message to all subscriptions."""
        if _LOGGER.isEnabledFor(logging.DEBUG):
            if msg.new_obj is not None:
                _LOGGER.debug(
                    "emitting message: %s:%s:%s:%s",
                    msg.action,
                    msg.new_obj.model,
                    msg.new_obj.id,
                    list(msg.changed_data),
                )
            elif msg.old_obj is not None:
                _LOGGER.debug(
                    "emitting message: %s:%s:%s",
                    msg.action,
                    msg.old_obj.model,
                    msg.old_obj.id,
                )
            else:
                _LOGGER.debug("emitting message: %s", msg.action)

        for sub in self._ws_subscriptions:
            try:
                sub(msg)
            except Exception:
                _LOGGER.exception("Exception while running subscription handler")

    def _get_last_update_id(self) -> str | None:
        if self._bootstrap is None:
            return None
        return self._bootstrap.last_update_id

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        packet = WSPacket(msg.data)
        processed_message = self.bootstrap.process_ws_packet(
            packet,
            models=self._subscribed_models,
            ignore_stats=self._ignore_stats,
        )
        if processed_message is None:
            return

        self.emit_message(processed_message)

    async def _get_event_paginate(
        self,
        params: dict[str, Any],
        *,
        start: datetime,
        end: datetime | None,
    ) -> list[dict[str, Any]]:
        start_int = to_js_time(start)
        end_int = to_js_time(end) if end else None
        offset = 0
        current_start = sys.maxsize
        events: list[dict[str, Any]] = []
        request_count = 0
        logged = False

        params["limit"] = 100
        # greedy algorithm
        # always force desc to receive faster results in the vast majority of cases
        params["orderDirection"] = "DESC"

        _LOGGER.debug("paginate desc %s %s", start_int, end_int)
        while current_start > start_int:
            params["offset"] = offset

            _LOGGER.debug("page desc %s %s", offset, current_start)
            new_events = await self.api_request_list("events", params=params)
            request_count += 1
            if not new_events:
                break

            if end_int is not None:
                _LOGGER.debug("page end %s (%s)", new_events[0]["end"], end_int)
                for event in new_events:
                    if event["start"] <= end_int:
                        events.append(event)
                    else:
                        break
            else:
                events += new_events

            offset += 100
            if events:
                current_start = events[-1]["start"]
            if not logged and request_count > 5:
                logged = True
                _LOGGER.warning(TYPES_BUG_MESSAGE)

        to_remove = 0
        for event in reversed(events):
            if event["start"] < start_int:
                to_remove += 1
            else:
                break
        if to_remove:
            events = events[:-to_remove]

        return events

    async def get_events_raw(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        offset: int | None = None,
        types: list[EventType] | None = None,
        smart_detect_types: list[SmartDetectObjectType] | None = None,
        sorting: Literal["asc", "desc"] = "asc",
        descriptions: bool = True,
        all_cameras: bool | None = None,
        category: EventCategories | None = None,
        # used for testing
        _allow_manual_paginate: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Get list of events from Protect

        Args:
        ----
            start: start time for events
            end: end time for events
            limit: max number of events to return
            offset: offset to start fetching events from
            types: list of EventTypes to get events for
            smart_detect_types: Filters the Smart detection types for the events
            sorting: sort events by ascending or decending, defaults to ascending (chronologic order)
            description: included additional event metadata
            category: event category, will provide additional category/subcategory fields


        If `limit`, `start` and `end` are not provided, it will default to all events in the last 24 hours.

        If `start` is provided, then `end` or `limit` must be provided. If `end` is provided, then `start` or
        `limit` must be provided. Otherwise, you will get a 400 error from UniFi Protect

        """
        # if no parameters are passed in, default to all events from last 24 hours
        if limit is None and start is None and end is None:
            end = utc_now() + timedelta(seconds=10)
            start = end - timedelta(hours=1)

        params: dict[str, Any] = {
            "orderDirection": sorting.upper(),
            "withoutDescriptions": str(not descriptions).lower(),
        }
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        if start is not None:
            params["start"] = to_js_time(start)

        if end is not None:
            params["end"] = to_js_time(end)

        if types is not None:
            params["types"] = [e.value for e in types]

        if smart_detect_types is not None:
            params["smartDetectTypes"] = [e.value for e in smart_detect_types]

        if all_cameras is not None:
            params["allCameras"] = str(all_cameras).lower()

        if category is not None:
            params["categories"] = category

        # manual workaround for a UniFi Protect bug
        # if types if missing from query params
        if _allow_manual_paginate and "types" not in params and start is not None:
            if sorting == "asc":
                events = await self._get_event_paginate(
                    params,
                    start=start,
                    end=end,
                )
                events = list(reversed(events))
            else:
                events = await self._get_event_paginate(
                    params,
                    start=start,
                    end=end,
                )

            if limit:
                offset = offset or 0
                events = events[offset : limit + offset]
            elif offset:
                events = events[offset:]
            return events

        return await self.api_request_list("events", params=params)

    async def get_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        offset: int | None = None,
        types: list[EventType] | None = None,
        smart_detect_types: list[SmartDetectObjectType] | None = None,
        sorting: Literal["asc", "desc"] = "asc",
        descriptions: bool = True,
        category: EventCategories | None = None,
        # used for testing
        _allow_manual_paginate: bool = True,
    ) -> list[Event]:
        """
        Same as `get_events_raw`, except

        * returns actual `Event` objects instead of raw Python dictionaries
        * filers out non-device events
        * filters out events with too low of a score

        Args:
        ----
            start: start time for events
            end: end time for events
            limit: max number of events to return
            offset: offset to start fetching events from
            types: list of EventTypes to get events for
            smart_detect_types: Filters the Smart detection types for the events
            sorting: sort events by ascending or decending, defaults to ascending (chronologic order)
            description: included additional event metadata
            category: event category, will provide additional category/subcategory fields


        If `limit`, `start` and `end` are not provided, it will default to all events in the last 24 hours.

        If `start` is provided, then `end` or `limit` must be provided. If `end` is provided, then `start` or
        `limit` must be provided. Otherwise, you will get a 400 error from UniFi Protect

        """
        response = await self.get_events_raw(
            start=start,
            end=end,
            limit=limit,
            offset=offset,
            types=types,
            smart_detect_types=smart_detect_types,
            sorting=sorting,
            descriptions=descriptions,
            category=category,
            _allow_manual_paginate=_allow_manual_paginate,
        )
        events = []

        for event_dict in response:
            # ignore unknown events
            if (
                "type" not in event_dict
                or event_dict["type"] not in EventType.values_set()
            ):
                _LOGGER.debug("Unknown event type: %s", event_dict)
                continue

            event = create_from_unifi_dict(event_dict, api=self)

            # should never happen
            if not isinstance(event, Event):
                continue

            if (
                event.type.value in EventType.device_events_set()
                and event.score >= self._minimum_score
            ):
                events.append(event)

        return events

    def subscribe_websocket(
        self,
        ws_callback: Callable[[WSSubscriptionMessage], None],
    ) -> Callable[[], None]:
        """
        Subscribe to websocket events.

        Returns a callback that will unsubscribe.
        """
        _LOGGER.debug("Adding subscription: %s", ws_callback)
        self._ws_subscriptions.append(ws_callback)
        self._get_websocket().start()
        return partial(self._unsubscribe_websocket, ws_callback)

    def _unsubscribe_websocket(
        self,
        ws_callback: Callable[[WSSubscriptionMessage], None],
    ) -> None:
        """Unsubscribe to websocket events."""
        _LOGGER.debug("Removing subscription: %s", ws_callback)
        self._ws_subscriptions.remove(ws_callback)
        if not self._ws_subscriptions:
            self._get_websocket().stop()

    def subscribe_websocket_state(
        self,
        ws_callback: Callable[[WebsocketState], None],
    ) -> Callable[[], None]:
        """
        Subscribe to websocket state changes.

        Returns a callback that will unsubscribe.
        """
        self._ws_state_subscriptions.append(ws_callback)
        return partial(self._unsubscribe_websocket_state, ws_callback)

    def _unsubscribe_websocket_state(
        self,
        ws_callback: Callable[[WebsocketState], None],
    ) -> None:
        """Unsubscribe to websocket state changes."""
        self._ws_state_subscriptions.remove(ws_callback)

    def _on_websocket_state_change(self, state: WebsocketState) -> None:
        """Websocket state changed."""
        super()._on_websocket_state_change(state)
        for sub in self._ws_state_subscriptions:
            try:
                sub(state)
            except Exception:
                _LOGGER.exception("Exception while running websocket state handler")

    async def get_bootstrap(self) -> Bootstrap:
        """
        Gets bootstrap object from UFP instance

        This is a great alternative if you need metadata about the NVR without connecting to the Websocket
        """
        data = await self.api_request_obj("bootstrap")
        return Bootstrap.from_unifi_dict(**data, api=self)

    async def get_devices_raw(self, model_type: ModelType) -> list[dict[str, Any]]:
        """Gets a raw device list given a model_type"""
        return await self.api_request_list(model_type.devices_key)

    async def get_devices(
        self,
        model_type: ModelType,
        expected_type: type[ProtectModel] | None = None,
    ) -> list[ProtectModel]:
        """Gets a device list given a model_type, converted into Python objects"""
        objs: list[ProtectModel] = []

        for obj_dict in await self.get_devices_raw(model_type):
            obj = create_from_unifi_dict(obj_dict, api=self)

            if expected_type is not None and not isinstance(obj, expected_type):
                raise NvrError(f"Unexpected model returned: {obj.model}")
            if (
                self.ignore_unadopted
                and isinstance(obj, ProtectAdoptableDeviceModel)
                and not obj.is_adopted
            ):
                continue

            objs.append(obj)

        return objs

    async def get_cameras(self) -> list[Camera]:
        """
        Gets the list of cameras straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.cameras`
        """
        return cast(list[Camera], await self.get_devices(ModelType.CAMERA, Camera))

    async def get_lights(self) -> list[Light]:
        """
        Gets the list of lights straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.lights`
        """
        return cast(list[Light], await self.get_devices(ModelType.LIGHT, Light))

    async def get_sensors(self) -> list[Sensor]:
        """
        Gets the list of sensors straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.sensors`
        """
        return cast(list[Sensor], await self.get_devices(ModelType.SENSOR, Sensor))

    async def get_doorlocks(self) -> list[Doorlock]:
        """
        Gets the list of doorlocks straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.doorlocks`
        """
        return cast(
            list[Doorlock],
            await self.get_devices(ModelType.DOORLOCK, Doorlock),
        )

    async def get_chimes(self) -> list[Chime]:
        """
        Gets the list of chimes straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.chimes`
        """
        return cast(list[Chime], await self.get_devices(ModelType.CHIME, Chime))

    async def get_aiports(self) -> list[AiPort]:
        """
        Gets the list of aiports straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.aiports`
        """
        return cast(list[AiPort], await self.get_devices(ModelType.AIPORT, AiPort))

    async def get_viewers(self) -> list[Viewer]:
        """
        Gets the list of viewers straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.viewers`
        """
        return cast(list[Viewer], await self.get_devices(ModelType.VIEWPORT, Viewer))

    async def get_bridges(self) -> list[Bridge]:
        """
        Gets the list of bridges straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.bridges`
        """
        return cast(list[Bridge], await self.get_devices(ModelType.BRIDGE, Bridge))

    async def get_liveviews(self) -> list[Liveview]:
        """
        Gets the list of liveviews straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.liveviews`
        """
        return cast(
            list[Liveview],
            await self.get_devices(ModelType.LIVEVIEW, Liveview),
        )

    async def get_device_raw(
        self,
        model_type: ModelType,
        device_id: str,
    ) -> dict[str, Any]:
        """Gets a raw device give the device model_type and id"""
        return await self.api_request_obj(f"{model_type.value}s/{device_id}")

    async def get_device(
        self,
        model_type: ModelType,
        device_id: str,
        expected_type: type[ProtectModelWithId] | None = None,
    ) -> ProtectModelWithId:
        """Gets a device give the device model_type and id, converted into Python object"""
        obj = create_from_unifi_dict(
            await self.get_device_raw(model_type, device_id),
            api=self,
        )

        if expected_type is not None and not isinstance(obj, expected_type):
            raise NvrError(f"Unexpected model returned: {obj.model}")
        if (
            self.ignore_unadopted
            and isinstance(obj, ProtectAdoptableDeviceModel)
            and not obj.is_adopted
        ):
            raise NvrError("Device is not adopted")

        return cast(ProtectModelWithId, obj)

    async def get_nvr(self) -> NVR:
        """
        Gets an NVR object straight from the NVR.

        This is a great alternative if you need metadata about the NVR without connecting to the Websocket
        """
        data = await self.api_request_obj("nvr")
        return NVR.from_unifi_dict(**data, api=self)

    async def get_event(self, event_id: str) -> Event:
        """
        Gets an event straight from the NVR.

        This is a great alternative if the event is no longer in the `self.bootstrap.events[event_id]` cache
        """
        return cast(Event, await self.get_device(ModelType.EVENT, event_id, Event))

    async def get_camera(self, device_id: str) -> Camera:
        """
        Gets a camera straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.cameras[device_id]`
        """
        return cast(Camera, await self.get_device(ModelType.CAMERA, device_id, Camera))

    async def get_light(self, device_id: str) -> Light:
        """
        Gets a light straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.lights[device_id]`
        """
        return cast(Light, await self.get_device(ModelType.LIGHT, device_id, Light))

    async def get_sensor(self, device_id: str) -> Sensor:
        """
        Gets a sensor straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.sensors[device_id]`
        """
        return cast(Sensor, await self.get_device(ModelType.SENSOR, device_id, Sensor))

    async def get_doorlock(self, device_id: str) -> Doorlock:
        """
        Gets a doorlock straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.doorlocks[device_id]`
        """
        return cast(
            Doorlock,
            await self.get_device(ModelType.DOORLOCK, device_id, Doorlock),
        )

    async def get_chime(self, device_id: str) -> Chime:
        """
        Gets a chime straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.chimes[device_id]`
        """
        return cast(Chime, await self.get_device(ModelType.CHIME, device_id, Chime))

    async def get_aiport(self, device_id: str) -> AiPort:
        """
        Gets a AiPort straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.aiport[device_id]`
        """
        return cast(AiPort, await self.get_device(ModelType.AIPORT, device_id, AiPort))

    async def get_viewer(self, device_id: str) -> Viewer:
        """
        Gets a viewer straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.viewers[device_id]`
        """
        return cast(
            Viewer,
            await self.get_device(ModelType.VIEWPORT, device_id, Viewer),
        )

    async def get_bridge(self, device_id: str) -> Bridge:
        """
        Gets a bridge straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.bridges[device_id]`
        """
        return cast(Bridge, await self.get_device(ModelType.BRIDGE, device_id, Bridge))

    async def get_liveview(self, device_id: str) -> Liveview:
        """
        Gets a liveview straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.liveviews[device_id]`
        """
        return cast(
            Liveview,
            await self.get_device(ModelType.LIVEVIEW, device_id, Liveview),
        )

    async def get_camera_snapshot(
        self,
        camera_id: str,
        width: int | None = None,
        height: int | None = None,
        dt: datetime | None = None,
    ) -> bytes | None:
        """
        Gets snapshot for a camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """
        params: dict[str, Any] = {}
        if dt is not None:
            path = "recording-snapshot"
            params["ts"] = to_js_time(dt)
        else:
            path = "snapshot"
            params["ts"] = int(time.time() * 1000)
            params["force"] = "true"

        if width is not None:
            params["w"] = width

        if height is not None:
            params["h"] = height

        return await self.api_request_raw(
            f"cameras/{camera_id}/{path}",
            params=params,
            raise_exception=False,
        )

    async def get_public_api_camera_snapshot(
        self,
        camera_id: str,
        high_quality: bool = False,
    ) -> bytes | None:
        """Gets snapshot for a camera using public api."""
        return await self.api_request_raw(
            public_api=True,
            raise_exception=False,
            url=f"/v1/cameras/{camera_id}/snapshot",
            params={"highQuality": pybool_to_json_bool(high_quality)},
        )

    async def get_package_camera_snapshot(
        self,
        camera_id: str,
        width: int | None = None,
        height: int | None = None,
        dt: datetime | None = None,
    ) -> bytes | None:
        """
        Gets snapshot from the package camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """
        params: dict[str, Any] = {}
        if dt is not None:
            path = "recording-snapshot"
            params["ts"] = to_js_time(dt)
            params["lens"] = 2
        else:
            path = "package-snapshot"
            params["ts"] = int(time.time() * 1000)
            params["force"] = "true"

        if width is not None:
            params["w"] = width

        if height is not None:
            params["h"] = height

        return await self.api_request_raw(
            f"cameras/{camera_id}/{path}",
            params=params,
            raise_exception=False,
        )

    async def _stream_response(
        self,
        response: aiohttp.ClientResponse,
        chunk_size: int,
        iterator_callback: IteratorCallback | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        total = response.content_length or 0
        current = 0
        if iterator_callback is not None:
            await iterator_callback(total, None)
        async for chunk in response.content.iter_chunked(chunk_size):
            step = len(chunk)
            current += step
            if iterator_callback is not None:
                await iterator_callback(total, chunk)
            if progress_callback is not None:
                await progress_callback(step, current, total)

    async def get_camera_video(
        self,
        camera_id: str,
        start: datetime,
        end: datetime,
        channel_index: int = 0,
        validate_channel_id: bool = True,
        output_file: Path | None = None,
        iterator_callback: IteratorCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        chunk_size: int = 65536,
        fps: int | None = None,
    ) -> bytes | None:
        """
        Exports MP4 video from a given camera at a specific time.

        Start/End of video export are approximate. It may be +/- a few seconds.

        It is recommended to provide a output file or progress callback for larger
        video clips, otherwise the full video must be downloaded to memory before
        being written.

        Providing the `fps` parameter creates a "timelapse" export wtih the given FPS
        value. Protect app gives the options for 60x (fps=4), 120x (fps=8), 300x
        (fps=20), and 600x (fps=40).
        """
        if validate_channel_id and self._bootstrap is not None:
            camera = self._bootstrap.cameras[camera_id]
            try:
                camera.channels[channel_index]
            except IndexError as e:
                raise BadRequest from e

        params = {
            "camera": camera_id,
            "start": to_js_time(start),
            "end": to_js_time(end),
        }

        if fps is not None:
            params["fps"] = fps
            params["type"] = "timelapse"

        if channel_index == 3:
            params.update({"lens": 2})
        else:
            params.update({"channel": channel_index})

        path = "video/export"
        if (
            iterator_callback is None
            and progress_callback is None
            and output_file is None
        ):
            return await self.api_request_raw(
                path,
                params=params,
                raise_exception=False,
            )

        _LOGGER.debug(
            "Requesting camera video: %s%s %s", self.private_api_path, path, params
        )
        r = await self.request(
            "get",
            f"{self.private_api_path}{path}",
            auto_close=False,
            timeout=0,
            params=params,
        )
        if r.status != 200:
            await self._raise_for_status(r, True)

        if output_file is not None:
            async with aiofiles.open(output_file, "wb") as output:

                async def callback(total: int, chunk: bytes | None) -> None:
                    if iterator_callback is not None:
                        await iterator_callback(total, chunk)
                    if chunk is not None:
                        await output.write(chunk)

                await self._stream_response(r, chunk_size, callback, progress_callback)
        else:
            await self._stream_response(
                r,
                chunk_size,
                iterator_callback,
                progress_callback,
            )
        r.close()
        return None

    async def _get_image_with_retry(
        self,
        path: str,
        retry_timeout: int = RETRY_TIMEOUT,
        **kwargs: Any,
    ) -> bytes | None:
        """
        Retries image request until it returns or timesout. Used for event images like thumbnails and heatmaps.

        Note: thumbnails / heatmaps do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return None.
        """
        now = time.monotonic()
        timeout = now + retry_timeout
        data: bytes | None = None
        while data is None and now < timeout:
            data = await self.api_request_raw(path, raise_exception=False, **kwargs)
            if data is None:
                await asyncio.sleep(0.5)
                now = time.monotonic()

        return data

    async def get_event_thumbnail(
        self,
        thumbnail_id: str,
        width: int | None = None,
        height: int | None = None,
        retry_timeout: int = RETRY_TIMEOUT,
    ) -> bytes | None:
        """
        Gets given thumbanail from a given event.

        Thumbnail response is a JPEG image.

        Note: thumbnails / heatmaps do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return 404.
        """
        params: dict[str, Any] = {}

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        # old thumbnail URL use thumbnail ID, which is just `e-{event_id}`
        thumbnail_id = thumbnail_id.replace("e-", "")
        return await self._get_image_with_retry(
            f"events/{thumbnail_id}/thumbnail",
            params=params,
            retry_timeout=retry_timeout,
        )

    async def get_event_animated_thumbnail(
        self,
        thumbnail_id: str,
        width: int | None = None,
        height: int | None = None,
        *,
        speedup: int = 10,
        retry_timeout: int = RETRY_TIMEOUT,
    ) -> bytes | None:
        """
        Gets given animated thumbanil from a given event.

        Animated thumbnail response is a GIF image.

        Note: thumbnails / do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return 404.
        """
        params: dict[str, Any] = {
            "keyFrameOnly": "true",
            "speedup": speedup,
        }

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        # old thumbnail URL use thumbnail ID, which is just `e-{event_id}`
        thumbnail_id = thumbnail_id.replace("e-", "")
        return await self._get_image_with_retry(
            f"events/{thumbnail_id}/animated-thumbnail",
            params=params,
            retry_timeout=retry_timeout,
        )

    async def get_event_heatmap(
        self,
        heatmap_id: str,
        retry_timeout: int = RETRY_TIMEOUT,
    ) -> bytes | None:
        """
        Gets given heatmap from a given event.

        Heatmap response is a PNG image.

        Note: thumbnails / heatmaps do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return None.
        """
        # old heatmap URL use heatmap ID, which is just `e-{event_id}`
        heatmap_id = heatmap_id.replace("e-", "")
        return await self._get_image_with_retry(
            f"events/{heatmap_id}/heatmap",
            retry_timeout=retry_timeout,
        )

    async def get_event_smart_detect_track_raw(self, event_id: str) -> dict[str, Any]:
        """Gets raw Smart Detect Track for a Smart Detection"""
        return await self.api_request_obj(f"events/{event_id}/smartDetectTrack")

    async def get_event_smart_detect_track(self, event_id: str) -> SmartDetectTrack:
        """Gets raw Smart Detect Track for a Smart Detection"""
        data = await self.api_request_obj(f"events/{event_id}/smartDetectTrack")

        return SmartDetectTrack.from_unifi_dict(api=self, **data)

    async def update_device(
        self,
        model_type: ModelType,
        device_id: str,
        data: dict[str, Any],
    ) -> None:
        """
        Sends an update for a device back to UFP

        USE WITH CAUTION, all possible combinations of updating objects have not been fully tested.
        May have unexpected side effects.

        Tested updates have been added a methods on applicable devices.
        """
        await self.api_request(
            f"{model_type.value}s/{device_id}",
            method="patch",
            json=data,
        )

    async def update_nvr(self, data: dict[str, Any]) -> None:
        """
        Sends an update for main UFP NVR device

        USE WITH CAUTION, all possible combinations of updating objects have not been fully tested.
        May have unexpected side effects.

        Tested updates have been added a methods on applicable devices.
        """
        await self.api_request("nvr", method="patch", json=data)

    async def reboot_nvr(self) -> None:
        """Reboots NVR"""
        await self.api_request("nvr/reboot", method="post")

    async def reboot_device(self, model_type: ModelType, device_id: str) -> None:
        """Reboots an adopted device"""
        await self.api_request(f"{model_type.value}s/{device_id}/reboot", method="post")

    async def unadopt_device(self, model_type: ModelType, device_id: str) -> None:
        """Unadopt/Unmanage adopted device"""
        await self.api_request(f"{model_type.value}s/{device_id}", method="delete")

    async def adopt_device(self, model_type: ModelType, device_id: str) -> None:
        """Adopts a device"""
        key = model_type.devices_key
        data = await self.api_request_obj(
            "devices/adopt",
            method="post",
            json={key: {device_id: {}}},
        )

        if not data.get(key, {}).get(device_id, {}).get("adopted", False):
            raise BadRequest("Could not adopt device")

    async def close_lock(self, device_id: str) -> None:
        """Close doorlock (lock)"""
        await self.api_request(f"doorlocks/{device_id}/close", method="post")

    async def open_lock(self, device_id: str) -> None:
        """Open doorlock (unlock)"""
        await self.api_request(f"doorlocks/{device_id}/open", method="post")

    async def calibrate_lock(self, device_id: str) -> None:
        """
        Calibrate the doorlock.

        Door must be open and lock unlocked.
        """
        await self.api_request(
            f"doorlocks/{device_id}/calibrate",
            method="post",
            json={"auto": True},
        )

    async def play_speaker(
        self,
        device_id: str,
        *,
        volume: int | None = None,
        repeat_times: int | None = None,
        ringtone_id: str | None = None,
        track_no: int | None = None,
    ) -> None:
        """Plays chime tones on a chime"""
        data: dict[str, Any] | None = None
        if volume or repeat_times or ringtone_id or track_no:
            chime = self.bootstrap.chimes.get(device_id)
            if chime is None:
                raise BadRequest("Invalid chime ID %s", device_id)

            data = {
                "volume": volume or chime.volume,
                "repeatTimes": repeat_times or chime.repeat_times,
                "trackNo": track_no or chime.track_no,
            }
            if ringtone_id:
                data["ringtoneId"] = ringtone_id
                data.pop("trackNo", None)

        await self.api_request(
            f"chimes/{device_id}/play-speaker",
            method="post",
            json=data,
        )

    async def play_buzzer(self, device_id: str) -> None:
        """Plays chime tones on a chime"""
        await self.api_request(f"chimes/{device_id}/play-buzzer", method="post")

    async def set_light_is_led_force_on(
        self, device_id: str, is_led_force_on: bool
    ) -> None:
        """Sets isLedForceOn for light."""  # workaround because forceOn doesnt work via websocket
        await self.api_request(
            f"lights/{device_id}",
            method="patch",
            json={"lightOnSettings": {"isLedForceOn": is_led_force_on}},
        )

    async def clear_tamper_sensor(self, device_id: str) -> None:
        """Clears tamper status for sensor"""
        await self.api_request(f"sensors/{device_id}/clear-tamper-flag", method="post")

    async def _get_versions_from_api(
        self,
        url: str,
        package: str = "unifi-protect",
    ) -> set[Version]:
        session = await self.get_session()
        versions: set[Version] = set()

        try:
            async with session.get(url) as response:
                is_package = False
                for line in (await response.text()).split("\n"):
                    if line.startswith("Package: "):
                        is_package = False
                        if line == f"Package: {package}":
                            is_package = True

                    if is_package and line.startswith("Version: "):
                        versions.add(Version(line.split(": ")[-1]))
        except (
            TimeoutError,
            asyncio.TimeoutError,
            aiohttp.ServerDisconnectedError,
            client_exceptions.ClientError,
        ) as err:
            raise NvrError(f"Error packages from {url}: {err}") from err

        return versions

    async def relative_move_ptz_camera(
        self,
        device_id: str,
        *,
        pan: float,
        tilt: float,
        pan_speed: int = 10,
        tilt_speed: int = 10,
        scale: int = 0,
    ) -> None:
        """
        Move PTZ Camera relatively.

        Pan/tilt values vary from camera to camera, but for G4 PTZ:
            * Pan values range from 1 (0°) to 35200 (360°/0°).
            * Tilt values range from 1 (-20°) to 9777 (90°).

        Relative positions cannot move more then 4095 units in either direction at a time.

        Camera objects have ptz values in feature flags and the methods on them provide better
        control.
        """
        data = {
            "type": "relative",
            "payload": {
                "panPos": pan,
                "tiltPos": tilt,
                "panSpeed": pan_speed,
                "tiltSpeed": tilt_speed,
                "scale": scale,
            },
        }

        await self.api_request(f"cameras/{device_id}/move", method="post", json=data)

    async def center_ptz_camera(
        self,
        device_id: str,
        *,
        x: int,
        y: int,
        z: int,
    ) -> None:
        """
        Center PTZ Camera on point in viewport.

        x, y, z values range from 0 to 1000.

        x, y are relative coords for the current viewport:
            * (0, 0) is top left
            * (500, 500) is the center
            * (1000, 1000) is the bottom right

        z value is zoom, but since it is capped at 1000, probably better to use `ptz_zoom_camera`.
        """
        data = {
            "type": "center",
            "payload": {
                "x": x,
                "y": y,
                "z": z,
            },
        }

        await self.api_request(f"cameras/{device_id}/move", method="post", json=data)

    async def zoom_ptz_camera(
        self,
        device_id: str,
        *,
        zoom: float,
        speed: int = 10,
    ) -> None:
        """
        Zoom PTZ Camera.

        Zoom levels vary from camera to camera, but for G4 PTZ it goes from 0 (1x) to 2010 (22x).

        Zoom speed does not seem to do much, if anything.

        Camera objects have ptz values in feature flags and the methods on them provide better
        control.
        """
        data = {
            "type": "zoom",
            "payload": {
                "zoomPos": zoom,
                "zoomSpeed": speed,
            },
        }

        await self.api_request(f"cameras/{device_id}/move", method="post", json=data)

    async def get_position_ptz_camera(self, device_id: str) -> PTZPosition:
        """Get current PTZ camera position."""
        pos = await self.api_request_obj(f"cameras/{device_id}/ptz/position")
        return PTZPosition(**pos)

    async def goto_ptz_camera(self, device_id: str, *, slot: int = -1) -> None:
        """
        Goto PTZ slot position.

        -1 is Home slot.
        """
        await self.api_request(f"cameras/{device_id}/ptz/goto/{slot}", method="post")

    async def create_preset_ptz_camera(self, device_id: str, *, name: str) -> PTZPreset:
        """Create PTZ Preset for camera based on current camera settings."""
        preset = await self.api_request_obj(
            f"cameras/{device_id}/ptz/preset",
            method="post",
            json={"name": name},
        )

        return PTZPreset(**preset)

    async def get_presets_ptz_camera(self, device_id: str) -> list[PTZPreset]:
        """Get PTZ Presets for camera."""
        presets = await self.api_request(f"cameras/{device_id}/ptz/preset")

        if not presets:
            return []

        presets = cast(list[dict[str, Any]], presets)
        return [PTZPreset(**p) for p in presets]

    async def delete_preset_ptz_camera(self, device_id: str, *, slot: int) -> None:
        """Delete PTZ preset for camera."""
        await self.api_request(
            f"cameras/{device_id}/ptz/preset/{slot}",
            method="delete",
        )

    async def get_home_ptz_camera(self, device_id: str) -> PTZPreset:
        """Get PTZ home preset (-1)."""
        preset = await self.api_request_obj(f"cameras/{device_id}/ptz/home")
        return PTZPreset(**preset)

    async def set_home_ptz_camera(self, device_id: str) -> PTZPreset:
        """Set PTZ home preset (-1) to current position."""
        preset = await self.api_request_obj(
            f"cameras/{device_id}/ptz/home",
            method="post",
        )
        return PTZPreset(**preset)

    async def create_api_key(self, name: str) -> str:
        """Create an API key with the given name and return the full API key."""
        if not name:
            raise BadRequest("API key name cannot be empty")

        response = await self.api_request(
            api_path="/proxy/users/api/v2",
            url="/user/self/keys",
            method="post",
            json={"name": name},
        )

        if (
            not isinstance(response, dict)
            or "data" not in response
            or not isinstance(response["data"], dict)
            or "full_api_key" not in response["data"]
        ):
            raise BadRequest("Failed to create API key")

        return response["data"]["full_api_key"]

    def set_api_key(self, api_key: str) -> None:
        """Set the API key for the NVR."""
        if not api_key:
            raise BadRequest("API key cannot be empty")

        self._api_key = api_key

    def is_api_key_set(self) -> bool:
        """Check if the API key is set."""
        return bool(self._api_key)

    async def get_meta_info(self) -> MetaInfo:
        """Get metadata about the NVR."""
        data = await self.api_request(
            url="/v1/meta/info",
            public_api=True,
        )
        if not isinstance(data, dict):
            raise NvrError("Failed to retrieve meta info from public API")
        return MetaInfo(**data)
