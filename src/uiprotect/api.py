"""UniFi Protect Server Wrapper."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import random
import re
import sys
import time
import warnings
from datetime import datetime, timedelta
from functools import partial
from http import HTTPStatus, cookies
from http.cookies import Morsel, SimpleCookie
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Self, TypedDict, cast
from urllib.parse import SplitResult, quote

import aiofiles
import aiohttp
import orjson
from aiofiles import os as aos
from aiohttp import ClientResponse, CookieJar, client_exceptions
from aiozoneinfo import async_get_time_zone
from platformdirs import user_cache_dir, user_config_dir
from yarl import URL

from uiprotect.data.base import ProtectBaseObject
from uiprotect.data.convert import list_from_unifi_list
from uiprotect.data.nvr import MetaInfo
from uiprotect.data.user import Keyring, Keyrings, UlpUser, UlpUsers

from ._compat import cached_property
from .data import (
    NVR,
    ArmProfile,
    Bootstrap,
    Bridge,
    Camera,
    ChannelQuality,
    Doorlock,
    Event,
    EventCategories,
    EventType,
    Fob,
    Light,
    LinkStation,
    Liveview,
    ModelType,
    NvrArmMode,
    NvrArmModeStatus,
    OsdOverlayLocation,
    ProtectAdoptableDeviceModel,
    ProtectModel,
    PublicArmScheduleDict,
    PublicBootstrap,
    PublicBridge,
    PublicFile,
    PublicHdrMode,
    PublicLiveview,
    PublicLiveviewSlotDict,
    PublicNVR,
    PublicSensorAlarmSettings,
    PublicSensorHumiditySettings,
    PublicSensorLightSettings,
    PublicSensorMotionSettings,
    PublicSensorTemperatureSettings,
    PublicUlpUser,
    PublicUser,
    PublicViewer,
    Relay,
    Sensor,
    Siren,
    SmartDetectAudioType,
    SmartDetectObjectType,
    SmartDetectTrack,
    Speaker,
    Version,
    VideoMode,
    Viewer,
    WSAction,
    WSPacket,
    WSSubscriptionMessage,
    create_from_unifi_dict,
)
from .data.devices import AiPort, Chime
from .data.types import (
    AssetFileType,
    IteratorCallback,
    ProgressCallback,
    PTZPatrol,
    PTZPreset,
    SirenDuration,
)
from .exceptions import BadRequest, GlobalAlarmManagerError, NotAuthorized, NvrError
from .stream import TalkbackSession

if TYPE_CHECKING:
    from .events.dispatcher import EventDispatcher
from .utils import (
    decode_token_cookie,
    format_host_for_url,
    get_response_reason,
    ip_from_host,
    pybool_to_json_bool,
    set_debug,
    to_js_time,
    utc_now,
)
from .websocket import Websocket, WebsocketState

if TYPE_CHECKING:
    from collections.abc import Callable

    from uiprotect.data.devices import LightDeviceSettings, LightModeSettings

    from .data.base import ProtectModelWithId
    from .events import EventChange, ProtectEvent

if "partitioned" not in cookies.Morsel._reserved:  # type: ignore[attr-defined]
    # See: https://github.com/python/cpython/issues/112713
    cookies.Morsel._reserved["partitioned"] = "partitioned"  # type: ignore[attr-defined]
    cookies.Morsel._flags.add("partitioned")  # type: ignore[attr-defined]


async def _async_warm_nvr_timezone(nvr_data: dict[str, Any]) -> None:
    """
    Warm zoneinfo's cache for ``nvr_data["timezone"]`` off the event loop.

    ``NVR.unifi_dict_conversions`` constructs ``ZoneInfo(name)`` synchronously
    during parse; first construction does an ``os.stat`` lookup that blocks
    the loop. Awaiting :func:`async_get_time_zone` here primes ZoneInfo's
    internal cache so the later sync construction is a free hit.
    """
    tz_name = nvr_data.get("timezone")
    if isinstance(tz_name, str):
        await async_get_time_zone(tz_name)


class LightPatchRequest(TypedDict, total=False):
    """Type for PATCH /v1/lights/{id} request body."""

    name: str
    isLightForceEnabled: bool
    lightModeSettings: dict[str, Any]
    lightDeviceSettings: dict[str, Any]


class PublicApiChimeRingSettingRequest(TypedDict):
    """Type for ringSettings items in PATCH /v1/chimes/{id} request body (Public API)."""

    cameraId: str
    repeatTimes: int
    ringtoneId: NotRequired[str | None]
    volume: int


class PublicApiChimePatchRequest(TypedDict, total=False):
    """Type for PATCH /v1/chimes/{id} request body (Public API)."""

    name: str
    cameraIds: list[str]
    ringSettings: list[PublicApiChimeRingSettingRequest]


class CameraPublicApiLcdMessageRequest(TypedDict, total=False):
    """
    Type for lcdMessage in PATCH /v1/cameras/{id} request body (Public API).

    Per the integration spec, ``type`` is always required.  ``text`` is required
    for CUSTOM_MESSAGE and IMAGE; ``resetAt`` is optional for all variants (UNIX
    timestamp in ms; omit to use the NVR default, pass ``None`` for "forever").
    """

    type: str
    text: str
    resetAt: int | None


TOKEN_COOKIE_MAX_EXP_SECONDS = 60

# how many seconds before the bootstrap is refreshed from Protect
DEVICE_UPDATE_INTERVAL = 900
# retry timeout for thumbnails/heatmaps
RETRY_TIMEOUT = 10

# Retry configuration constants
RETRY_DEFAULT_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 30.0
RETRY_EXPONENTIAL_BASE = 2.0
RETRY_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

TYPES_BUG_MESSAGE = """There is currently a bug in UniFi Protect that makes `start` / `end` not work if `types` is not provided. This means uiprotect has to iterate over all of the events matching the filters provided to return values.

