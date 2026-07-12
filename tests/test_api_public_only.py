"""Tests for the public-only (API-key-only) ProtectApiClient mode."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiofiles import os as aos

from uiprotect.api import ProtectApiClient
from uiprotect.data import PublicBootstrap
from uiprotect.data.nvr import MetaInfo
from uiprotect.data.types import Version
from uiprotect.exceptions import (
    BadRequest,
    NotAuthorized,
    NvrError,
    PublicOnlyModeError,
)

from .test_api_public import _make_public_nvr, _mock_update_public_endpoints

if TYPE_CHECKING:
    from pathlib import Path

API_KEY = "test-public-key"


def _public_only_client() -> ProtectApiClient:
    return ProtectApiClient.public_only(
        "127.0.0.1",
        443,
        api_key=API_KEY,
        verify_ssl=False,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_public_only_factory_sets_flag() -> None:
    client = _public_only_client()
    assert client.is_public_only is True
    assert client._api_key == API_KEY


def test_keyword_api_key_only_is_public_only() -> None:
    client = ProtectApiClient("127.0.0.1", 443, api_key=API_KEY)
    assert client.is_public_only is True


def test_full_credentials_not_public_only() -> None:
    client = ProtectApiClient("127.0.0.1", 443, "user", "pw")
    assert client.is_public_only is False


def test_credentials_plus_api_key_not_public_only() -> None:
    client = ProtectApiClient("127.0.0.1", 443, "user", "pw", api_key=API_KEY)
    assert client.is_public_only is False


def test_positional_credentials_still_work() -> None:
    creds = ("user", "pw")
    client = ProtectApiClient("127.0.0.1", 443, *creds)
    assert client._username == creds[0]
    assert client._password == creds[1]
    assert client.is_public_only is False


def test_no_auth_material_raises() -> None:
    with pytest.raises(BadRequest):
        ProtectApiClient("127.0.0.1", 443)


def test_partial_credentials_raise() -> None:
    with pytest.raises(BadRequest):
        ProtectApiClient("127.0.0.1", 443, "user")
    with pytest.raises(BadRequest):
        ProtectApiClient("127.0.0.1", 443, "user", api_key=API_KEY)


# ---------------------------------------------------------------------------
# Private-session entry points are guarded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_authenticate_raises_public_only() -> None:
    client = _public_only_client()
    with (
        patch.object(client, "request", new=AsyncMock()) as request,
        pytest.raises(PublicOnlyModeError),
    ):
        await client.authenticate()
    request.assert_not_called()


@pytest.mark.asyncio()
async def test_ensure_authenticated_raises_public_only() -> None:
    client = _public_only_client()
    with pytest.raises(PublicOnlyModeError):
        await client.ensure_authenticated()


@pytest.mark.asyncio()
async def test_update_raises_public_only() -> None:
    client = _public_only_client()
    with (
        patch.object(client, "request", new=AsyncMock()) as request,
        pytest.raises(PublicOnlyModeError),
    ):
        await client.update()
    request.assert_not_called()


@pytest.mark.asyncio()
async def test_get_bootstrap_raises_public_only() -> None:
    client = _public_only_client()
    with pytest.raises(PublicOnlyModeError):
        await client.get_bootstrap()


def test_private_bootstrap_property_raises() -> None:
    client = _public_only_client()
    with pytest.raises(BadRequest):
        _ = client.bootstrap


# ---------------------------------------------------------------------------
# Public surface remains available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_update_public_works_without_private_session() -> None:
    client = _public_only_client()
    _mock_update_public_endpoints(client)
    with (
        patch.object(client, "authenticate", new=AsyncMock()) as authenticate,
        patch.object(client, "get_console_mac", new=AsyncMock(return_value=None)),
    ):
        result = await client.update_public()
    assert isinstance(result, PublicBootstrap)
    assert client.has_public_bootstrap is True
    authenticate.assert_not_called()


@pytest.mark.asyncio()
async def test_update_public_backfills_nvr_mac_from_console() -> None:
    """Older firmware omits the NVR mac; it is stamped from the console."""
    client = _public_only_client()
    _mock_update_public_endpoints(client)
    console = AsyncMock(return_value="E4:38:83:32:C9:B1")
    with patch.object(client, "get_console_mac", new=console):
        pb = await client.update_public()
    assert pb.nvr is not None
    # Native format (uppercase, no separators), NOT the normalize_mac lowercase.
    assert pb.nvr.mac == "E4388332C9B1"
    console.assert_awaited_once()


@pytest.mark.asyncio()
async def test_update_public_keeps_native_nvr_mac_without_console() -> None:
    """Newer firmware already carries the mac; no console request is made."""
    client = _public_only_client()
    nvr = _make_public_nvr(client)
    nvr.mac = "AABBCCDDEEFF"
    console = AsyncMock(return_value="E4388332C9B1")
    _mock_update_public_endpoints(client, get_nvr_public=AsyncMock(return_value=nvr))
    with patch.object(client, "get_console_mac", new=console):
        pb = await client.update_public()
    assert pb.nvr is not None
    assert pb.nvr.mac == "AABBCCDDEEFF"
    console.assert_not_awaited()


@pytest.mark.asyncio()
async def test_update_public_leaves_nvr_mac_none_when_unresolvable() -> None:
    """An unreachable console leaves the mac unset rather than crashing."""
    client = _public_only_client()
    _mock_update_public_endpoints(client)
    console = AsyncMock(return_value=None)
    with patch.object(client, "get_console_mac", new=console):
        pb = await client.update_public()
    assert pb.nvr is not None
    assert pb.nvr.mac is None
    console.assert_awaited_once()


@pytest.mark.asyncio()
async def test_subscribe_events_registers_without_auth() -> None:
    client = _public_only_client()
    unsub = client.subscribe_events_websocket(lambda _msg: None)
    assert len(client._events_ws_subscriptions) == 1
    unsub()
    assert len(client._events_ws_subscriptions) == 0


@pytest.mark.asyncio()
async def test_subscribe_devices_registers_without_auth() -> None:
    client = _public_only_client()
    unsub = client.subscribe_devices_websocket(lambda _msg: None)
    assert len(client._devices_ws_subscriptions) == 1
    unsub()
    assert len(client._devices_ws_subscriptions) == 0


@pytest.mark.asyncio()
async def test_public_ws_auth_returns_api_key_header() -> None:
    client = _public_only_client()
    headers = await client._auth_public_api_websocket()
    assert headers == {"X-API-KEY": API_KEY}


@pytest.mark.asyncio()
async def test_public_ws_auth_revoked_key_raises() -> None:
    client = _public_only_client()
    client._api_key = None
    with pytest.raises(NotAuthorized, match="API key is required"):
        await client._auth_public_api_websocket()


# ---------------------------------------------------------------------------
# Auth-error mapping on public requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
@pytest.mark.parametrize("status", [401, 403])
async def test_public_request_maps_auth_error(status: int) -> None:
    client = _public_only_client()
    response = Mock()
    response.status = status
    response.url = "https://127.0.0.1/integration/v1/meta/info"
    with (
        patch.object(client, "request", new=AsyncMock(return_value=response)),
        patch("uiprotect.api.get_response_reason", return_value="denied"),
        pytest.raises(NotAuthorized),
    ):
        await client.get_meta_info()


@pytest.mark.asyncio()
async def test_public_request_missing_key_raises() -> None:
    client = ProtectApiClient("127.0.0.1", 443, "user", "pw")
    assert client._api_key is None
    with pytest.raises(NotAuthorized, match="API key is required"):
        await client.get_meta_info()


# ---------------------------------------------------------------------------
# Console mac resolution (off-contract UniFi-OS /api/system fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_get_console_mac_returns_mac() -> None:
    client = _public_only_client()
    with patch.object(
        client,
        "api_request",
        new=AsyncMock(return_value={"mac": "E4388332C9B1", "name": "UNVR"}),
    ) as api_request:
        mac = await client.get_console_mac()
    assert mac == "E4388332C9B1"
    api_request.assert_awaited_once()
    kwargs = api_request.await_args.kwargs
    assert kwargs["url"] == "/system"
    assert kwargs["api_path"] == "/api"
    assert kwargs["require_auth"] is False


@pytest.mark.asyncio()
async def test_get_console_mac_missing_mac_returns_none() -> None:
    client = _public_only_client()
    with patch.object(
        client, "api_request", new=AsyncMock(return_value={"name": "UNVR"})
    ):
        assert await client.get_console_mac() is None


@pytest.mark.asyncio()
async def test_get_console_mac_empty_mac_returns_none() -> None:
    client = _public_only_client()
    with patch.object(client, "api_request", new=AsyncMock(return_value={"mac": ""})):
        assert await client.get_console_mac() is None


@pytest.mark.asyncio()
async def test_get_console_mac_non_dict_returns_none() -> None:
    client = _public_only_client()
    with patch.object(client, "api_request", new=AsyncMock(return_value=None)):
        assert await client.get_console_mac() is None


@pytest.mark.asyncio()
async def test_get_console_mac_unreachable_returns_none() -> None:
    client = _public_only_client()
    with patch.object(
        client, "api_request", new=AsyncMock(side_effect=NvrError("unreachable"))
    ):
        assert await client.get_console_mac() is None


@pytest.mark.asyncio()
async def test_get_console_mac_timeout_returns_none() -> None:
    client = _public_only_client()
    with patch.object(client, "api_request", new=AsyncMock(side_effect=TimeoutError)):
        assert await client.get_console_mac() is None


@pytest.mark.asyncio()
async def test_resolve_nvr_mac_prefers_public_bootstrap() -> None:
    """Public bootstrap mac wins and skips the console call."""
    client = _public_only_client()
    client._public_bootstrap = Mock(nvr=Mock(mac="AA:BB:CC:DD:EE:FF"))
    client._bootstrap = Mock(nvr=Mock(mac="112233445566"))
    console = AsyncMock(return_value="778899AABBCC")
    with patch.object(client, "get_console_mac", new=console):
        assert await client.resolve_nvr_mac() == "aabbccddeeff"
    console.assert_not_awaited()


@pytest.mark.asyncio()
async def test_resolve_nvr_mac_falls_back_to_private_bootstrap() -> None:
    """A mac-less public nvr falls back to the private bootstrap mac."""
    client = _public_only_client()
    client._public_bootstrap = Mock(nvr=Mock(mac=None))
    client._bootstrap = Mock(nvr=Mock(mac="11:22:33:44:55:66"))
    console = AsyncMock(return_value="778899AABBCC")
    with patch.object(client, "get_console_mac", new=console):
        assert await client.resolve_nvr_mac() == "112233445566"
    console.assert_not_awaited()


@pytest.mark.asyncio()
async def test_resolve_nvr_mac_skips_public_when_nvr_absent() -> None:
    """A public bootstrap without an nvr falls back to the private mac."""
    client = _public_only_client()
    client._public_bootstrap = Mock(nvr=None)
    client._bootstrap = Mock(nvr=Mock(mac="11:22:33:44:55:66"))
    with patch.object(client, "get_console_mac", new=AsyncMock()):
        assert await client.resolve_nvr_mac() == "112233445566"


@pytest.mark.asyncio()
async def test_resolve_nvr_mac_falls_back_to_console() -> None:
    """With no bootstraps, the console mac is used and normalized."""
    client = _public_only_client()
    assert client._public_bootstrap is None
    assert client._bootstrap is None
    with patch.object(
        client, "get_console_mac", new=AsyncMock(return_value="E4:38:83:32:C9:B1")
    ):
        assert await client.resolve_nvr_mac() == "e4388332c9b1"


@pytest.mark.asyncio()
async def test_resolve_nvr_mac_returns_none_when_no_source() -> None:
    """Resolver returns None when no source yields a mac."""
    client = _public_only_client()
    with patch.object(client, "get_console_mac", new=AsyncMock(return_value=None)):
        assert await client.resolve_nvr_mac() is None


# ---------------------------------------------------------------------------
# Min-version source
# ---------------------------------------------------------------------------


def test_meta_info_version_is_parsed() -> None:
    meta = MetaInfo(application_version="7.0.104")
    assert meta.version == Version("7.0.104")
    assert meta.version >= Version("5.0.0")


def test_meta_info_from_unifi_dict_maps_wire_key() -> None:
    meta = MetaInfo.from_unifi_dict(applicationVersion="7.0.104")
    assert meta.application_version == "7.0.104"
    assert meta.version == Version("7.0.104")


# ---------------------------------------------------------------------------
# Session helpers short-circuit (no private username to key the store on)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_load_session_noop_public_only() -> None:
    client = _public_only_client()
    with patch.object(client, "get_session", new=AsyncMock()) as get_session:
        await client._load_session()
    get_session.assert_not_called()
    assert client._session is None
    assert client._loaded_session is False


@pytest.mark.asyncio()
async def test_clear_session_noop_public_only(tmp_path: Path) -> None:
    client = ProtectApiClient(
        "127.0.0.1",
        443,
        api_key=API_KEY,
        verify_ssl=False,
        config_dir=tmp_path,
    )
    assert client.is_public_only is True
    assert client.store_sessions is True

    await client.clear_session()

    assert not await aos.path.exists(client.config_file)
