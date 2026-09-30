"""Tests for ``subscribe_public_store_changes``."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from uiprotect.data import (
    ArmProfile,
    PublicBootstrap,
    PublicCamera,
    PublicLiveview,
    PublicStoreChange,
    PublicUlpUser,
    RTSPSStreams,
)
from uiprotect.data.types import DeviceState, ModelType, UlpUserStatus
from uiprotect.exceptions import NvrError

from .test_api_public import _liveview_raw, _mock_update_public_endpoints

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient
    from uiprotect.data import PublicStoreName

PROFILE_ID = "6878d82800155803e45928e0"
OTHER_ID = "p2"


def _profile_raw(name: str = "Night", profile_id: str = PROFILE_ID) -> dict[str, Any]:
    return {
        "id": profile_id,
        "name": name,
        "automations": ["a1"],
        "creator": "user-1",
        "schedules": [{"start": "0 22 * * *", "end": "0 6 * * *"}],
        "recordEverything": True,
        "activationDelay": 60000,
        "createdAt": "2026-04-23T18:15:43.213Z",
        "updatedAt": "2026-04-24T09:00:00.000Z",
    }


def _profile(client: ProtectApiClient, **kwargs: Any) -> ArmProfile:
    return ArmProfile.from_unifi_dict(**_profile_raw(**kwargs), api=client)


def _ulp_user(
    client: ProtectApiClient,
    user_id: str = "ulp-1",
    status: UlpUserStatus = UlpUserStatus.ACTIVE,
) -> PublicUlpUser:
    return PublicUlpUser(
        api=client,
        id=user_id,
        model=ModelType.ULP_USER,
        first_name="A",
        last_name="B",
        full_name="A B",
        status=status,
    )


def _change(
    store: PublicStoreName,
    *,
    added: set[str] | None = None,
    removed: set[str] | None = None,
    updated: set[str] | None = None,
) -> PublicStoreChange:
    return PublicStoreChange(
        store,
        frozenset(added or ()),
        frozenset(removed or ()),
        frozenset(updated or ()),
    )


@pytest.fixture
def changes(protect_client: ProtectApiClient) -> list[PublicStoreChange]:
    protect_client._public_bootstrap = PublicBootstrap()
    received: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(received.append)
    return received


async def _create(client: ProtectApiClient) -> ArmProfile:
    return await client.create_arm_profile_public(
        name="Night",
        automations=["a1"],
        schedules=[{"start": "0 22 * * *", "end": "0 6 * * *"}],
        record_everything=True,
        activation_delay=60000,
    )


@pytest.mark.asyncio()
async def test_create_then_resync_with_same_data_notifies_once(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    """A create announces the add; a resync returning the same profile is silent."""
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    await _create(protect_client)
    assert changes == [_change("arm_profiles", added={PROFILE_ID})]

    _mock_update_public_endpoints(
        protect_client,
        _fetch_arm_profiles=AsyncMock(return_value=[_profile(protect_client)]),
    )
    await protect_client.update_public()

    assert changes == [_change("arm_profiles", added={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_create_with_existing_identical_profile_is_silent(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    pb = protect_client.public_bootstrap
    pb.arm_profiles[PROFILE_ID] = _profile(protect_client)
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    await _create(protect_client)
    assert changes == []


@pytest.mark.asyncio()
async def test_create_keeps_other_profiles(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    pb = protect_client.public_bootstrap
    other = _profile(protect_client, profile_id=OTHER_ID)
    pb.arm_profiles[OTHER_ID] = other
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    await _create(protect_client)
    assert changes == [_change("arm_profiles", added={PROFILE_ID})]
    assert pb.arm_profiles[OTHER_ID] is other


@pytest.mark.asyncio()
async def test_update_setter_notifies_only_on_change(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    pb = protect_client.public_bootstrap
    pb.arm_profiles[PROFILE_ID] = _profile(protect_client)
    other = _profile(protect_client, profile_id=OTHER_ID)
    pb.arm_profiles[OTHER_ID] = other

    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    await protect_client.update_arm_profile_public(PROFILE_ID, name="Night")
    assert changes == []

    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw(name="Day"))
    await protect_client.update_arm_profile_public(PROFILE_ID, name="Day")
    assert changes == [_change("arm_profiles", updated={PROFILE_ID})]
    assert pb.arm_profiles[PROFILE_ID].name == "Day"
    assert pb.arm_profiles[OTHER_ID] is other


@pytest.mark.asyncio()
async def test_update_then_reconnect_resync_notifies_once(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    """A reconnect resync returning the updated profile does not re-announce it."""
    protect_client.public_bootstrap.arm_profiles[PROFILE_ID] = _profile(protect_client)
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw(name="Day"))
    await protect_client.update_arm_profile_public(PROFILE_ID, name="Day")
    assert changes == [_change("arm_profiles", updated={PROFILE_ID})]

    _mock_update_public_endpoints(
        protect_client,
        _fetch_arm_profiles=AsyncMock(
            return_value=[_profile(protect_client, name="Day")]
        ),
    )
    await protect_client._resync_public_bootstrap()

    assert changes == [_change("arm_profiles", updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_setter_during_resync_fetch_is_not_rolled_back(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    """A resync whose fetch predates a create leaves the created profile alone."""
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())

    async def _stale_fetch() -> list[ArmProfile]:
        await _create(protect_client)
        return []

    _mock_update_public_endpoints(
        protect_client, _fetch_arm_profiles=AsyncMock(side_effect=_stale_fetch)
    )
    await protect_client.update_public()

    assert changes == [_change("arm_profiles", added={PROFILE_ID})]
    assert PROFILE_ID in protect_client.public_bootstrap.arm_profiles

    _mock_update_public_endpoints(
        protect_client,
        _fetch_arm_profiles=AsyncMock(return_value=[_profile(protect_client)]),
    )
    await protect_client.update_public()

    assert changes == [_change("arm_profiles", added={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_delete_setter_notifies_only_on_change(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    pb = protect_client.public_bootstrap
    pb.arm_profiles[PROFILE_ID] = _profile(protect_client)
    protect_client.api_request_raw = AsyncMock(return_value=None)

    await protect_client.delete_arm_profile_public(PROFILE_ID)
    assert changes == [_change("arm_profiles", removed={PROFILE_ID})]
    assert pb.arm_profiles == {}

    await protect_client.delete_arm_profile_public(PROFILE_ID)
    assert len(changes) == 1


@pytest.mark.asyncio()
async def test_setters_without_bootstrap_notify_nothing(
    protect_client: ProtectApiClient,
) -> None:
    protect_client._public_bootstrap = None
    received: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(received.append)
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    protect_client.api_request_raw = AsyncMock(return_value=None)

    await _create(protect_client)
    await protect_client.delete_arm_profile_public(PROFILE_ID)

    assert received == []


@pytest.mark.asyncio()
async def test_get_arm_profiles_notifies_only_on_change(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    protect_client.api_request_list = AsyncMock(return_value=[_profile_raw()])
    await protect_client.get_arm_profiles_public()
    await protect_client.get_arm_profiles_public()
    assert changes == [_change("arm_profiles", added={PROFILE_ID})]

    protect_client.api_request_list = AsyncMock(return_value=[])
    await protect_client.get_arm_profiles_public()
    assert changes[1:] == [_change("arm_profiles", removed={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_resync_arm_profiles_notifies_only_on_change(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    def _resync(*profiles: ArmProfile) -> None:
        _mock_update_public_endpoints(
            protect_client, _fetch_arm_profiles=AsyncMock(return_value=list(profiles))
        )

    _resync(_profile(protect_client))
    await protect_client.update_public()
    _resync(_profile(protect_client))
    await protect_client.update_public()
    assert changes == [_change("arm_profiles", added={PROFILE_ID})]

    _resync(
        _profile(protect_client, name="Day"), _profile(protect_client, profile_id="p2")
    )
    await protect_client.update_public()
    assert changes[1:] == [_change("arm_profiles", added={"p2"}, updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_resync_ulp_users_notifies_only_on_change(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    def _resync(*users: PublicUlpUser) -> None:
        _mock_update_public_endpoints(
            protect_client, get_ulp_users_public=AsyncMock(return_value=list(users))
        )

    _resync(_ulp_user(protect_client), _ulp_user(protect_client, "ulp-2"))
    await protect_client.update_public()
    _resync(_ulp_user(protect_client), _ulp_user(protect_client, "ulp-2"))
    await protect_client.update_public()
    assert changes == [_change("ulp_users", added={"ulp-1", "ulp-2"})]

    _resync(_ulp_user(protect_client, status=UlpUserStatus.DEACTIVATED))
    await protect_client.update_public()
    assert changes[1:] == [_change("ulp_users", removed={"ulp-2"}, updated={"ulp-1"})]


@pytest.mark.asyncio()
async def test_first_prime_notifies(protect_client: ProtectApiClient) -> None:
    """The prime that materialises the bootstrap announces its stores too."""
    protect_client._public_bootstrap = None
    received: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(received.append)
    _mock_update_public_endpoints(
        protect_client,
        get_ulp_users_public=AsyncMock(return_value=[_ulp_user(protect_client)]),
        _fetch_arm_profiles=AsyncMock(return_value=[_profile(protect_client)]),
    )

    await protect_client.update_public()

    assert received == [
        _change("ulp_users", added={"ulp-1"}),
        _change("arm_profiles", added={PROFILE_ID}),
    ]


@pytest.mark.asyncio()
async def test_failed_endpoint_keeps_cache_and_notifies_nothing(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    pb = protect_client.public_bootstrap
    profile = _profile(protect_client)
    user = _ulp_user(protect_client)
    pb.arm_profiles[PROFILE_ID] = profile
    pb.ulp_users["ulp-1"] = user
    _mock_update_public_endpoints(
        protect_client,
        get_ulp_users_public=AsyncMock(side_effect=NvrError("timeout")),
        _fetch_arm_profiles=AsyncMock(side_effect=NvrError("timeout")),
    )

    await protect_client.update_public()

    assert changes == []
    assert pb.arm_profiles == {PROFILE_ID: profile}
    assert pb.ulp_users == {"ulp-1": user}


@pytest.mark.asyncio()
async def test_subscriber_error_is_logged_and_unsubscribe_works(
    protect_client: ProtectApiClient,
    changes: list[PublicStoreChange],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(_change: PublicStoreChange) -> None:
        raise RuntimeError("boom")

    unsub = protect_client.subscribe_public_store_changes(_boom)
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    with caplog.at_level(logging.ERROR):
        await _create(protect_client)
    assert "Exception while running public store handler" in caplog.text
    assert len(changes) == 1

    unsub()
    caplog.clear()
    protect_client.api_request_raw = AsyncMock(return_value=None)
    await protect_client.delete_arm_profile_public(PROFILE_ID)
    assert "public store handler" not in caplog.text
    assert len(changes) == 2


@pytest.mark.asyncio()
async def test_subscriber_unsubscribing_itself_does_not_skip_others(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    unsubs: list[Any] = []
    first: list[PublicStoreChange] = []

    def _once(change: PublicStoreChange) -> None:
        first.append(change)
        unsubs[0]()

    changes.clear()
    protect_client._public_store_subscriptions.clear()
    unsubs.append(protect_client.subscribe_public_store_changes(_once))
    protect_client.subscribe_public_store_changes(changes.append)
    protect_client.api_request_obj = AsyncMock(return_value=_profile_raw())
    await _create(protect_client)

    assert first == changes == [_change("arm_profiles", added={PROFILE_ID})]
    assert protect_client._public_store_subscriptions == [changes.append]


@pytest.mark.asyncio()
async def test_callback_sees_carried_forward_rtsps_streams(
    protect_client: ProtectApiClient, changes: list[PublicStoreChange]
) -> None:
    """A store-change callback never reads an emptied camera ``rtsps_streams``."""
    streams = RTSPSStreams(high="rtsps://example.com/cam1")
    protect_client.public_bootstrap.cameras["cam1"] = PublicCamera.model_construct(
        id="cam1", state=DeviceState.CONNECTED, rtsps_streams=streams
    )
    fresh = PublicCamera.model_construct(
        id="cam1", state=DeviceState.CONNECTED, rtsps_streams=None
    )
    seen: list[RTSPSStreams | None] = []
    protect_client.subscribe_public_store_changes(
        lambda _change: seen.append(
            protect_client.public_bootstrap.cameras["cam1"].rtsps_streams
        )
    )
    _mock_update_public_endpoints(
        protect_client,
        get_cameras_public=AsyncMock(return_value=[fresh]),
        _fetch_arm_profiles=AsyncMock(return_value=[_profile(protect_client)]),
    )

    await protect_client.update_public()

    assert len(changes) == 1
    assert seen == [streams]


def test_apply_store_mutates_in_place(protect_client: ProtectApiClient) -> None:
    pb = PublicBootstrap()
    store = pb.arm_profiles
    first = _profile(protect_client)

    assert pb.apply_store("arm_profiles", [first]) == _change(
        "arm_profiles", added={PROFILE_ID}
    )
    assert pb.apply_store("arm_profiles", [_profile(protect_client)]) is None
    assert pb.apply_store("arm_profiles", [], removed_ids=["missing"]) is None
    assert pb.apply_store("arm_profiles", [], replace=True) == _change(
        "arm_profiles", removed={PROFILE_ID}
    )
    assert pb.arm_profiles is store
    assert store == {}


def _liveview(
    client: ProtectApiClient, liveview_id: str = "lv-1", name: str = "Garage"
) -> PublicLiveview:
    return PublicLiveview.from_unifi_dict(
        **_liveview_raw(id=liveview_id, name=name), api=client
    )


@pytest.mark.asyncio()
async def test_liveview_refresh_announces_add_remove_and_rename(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(
        protect_client,
        _fetch_liveviews=AsyncMock(
            return_value=[_liveview(protect_client), _liveview(protect_client, "lv-2")]
        ),
    )
    await protect_client.update_public()
    changes: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(changes.append)

    protect_client._fetch_liveviews = AsyncMock(
        return_value=[
            _liveview(protect_client, name="Renamed"),
            _liveview(protect_client, "lv-3"),
        ]
    )
    await protect_client.refresh_public_store("liveviews")
    assert changes == [
        _change("liveviews", added={"lv-3"}, removed={"lv-2"}, updated={"lv-1"})
    ]
    assert protect_client.public_bootstrap.liveviews["lv-1"].name == "Renamed"

    await protect_client.refresh_public_store("liveviews")
    assert len(changes) == 1


@pytest.mark.asyncio()
async def test_update_public_announces_liveview_prime(
    protect_client: ProtectApiClient,
) -> None:
    changes: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(changes.append)
    _mock_update_public_endpoints(
        protect_client,
        _fetch_liveviews=AsyncMock(return_value=[_liveview(protect_client)]),
    )
    await protect_client.update_public()
    assert changes == [_change("liveviews", added={"lv-1"})]


@pytest.mark.asyncio()
async def test_refresh_public_store_drops_result_after_setter_write(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(protect_client)
    await protect_client.update_public()
    release = asyncio.Event()

    async def _stale() -> list[PublicLiveview]:
        await release.wait()
        return []

    protect_client._fetch_liveviews = AsyncMock(side_effect=_stale)
    refresh = asyncio.create_task(protect_client.refresh_public_store("liveviews"))
    await asyncio.sleep(0)

    protect_client.api_request_obj = AsyncMock(return_value=_liveview_raw(id="lv-1"))
    await protect_client.get_liveview_public("lv-1")
    release.set()
    await refresh
    assert list(protect_client.public_bootstrap.liveviews) == ["lv-1"]


@pytest.mark.asyncio()
async def test_refresh_public_store_rejects_unknown_store(
    protect_client: ProtectApiClient,
) -> None:
    with pytest.raises(ValueError, match="Unknown public store"):
        await protect_client.refresh_public_store("cameras")  # type: ignore[arg-type]


@pytest.mark.asyncio()
async def test_get_liveviews_public_keeps_newer_setter_write(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(protect_client)
    await protect_client.update_public()
    changes: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(changes.append)
    release = asyncio.Event()

    async def _stale() -> list[PublicLiveview]:
        await release.wait()
        return []

    protect_client._fetch_liveviews = AsyncMock(side_effect=_stale)
    getter = asyncio.create_task(protect_client.get_liveviews_public())
    await asyncio.sleep(0)

    protect_client.api_request_obj = AsyncMock(return_value=_liveview_raw(id="lv-1"))
    await protect_client.get_liveview_public("lv-1")
    release.set()
    assert await getter == []
    assert list(protect_client.public_bootstrap.liveviews) == ["lv-1"]
    assert changes == [_change("liveviews", added={"lv-1"})]


@pytest.mark.asyncio()
async def test_liveview_writes_announce_changes(
    protect_client: ProtectApiClient,
) -> None:
    _mock_update_public_endpoints(protect_client)
    await protect_client.update_public()
    changes: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(changes.append)

    protect_client.api_request_obj = AsyncMock(return_value=_liveview_raw(id="lv-1"))
    await protect_client.create_liveview_public(
        name="Garage",
        is_default=False,
        is_global=True,
        owner="u1",
        layout=1,
        slots=[],
    )
    await protect_client.get_liveview_public("lv-1")
    protect_client.api_request_obj = AsyncMock(
        return_value=_liveview_raw(id="lv-1", name="Renamed")
    )
    await protect_client.update_liveview_public("lv-1", name="Renamed")

    assert changes == [
        _change("liveviews", added={"lv-1"}),
        _change("liveviews", updated={"lv-1"}),
    ]