If your Protect instance has a lot of events, this request will take much longer then expected. It is recommended adding additional filters to speed the request up."""


_LOGGER = logging.getLogger(__name__)
_COOKIE_RE = re.compile(r"^set-cookie: ", re.IGNORECASE)


# Sentinel used by ``update_viewer_public`` to distinguish "do not change" (the
# default) from "explicitly set to null". The viewer's ``liveview`` wire field
# is legitimately nullable, so a plain ``None`` cannot serve both meanings.
# A dedicated singleton type keeps the sentinel out of ``Any`` so callers
# can't accidentally smuggle it through the typed surface.
class _UnsetType:
    # ``Self`` rather than ``_UnsetType`` so the singleton stays correctly
    # typed under any (currently hypothetical) subclass — also satisfies PYI034.
    _instance: Self | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET: _UnsetType = _UnsetType()


# Substring present in the 400 error reason returned by the NVR when the
# alarm-manager endpoint is *not local* (i.e. set to Global instead of Local).
# Matched case-insensitively so minor server-side capitalisation changes are
# tolerated. Extracted as a constant to make the match visible and easy to update.
_GLOBAL_ALARM_MANAGER_REASON = "global alarm manager"


def _log_or_raise(label: str, exc: BaseException) -> None:
    """
    Log expected endpoint-unavailable errors; re-raise anything unexpected.

    ``NvrError`` and ``BadRequest`` are treated as expected failures for
    optional Public API endpoints (e.g., alarm-manager, sirens, relays) that
    may not exist on all systems.  Any other exception type is re-raised
    immediately — the caller must handle it (e.g. ``CancelledError``,
    validation errors from an updated server payload).
    """
    if isinstance(exc, (BadRequest, NvrError)):
        _LOGGER.debug("%s endpoint unavailable: %s", label, exc)
    else:
        raise exc


NFC_FINGERPRINT_SUPPORT_VERSION = Version("5.1.57")

# Minimum interval (seconds) between two automatic public-bootstrap resyncs
# triggered by devices-websocket reconnects. Guards against reconnect storms
# on flaky networks or controller reboots.
PUBLIC_RESYNC_MIN_INTERVAL = 10.0


def calculate_retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """
    Calculate delay before next retry attempt with exponential backoff and jitter.

    Args:
        attempt: Current retry attempt number (0-based).
        retry_after: Optional Retry-After header value in seconds.

    Returns:
        Delay in seconds before next retry.

    """
    if retry_after is not None and retry_after > 0:
        delay = min(retry_after, RETRY_MAX_DELAY)
        # Only add positive jitter when server specified a delay
        jitter_range = delay * 0.25
        delay += random.uniform(0, jitter_range)  # noqa: S311
    else:
        delay = RETRY_BASE_DELAY * (RETRY_EXPONENTIAL_BASE**attempt)
        delay = min(delay, RETRY_MAX_DELAY)
        # Full jitter (±25% of delay) for calculated delays
        jitter_range = delay * 0.25
        delay += random.uniform(-jitter_range, jitter_range)  # noqa: S311

    # Ensure delay stays within bounds [0.1, RETRY_MAX_DELAY]
    return max(0.1, min(delay, RETRY_MAX_DELAY))


def parse_retry_after(response: ClientResponse) -> float | None:
    """
    Parse Retry-After header from response.

    Args:
        response: HTTP response object.

    Returns:
        Retry delay in seconds, or None if header not present/parseable.

    """
    retry_after = response.headers.get("Retry-After")
    if retry_after is None:
        return None

    try:
        # Retry-After can be seconds or HTTP-date, we only handle seconds
        return float(retry_after)
    except ValueError:
        _LOGGER.debug("Could not parse Retry-After header: %s", retry_after)
        return None


# =============================================================================
# Helper Functions
# =============================================================================


def get_user_hash(host: str, username: str) -> str:
    session = hashlib.sha256()
    session.update(host.encode("utf8"))
    session.update(username.encode("utf8"))
    return session.hexdigest()


class RTSPSStreams(ProtectBaseObject):
    """RTSPS stream URLs for a camera."""

    model_config = {"extra": "allow"}
    # Intentionally no variables like 'high', 'medium', 'low' are defined here.
    # The API naming appears inconsistent - what's called "quality" might actually be "channels".
    # Besides standard qualities (high/medium/low), there are special cases like "package" for doorbells
    # and unclear implementation for 180° cameras with dual sensors. Dynamic handling via __pydantic_extra__ is safer.

    def get_stream_url(self, quality: str) -> str | None:
        """Get stream URL for a specific quality level."""
        return getattr(self, quality, None)

    def get_available_stream_qualities(self) -> list[str]:
        """
        List available RTSPS quality keys from the server.

        Returns raw strings; may include values not in :class:`ChannelQuality`.
        """
        if self.__pydantic_extra__ is None:
            return []
        return list(self.__pydantic_extra__.keys())

    def get_active_stream_qualities(self) -> list[str]:
        """Get list of currently active RTSPS stream quality levels (only those with stream URLs)."""
        if self.__pydantic_extra__ is None:
            return []
        return [
            key
            for key, value in self.__pydantic_extra__.items()
            if isinstance(value, str) and value is not None
        ]

    def get_inactive_stream_qualities(self) -> list[str]:
        """Get list of inactive RTSPS stream quality levels (supported but not currently active)."""
        if self.__pydantic_extra__ is None:
            return []
        return [
            key
            for key, value in self.__pydantic_extra__.items()
            if not (isinstance(value, str) and value is not None)
        ]


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
    _max_retries: int = RETRY_DEFAULT_ATTEMPTS

    headers: dict[str, str] | None = None
    _private_websocket: Websocket | None = None
    _events_websocket: Websocket | None = None
    _devices_websocket: Websocket | None = None
    _public_resync_task: asyncio.Task[None] | None = None

    private_api_path: str = "/proxy/protect/api/"
    public_api_path: str = "/proxy/protect/integration"
    private_ws_path: str = "/proxy/protect/ws/updates"
    events_ws_path: str = "/proxy/protect/integration/v1/subscribe/events"
    devices_ws_path: str = "/proxy/protect/integration/v1/subscribe/devices"

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
        max_retries: int = RETRY_DEFAULT_ATTEMPTS,
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
        self._max_retries = max_retries

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
        formatted_host = format_host_for_url(self._host)

        if self._port != 443:
            self._url = URL(f"https://{formatted_host}:{self._port}")
            self._ws_url = URL(
                f"wss://{formatted_host}:{self._port}{self.private_ws_path}"
            )
            self._events_ws_url = URL(
                f"https://{formatted_host}:{self._port}{self.events_ws_path}"
            )
            self._devices_ws_url = URL(
                f"https://{formatted_host}:{self._port}{self.devices_ws_path}"
            )
        else:
            self._url = URL(f"https://{formatted_host}")
            self._ws_url = URL(f"wss://{formatted_host}{self.private_ws_path}")
            self._events_ws_url = URL(f"https://{formatted_host}{self.events_ws_path}")
            self._devices_ws_url = URL(
                f"https://{formatted_host}{self.devices_ws_path}"
            )

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
    def events_ws_url(self) -> str:
        """Get Events Websocket URL."""
        return str(self._events_ws_url)

    @property
    def devices_ws_url(self) -> str:
        """Get Devices Websocket URL."""
        return str(self._devices_ws_url)

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

    async def _auth_public_api_websocket(
        self, force: bool = False
    ) -> dict[str, str] | None:
        """Authenticate for Public API Websocket."""
        if self._api_key is None:
            raise NotAuthorized("API key is required for public API WebSocket")

        return {"X-API-KEY": self._api_key}

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

    def _get_events_websocket(self) -> Websocket:
        """Gets or creates current Events Websocket."""
        if self._events_websocket is None:
            self._events_websocket = Websocket(
                lambda: self._events_ws_url,
                self._auth_public_api_websocket,
                lambda: None,
                self.get_public_api_session,
                self._process_events_ws_message,
                self._on_events_websocket_state_change,
                verify=self._verify_ssl,
                timeout=self._ws_timeout,
                receive_timeout=self._ws_receive_timeout,
            )
        return self._events_websocket

    def _get_devices_websocket(self) -> Websocket:
        """Gets or creates current Devices Websocket."""
        if self._devices_websocket is None:
            self._devices_websocket = Websocket(
                lambda: self._devices_ws_url,
                self._auth_public_api_websocket,
                lambda: None,
                self.get_public_api_session,
                self._process_devices_ws_message,
                self._on_devices_websocket_state_change,
                verify=self._verify_ssl,
                timeout=self._ws_timeout,
                receive_timeout=self._ws_receive_timeout,
            )
        return self._devices_websocket

    def _update_bootstrap_soon(self) -> None:
        """Update bootstrap soon."""
        _LOGGER.debug("Updating bootstrap soon")
        # Force the next bootstrap update
        # since the lastUpdateId is not valid anymore
        if self._update_task and not self._update_task.done():
            return
        self._update_task = asyncio.create_task(self.update())

    async def close_session(self) -> None:
        """Closing and deletes all client sessions."""
        await self._cancel_update_task()
        await self._cancel_public_resync_task()
        if self._session is not None:
            await self._session.close()
            self._session = None
            self._loaded_session = False
        if self._public_api_session is not None:
            await self._public_api_session.close()
            self._public_api_session = None

    async def close_public_api_session(self) -> None:
        """Closing and deletes public API client session."""
        if self._public_api_session is not None:
            await self._public_api_session.close()
            self._public_api_session = None

    async def _cancel_update_task(self) -> None:
        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task
            self._update_task = None

    async def _cancel_public_resync_task(self) -> None:
        # If a subclass tracks queued follow-up resync work, clear it before
        # cancellation so shutdown cannot re-schedule a new task in a
        # ``finally`` block.
        self._public_resync_pending = False
        if self._public_resync_task is not None:
            self._public_resync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._public_resync_task
            self._public_resync_task = None

    def set_header(self, key: str, value: str | None) -> None:
        """Set header."""
        self.headers = self.headers or {}
        if value is None:
            self.headers.pop(key, None)
        else:
            self.headers[key] = value

    async def _do_request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        request_url: URL,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Execute a single HTTP request with disconnect retry."""
        last_err: aiohttp.ServerDisconnectedError | None = None
        for _attempt in range(2):
            try:
                req_context = session.request(
                    method,
                    request_url,
                    headers=headers,
                    **kwargs,
                )
                response = await req_context.__aenter__()
                try:
                    await self._update_last_token_cookie(response)
                except Exception:
                    response.release()
                    raise
                return response
            except aiohttp.ServerDisconnectedError as err:
                # If the server disconnected, try again
                # since HTTP/1.1 allows the server to disconnect at any time
                last_err = err
            except client_exceptions.ClientError as err:
                raise NvrError(
                    f"Error requesting data from {self._host}: {err}",
                ) from err

        raise NvrError(
            f"Error requesting data from {self._host}: {last_err}",
        ) from last_err

    async def request(
        self,
        method: str,
        url: str,
        require_auth: bool = False,
        auto_close: bool = True,
        public_api: bool = False,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """
        Make a request to UniFi Protect with automatic retry on transient errors.

        Automatically retries requests that receive 408, 429, 500, 502, 503,
        or 504 status codes using exponential backoff.
        """
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

        # First attempt (always happens, even with max_retries=0)
        response = await self._do_request(
            session, method, request_url, headers, **kwargs
        )

        # Retry loop for transient errors
        for retry_attempt in range(self._max_retries):
            if response.status not in RETRY_STATUS_CODES:
                break

            retry_after = parse_retry_after(response)
            response.release()
            delay = calculate_retry_delay(retry_attempt, retry_after)
            # Escalate log level: DEBUG (1st) → INFO (2nd) → WARNING (3rd+)
            log_level = (logging.DEBUG, logging.INFO, logging.WARNING)[
                min(retry_attempt, 2)
            ]
            _LOGGER.log(
                log_level,
                "Request to %s returned %s, retrying in %.2f seconds (attempt %d/%d)",
                request_url,
                response.status,
                delay,
                retry_attempt + 1,
                self._max_retries,
            )
            await asyncio.sleep(delay)
            response = await self._do_request(
                session, method, request_url, headers, **kwargs
            )

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
            # Check for successful status codes (2xx range)
            if not (200 <= response.status < 300):
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

        # Success status codes (2xx) should not raise exceptions
        if 200 <= status < 300:
            return

        if raise_exception:
            if status in {
                HTTPStatus.UNAUTHORIZED.value,
                HTTPStatus.FORBIDDEN.value,
            }:
                raise NotAuthorized(msg % (url, status, reason))
            if status == HTTPStatus.TOO_MANY_REQUESTS.value:
                _LOGGER.debug("Too many requests - Login is rate limited: %s", response)
                raise NvrError(msg % (url, status, reason))
            # Handle 400 Bad Request specifically; check for global alarm
            # manager error (returned when alarm-manager is not local, e.g.
            # set to global instead), but treat other 4xx as generic bad request.
            if status == HTTPStatus.BAD_REQUEST.value:
                if _GLOBAL_ALARM_MANAGER_REASON in reason.lower():
                    raise GlobalAlarmManagerError(msg % (url, status, reason))
                raise BadRequest(msg % (url, status, reason))
            # Other 4xx client errors also raise BadRequest
            if (
                status > HTTPStatus.BAD_REQUEST.value
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

            csrf_token = response.headers.get("x-csrf-token")
            if csrf_token:
                self.set_header("x-csrf-token", csrf_token)

            cookie_header = response.headers.get("set-cookie", "")
            self.set_header("cookie", cookie_header)
            self._is_authenticated = True

            # parse and store the cookie for session persistence
            if self.store_sessions and cookie_header:
                # extract cookie from header to save in session file
                cookie = SimpleCookie(cookie_header)
                if cookie:
                    for cookie_obj in cookie.values():
                        self._last_token_cookie = cookie_obj
                        await self._update_auth_config(cookie_obj)
                        break  # auth response only contains single cookie (TOKEN or UOS_TOKEN)

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

        # Only mark as authenticated if we have both cookie and CSRF token
        csrf_token = session.get("csrf")
        if not csrf_token:
            _LOGGER.debug("Session found but missing CSRF token, will re-authenticate")
            return None

        self._is_authenticated = True
        self.set_header("cookie", cookie_value)
        self.set_header("x-csrf-token", csrf_token)
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

        token_expires_at = cast("int", self._last_token_cookie_decode["exp"])
        max_expire_time = time.time() + TOKEN_COOKIE_MAX_EXP_SECONDS

        return token_expires_at >= max_expire_time

    async def clear_session(self) -> None:
        """Clears stored session for this specific user/host combination."""
        if not self.store_sessions:
            return

        config: dict[str, Any] = {}
        session_hash = get_user_hash(str(self._url), self._username)
        try:
            async with aiofiles.open(self.config_file, "rb") as f:
                config_data = await f.read()
                if config_data:
                    try:
                        config = orjson.loads(config_data)
                    except orjson.JSONDecodeError:
                        _LOGGER.warning("Invalid config file, ignoring.")
                        return
        except FileNotFoundError:
            return

        if "sessions" in config and session_hash in config["sessions"]:
            del config["sessions"][session_hash]

            async with aiofiles.open(self.config_file, "wb") as f:
                await f.write(orjson.dumps(config, option=orjson.OPT_INDENT_2))

            _LOGGER.debug("Cleared session for %s", session_hash)

            # Clear authentication state only when session was actually removed
            self._is_authenticated = False
            self._last_token_cookie = None
            self._last_token_cookie_decode = None

    async def clear_all_sessions(self) -> None:
        """Clears all stored sessions from the config file."""
        if not self.store_sessions:
            return

        try:
            await aos.remove(self.config_file)
        except FileNotFoundError:
            # File already gone - either never existed or removed by another process
            return

        # If we get here, the file was successfully removed (no exception raised)
        _LOGGER.debug("Cleared all sessions from config file")

        # Clear authentication state only after successful deletion
        self._is_authenticated = False
        self._last_token_cookie = None
        self._last_token_cookie_decode = None

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
        if self._events_websocket:
            events_websocket = self._get_events_websocket()
            events_websocket.stop()
            await events_websocket.wait_closed()
            self._events_websocket = None
        if self._devices_websocket:
            devices_websocket = self._get_devices_websocket()
            devices_websocket.stop()
            await devices_websocket.wait_closed()
            self._devices_websocket = None

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        raise NotImplementedError

    def _process_events_ws_message(self, msg: aiohttp.WSMessage) -> None:
        """Process events websocket message - to be implemented by subclass."""
        raise NotImplementedError

    def _process_devices_ws_message(self, msg: aiohttp.WSMessage) -> None:
        """Process devices websocket message - to be implemented by subclass."""
        raise NotImplementedError

    def _get_last_update_id(self) -> str | None:
        raise NotImplementedError

    async def update(self) -> Bootstrap:
        raise NotImplementedError

    def _on_websocket_state_change(self, state: WebsocketState) -> None:
        """Websocket state changed."""
        _LOGGER.debug("Websocket state changed: %s", state)

    def _on_events_websocket_state_change(self, state: WebsocketState) -> None:
        """Events websocket state changed."""
        _LOGGER.debug("Events websocket state changed: %s", state)

    def _on_devices_websocket_state_change(self, state: WebsocketState) -> None:
        """Devices websocket state changed."""
        _LOGGER.debug("Devices websocket state changed: %s", state)


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
    # ``None`` means "inherit ``_subscribed_models``"; an explicit (possibly
    # empty) set overrides the global filter for that websocket. An empty set
    # therefore means "allow all models" — matching the private-WS behaviour.
    _events_ws_subscribed_models: set[ModelType] | None
    _devices_ws_subscribed_models: set[ModelType] | None
    _ignore_stats: bool
    _ws_subscriptions: list[Callable[[WSSubscriptionMessage], None]]
    _events_ws_subscriptions: list[Callable[[WSSubscriptionMessage], None]]
    _devices_ws_subscriptions: list[Callable[[WSSubscriptionMessage], None]]
    _ws_state_subscriptions: list[Callable[[WebsocketState], None]]
    _events_ws_state_subscriptions: list[Callable[[WebsocketState], None]]
    _devices_ws_state_subscriptions: list[Callable[[WebsocketState], None]]
    _bootstrap: Bootstrap | None = None
    _public_bootstrap: PublicBootstrap | None = None
    # True after the first time the devices WS transitions to CONNECTED; used
    # to distinguish the *initial* connect from a *reconnect*. Only the
    # latter triggers an automatic `update_public()` resync.
    _devices_ws_has_been_connected: bool = False
    # Monotonic timestamp of the last successful/attempted reconnect resync,
    # used to debounce a flapping websocket into a single refresh.
    _last_public_resync: float = 0.0
    # Set when another reconnect happens while a public resync task is
    # still running; consumed in ``_resync_public_bootstrap`` to run one
    # follow-up refresh.
    _public_resync_pending: bool = False
    _last_update_dt: datetime | None = None
    _connection_host: IPv4Address | IPv6Address | str | None = None
    # Lazy dispatcher; ``subscribe_events`` materialises it.
    _event_dispatcher: EventDispatcher | None = None
    # Internal events-WS adapter unsubscribe; populated while the typed
    # ``subscribe_events`` callback list is non-empty.
    _event_ws_adapter_unsub: Callable[[], None] | None = None
    # Monotonic timestamp of the last "REMOVE for unknown event" INFO log;
    # throttled so a burst of unknown-id removes does not flood the log.
    _events_remove_unknown_last_log: float = 0.0
    # Non-throttled running total of unknown-id REMOVE frames. The INFO log is
    # rate-limited, so this counter keeps a sustained cache/server desync
    # observable even when individual lines are suppressed.
    _events_remove_unknown_count: int = 0

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
        events_ws_subscribed_models: set[ModelType] | None = None,
        devices_ws_subscribed_models: set[ModelType] | None = None,
        ignore_stats: bool = False,
        ignore_unadopted: bool = True,
        debug: bool = False,
        ws_receive_timeout: int | None = None,
        max_retries: int = RETRY_DEFAULT_ATTEMPTS,
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
            max_retries=max_retries,
        )

        self._minimum_score = minimum_score
        self._subscribed_models = subscribed_models or set()
        # Preserve ``None`` vs. empty-set distinction: ``None`` inherits from
        # ``_subscribed_models``; an explicit empty set means "allow all".
        self._events_ws_subscribed_models = events_ws_subscribed_models
        self._devices_ws_subscribed_models = devices_ws_subscribed_models
        self._ignore_stats = ignore_stats
        self._ws_subscriptions = []
        self._events_ws_subscriptions = []
        self._devices_ws_subscriptions = []
        self._ws_state_subscriptions = []
        self._events_ws_state_subscriptions = []
        self._devices_ws_state_subscriptions = []
        self._event_dispatcher = None
        self.ignore_unadopted = ignore_unadopted
        self._update_lock = asyncio.Lock()

        if override_connection_host:
            self._connection_host = self._host

        if debug:
            set_debug()

    def _set_connection_host_from_bootstrap(self) -> None:
        """
        Set connection host from bootstrap NVR hosts (sync).

        NOTE: Must stay in sync with _async_set_connection_host_from_bootstrap().
        Sync version for property getter, async version for update() method.
        """
        index = 0
        try:
            index = self.bootstrap.nvr.hosts.index(self._host)
        except ValueError:
            try:
                host = ip_address(self._host)
                with contextlib.suppress(ValueError):
                    index = self.bootstrap.nvr.hosts.index(host)
            except ValueError:
                pass

        self._connection_host = self.bootstrap.nvr.hosts[index]

    async def _async_set_connection_host_from_bootstrap(
        self,
        bootstrap: Bootstrap,
    ) -> None:
        """
        Set connection host from bootstrap NVR hosts (async).

        NOTE: Must stay in sync with _set_connection_host_from_bootstrap().
        Async version allows DNS resolution via ip_from_host().
        """
        index = 0
        try:
            index = bootstrap.nvr.hosts.index(self._host)
        except ValueError:
            try:
                host_ip = await ip_from_host(self._host)
                index = bootstrap.nvr.hosts.index(host_ip)
            except ValueError:
                pass

        self._connection_host = bootstrap.nvr.hosts[index]

    @cached_property
    def bootstrap(self) -> Bootstrap:
        if self._bootstrap is None:
            raise BadRequest("Client not initialized, run `update` first")

        return self._bootstrap

    @property
    def public_bootstrap(self) -> PublicBootstrap:
        """
        In-memory cache of Public Integration API resources.

        Must be populated via :meth:`update_public` first; raises
        :class:`BadRequest` otherwise. This is a conscious mirror of
        :attr:`bootstrap` so that merely *reading* the property never changes
        WS-handler semantics (which keys off ``_public_bootstrap is not
        None``).
        """
        if self._public_bootstrap is None:
            raise BadRequest(
                "Public bootstrap not initialized, run `update_public` first"
            )
        return self._public_bootstrap

    @property
    def has_public_bootstrap(self) -> bool:
        """Whether :meth:`update_public` has been called at least once."""
        return self._public_bootstrap is not None

    @property
    def connection_host(self) -> IPv4Address | IPv6Address | str:
        """Connection host to use for generating RTSP URLs."""
        if self._connection_host is None:
            self._set_connection_host_from_bootstrap()

        assert self._connection_host is not None
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
                    cast("list[Keyring]", list_from_unifi_list(self, keyrings))
                )
                bootstrap.ulp_users = UlpUsers.from_list(
                    cast("list[UlpUser]", list_from_unifi_list(self, ulp_users))
                )
            self.__dict__.pop("bootstrap", None)
            self._bootstrap = bootstrap

            # Set connection host if not set via override_connection_host
            if self._connection_host is None:
                await self._async_set_connection_host_from_bootstrap(bootstrap)

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

    def emit_events_message(self, msg: WSSubscriptionMessage) -> None:
        """Emit message to all events subscriptions."""
        if _LOGGER.isEnabledFor(logging.DEBUG):
            if msg.new_obj is not None:
                _LOGGER.debug(
                    "emitting events message: %s:%s:%s:%s",
                    msg.action,
                    msg.new_obj.model,
                    msg.new_obj.id,
                    list(msg.changed_data),
                )
            elif msg.old_obj is not None:
                _LOGGER.debug(
                    "emitting events message: %s:%s:%s",
                    msg.action,
                    msg.old_obj.model,
                    msg.old_obj.id,
                )
            else:
                _LOGGER.debug("emitting events message: %s", msg.action)

        for sub in self._events_ws_subscriptions:
            try:
                sub(msg)
            except Exception:
                _LOGGER.exception("Exception while running events subscription handler")

    def emit_devices_message(self, msg: WSSubscriptionMessage) -> None:
        """Emit message to all devices subscriptions."""
        if _LOGGER.isEnabledFor(logging.DEBUG):
            if msg.new_obj is not None:
                _LOGGER.debug(
                    "emitting devices message: %s:%s:%s:%s",
                    msg.action,
                    msg.new_obj.model,
                    msg.new_obj.id,
                    list(msg.changed_data),
                )
            elif msg.old_obj is not None:
                _LOGGER.debug(
                    "emitting devices message: %s:%s:%s",
                    msg.action,
                    msg.old_obj.model,
                    msg.old_obj.id,
                )
            else:
                _LOGGER.debug("emitting devices message: %s", msg.action)

        for sub in self._devices_ws_subscriptions:
            try:
                sub(msg)
            except Exception:
                _LOGGER.exception(
                    "Exception while running devices subscription handler"
                )

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

    def _process_events_ws_message(self, msg: aiohttp.WSMessage) -> None:
        """
        Process events websocket message (Public API - JSON format).

        ``add`` payloads may be minimal/partial (e.g. motion start without
        ``score`` / ``smartDetect*``), but must still be constructable as an
        :class:`Event` — see the defaults on :class:`Event` for the optional
        fields. ``update`` messages carry partial diffs (typically ``end``)
        that are merged into the cached event by :class:`PublicBootstrap`.
        """
        if msg.type != aiohttp.WSMsgType.TEXT:
            _LOGGER.debug("Ignoring non-text websocket message: %s", msg.type)
            return

        try:
            data = orjson.loads(msg.data)
            action_type = data.get("type")
            item = data.get("item", {})
            model_key = item.get("modelKey")

            if not action_type or not model_key:
                _LOGGER.debug("Invalid public API websocket message: %s", data)
                return

            model_type = ModelType.from_string(model_key)

            if model_type is ModelType.UNKNOWN:
                _LOGGER.debug("Unknown model type in public API message: %s", model_key)
                return

            # Respect ``subscribed_models`` for the events WS too.
            # ``None`` => inherit the global filter; an explicit (possibly
            # empty) per-WS set overrides it.
            _events_filter = (
                self._subscribed_models
                if self._events_ws_subscribed_models is None
                else self._events_ws_subscribed_models
            )
            if _events_filter and model_type not in _events_filter:
                return

            update_id = item.get("id", "")

            new_obj: ProtectModelWithId | None = None
            old_obj: ProtectModelWithId | None = None
            if self._public_bootstrap is not None and model_type is ModelType.EVENT:
                new_event, old_event = self._public_bootstrap.process_events_ws_message(
                    self, data
                )
                new_obj = new_event
                old_obj = old_event

            msg_obj = WSSubscriptionMessage(
                action=WSAction(action_type),
                new_update_id=update_id,
                changed_data=item,
                new_obj=new_obj,
                old_obj=old_obj,
            )

            self.emit_events_message(msg_obj)
        except Exception:
            _LOGGER.exception("Error processing public API events websocket message")

    def _process_devices_ws_message(self, msg: aiohttp.WSMessage) -> None:
        """Process devices websocket message (Public API - JSON format)."""
        if msg.type != aiohttp.WSMsgType.TEXT:
            _LOGGER.debug("Ignoring non-text websocket message: %s", msg.type)
            return

        try:
            data = orjson.loads(msg.data)
            action_type = data.get("type")  # "update", "add", "remove"
            item = data.get("item", {})
            model_key = item.get("modelKey")

            if not action_type or not model_key:
                _LOGGER.debug("Invalid public API websocket message: %s", data)
                return

            # Create a WSSubscriptionMessage similar to private WS
            model_type = ModelType.from_string(model_key)

            if model_type is ModelType.UNKNOWN:
                _LOGGER.debug("Unknown model type in public API message: %s", model_key)
                return

            # Respect the ``subscribed_models`` filter that callers pass in.
            # Empty set means "all" (matches private-WS behaviour).
            # ``None`` => inherit the global filter; an explicit (possibly
            # empty) per-WS set overrides it.
            _devices_filter = (
                self._subscribed_models
                if self._devices_ws_subscribed_models is None
                else self._devices_ws_subscribed_models
            )
            if _devices_filter and model_type not in _devices_filter:
                return

            update_id = item.get("id", "")

            # Apply the change to the PublicBootstrap cache when it has been
            # materialised via `update_public`. Without that opt-in, the
            # subscription message carries ``new_obj=None`` and subscribers
            # must fall back to ``changed_data`` (the raw payload). This
            # preserves legacy behaviour exactly and avoids producing
            # partially-validated model instances for consumers that haven't
            # opted into the cache.
            new_obj: ProtectModelWithId | None = None
            old_obj: ProtectModelWithId | None = None
            if self._public_bootstrap is not None:
                _, new_obj, old_obj = self._public_bootstrap.process_devices_ws_message(
                    self, data
                )

            msg_obj = WSSubscriptionMessage(
                action=WSAction(action_type),
                new_update_id=update_id,
                changed_data=item,
                new_obj=new_obj,
                old_obj=old_obj,
            )

            self.emit_devices_message(msg_obj)
        except Exception:
            _LOGGER.exception("Error processing public API devices websocket message")

    async def _get_event_paginate(  # noqa: PLR0912
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

    async def get_events_raw(  # noqa: PLR0912
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

    def subscribe_events_websocket(
        self,
        ws_callback: Callable[[WSSubscriptionMessage], None],
    ) -> Callable[[], None]:
        """
        Subscribe to events websocket events.

        Returns a callback that will unsubscribe.
        """
        _LOGGER.debug("Adding events subscription: %s", ws_callback)
        self._events_ws_subscriptions.append(ws_callback)
        self._get_events_websocket().start()
        return partial(self._unsubscribe_events_websocket, ws_callback)

    def subscribe_devices_websocket(
        self,
        ws_callback: Callable[[WSSubscriptionMessage], None],
    ) -> Callable[[], None]:
        """
        Subscribe to devices websocket events.

        Returns a callback that will unsubscribe.
        """
        _LOGGER.debug("Adding devices subscription: %s", ws_callback)
        self._devices_ws_subscriptions.append(ws_callback)
        self._get_devices_websocket().start()
        return partial(self._unsubscribe_devices_websocket, ws_callback)

    def subscribe_events(
        self,
        callback: Callable[[ProtectEvent, EventChange], None],
    ) -> Callable[[], None]:
        """
        Subscribe to typed public event lifecycle callbacks.

        Only events whose ``EventType`` maps to a non-``OTHER``
        ``ProtectEventChannel`` (detection / sensor / alarm-hub /
        access) are delivered; administrative events such as
        ``provision``, ``factoryReset`` and ``fwUpdate`` are dropped.
        Callers needing the unfiltered stream should use
        ``subscribe_events_websocket`` instead.

        The callback must not raise: an exception is caught and logged but
        otherwise swallowed, so a raising callback silently loses that
        delivery (e.g. an ``ENDED`` that never reaches the consumer). Do any
        fallible work inside a guard the callback owns.

        Identity and ``device_mac`` resolve with eventual consistency: the
        first event for a freshly-enrolled ULP user can resolve to
        ``UnknownIdentity(reason="ulp_user_not_cached")``, and a device not
        yet in the bootstrap yields ``device_mac=None``, until the next
        ``update_public()`` / reconnect resync refreshes
        ``public_bootstrap.ulp_users`` and the device stores. Smart-detect
        detected attributes (license-plate text, face-match name) are not
        exposed over the public API today — fall back to the private path
        via ``event.raw`` when you need them.
        """
        if self._public_bootstrap is None:
            raise RuntimeError(
                "subscribe_events() requires update_public() to have been called"
                " at least once"
            )

        # Local import to avoid circular import (events.dispatcher → api).
        from .events.dispatcher import EventDispatcher  # noqa: PLC0415

        if self._event_dispatcher is None:
            self._event_dispatcher = EventDispatcher(self)
        dispatcher = self._event_dispatcher

        first = dispatcher.subscriber_count == 0
        dispatcher.add_subscriber(callback)

        if first:
            self._event_ws_adapter_unsub = self.subscribe_events_websocket(
                self._adapt_events_ws_message
            )
            dispatcher.start_ttl_sweep()

        return partial(self._unsubscribe_events, callback)

    def _unsubscribe_events(
        self,
        callback: Callable[[ProtectEvent, EventChange], None],
    ) -> None:
        if self._event_dispatcher is None:
            return
        self._event_dispatcher.remove_subscriber(callback)
        if self._event_dispatcher.subscriber_count == 0:
            self._event_dispatcher.stop_ttl_sweep()
            unsub = getattr(self, "_event_ws_adapter_unsub", None)
            if unsub is not None:
                unsub()
                self._event_ws_adapter_unsub = None

    def active_events(self, device_id: str | None = None) -> list[ProtectEvent]:
        """
        Return the in-flight public events, optionally filtered by device.

        Derived directly from ``public_bootstrap.events``, so it works
        before any ``subscribe_events`` call (e.g. restoring state after a
        reload). Returns ``[]`` until ``update_public()`` has primed the
        public bootstrap.
        """
        if self._public_bootstrap is None:
            return []
        if self._event_dispatcher is None:
            # Local import to avoid circular import (events.dispatcher → api).
            from .events.dispatcher import EventDispatcher  # noqa: PLC0415

            self._event_dispatcher = EventDispatcher(self)
        return self._event_dispatcher.active_events(device_id=device_id)

    def _adapt_events_ws_message(self, msg: WSSubscriptionMessage) -> None:
        if self._event_dispatcher is None:
            return
        dispatcher = self._event_dispatcher
        old_obj = msg.old_obj if isinstance(msg.old_obj, Event) else None
        if msg.action in (WSAction.ADD, WSAction.UPDATE):
            if msg.new_obj is None:
                # Benign in normal desync/reconnect: an UPDATE for an event id
                # the store has not cached (or a merge/construct failure already
                # surfaced by PublicBootstrap) arrives without a merged Event.
                # Not a server contract change — drop quietly.
                event_id = msg.changed_data.get("id") if msg.changed_data else None
                _LOGGER.debug(
                    "Events-WS %s without merged Event obj (id=%s) — dropping frame",
                    msg.action,
                    event_id,
                )
                return
            if not isinstance(msg.new_obj, Event):
                # A merged object of the wrong type is a genuine shape violation.
                _LOGGER.warning(
                    "Events-WS %s merged obj is not an Event — dropping frame"
                    " (possible server contract change)",
                    msg.action,
                )
                return
            dispatcher.dispatch(msg.action, msg.new_obj, old_obj)
            return
        if msg.action is WSAction.REMOVE:
            if old_obj is None:
                # The store handed back no pre-removal object — a remove for
                # an event we never cached.
                event_id = msg.changed_data.get("id") if msg.changed_data else None
                self._events_remove_unknown_count += 1
                now = time.monotonic()
                if now - self._events_remove_unknown_last_log >= 60.0:
                    _LOGGER.info(
                        "Events-WS remove for unknown event %s — skipping"
                        " (throttled, logged at most once per 60s; %d total"
                        " unknown removes so far)",
                        event_id,
                        self._events_remove_unknown_count,
                    )
                    self._events_remove_unknown_last_log = now
                return
            dispatcher.dispatch(WSAction.REMOVE, None, old_obj)

    def _unsubscribe_websocket(
        self,
        ws_callback: Callable[[WSSubscriptionMessage], None],
    ) -> None:
        """Unsubscribe to websocket events."""
        _LOGGER.debug("Removing subscription: %s", ws_callback)
        self._ws_subscriptions.remove(ws_callback)
        if not self._ws_subscriptions:
            self._get_websocket().stop()

    def _unsubscribe_events_websocket(
        self,
        ws_callback: Callable[[WSSubscriptionMessage], None],
    ) -> None:
        """Unsubscribe to events websocket events."""
        _LOGGER.debug("Removing events subscription: %s", ws_callback)
        self._events_ws_subscriptions.remove(ws_callback)
        if not self._events_ws_subscriptions:
            self._get_events_websocket().stop()

    def _unsubscribe_devices_websocket(
        self,
        ws_callback: Callable[[WSSubscriptionMessage], None],
    ) -> None:
        """Unsubscribe to devices websocket events."""
        _LOGGER.debug("Removing devices subscription: %s", ws_callback)
        self._devices_ws_subscriptions.remove(ws_callback)
        if not self._devices_ws_subscriptions:
            self._get_devices_websocket().stop()

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

    def subscribe_events_websocket_state(
        self,
        ws_callback: Callable[[WebsocketState], None],
    ) -> Callable[[], None]:
        """
        Subscribe to events websocket state changes.

        Returns a callback that will unsubscribe.
        """
        self._events_ws_state_subscriptions.append(ws_callback)
        return partial(self._unsubscribe_events_websocket_state, ws_callback)

    def subscribe_devices_websocket_state(
        self,
        ws_callback: Callable[[WebsocketState], None],
    ) -> Callable[[], None]:
        """
        Subscribe to devices websocket state changes.

        Returns a callback that will unsubscribe.
        """
        self._devices_ws_state_subscriptions.append(ws_callback)
        return partial(self._unsubscribe_devices_websocket_state, ws_callback)

    def _unsubscribe_websocket_state(
        self,
        ws_callback: Callable[[WebsocketState], None],
    ) -> None:
        """Unsubscribe to websocket state changes."""
        self._ws_state_subscriptions.remove(ws_callback)

    def _unsubscribe_events_websocket_state(
        self,
        ws_callback: Callable[[WebsocketState], None],
    ) -> None:
        """Unsubscribe to events websocket state changes."""
        self._events_ws_state_subscriptions.remove(ws_callback)

    def _unsubscribe_devices_websocket_state(
        self,
        ws_callback: Callable[[WebsocketState], None],
    ) -> None:
        """Unsubscribe to devices websocket state changes."""
        self._devices_ws_state_subscriptions.remove(ws_callback)

    def _on_websocket_state_change(self, state: WebsocketState) -> None:
        """Websocket state changed."""
        super()._on_websocket_state_change(state)
        for sub in self._ws_state_subscriptions:
            try:
                sub(state)
            except Exception:
                _LOGGER.exception("Exception while running websocket state handler")

    def _on_events_websocket_state_change(self, state: WebsocketState) -> None:
        """Events Websocket state changed."""
        for sub in self._events_ws_state_subscriptions:
            try:
                sub(state)
            except Exception:
                _LOGGER.exception(
                    "Exception while running events websocket state handler"
                )

    def _on_devices_websocket_state_change(self, state: WebsocketState) -> None:
        """Devices Websocket state changed."""
        # On *reconnect* any add/update/remove emitted while we were offline
        # is lost — schedule a background `update_public()` to re-sync the
        # public bootstrap cache. No-op when the cache was never
        # materialised (callers not using the cache) or
        # on the very first connect (the caller is expected to prime the
        # cache via `update_public()` themselves). Flapping websockets are
        # debounced via :attr:`PUBLIC_RESYNC_MIN_INTERVAL` so a reconnect
        # storm collapses into a single refresh.
        if state is WebsocketState.CONNECTED:
            if not self._devices_ws_has_been_connected:
                self._devices_ws_has_been_connected = True
            elif self._public_bootstrap is not None:
                if (
                    self._public_resync_task is not None
                    and not self._public_resync_task.done()
                ):
                    self._public_resync_pending = True
                else:
                    now = time.monotonic()
                    if now - self._last_public_resync >= PUBLIC_RESYNC_MIN_INTERVAL:
                        # Deliberately updated *before* the task runs (not after
                        # success) so a flapping WS combined with a persistently
                        # failing NVR cannot spin up a continuous resync storm.
                        # Trade-off: a single failed attempt suppresses the next
                        # reconnect within the debounce window.
                        self._last_public_resync = now
                        self._public_resync_task = asyncio.create_task(
                            self._resync_public_bootstrap()
                        )
                    else:
                        _LOGGER.debug(
                            "Skipping public bootstrap resync (debounced, last was %.1fs ago)",
                            now - self._last_public_resync,
                        )
                # Force-end events that stayed open across the gap. The resync
                # above refreshes identity/devices; events arrive only via WS
                # so the sweep is what guarantees no stuck-active sensor. Gate
                # on a live subscriber so a reconnect after the last
                # unsubscribe does not mutate the shared event store.
                if (
                    self._event_dispatcher is not None
                    and self._event_dispatcher.subscriber_count > 0
                ):
                    count = self._event_dispatcher.flush_stale_on_reconnect()
                    if count > 0:
                        _LOGGER.warning(
                            "Websocket reconnected after gap; some events may"
                            " have been missed (force-ended %d stale active"
                            " events).",
                            count,
                        )

        for sub in self._devices_ws_state_subscriptions:
            try:
                sub(state)
            except Exception:
                _LOGGER.exception(
                    "Exception while running devices websocket state handler"
                )

    async def _resync_public_bootstrap(self) -> None:
        """Re-sync the public bootstrap cache after a websocket reconnect."""
        try:
            await self.update_public()
        except Exception:
            _LOGGER.exception("Failed to resync public bootstrap after reconnect")
        finally:
            if self._public_resync_pending:
                self._public_resync_pending = False
                self._last_public_resync = time.monotonic()
                self._public_resync_task = asyncio.create_task(
                    self._resync_public_bootstrap()
                )

    async def get_bootstrap(self) -> Bootstrap:
        """
        Gets bootstrap object from UFP instance

        This is a great alternative if you need metadata about the NVR without connecting to the Websocket
        """
        data = await self.api_request_obj("bootstrap")
        await _async_warm_nvr_timezone(data["nvr"])
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
        return cast("list[Camera]", await self.get_devices(ModelType.CAMERA, Camera))

    async def get_lights(self) -> list[Light]:
        """
        Gets the list of lights straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.lights`

        .. deprecated::
            Use :meth:`get_lights_public` instead. This method uses the private API
            and will be removed in a future version.
        """
        return cast("list[Light]", await self.get_devices(ModelType.LIGHT, Light))

    async def get_sensors(self) -> list[Sensor]:
        """
        Gets the list of sensors straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.sensors`
        """
        return cast("list[Sensor]", await self.get_devices(ModelType.SENSOR, Sensor))

    async def get_doorlocks(self) -> list[Doorlock]:
        """
        Gets the list of doorlocks straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.doorlocks`
        """
        return cast(
            "list[Doorlock]",
            await self.get_devices(ModelType.DOORLOCK, Doorlock),
        )

    async def get_chimes(self) -> list[Chime]:
        """
        Gets the list of chimes straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.chimes`
        """
        return cast("list[Chime]", await self.get_devices(ModelType.CHIME, Chime))

    async def get_aiports(self) -> list[AiPort]:
        """
        Gets the list of aiports straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.aiports`
        """
        return cast("list[AiPort]", await self.get_devices(ModelType.AIPORT, AiPort))

    async def get_viewers(self) -> list[Viewer]:
        """
        Gets the list of viewers straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.viewers`
        """
        return cast("list[Viewer]", await self.get_devices(ModelType.VIEWPORT, Viewer))

    async def get_bridges(self) -> list[Bridge]:
        """
        Gets the list of bridges straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.bridges`
        """
        return cast("list[Bridge]", await self.get_devices(ModelType.BRIDGE, Bridge))

    async def get_liveviews(self) -> list[Liveview]:
        """
        Gets the list of liveviews straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.liveviews`
        """
        return cast(
            "list[Liveview]",
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

        return cast("ProtectModelWithId", obj)

    async def get_nvr(self) -> NVR:
        """
        Gets an NVR object straight from the NVR.

        This is a great alternative if you need metadata about the NVR without connecting to the Websocket
        """
        data = await self.api_request_obj("nvr")
        await _async_warm_nvr_timezone(data)
        return NVR.from_unifi_dict(**data, api=self)

    async def get_event(self, event_id: str) -> Event:
        """
        Gets an event straight from the NVR.

        This is a great alternative if the event is no longer in the `self.bootstrap.events[event_id]` cache
        """
        return cast("Event", await self.get_device(ModelType.EVENT, event_id, Event))

    async def get_camera(self, device_id: str) -> Camera:
        """
        Gets a camera straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.cameras[device_id]`
        """
        return cast(
            "Camera", await self.get_device(ModelType.CAMERA, device_id, Camera)
        )

    async def get_light(self, device_id: str) -> Light:
        """
        Gets a light straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.lights[device_id]`

        .. deprecated::
            Use :meth:`get_light_public` instead. This method uses the private API
            and will be removed in a future version.
        """
        return cast("Light", await self.get_device(ModelType.LIGHT, device_id, Light))

    async def get_sensor(self, device_id: str) -> Sensor:
        """
        Gets a sensor straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.sensors[device_id]`
        """
        return cast(
            "Sensor", await self.get_device(ModelType.SENSOR, device_id, Sensor)
        )

    async def get_doorlock(self, device_id: str) -> Doorlock:
        """
        Gets a doorlock straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.doorlocks[device_id]`
        """
        return cast(
            "Doorlock",
            await self.get_device(ModelType.DOORLOCK, device_id, Doorlock),
        )

    async def get_chime(self, device_id: str) -> Chime:
        """
        Gets a chime straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.chimes[device_id]`
        """
        return cast("Chime", await self.get_device(ModelType.CHIME, device_id, Chime))

    async def get_aiport(self, device_id: str) -> AiPort:
        """
        Gets a AiPort straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.aiport[device_id]`
        """
        return cast(
            "AiPort", await self.get_device(ModelType.AIPORT, device_id, AiPort)
        )

    async def get_viewer(self, device_id: str) -> Viewer:
        """
        Gets a viewer straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.viewers[device_id]`
        """
        return cast(
            "Viewer",
            await self.get_device(ModelType.VIEWPORT, device_id, Viewer),
        )

    async def get_bridge(self, device_id: str) -> Bridge:
        """
        Gets a bridge straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.bridges[device_id]`
        """
        return cast(
            "Bridge", await self.get_device(ModelType.BRIDGE, device_id, Bridge)
        )

    async def get_liveview(self, device_id: str) -> Liveview:
        """
        Gets a liveview straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.liveviews[device_id]`
        """
        return cast(
            "Liveview",
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
        package: bool = False,
    ) -> bytes | None:
        """
        Gets snapshot for a camera using public api.

        Args:
            camera_id: Camera ID.
            high_quality: Force 1080P+ resolution.
            package: If ``True``, fetch from the package camera (only supported
                on cameras with ``hasPackageCamera: true``). Requires Protect
                on the NVR.

        """
        params: dict[str, Any] = {"highQuality": pybool_to_json_bool(high_quality)}
        if package:
            params["channel"] = "package"
        return await self.api_request_raw(
            public_api=True,
            raise_exception=False,
            url=f"/v1/cameras/{camera_id}/snapshot",
            params=params,
        )

    async def create_camera_rtsps_streams(
        self,
        camera_id: str,
        qualities: list[ChannelQuality | str] | ChannelQuality | str,
    ) -> RTSPSStreams | None:
        """Creates RTSPS streams for a camera using public API."""
        if isinstance(qualities, str):
            qualities = [qualities]

        data = {"qualities": [str(q) for q in qualities]}
        response = await self.api_request_raw(
            public_api=True,
            url=f"/v1/cameras/{camera_id}/rtsps-stream",
            method="POST",
            json=data,
        )

        if response is None:
            return None

        try:
            response_json = orjson.loads(response)
            return RTSPSStreams(**response_json)
        except (orjson.JSONDecodeError, TypeError) as ex:
            _LOGGER.error(
                "Could not decode JSON response for create RTSPS streams (camera %s): %s",
                camera_id,
                ex,
            )
            return None

    async def get_camera_rtsps_streams(
        self,
        camera_id: str,
    ) -> RTSPSStreams | None:
        """Gets existing RTSPS streams for a camera using public API."""
        response = await self.api_request_raw(
            public_api=True,
            url=f"/v1/cameras/{camera_id}/rtsps-stream",
            method="GET",
        )

        if response is None:
            return None

        try:
            response_json = orjson.loads(response)
            return RTSPSStreams(**response_json)
        except (orjson.JSONDecodeError, TypeError) as ex:
            _LOGGER.error(
                "Could not decode JSON response for get RTSPS streams (camera %s): %s",
                camera_id,
                ex,
            )
            return None

    async def delete_camera_rtsps_streams(
        self,
        camera_id: str,
        qualities: list[ChannelQuality | str] | ChannelQuality | str,
    ) -> bool:
        """Deletes RTSPS streams for a camera using public API."""
        if isinstance(qualities, str):
            qualities = [qualities]

        # Build query parameters for qualities
        params = [("qualities", str(quality)) for quality in qualities]

        response = await self.api_request_raw(
            public_api=True,
            url=f"/v1/cameras/{camera_id}/rtsps-stream",
            method="DELETE",
            params=params,
        )

        return response is not None

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

        Providing the `fps` parameter creates a "timelapse" export with the given FPS
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
        thumbnail_id = thumbnail_id.removeprefix("e-")
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
        thumbnail_id = thumbnail_id.removeprefix("e-")
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
        heatmap_id = heatmap_id.removeprefix("e-")
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
        """
        Plays chime tones on a chime.

        Args:
        ----
            device_id: The chime device ID
            volume: Volume level for playback (0-100)
            repeat_times: Number of times to repeat the tone
            ringtone_id: The ringtone ID (UUID) to play. Preferred over track_no.
            track_no: Legacy track number from speakerTrackList.
                .. deprecated::
                    Use ringtone_id instead. track_no maps to the speaker track
                    list but ringtone_id is the current API standard.

        """
        data: dict[str, Any] | None = None
        if (
            volume is not None
            or repeat_times is not None
            or ringtone_id is not None
            or track_no is not None
        ):
            chime = self.bootstrap.chimes.get(device_id)
            if chime is None:
                raise BadRequest(f"Invalid chime ID {device_id}")

            data = {
                "volume": volume if volume is not None else chime.volume,
                "repeatTimes": repeat_times
                if repeat_times is not None
                else chime.repeat_times,
            }
            if ringtone_id is not None:
                data["ringtoneId"] = ringtone_id
            elif track_no is not None:
                warnings.warn(
                    "track_no is deprecated, use ringtone_id instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
                data["trackNo"] = track_no
            # If neither ringtone_id nor track_no provided, don't include in payload

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
        """
        Sets isLedForceOn for light.

        .. deprecated::
            Use :meth:`update_light_public` instead. This method uses the private API
            and will be removed in a future version.
        """
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
            aiohttp.ServerDisconnectedError,
            client_exceptions.ClientError,
        ) as err:
            raise NvrError(f"Error packages from {url}: {err}") from err

        return versions

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

    # Public API Methods

    async def get_nvr_public(self) -> PublicNVR:
        """Get NVR information using public API."""
        data = await self.api_request_obj(url="/v1/nvrs", public_api=True)
        return PublicNVR.from_unifi_dict(**data, api=self)

    async def get_lights_public(self) -> list[Light]:
        """Get all lights using public API."""
        data = await self.api_request_list(url="/v1/lights", public_api=True)
        return [Light.from_unifi_dict(**light_data, api=self) for light_data in data]

    async def get_light_public(self, light_id: str) -> Light:
        """Get a specific light using public API."""
        data = await self.api_request_obj(url=f"/v1/lights/{light_id}", public_api=True)
        return Light.from_unifi_dict(**data, api=self)

    async def update_light_public(
        self,
        light_id: str,
        *,
        name: str | None = None,
        is_light_force_enabled: bool | None = None,
        light_mode_settings: LightModeSettings | None = None,
        light_device_settings: LightDeviceSettings | None = None,
    ) -> Light:
        """
        Update light settings using public API.

        Args:
        ----
            light_id: The light's ID
            name: Light name
            is_light_force_enabled: Force enable the light
            light_mode_settings: Light mode settings (mode, enable_at)
            light_device_settings: Light device settings (LED level, PIR settings, etc.)

        Returns:
        -------
            Updated Light object

        Raises:
        ------
            BadRequest: If no parameters are provided

        """
        data: LightPatchRequest = {}
        if name is not None:
            data["name"] = name
        if is_light_force_enabled is not None:
            data["isLightForceEnabled"] = is_light_force_enabled
        if light_mode_settings is not None:
            data["lightModeSettings"] = light_mode_settings.unifi_dict()
        if light_device_settings is not None:
            # luxSensitivity may come from Private API but is not settable - filter it out
            device_dict = light_device_settings.unifi_dict()
            device_dict.pop("luxSensitivity", None)
            data["lightDeviceSettings"] = device_dict

        if not data:
            raise BadRequest("At least one parameter must be provided")

        result = await self.api_request_obj(
            url=f"/v1/lights/{light_id}",
            method="patch",
            json=data,
            public_api=True,
        )
        return Light.from_unifi_dict(**result, api=self)

    async def get_cameras_public(self) -> list[Camera]:
        """Get all cameras using public API."""
        data = await self.api_request_list(url="/v1/cameras", public_api=True)
        return [Camera.from_unifi_dict(**camera_data, api=self) for camera_data in data]

    async def get_camera_public(self, camera_id: str) -> Camera:
        """Get a specific camera using public API."""
        data = await self.api_request_obj(
            url=f"/v1/cameras/{camera_id}", public_api=True
        )
        return Camera.from_unifi_dict(**data, api=self)

    async def update_camera_public(
        self,
        camera_id: str,
        *,
        name: str | None = None,
        hdr_type: PublicHdrMode | None = None,
        video_mode: VideoMode | None = None,
        led_is_enabled: bool | None = None,
        led_welcome_led: bool | None = None,
        led_flood_led: bool | None = None,
        mic_volume: int | None = None,
        smart_detect_object_types: list[SmartDetectObjectType] | None = None,
        smart_detect_audio_types: list[SmartDetectAudioType] | None = None,
        lcd_message: CameraPublicApiLcdMessageRequest | None = None,
        osd_name_enabled: bool | None = None,
        osd_date_enabled: bool | None = None,
        osd_logo_enabled: bool | None = None,
        osd_nerd_mode_enabled: bool | None = None,
        osd_overlay_location: OsdOverlayLocation | None = None,
    ) -> Camera:
        """
        Patch camera settings using public API.

        Returns a fresh Camera object deserialized from the PATCH response.
        The returned object is not merged into the bootstrap cache; callers
        that need cache consistency should update the relevant fields manually
        (as the device-level convenience methods already do).
        """
        body = self._filter_none(
            (
                ("name", name),
                ("hdrType", hdr_type),
                ("videoMode", video_mode),
                ("lcdMessage", lcd_message),
            )
        )
        led = self._filter_none(
            (
                ("isEnabled", led_is_enabled),
                ("welcomeLed", led_welcome_led),
                ("floodLed", led_flood_led),
            )
        )
        if led:
            body["ledSettings"] = led
        if mic_volume is not None:
            if not 1 <= mic_volume <= 100:
                raise BadRequest("mic_volume must be between 1 and 100")
            body["micVolume"] = mic_volume
        detect: dict[str, Any] = {}
        if smart_detect_object_types is not None:
            detect["objectTypes"] = list(smart_detect_object_types)
        if smart_detect_audio_types is not None:
            detect["audioTypes"] = list(smart_detect_audio_types)
        if detect:
            body["smartDetectSettings"] = detect
        osd = self._filter_none(
            (
                ("isNameEnabled", osd_name_enabled),
                ("isDateEnabled", osd_date_enabled),
                ("isLogoEnabled", osd_logo_enabled),
                ("isDebugEnabled", osd_nerd_mode_enabled),
                ("overlayLocation", osd_overlay_location),
            )
        )
        if osd:
            body["osdSettings"] = osd
        if not body:
            raise BadRequest("At least one parameter must be provided")
        result = await self.api_request_obj(
            url=f"/v1/cameras/{camera_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        return Camera.from_unifi_dict(**result, api=self)

    async def get_chimes_public(self) -> list[Chime]:
        """Get all chimes using public API."""
        data = await self.api_request_list(url="/v1/chimes", public_api=True)
        return [Chime.from_unifi_dict(**chime_data, api=self) for chime_data in data]

    async def get_chime_public(self, chime_id: str) -> Chime:
        """Get a specific chime using public API."""
        data = await self.api_request_obj(url=f"/v1/chimes/{chime_id}", public_api=True)
        return Chime.from_unifi_dict(**data, api=self)

    async def update_chime_public(
        self,
        chime_id: str,
        *,
        name: str | None = None,
        camera_ids: list[str] | None = None,
        ring_settings: list[PublicApiChimeRingSettingRequest] | None = None,
    ) -> Chime:
        """
        Update chime settings using public API.

        Args:
        ----
            chime_id: The chime's ID
            name: Chime name
            camera_ids: List of paired doorbell camera IDs
            ring_settings: List of ring settings per camera. Each dict should contain:
                - cameraId: The camera ID this setting applies to
                - volume: Ring volume (0-100)
                - repeatTimes: How many times to repeat (1-10)
                - ringtoneId (optional): The ringtone ID to use

        Returns:
        -------
            Updated Chime object

        Raises:
        ------
            BadRequest: If no parameters are provided

        """
        data: PublicApiChimePatchRequest = {}
        if name is not None:
            data["name"] = name
        if camera_ids is not None:
            data["cameraIds"] = camera_ids
        if ring_settings is not None:
            data["ringSettings"] = ring_settings

        if not data:
            raise BadRequest("At least one parameter must be provided")

        result = await self.api_request_obj(
            url=f"/v1/chimes/{chime_id}",
            method="patch",
            json=data,
            public_api=True,
        )
        return Chime.from_unifi_dict(**result, api=self)

    # PTZ Control Private API Methods

    async def get_presets_ptz_camera(self, device_id: str) -> list[PTZPreset]:
        """Get PTZ Presets for camera."""
        presets = await self.api_request(f"cameras/{device_id}/ptz/preset")

        if not presets:
            return []

        presets = cast("list[dict[str, Any]]", presets)
        return [PTZPreset(**p) for p in presets]

    async def get_patrols_ptz_camera(self, device_id: str) -> list[PTZPatrol]:
        """Get PTZ Patrols for camera."""
        patrols = await self.api_request(f"cameras/{device_id}/ptz/patrol")

        if not patrols:
            return []

        patrols = cast("list[dict[str, Any]]", patrols)
        return [PTZPatrol(**p) for p in patrols]

    # PTZ Control Public API Methods

    async def ptz_goto_preset_public(self, camera_id: str, *, slot: int) -> None:
        """Move PTZ camera to preset position using public API."""
        await self.api_request_raw(
            url=f"/v1/cameras/{camera_id}/ptz/goto/{slot}",
            method="post",
            public_api=True,
        )

    async def ptz_patrol_start_public(self, camera_id: str, *, slot: int) -> None:
        """Start a PTZ patrol using public API."""
        await self.api_request_raw(
            url=f"/v1/cameras/{camera_id}/ptz/patrol/start/{slot}",
            method="post",
            public_api=True,
        )

    async def ptz_patrol_stop_public(self, camera_id: str) -> None:
        """Stop the active PTZ patrol using public API."""
        await self.api_request_raw(
            url=f"/v1/cameras/{camera_id}/ptz/patrol/stop",
            method="post",
            public_api=True,
        )

    async def create_talkback_session_public(self, camera_id: str) -> TalkbackSession:
        """
        Create a talkback session for a camera using public API.

        Returns the talkback stream URL and audio configuration.
        """
        data = await self.api_request_obj(
            url=f"/v1/cameras/{camera_id}/talkback-session",
            method="post",
            public_api=True,
        )
        return TalkbackSession.from_unifi_dict(**data)

    async def disable_camera_mic_permanently_public(self, camera_id: str) -> Camera:
        """
        Permanently disable a camera's microphone.

        Irreversible without a factory reset of the camera. The spec returns
        the updated camera object (not a 204).
        """
        data = await self.api_request_obj(
            url=f"/v1/cameras/{camera_id}/disable-mic-permanently",
            method="post",
            public_api=True,
        )
        return Camera.from_unifi_dict(**data, api=self)

    # ------------------------------------------------------------------
    # Public API: Sensors
    # ------------------------------------------------------------------

    async def get_sensors_public(self) -> list[Sensor]:
        """Get all sensors using public API."""
        data = await self.api_request_list(url="/v1/sensors", public_api=True)
        return [Sensor.from_unifi_dict(**item, api=self) for item in data]

    async def get_sensor_public(self, sensor_id: str) -> Sensor:
        """Get a specific sensor using public API."""
        data = await self.api_request_obj(
            url=f"/v1/sensors/{sensor_id}", public_api=True
        )
        return Sensor.from_unifi_dict(**data, api=self)

    async def update_sensor_public(
        self,
        sensor_id: str,
        *,
        name: str | None = None,
        light_settings: PublicSensorLightSettings | None = None,
        humidity_settings: PublicSensorHumiditySettings | None = None,
        temperature_settings: PublicSensorTemperatureSettings | None = None,
        motion_settings: PublicSensorMotionSettings | None = None,
        alarm_settings: PublicSensorAlarmSettings | None = None,
    ) -> Sensor:
        """
        Patch sensor settings using public API.

        Each ``*_settings`` argument is a :class:`~typing.TypedDict` with
        ``total=False`` — pass only the keys you want to change.
        """
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if light_settings is not None:
            body["lightSettings"] = dict(light_settings)
        if humidity_settings is not None:
            body["humiditySettings"] = dict(humidity_settings)
        if temperature_settings is not None:
            body["temperatureSettings"] = dict(temperature_settings)
        if motion_settings is not None:
            body["motionSettings"] = dict(motion_settings)
        if alarm_settings is not None:
            body["alarmSettings"] = dict(alarm_settings)

        if not body:
            raise BadRequest("At least one parameter must be provided")

        result = await self.api_request_obj(
            url=f"/v1/sensors/{sensor_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        return Sensor.from_unifi_dict(**result, api=self)

    # ------------------------------------------------------------------
    # Public API: Sirens
    # ------------------------------------------------------------------

    @staticmethod
    def _build_named_led_patch_body(
        *, name: str | None = None, led_is_enabled: bool | None = None
    ) -> dict[str, Any]:
        """Build common PATCH body for resources with name + ledSettings."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if led_is_enabled is not None:
            body["ledSettings"] = {"isEnabled": led_is_enabled}
        return body

    @staticmethod
    def _filter_none(items: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
        """Return a dict from key-value pairs, dropping any pair whose value is None."""
        return {k: v for k, v in items if v is not None}

    async def get_sirens_public(self) -> list[Siren]:
        """Get all sirens using public API."""
        data = await self.api_request_list(url="/v1/sirens", public_api=True)
        return [Siren.from_unifi_dict(**item, api=self) for item in data]

    async def get_siren_public(self, siren_id: str) -> Siren:
        """Get a specific siren using public API."""
        data = await self.api_request_obj(url=f"/v1/sirens/{siren_id}", public_api=True)
        return Siren.from_unifi_dict(**data, api=self)

    async def update_siren_public(
        self,
        siren_id: str,
        *,
        name: str | None = None,
        volume: int | None = None,
        led_is_enabled: bool | None = None,
    ) -> Siren:
        """Patch siren settings using public API."""
        body = self._build_named_led_patch_body(
            name=name,
            led_is_enabled=led_is_enabled,
        )
        if volume is not None:
            body["volume"] = volume

        if not body:
            raise BadRequest("At least one parameter must be provided")

        result = await self.api_request_obj(
            url=f"/v1/sirens/{siren_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        return Siren.from_unifi_dict(**result, api=self)

    async def play_siren_public(
        self, siren_id: str, *, duration: SirenDuration | int | None = None
    ) -> None:
        """Activate a siren. ``duration`` may be a supported integer or :class:`SirenDuration`; defaults to 5 seconds."""
        if duration is None:
            norm_duration = SirenDuration.FIVE
        elif isinstance(duration, SirenDuration):
            norm_duration = duration
        else:
            try:
                norm_duration = SirenDuration(duration)
            except ValueError as err:
                raise BadRequest(
                    "duration must be one of the supported siren durations "
                    f"{', '.join(str(item.value) for item in SirenDuration)} seconds"
                ) from err
        await self.api_request_raw(
            url=f"/v1/sirens/{siren_id}/play",
            method="post",
            public_api=True,
            json={"duration": norm_duration},
        )

    async def stop_siren_public(self, siren_id: str) -> None:
        """Stop an active siren."""
        await self.api_request_raw(
            url=f"/v1/sirens/{siren_id}/stop",
            method="post",
            public_api=True,
        )

    async def test_siren_sound_public(
        self, siren_id: str, *, volume: int | None = None
    ) -> None:
        """Test the siren sound (5 seconds)."""
        body: dict[str, Any] = {}
        if volume is not None:
            body["volume"] = volume
        await self.api_request_raw(
            url=f"/v1/sirens/{siren_id}/test-sound",
            method="post",
            public_api=True,
            json=body,
        )

    # ------------------------------------------------------------------
    # Public API: Relays
    # ------------------------------------------------------------------

    async def get_relays_public(self) -> list[Relay]:
        """Get all relays using public API."""
        data = await self.api_request_list(url="/v1/relays", public_api=True)
        return [Relay.from_unifi_dict(**item, api=self) for item in data]

    async def get_relay_public(self, relay_id: str) -> Relay:
        """Get a specific relay using public API."""
        data = await self.api_request_obj(url=f"/v1/relays/{relay_id}", public_api=True)
        return Relay.from_unifi_dict(**data, api=self)

    async def update_relay_public(
        self,
        relay_id: str,
        *,
        name: str | None = None,
        led_is_enabled: bool | None = None,
    ) -> Relay:
        """Patch relay settings using public API."""
        body = self._build_named_led_patch_body(
            name=name,
            led_is_enabled=led_is_enabled,
        )

        if not body:
            raise BadRequest("At least one parameter must be provided")

        result = await self.api_request_obj(
            url=f"/v1/relays/{relay_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        return Relay.from_unifi_dict(**result, api=self)

    async def activate_relay_output_public(
        self,
        relay_id: str,
        output_id: int,
        *,
        state: Literal["on", "off"] | None = None,
        pulse_duration_ms: int | None = None,
    ) -> None:
        """
        Activate, toggle or pulse a relay output.

        Omit ``state`` to toggle the current state. ``pulse_duration_ms`` is
        only valid together with ``state='on'``; the output will auto-turn
        off after the given milliseconds.
        """
        if pulse_duration_ms is not None and state != "on":
            raise BadRequest("pulse_duration_ms may only be combined with state='on'")
        body: dict[str, Any] = {}
        if state is not None:
            body["state"] = state
        if pulse_duration_ms is not None:
            body["pulseDuration"] = pulse_duration_ms
        await self.api_request_raw(
            url=f"/v1/relays/{relay_id}/outputs/{output_id}/activate",
            method="post",
            public_api=True,
            json=body or None,
        )

    # ------------------------------------------------------------------
    # Public API: Fobs
    # ------------------------------------------------------------------

    async def get_fobs_public(self) -> list[Fob]:
        """Get all key fobs using public API."""
        data = await self.api_request_list(url="/v1/fobs", public_api=True)
        return [Fob.from_unifi_dict(**item, api=self) for item in data]

    async def get_fob_public(self, fob_id: str) -> Fob:
        """Get a specific key fob using public API."""
        data = await self.api_request_obj(url=f"/v1/fobs/{fob_id}", public_api=True)
        return Fob.from_unifi_dict(**data, api=self)

    async def update_fob_public(self, fob_id: str, *, name: str | None = None) -> Fob:
        """Patch key-fob settings using public API."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if not body:
            raise BadRequest("At least one parameter must be provided")
        result = await self.api_request_obj(
            url=f"/v1/fobs/{fob_id}", method="patch", json=body, public_api=True
        )
        return Fob.from_unifi_dict(**result, api=self)

    # ------------------------------------------------------------------
    # Public API: Speakers
    # ------------------------------------------------------------------

    async def get_speakers_public(self) -> list[Speaker]:
        """Get all speakers using public API."""
        data = await self.api_request_list(url="/v1/speakers", public_api=True)
        return [Speaker.from_unifi_dict(**item, api=self) for item in data]

    async def get_speaker_public(self, speaker_id: str) -> Speaker:
        """Get a specific speaker using public API."""
        data = await self.api_request_obj(
            url=f"/v1/speakers/{speaker_id}", public_api=True
        )
        return Speaker.from_unifi_dict(**data, api=self)

    async def update_speaker_public(
        self,
        speaker_id: str,
        *,
        name: str | None = None,
        volume: int | None = None,
        mic_volume: int | None = None,
        is_mic_enabled: bool | None = None,
    ) -> Speaker:
        """Patch speaker settings using public API."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if volume is not None:
            body["volume"] = volume
        if mic_volume is not None:
            body["micVolume"] = mic_volume
        if is_mic_enabled is not None:
            body["isMicEnabled"] = is_mic_enabled
        if not body:
            raise BadRequest("At least one parameter must be provided")
        result = await self.api_request_obj(
            url=f"/v1/speakers/{speaker_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        return Speaker.from_unifi_dict(**result, api=self)

    async def test_speaker_sound_public(
        self, speaker_id: str, *, volume: int | None = None
    ) -> None:
        """Test the speaker sound at the given volume."""
        body: dict[str, Any] = {}
        if volume is not None:
            body["volume"] = volume
        await self.api_request_raw(
            url=f"/v1/speakers/{speaker_id}/test-sound",
            method="post",
            public_api=True,
            json=body,
        )

    # ------------------------------------------------------------------
    # Public API: Link stations / Alarm hubs
    # ------------------------------------------------------------------

    async def get_link_stations_public(self) -> list[LinkStation]:
        """Get all link stations using public API."""
        data = await self.api_request_list(url="/v1/link-stations", public_api=True)
        return [LinkStation.from_unifi_dict(**item, api=self) for item in data]

    async def get_alarm_hubs_public(self) -> list[LinkStation]:
        """Get all alarm hubs using public API."""
        data = await self.api_request_list(url="/v1/alarm-hubs", public_api=True)
        return [LinkStation.from_unifi_dict(**item, api=self) for item in data]

    async def get_link_station_public(self, link_station_id: str) -> LinkStation:
        """Get a specific link station using public API."""
        data = await self.api_request_obj(
            url=f"/v1/link-stations/{link_station_id}", public_api=True
        )
        return LinkStation.from_unifi_dict(**data, api=self)

    async def get_alarm_hub_public(self, hub_id: str) -> LinkStation:
        """Get a specific alarm hub using public API."""
        data = await self.api_request_obj(
            url=f"/v1/alarm-hubs/{hub_id}", public_api=True
        )
        return LinkStation.from_unifi_dict(**data, api=self)

    async def update_link_station_public(
        self, link_station_id: str, *, name: str | None = None
    ) -> LinkStation:
        """Patch link station settings using public API."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if not body:
            raise BadRequest("At least one parameter must be provided")
        result = await self.api_request_obj(
            url=f"/v1/link-stations/{link_station_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        return LinkStation.from_unifi_dict(**result, api=self)

    async def update_alarm_hub_public(
        self, hub_id: str, *, name: str | None = None
    ) -> LinkStation:
        """Patch alarm hub settings using public API."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if not body:
            raise BadRequest("At least one parameter must be provided")
        result = await self.api_request_obj(
            url=f"/v1/alarm-hubs/{hub_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        return LinkStation.from_unifi_dict(**result, api=self)

    async def trigger_alarm_hub_output_public(
        self,
        hub_id: str,
        output_id: int,
        *,
        enable: bool | None = None,
        delay: int | None = None,
        duration: int | None = None,
    ) -> None:
        """Trigger an alarm-hub output channel using public API."""
        if delay is not None and delay < 0:
            raise BadRequest("delay must be >= 0")
        if duration is not None and duration < 0:
            raise BadRequest("duration must be >= 0")
        body: dict[str, Any] = {}
        if enable is not None:
            body["enable"] = enable
        if delay is not None:
            body["delay"] = delay
        if duration is not None:
            body["duration"] = duration
        await self.api_request_raw(
            url=f"/v1/alarm-hubs/{hub_id}/outputs/{output_id}/trigger",
            method="post",
            public_api=True,
            json=body or None,
        )

    # ------------------------------------------------------------------
    # Public API: Bridges
    # ------------------------------------------------------------------

    async def get_bridges_public(self) -> list[PublicBridge]:
        """Get all bridges using public API."""
        data = await self.api_request_list(url="/v1/bridges", public_api=True)
        return [PublicBridge.from_unifi_dict(**item, api=self) for item in data]

    async def get_bridge_public(self, bridge_id: str) -> PublicBridge:
        """Get a specific bridge using public API."""
        data = await self.api_request_obj(
            url=f"/v1/bridges/{bridge_id}", public_api=True
        )
        bridge = PublicBridge.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.bridges[bridge.id] = bridge
        return bridge

    async def update_bridge_public(
        self, bridge_id: str, *, name: str | None = None
    ) -> PublicBridge:
        """Patch bridge settings using public API."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if not body:
            raise BadRequest("At least one parameter must be provided")
        data = await self.api_request_obj(
            url=f"/v1/bridges/{bridge_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        bridge = PublicBridge.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.bridges[bridge.id] = bridge
        return bridge

    # ------------------------------------------------------------------
    # Public API: Viewers
    # ------------------------------------------------------------------

    async def get_viewers_public(self) -> list[PublicViewer]:
        """Get all viewers using public API."""
        data = await self.api_request_list(url="/v1/viewers", public_api=True)
        return [PublicViewer.from_unifi_dict(**item, api=self) for item in data]

    async def get_viewer_public(self, viewer_id: str) -> PublicViewer:
        """Get a specific viewer using public API."""
        data = await self.api_request_obj(
            url=f"/v1/viewers/{viewer_id}", public_api=True
        )
        viewer = PublicViewer.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.viewers[viewer.id] = viewer
        return viewer

    async def update_viewer_public(
        self,
        viewer_id: str,
        *,
        name: str | None = None,
        liveview: str | None | _UnsetType = _UNSET,
    ) -> PublicViewer:
        """Patch viewer settings using public API. Pass ``liveview=None`` to clear."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        # ``liveview`` is genuinely nullable on the wire — distinguish the
        # default sentinel (no change) from an explicit ``None`` (clear).
        if liveview is not _UNSET:
            body["liveview"] = liveview
        if not body:
            raise BadRequest("At least one parameter must be provided")
        data = await self.api_request_obj(
            url=f"/v1/viewers/{viewer_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        viewer = PublicViewer.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.viewers[viewer.id] = viewer
        return viewer

    # ------------------------------------------------------------------
    # Public API: Liveviews
    # ------------------------------------------------------------------

    async def get_liveviews_public(self) -> list[PublicLiveview]:
        """Get all liveviews using public API."""
        data = await self.api_request_list(url="/v1/liveviews", public_api=True)
        return [PublicLiveview.from_unifi_dict(**item, api=self) for item in data]

    async def get_liveview_public(self, liveview_id: str) -> PublicLiveview:
        """Get a specific liveview using public API."""
        data = await self.api_request_obj(
            url=f"/v1/liveviews/{liveview_id}", public_api=True
        )
        liveview = PublicLiveview.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.liveviews[liveview.id] = liveview
        return liveview

    async def create_liveview_public(
        self,
        *,
        name: str,
        is_default: bool,
        is_global: bool,
        owner: str,
        layout: int,
        slots: list[PublicLiveviewSlotDict],
    ) -> PublicLiveview:
        """Create a new liveview using public API."""
        if not 1 <= layout <= 26:
            raise BadRequest("layout must be between 1 and 26")
        body: dict[str, Any] = {
            "name": name,
            "isDefault": is_default,
            "isGlobal": is_global,
            "owner": owner,
            "layout": layout,
            "slots": [dict(s) for s in slots],
        }
        data = await self.api_request_obj(
            url="/v1/liveviews",
            method="post",
            json=body,
            public_api=True,
        )
        liveview = PublicLiveview.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.liveviews[liveview.id] = liveview
        return liveview

    async def update_liveview_public(
        self,
        liveview_id: str,
        *,
        name: str | None = None,
        is_default: bool | None = None,
        is_global: bool | None = None,
        owner: str | None = None,
        layout: int | None = None,
        slots: list[PublicLiveviewSlotDict] | None = None,
    ) -> PublicLiveview:
        """Patch an existing liveview (partial update) using public API."""
        if layout is not None and not 1 <= layout <= 26:
            raise BadRequest("layout must be between 1 and 26")
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if is_default is not None:
            body["isDefault"] = is_default
        if is_global is not None:
            body["isGlobal"] = is_global
        if owner is not None:
            body["owner"] = owner
        if layout is not None:
            body["layout"] = layout
        if slots is not None:
            body["slots"] = [dict(s) for s in slots]
        if not body:
            raise BadRequest("At least one parameter must be provided")
        data = await self.api_request_obj(
            url=f"/v1/liveviews/{liveview_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        liveview = PublicLiveview.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.liveviews[liveview.id] = liveview
        return liveview

    # ------------------------------------------------------------------
    # Public API: Alarm manager webhook
    # ------------------------------------------------------------------

    async def send_alarm_webhook_public(self, trigger_id: str) -> None:
        """Fire the alarm-manager webhook for the given trigger id."""
        if not trigger_id:
            raise BadRequest("trigger_id is required")
        await self.api_request_raw(
            url=f"/v1/alarm-manager/webhook/{quote(trigger_id, safe='')}",
            method="post",
            public_api=True,
        )

    # ------------------------------------------------------------------
    # Public API: Arm profiles (local alarm manager only)
    # ------------------------------------------------------------------

    async def get_arm_profiles_public(self) -> list[ArmProfile]:
        """Get all arm profiles."""
        data = await self.api_request_list(url="/v1/arm-profiles", public_api=True)
        profiles = [ArmProfile.from_unifi_dict(**item, api=self) for item in data]
        if self._public_bootstrap is not None:
            # Update in place to preserve dict identity for consumers holding
            # a reference to ``public_bootstrap.arm_profiles``.
            arm_profiles = self._public_bootstrap.arm_profiles
            arm_profiles.clear()
            arm_profiles.update({p.id: p for p in profiles})
        return profiles

    async def create_arm_profile_public(
        self,
        *,
        name: str,
        automations: list[str],
        schedules: list[PublicArmScheduleDict],
        record_everything: bool,
        activation_delay: int,
    ) -> ArmProfile:
        """Create a new arm profile."""
        body = {
            "name": name,
            "automations": automations,
            "schedules": [dict(s) for s in schedules],
            "recordEverything": record_everything,
            "activationDelay": activation_delay,
        }
        data = await self.api_request_obj(
            url="/v1/arm-profiles",
            method="post",
            json=body,
            public_api=True,
        )
        profile = ArmProfile.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.arm_profiles[profile.id] = profile
        return profile

    async def update_arm_profile_public(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        automations: list[str] | None = None,
        schedules: list[PublicArmScheduleDict] | None = None,
        record_everything: bool | None = None,
        activation_delay: int | None = None,
    ) -> ArmProfile:
        """Update an existing arm profile (partial update)."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if automations is not None:
            body["automations"] = automations
        if schedules is not None:
            body["schedules"] = [dict(s) for s in schedules]
        if record_everything is not None:
            body["recordEverything"] = record_everything
        if activation_delay is not None:
            body["activationDelay"] = activation_delay

        if not body:
            raise BadRequest("At least one parameter must be provided")

        data = await self.api_request_obj(
            url=f"/v1/arm-profiles/{profile_id}",
            method="patch",
            json=body,
            public_api=True,
        )
        profile = ArmProfile.from_unifi_dict(**data, api=self)
        if self._public_bootstrap is not None:
            self._public_bootstrap.arm_profiles[profile.id] = profile
        return profile

    async def delete_arm_profile_public(self, profile_id: str) -> None:
        """Delete an arm profile."""
        await self.api_request_raw(
            url=f"/v1/arm-profiles/{profile_id}",
            method="delete",
            public_api=True,
        )
        if self._public_bootstrap is not None:
            self._public_bootstrap.arm_profiles.pop(profile_id, None)

    async def get_arm_manager_settings_public(self) -> NvrArmMode | None:
        """
        Return current arm-manager state from the NVR cache.

        The arm-manager state is embedded in the NVR object (``armMode``
        field of ``GET /v1/nvrs``) — there is no dedicated GET endpoint.
        If the bootstrap cache is not yet populated, fetches the NVR now
        via :meth:`get_nvr_public` so the full ``PublicNVR`` is always
        constructed through the same code path.
        """
        if self._public_bootstrap is not None:
            return self._public_bootstrap.arm_mode
        nvr = await self.get_nvr_public()
        return nvr.arm_mode

    async def set_current_arm_profile_public(self, profile_id: str) -> None:
        """Set the currently selected arm profile."""
        await self.api_request_raw(
            url="/v1/arm-profiles/settings",
            method="patch",
            json={"armProfileId": profile_id},
            public_api=True,
        )
        if (
            self._public_bootstrap is not None
            and self._public_bootstrap.arm_mode is not None
        ):
            self._public_bootstrap.arm_mode.arm_profile_id = profile_id

    async def enable_arm_alarm_public(self) -> None:
        """Enable the arm alarm with the currently selected profile."""
        await self.api_request_raw(
            url="/v1/arm-profiles/enable",
            method="post",
            public_api=True,
        )
        if (
            self._public_bootstrap is not None
            and self._public_bootstrap.arm_mode is not None
        ):
            self._public_bootstrap.arm_mode.status = NvrArmModeStatus.ARMING

    async def disable_arm_alarm_public(self) -> None:
        """Disable the arm alarm."""
        await self.api_request_raw(
            url="/v1/arm-profiles/disable",
            method="post",
            public_api=True,
        )
        if (
            self._public_bootstrap is not None
            and self._public_bootstrap.arm_mode is not None
        ):
            self._public_bootstrap.arm_mode.status = NvrArmModeStatus.DISABLED

    # ------------------------------------------------------------------
    # Public API: Users
    # ------------------------------------------------------------------

    async def get_users_public(self) -> list[PublicUser]:
        """Get all Protect users using public API."""
        data = await self.api_request_list(url="/v1/users", public_api=True)
        return [PublicUser.from_unifi_dict(**item, api=self) for item in data]

    async def get_user_public(self, user_id: str) -> PublicUser:
        """Get a specific Protect user using public API."""
        data = await self.api_request_obj(url=f"/v1/users/{user_id}", public_api=True)
        return PublicUser.from_unifi_dict(**data, api=self)

    # ------------------------------------------------------------------
    # Public API: ULP users (UniFi Identity)
    # ------------------------------------------------------------------

    async def get_ulp_users_public(self) -> list[PublicUlpUser]:
        """Get all UniFi Identity users using public API."""
        data = await self.api_request_list(url="/v1/ulp-users", public_api=True)
        return [PublicUlpUser.from_unifi_dict(**item, api=self) for item in data]

    async def get_ulp_user_public(self, ulp_user_id: str) -> PublicUlpUser:
        """Get a specific UniFi Identity user using public API."""
        data = await self.api_request_obj(
            url=f"/v1/ulp-users/{ulp_user_id}", public_api=True
        )
        return PublicUlpUser.from_unifi_dict(**data, api=self)

    # ------------------------------------------------------------------
    # Public API: Files (device assets)
    # ------------------------------------------------------------------

    async def get_files_public(
        self, file_type: AssetFileType | str = AssetFileType.ANIMATIONS
    ) -> list[PublicFile]:
        """List uploaded device asset files of the given type."""
        data = await self.api_request_list(
            url=f"/v1/files/{file_type}", public_api=True
        )
        return [PublicFile.from_unifi_dict(**item, api=self) for item in data]

    async def upload_file_public(
        self,
        file_type: AssetFileType | str,
        file: bytes,
        original_name: str,
        content_type: str = "image/png",
    ) -> PublicFile:
        """
        Upload a device asset as ``multipart/form-data``.

        The spec accepts ``image/gif``, ``image/jpeg``, ``image/png``,
        ``audio/mpeg``, ``audio/mp4``, ``audio/wave``, ``audio/x-caf``;
        ``content_type`` defaults to ``image/png`` for the common
        doorbell-animation case and must be overridden for other MIME types.
        ``aiohttp`` sets the multipart ``Content-Type`` header (with boundary)
        itself when ``data=`` is a :class:`aiohttp.FormData`, so this client
        never sets a JSON content-type for this call.
        """
        form = aiohttp.FormData()
        form.add_field(
            "file",
            file,
            filename=original_name,
            content_type=content_type,
        )
        raw = await self.api_request_raw(
            url=f"/v1/files/{file_type}",
            method="post",
            public_api=True,
            data=form,
        )
        if not raw:
            raise NvrError("Empty response from upload_file_public")
        return PublicFile.from_unifi_dict(**orjson.loads(raw), api=self)

    # ------------------------------------------------------------------
    # Public API: Bootstrap (opt-in)
    # ------------------------------------------------------------------

    async def update_public(self) -> PublicBootstrap:
        """
        Populate :attr:`public_bootstrap` from the Public Integration API.

        This is opt-in and completely independent of :meth:`update` / the
        private bootstrap. Safe to call multiple times — the
        :class:`PublicBootstrap` instance is created on first use and then
        updated in place on subsequent calls. All endpoint fetches run
        concurrently.

        Each endpoint is requested best-effort; endpoints that the NVR
        doesn't (yet) expose (``BadRequest`` / ``NvrError``) are logged at
        ``DEBUG`` and ignored, and a partial public bootstrap is returned.
        If an endpoint fails, its previously cached data is left unchanged
        (not cleared). Unexpected exceptions (e.g. validation errors from a
        new server payload) propagate to the caller.
        """
        if self._public_bootstrap is None:
            self._public_bootstrap = PublicBootstrap()
        pb = self._public_bootstrap

        # Bind coroutines to their labels and attribute names to avoid
        # manual index synchronization bugs.
        # ``get_arm_profiles_public`` writes into ``pb`` itself on success;
        # we gather it for concurrency and to swallow failures.
        # ``armMode`` is part of the NVR response; no separate call needed.
        endpoints = [
            (self.get_nvr_public(), "nvr", "nvr"),
            (self.get_cameras_public(), "cameras", "cameras"),
            (self.get_lights_public(), "lights", "lights"),
            (self.get_chimes_public(), "chimes", "chimes"),
            (self.get_sensors_public(), "sensors", "sensors"),
            (self.get_sirens_public(), "sirens", "sirens"),
            (self.get_relays_public(), "relays", "relays"),
            (self.get_fobs_public(), "fobs", "fobs"),
            (self.get_speakers_public(), "speakers", "speakers"),
            (self.get_link_stations_public(), "link-stations", "link_stations"),
            (self.get_liveviews_public(), "liveviews", "liveviews"),
            (self.get_bridges_public(), "bridges", "bridges"),
            (self.get_viewers_public(), "viewers", "viewers"),
            (self.get_ulp_users_public(), "ulp-users", "ulp_users"),
            (self.get_arm_profiles_public(), "arm-profiles", "arm_profiles"),
        ]

        results = await asyncio.gather(
            *[coro for coro, _, _ in endpoints], return_exceptions=True
        )

        # Process results with their corresponding labels and attributes.
        for (_, label, attr), result in zip(endpoints, results, strict=True):
            if isinstance(result, BaseException):
                _log_or_raise(label, result)
                continue
            if attr == "arm_profiles":
                # arm_profiles are already applied by get_arm_profiles_public;
                # skip here to avoid overwriting the in-place dict.
                continue
            if attr == "nvr":
                pb.nvr = result  # type: ignore[assignment]
            else:
                pb.apply_fetch_result(attr, result)  # type: ignore[arg-type]

        return pb
