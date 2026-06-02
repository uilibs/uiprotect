"""Tests for the Public API user / ULP-user endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tests.conftest import read_json_file
from uiprotect.data import PublicUlpUser, PublicUser, UlpUserStatus
from uiprotect.data.types import ModelType

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient

USER_ID = "u1"
ULP_USER_ID = "ulp-1"


@pytest.mark.asyncio()
async def test_get_users_public_calls_correct_url(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_list = AsyncMock(return_value=[])

    result = await protect_client.get_users_public()

    assert result == []
    protect_client.api_request_list.assert_called_once_with(
        url="/v1/users", public_api=True
    )


@pytest.mark.asyncio()
async def test_get_user_public_calls_correct_url(
    protect_client: ProtectApiClient,
) -> None:
    payload = {
        "id": USER_ID,
        "modelKey": "user",
        "name": "John Doe",
        "firstName": "John",
        "lastName": "Doe",
        "email": "john@example.com",
        "ucoreUserId": "ucore-1",
    }
    protect_client.api_request_obj = AsyncMock(return_value=payload)

    result = await protect_client.get_user_public(USER_ID)

    assert isinstance(result, PublicUser)
    assert result.id == USER_ID
    assert result.model is ModelType.USER
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/users/{USER_ID}", public_api=True
    )


@pytest.mark.asyncio()
async def test_public_user_parses_minimal_payload(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    """All four optional spec fields may legitimately be ``null`` on the wire."""
    payload = {
        "id": USER_ID,
        "modelKey": "user",
        "name": "Anonymous",
        "firstName": None,
        "lastName": None,
        "email": None,
        "ucoreUserId": None,
    }
    protect_client_no_debug.api_request_obj = AsyncMock(return_value=payload)

    user = await protect_client_no_debug.get_user_public(USER_ID)

    assert user.first_name is None
    assert user.last_name is None
    assert user.email is None
    assert user.ucore_user_id is None
    assert user.name == "Anonymous"


@pytest.mark.asyncio()
async def test_get_users_public_parses_list(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    payload = [
        {
            "id": "u1",
            "modelKey": "user",
            "name": "A B",
            "firstName": "A",
            "lastName": "B",
            "email": None,
            "ucoreUserId": None,
        },
        {
            "id": "u2",
            "modelKey": "user",
            "name": "C D",
            "firstName": "C",
            "lastName": "D",
            "email": "c.d@example.com",
            "ucoreUserId": "ucore-2",
        },
    ]
    protect_client_no_debug.api_request_list = AsyncMock(return_value=payload)

    users = await protect_client_no_debug.get_users_public()

    assert [u.id for u in users] == ["u1", "u2"]
    assert all(isinstance(u, PublicUser) for u in users)


@pytest.mark.asyncio()
async def test_get_ulp_users_public_calls_correct_url(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_list = AsyncMock(return_value=[])

    result = await protect_client.get_ulp_users_public()

    assert result == []
    protect_client.api_request_list.assert_called_once_with(
        url="/v1/ulp-users", public_api=True
    )


@pytest.mark.asyncio()
async def test_get_ulp_user_public_calls_correct_url(
    protect_client: ProtectApiClient,
) -> None:
    payload = {
        "id": ULP_USER_ID,
        "modelKey": "ulpUser",
        "firstName": "John",
        "lastName": "Doe",
        "fullName": "John Doe",
        "status": "ACTIVE",
    }
    protect_client.api_request_obj = AsyncMock(return_value=payload)

    result = await protect_client.get_ulp_user_public(ULP_USER_ID)

    assert isinstance(result, PublicUlpUser)
    assert result.id == ULP_USER_ID
    assert result.model is ModelType.ULP_USER
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/ulp-users/{ULP_USER_ID}", public_api=True
    )


@pytest.mark.asyncio()
async def test_public_ulp_user_parses_minimal_payload(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    payload = {
        "id": ULP_USER_ID,
        "modelKey": "ulpUser",
        "firstName": "John",
        "lastName": "Doe",
        "fullName": "John Doe",
        "status": "DEACTIVATED",
    }
    protect_client_no_debug.api_request_obj = AsyncMock(return_value=payload)

    user = await protect_client_no_debug.get_ulp_user_public(ULP_USER_ID)

    assert user.first_name == "John"
    assert user.last_name == "Doe"
    assert user.full_name == "John Doe"
    assert user.status is UlpUserStatus.DEACTIVATED


def test_public_ulp_user_status_round_trip_from_fixture() -> None:
    payload = read_json_file("sample_ulp_users")
    active_raw = next(p for p in payload if p["status"] == "ACTIVE")
    deactivated_raw = next(p for p in payload if p["status"] == "DEACTIVATED")

    active = PublicUlpUser.from_unifi_dict(**active_raw)
    deactivated = PublicUlpUser.from_unifi_dict(**deactivated_raw)

    assert active.status is UlpUserStatus.ACTIVE
    assert deactivated.status is UlpUserStatus.DEACTIVATED

    assert active.unifi_dict()["status"] == "ACTIVE"
    assert deactivated.unifi_dict()["status"] == "DEACTIVATED"


def test_public_ulp_user_status_accepts_unknown_value() -> None:
    payload = {
        "id": ULP_USER_ID,
        "modelKey": "ulpUser",
        "firstName": "John",
        "lastName": "Doe",
        "fullName": "John Doe",
        "status": "SUSPENDED",
    }

    user = PublicUlpUser.from_unifi_dict(**payload)

    assert user.status is UlpUserStatus.UNKNOWN
