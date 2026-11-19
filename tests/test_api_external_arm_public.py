"""Public API external (global) alarm-manager arm profiles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock

import orjson
import pytest

from tests.conftest import read_json_file
from uiprotect.api import ProtectApiClient
from uiprotect.data import ExternalArmProfile, ExternalArmProfileState
from uiprotect.exceptions import BadRequest

PROFILE_ID = "6a1b2c3d4e5f60718293a4b5"
BASE = "/proxy/protect/integration/v1/external/arm-profiles"


@pytest.fixture(name="protect_client")
def protect_client_fixture() -> ProtectApiClient:
    return ProtectApiClient.public_only("127.0.0.1", 0, api_key="key")


def _profile(**overrides: Any) -> dict[str, Any]:
    return {**read_json_file("sample_external_arm_profiles")[0], **overrides}


def _response(status: int, body: Any) -> Mock:
    response = Mock(status=status, url="https://127.0.0.1/x", reason="reason")
    response.read = AsyncMock(return_value=orjson.dumps(body))
    response.json = AsyncMock(return_value=body)
    return response


def _mock_request(
    client: ProtectApiClient, status: int = 200, body: Any = None
) -> AsyncMock:
    request = AsyncMock(return_value=_response(status, body))
    client.request = request  # type: ignore[method-assign]
    return request


def _assert_requested(request: AsyncMock, method: str, url: str) -> None:
    request.assert_awaited_once()
    args, kwargs = request.call_args
    assert args == (method, url)
    assert kwargs["public_api"] is True
    assert "json" not in kwargs


@pytest.mark.asyncio()
async def test_get_external_arm_profiles(protect_client: ProtectApiClient) -> None:
    """The list endpoint parses every profile."""
    request = _mock_request(
        protect_client, body=read_json_file("sample_external_arm_profiles")
    )

    profiles = await protect_client.get_external_arm_profiles_public()

    _assert_requested(request, "get", BASE)
    assert [p.id for p in profiles] == [PROFILE_ID]
    assert isinstance(profiles[0], ExternalArmProfile)
    assert profiles[0].state is ExternalArmProfileState.DISARMED
    assert profiles[0].api is protect_client


@pytest.mark.asyncio()
async def test_get_external_arm_profile(protect_client: ProtectApiClient) -> None:
    """The single fetch hits the profile path."""
    request = _mock_request(protect_client, body=_profile())

    profile = await protect_client.get_external_arm_profile_public(PROFILE_ID)

    _assert_requested(request, "get", f"{BASE}/{PROFILE_ID}")
    assert profile.id == PROFILE_ID
    assert profile.title == "test"


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("method", "action", "body", "state", "due_at"),
    [
        (
            "arm_external_arm_profile_public",
            "arm",
            _profile(state="armed"),
            ExternalArmProfileState.ARMED,
            None,
        ),
        (
            "arm_external_arm_profile_public",
            "arm",
            _profile(
                state="arming",
                activation_delay=30,
                state_promotion_due_at="2026-11-19T10:00:30Z",
            ),
            ExternalArmProfileState.ARMING,
            datetime(2026, 11, 19, 10, 0, 30, tzinfo=UTC),
        ),
        (
            "disarm_external_arm_profile_public",
            "disarm",
            _profile(state="disarmed"),
            ExternalArmProfileState.DISARMED,
            None,
        ),
    ],
    ids=["armed", "arming", "disarmed"],
)
async def test_external_arm_action_returns_response_profile(
    protect_client: ProtectApiClient,
    method: str,
    action: str,
    body: dict[str, Any],
    state: ExternalArmProfileState,
    due_at: datetime | None,
) -> None:
    """Arm/disarm POST without a body and return the profile from the response."""
    request = _mock_request(protect_client, body=body)

    profile = await getattr(protect_client, method)(PROFILE_ID)

    _assert_requested(request, "post", f"{BASE}/{PROFILE_ID}/actions/{action}")
    assert profile.id == PROFILE_ID
    assert profile.state is state
    assert profile.state_promotion_due_at == due_at


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("status", "error"),
    [(400, "Invalid external arm profile request"), (404, "Not Found")],
    ids=["no-alarms", "protect-7.3"],
)
@pytest.mark.parametrize(
    "method",
    [
        "get_external_arm_profile_public",
        "arm_external_arm_profile_public",
        "disarm_external_arm_profile_public",
    ],
)
async def test_external_arm_errors_raise_bad_request(
    protect_client: ProtectApiClient, method: str, status: int, error: str
) -> None:
    """A 400 or 404 surfaces as ``BadRequest``."""
    _mock_request(protect_client, status=status, body={"error": error})

    with pytest.raises(BadRequest, match=error):
        await getattr(protect_client, method)(PROFILE_ID)


@pytest.mark.asyncio()
async def test_get_external_arm_profiles_404_raises_bad_request(
    protect_client: ProtectApiClient,
) -> None:
    """The list endpoint is missing on Protect 7.3 and raises ``BadRequest``."""
    _mock_request(protect_client, status=404, body={"error": "Not Found"})

    with pytest.raises(BadRequest):
        await protect_client.get_external_arm_profiles_public()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("model_method", "action", "state"),
    [("arm", "arm", "armed"), ("disarm", "disarm", "disarmed")],
)
async def test_model_action_does_not_mutate_self(
    protect_client: ProtectApiClient, model_method: str, action: str, state: str
) -> None:
    """``arm``/``disarm`` return the response profile and leave ``self`` as is."""
    start = "disarmed" if action == "arm" else "armed"
    profile = ExternalArmProfile.from_unifi_dict(
        **_profile(state=start), api=protect_client
    )
    before = profile.unifi_dict()
    request = _mock_request(protect_client, body=_profile(state=state))

    result = await getattr(profile, model_method)()

    _assert_requested(request, "post", f"{BASE}/{PROFILE_ID}/actions/{action}")
    assert result is not profile
    assert result.state is ExternalArmProfileState(state)
    assert profile.state is ExternalArmProfileState(start)
    assert profile.unifi_dict() == before
