"""Tests for the public-only (API-key-only) ProtectApiClient mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data import PublicBootstrap
from uiprotect.data.nvr import MetaInfo
from uiprotect.data.types import Version
from uiprotect.exceptions import BadRequest, NotAuthorized, PublicOnlyModeError

from .test_api_public import _mock_update_public_endpoints

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
    with patch.object(client, "authenticate", new=AsyncMock()) as authenticate:
        result = await client.update_public()
    assert isinstance(result, PublicBootstrap)
    assert client.has_public_bootstrap is True
    authenticate.assert_not_called()


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
# Min-version source
# ---------------------------------------------------------------------------


def test_meta_info_version_is_parsed() -> None:
    meta = MetaInfo(applicationVersion="7.0.104")
    assert meta.version == Version("7.0.104")
    assert meta.version >= Version("5.0.0")
