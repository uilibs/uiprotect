"""Tests for the global alarm manager: external arm profiles and alarm-hub refetch."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import orjson
import pytest

from uiprotect.data import (
    ExternalArmProfile,
    ExternalArmProfileState,
    PublicBootstrap,
    PublicNVR,
    PublicStoreChange,
)
from uiprotect.data.public_devices import _parse_iso_datetime
from uiprotect.exceptions import BadRequest, ConflictError, NvrError
from uiprotect.websocket import WebsocketState

from .test_api_public import _mock_update_public_endpoints

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient

PROFILE_ID = "0193f0c2-aaaa-7bbb-8ccc-000000000001"
OTHER_ID = "0193f0c2-aaaa-7bbb-8ccc-000000000002"
STORE = "external_arm_profiles"


async def _hang(*_args: Any, **_kwargs: Any) -> None:
    await asyncio.sleep(60)


def _profile_raw(profile_id: str = PROFILE_ID, **extra: Any) -> dict[str, Any]:
    return {
        "id": profile_id,
        "title": "Away",
        "alarm_ids": ["alarm-1"],
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-02T10:00:00Z",
        "state": "disarmed",
        "state_set_at": "2026-11-12T03:00:00Z",
        "has_pin": False,
        "activation_delay": 60,
        **extra,
    }


def _profile(client: ProtectApiClient, **extra: Any) -> ExternalArmProfile:
    return ExternalArmProfile.from_unifi_dict(**_profile_raw(**extra), api=client)


def _frame(action: str, **item: Any) -> aiohttp.WSMessage:
    payload = {"type": action, "item": {"modelKey": "externalArmProfile", **item}}
    return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, orjson.dumps(payload), None)


def _change(
    *,
    added: set[str] | None = None,
    removed: set[str] | None = None,
    updated: set[str] | None = None,
) -> PublicStoreChange:
    return PublicStoreChange(
        STORE,
        frozenset(added or ()),
        frozenset(removed or ()),
        frozenset(updated or ()),
    )


@pytest.fixture
def pb(protect_client: ProtectApiClient) -> PublicBootstrap:
    protect_client._public_bootstrap = PublicBootstrap()
    return protect_client._public_bootstrap


@pytest.fixture
def changes(protect_client: ProtectApiClient, pb: PublicBootstrap) -> list[Any]:
    received: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(received.append)
    return received


def test_profile_parses_wire_payload(protect_client: ProtectApiClient) -> None:
    profile = _profile(
        protect_client,
        state="arming",
        state_promotion_due_at="2026-11-12T03:01:22.772174589Z",
    )
    assert profile.state is ExternalArmProfileState.ARMING
    assert profile.alarm_ids == ["alarm-1"]
    assert profile.state_set_at == datetime(2026, 11, 12, 3, 0, tzinfo=UTC)
    assert profile.state_promotion_due_at == datetime(
        2026, 11, 12, 3, 1, 22, 772174, tzinfo=UTC
    )
    assert profile.is_armed is False


@pytest.mark.parametrize(
    ("state", "armed"),
    [("armed", True), ("breaching", True), ("breached", True), ("disarmed", False)],
)
def test_profile_is_armed(
    protect_client: ProtectApiClient, state: str, armed: bool
) -> None:
    assert _profile(protect_client, state=state).is_armed is armed


def test_profile_unknown_state_coerces(protect_client: ProtectApiClient) -> None:
    profile = _profile(protect_client, state="snoozed")
    assert profile.state is ExternalArmProfileState.UNKNOWN


def test_profile_merged_applies_partial(protect_client: ProtectApiClient) -> None:
    profile = _profile(
        protect_client,
        state="arming",
        state_promotion_due_at="2026-11-12T03:01:00Z",
    )
    merged = profile.merged(
        {
            "id": PROFILE_ID,
            "modelKey": "externalArmProfile",
            "state": "armed",
            "state_promotion_due_at": None,
        }
    )
    assert merged.state is ExternalArmProfileState.ARMED
    assert merged.state_promotion_due_at is None
    assert merged.title == "Away"
    assert profile.state is ExternalArmProfileState.ARMING


def test_nvr_feature_flags_drive_external_mode(
    protect_client: ProtectApiClient,
) -> None:
    pb = PublicBootstrap()
    assert pb.uses_external_alarm_manager is False
    raw = {"id": "nvr", "modelKey": "nvr", "armMode": {"status": "disabled"}}
    pb.nvr = PublicNVR.from_unifi_dict(**raw, api=protect_client)
    assert pb.uses_external_alarm_manager is False
    pb.nvr = PublicNVR.from_unifi_dict(
        **raw, featureFlags={"useExternalAlarmManager": True}, api=protect_client
    )
    assert pb.uses_external_alarm_manager is True


@pytest.mark.asyncio()
async def test_get_profiles_fills_store(
    protect_client: ProtectApiClient, pb: PublicBootstrap, changes: list[Any]
) -> None:
    protect_client.api_request_list = AsyncMock(return_value=[_profile_raw()])
    profiles = await protect_client.get_external_arm_profiles_public()
    protect_client.api_request_list.assert_awaited_once_with(
        url="/v1/external/arm-profiles", public_api=True
    )
    assert [p.id for p in profiles] == [PROFILE_ID]
    assert pb.external_arm_profiles[PROFILE_ID] is profiles[0]
    assert changes == [_change(added={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_get_profiles_drops_result_stale_by_a_write(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    async def _fetch(**_kwargs: Any) -> list[dict[str, Any]]:
        protect_client._apply_public_store(
            STORE, [_profile(protect_client, state="armed")]
        )
        return [_profile_raw()]

    protect_client.api_request_list = _fetch  # type: ignore[method-assign]
    await protect_client.get_external_arm_profiles_public()
    assert pb.external_arm_profiles[PROFILE_ID].state is ExternalArmProfileState.ARMED


@pytest.mark.asyncio()
async def test_get_profile(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    profile = await protect_client.get_external_arm_profile_public(PROFILE_ID)
    protect_client.api_request_obj.assert_awaited_once_with(
        url=f"/v1/external/arm-profiles/{PROFILE_ID}", public_api=True
    )
    assert pb.external_arm_profiles[PROFILE_ID] is profile


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("method", "action", "state"),
    [
        ("arm_external_arm_profile_public", "arm", "arming"),
        ("disarm_external_arm_profile_public", "disarm", "disarmed"),
    ],
)
async def test_arm_and_disarm_post_and_store(
    protect_client: ProtectApiClient,
    pb: PublicBootstrap,
    changes: list[Any],
    method: str,
    action: str,
    state: str,
) -> None:
    pb.external_arm_profiles[PROFILE_ID] = _profile(protect_client, state="armed")
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw(state=state))
    profile = await getattr(protect_client, method)(PROFILE_ID)
    protect_client.api_request_obj.assert_awaited_once_with(
        url=f"/v1/external/arm-profiles/{PROFILE_ID}/actions/{action}",
        method="post",
        public_api=True,
    )
    assert profile.state is ExternalArmProfileState(state)
    assert pb.external_arm_profiles[PROFILE_ID] is profile
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_update_public_loads_profiles(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(
        protect_client,
        _fetch_external_arm_profiles=AsyncMock(return_value=[_profile(protect_client)]),
    )
    pb = await protect_client.update_public()
    assert list(pb.external_arm_profiles) == [PROFILE_ID]


@pytest.mark.asyncio()
async def test_update_public_tolerates_missing_endpoint(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(
        protect_client,
        _fetch_external_arm_profiles=AsyncMock(side_effect=BadRequest("404")),
    )
    pb = await protect_client.update_public()
    assert pb.external_arm_profiles == {}


def test_update_frame_merges_and_notifies(
    protect_client: ProtectApiClient, pb: PublicBootstrap, changes: list[Any]
) -> None:
    pb.external_arm_profiles[PROFILE_ID] = _profile(protect_client)
    protect_client._process_updates_ws_message(
        _frame("update", id=PROFILE_ID, state="armed", state_promotion_due_at=None)
    )
    profile = pb.external_arm_profiles[PROFILE_ID]
    assert profile.state is ExternalArmProfileState.ARMED
    assert profile.title == "Away"
    assert changes == [_change(updated={PROFILE_ID})]


def test_bulk_update_frame_applies_to_every_id(
    protect_client: ProtectApiClient, pb: PublicBootstrap, changes: list[Any]
) -> None:
    pb.external_arm_profiles[PROFILE_ID] = _profile(protect_client)
    pb.external_arm_profiles[OTHER_ID] = _profile(protect_client, profile_id=OTHER_ID)
    protect_client._process_updates_ws_message(
        _frame("update", id=[PROFILE_ID, OTHER_ID], state="armed")
    )
    assert {p.state for p in pb.external_arm_profiles.values()} == {
        ExternalArmProfileState.ARMED
    }
    assert changes == [_change(updated={PROFILE_ID, OTHER_ID})]


def test_add_and_remove_frames(
    protect_client: ProtectApiClient, pb: PublicBootstrap, changes: list[Any]
) -> None:
    protect_client._process_updates_ws_message(_frame("add", **_profile_raw()))
    assert pb.external_arm_profiles[PROFILE_ID].title == "Away"
    protect_client._process_updates_ws_message(_frame("remove", id=PROFILE_ID))
    assert pb.external_arm_profiles == {}
    assert changes == [_change(added={PROFILE_ID}), _change(removed={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_update_for_unknown_profile_refetches(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    protect_client.api_request_list = AsyncMock(
        return_value=[_profile_raw(state="armed")]
    )
    protect_client._process_updates_ws_message(
        _frame("update", id=PROFILE_ID, state="armed")
    )
    task = protect_client._external_arm_profile_resync_task
    assert task is not None
    # A second trigger while the refetch runs does not start another.
    protect_client._start_external_arm_profile_resync()
    assert protect_client._external_arm_profile_resync_task is task
    await task
    assert pb.external_arm_profiles[PROFILE_ID].state is ExternalArmProfileState.ARMED


@pytest.mark.parametrize(
    "msg",
    [
        aiohttp.WSMessage(aiohttp.WSMsgType.BINARY, b"x", None),
        aiohttp.WSMessage(
            aiohttp.WSMsgType.TEXT,
            orjson.dumps({"type": "update", "item": {"modelKey": "camera"}}),
            None,
        ),
        aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, b"not json", None),
    ],
)
def test_irrelevant_or_broken_frames_are_ignored(
    protect_client: ProtectApiClient,
    pb: PublicBootstrap,
    changes: list[Any],
    msg: aiohttp.WSMessage,
) -> None:
    protect_client._process_updates_ws_message(msg)
    assert changes == []


def test_frame_without_bootstrap_is_ignored(protect_client: ProtectApiClient) -> None:
    protect_client._public_bootstrap = None
    protect_client._process_updates_ws_message(_frame("update", id=PROFILE_ID))


def test_frame_is_buffered_during_prime(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    protect_client._prime_ws_buffer = []
    msg = _frame("add", **_profile_raw())
    protect_client._process_updates_ws_message(msg)
    assert protect_client._prime_ws_buffer == [
        (protect_client._process_updates_ws_message, msg)
    ]
    assert pb.external_arm_profiles == {}


def test_subscribe_holds_updates_websocket_open(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    websocket = Mock()
    received: list[PublicStoreChange] = []
    with patch.object(protect_client, "_get_updates_websocket", return_value=websocket):
        unsub_a = protect_client.subscribe_external_arm_profiles(received.append)
        unsub_b = protect_client.subscribe_external_arm_profiles(Mock())
        assert websocket.start.call_count == 2

        protect_client._emit_public_store_change(
            PublicStoreChange("liveviews", frozenset({"x"}), frozenset(), frozenset())
        )
        protect_client._process_updates_ws_message(_frame("add", **_profile_raw()))
        assert received == [_change(added={PROFILE_ID})]

        unsub_a()
        websocket.stop.assert_not_called()
        unsub_b()
        websocket.stop.assert_called_once()


def test_updates_websocket_url_and_state(protect_client: ProtectApiClient) -> None:
    assert protect_client.updates_websocket_state is WebsocketState.DISCONNECTED
    websocket = protect_client._get_updates_websocket()
    assert protect_client._get_updates_websocket() is websocket
    url = protect_client._updates_ws_url
    assert url.path == "/proxy/protect/integration/v1/subscribe/updates"
    assert url.query["modelKeys"] == "externalArmProfile"


@pytest.mark.asyncio()
async def test_default_port_updates_url() -> None:
    from uiprotect import ProtectApiClient  # noqa: PLC0415

    client = ProtectApiClient("127.0.0.1", 443, api_key="key", store_sessions=False)
    assert str(client._updates_ws_url) == (
        "https://127.0.0.1/proxy/protect/integration/v1/subscribe/updates"
        "?modelKeys=externalArmProfile"
    )


@pytest.mark.asyncio()
async def test_reconnect_refetches_profiles(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    protect_client.api_request_list = AsyncMock(return_value=[_profile_raw()])
    protect_client._on_updates_websocket_state_change(WebsocketState.DISCONNECTED)
    protect_client._on_updates_websocket_state_change(WebsocketState.CONNECTED)
    assert protect_client._external_arm_profile_resync_task is None
    protect_client._on_updates_websocket_state_change(WebsocketState.CONNECTED)
    task = protect_client._external_arm_profile_resync_task
    assert task is not None
    await task
    assert PROFILE_ID in pb.external_arm_profiles


@pytest.mark.asyncio()
async def test_resync_failure_is_swallowed(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    protect_client.api_request_list = AsyncMock(side_effect=NvrError("down"))
    protect_client._start_external_arm_profile_resync()
    task = protect_client._external_arm_profile_resync_task
    assert task is not None
    await task
    assert pb.external_arm_profiles == {}


@pytest.mark.asyncio()
async def test_promotion_due_schedules_refetch(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    due = datetime.now(UTC) + timedelta(seconds=30)
    protect_client.api_request_obj = AsyncMock(
        return_value=_profile_raw(
            state="arming", state_promotion_due_at=due.isoformat()
        )
    )
    await protect_client.arm_external_arm_profile_public(PROFILE_ID)
    timer = protect_client._external_arm_profile_promotion_timer
    assert timer is not None
    assert 25 < timer.when() - asyncio.get_running_loop().time() < 35

    protect_client._process_updates_ws_message(
        _frame("update", id=PROFILE_ID, state="armed", state_promotion_due_at=None)
    )
    assert timer.cancelled()
    assert protect_client._external_arm_profile_promotion_timer is None


@pytest.mark.asyncio()
async def test_long_overdue_promotion_is_not_rescheduled(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    due = datetime.now(UTC) - timedelta(minutes=5)
    pb.external_arm_profiles[PROFILE_ID] = _profile(
        protect_client, state="arming", state_promotion_due_at=due.isoformat()
    )
    protect_client._schedule_external_arm_profile_promotion()
    assert protect_client._external_arm_profile_promotion_timer is None


def test_promotion_without_running_loop_is_skipped(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    due = datetime.now(UTC) + timedelta(seconds=30)
    pb.external_arm_profiles[PROFILE_ID] = _profile(
        protect_client, state="arming", state_promotion_due_at=due.isoformat()
    )
    protect_client._schedule_external_arm_profile_promotion()
    assert protect_client._external_arm_profile_promotion_timer is None


@pytest.mark.asyncio()
async def test_disconnect_stops_updates_websocket_and_tasks(
    protect_client: ProtectApiClient, pb: PublicBootstrap
) -> None:
    websocket = Mock(wait_closed=AsyncMock())
    protect_client._updates_websocket = websocket
    due = datetime.now(UTC) + timedelta(seconds=30)
    pb.external_arm_profiles[PROFILE_ID] = _profile(
        protect_client, state="arming", state_promotion_due_at=due.isoformat()
    )
    protect_client._schedule_external_arm_profile_promotion()
    timer = protect_client._external_arm_profile_promotion_timer
    assert timer is not None
    protect_client.api_request_list = AsyncMock(side_effect=_hang)
    protect_client._start_external_arm_profile_resync()
    resync = protect_client._external_arm_profile_resync_task
    assert resync is not None

    await protect_client.async_disconnect_ws()

    websocket.stop.assert_called_once()
    assert protect_client._updates_websocket is None
    assert timer.cancelled()
    assert resync.cancelled()


def test_set_api_key_resets_updates_websocket(
    protect_client: ProtectApiClient,
) -> None:
    websocket = Mock()
    protect_client._updates_websocket = websocket
    protect_client.set_api_key("new-key")
    websocket.reset_auth_failure.assert_called_once()
    protect_client._updates_websocket = None


def test_parse_iso_datetime_passes_through_parsed_values() -> None:
    now = datetime.now(UTC)
    assert _parse_iso_datetime(now) is now
    assert _parse_iso_datetime(None) is None


@pytest.mark.asyncio()
async def test_conflict_status_raises_conflict_error(
    protect_client: ProtectApiClient,
) -> None:
    response = Mock(status=409, url="https://test.com/x")
    with (
        patch(
            "uiprotect.api.get_response_reason",
            return_value="External arm profile state conflict",
        ),
        pytest.raises(ConflictError),
    ):
        await protect_client._raise_for_status(response, raise_exception=True)
