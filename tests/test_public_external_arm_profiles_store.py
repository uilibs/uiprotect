"""Tests for the ``external_arm_profiles`` public store."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from tests.conftest import read_json_file
from uiprotect.data import ExternalArmProfile, PublicNVR, PublicStoreChange
from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError

from .test_api_public import _NVR_RAW_BASE, _mock_update_public_endpoints

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient

PROFILE_ID = "6a1b2c3d4e5f60718293a4b5"
STORE = "external_arm_profiles"


def _raw(**overrides: Any) -> dict[str, Any]:
    return {**read_json_file("sample_external_arm_profiles")[0], **overrides}


def _profile(client: ProtectApiClient, **overrides: Any) -> ExternalArmProfile:
    return ExternalArmProfile.from_unifi_dict(**_raw(**overrides), api=client)


def _nvr(client: ProtectApiClient, flag: bool | None) -> PublicNVR:
    raw = deepcopy(_NVR_RAW_BASE)
    if flag is not None:
        raw["featureFlags"] = {"useExternalAlarmManager": flag}
    return PublicNVR.from_unifi_dict(**raw, api=client)


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


async def _prime(
    client: ProtectApiClient, flag: bool | None, *, profiles: bool = True
) -> list[PublicStoreChange]:
    _mock_update_public_endpoints(
        client,
        get_nvr_public=AsyncMock(return_value=_nvr(client, flag)),
        _fetch_external_arm_profiles=AsyncMock(
            return_value=[_profile(client)] if profiles else []
        ),
    )
    await client.update_public()
    changes: list[PublicStoreChange] = []
    client.subscribe_public_store_changes(changes.append)
    return changes


async def _tick(client: ProtectApiClient) -> str | None:
    timer = client._public_refresh_timer
    assert timer is not None
    timer.cancel()
    before = dict(client._public_refresh_tasks)
    client._run_public_refresh_tick()
    for store, task in client._public_refresh_tasks.items():
        if before.get(store) is not task:
            await task
            return store
    return None


_FAILURES = [
    BadRequest("404"),
    NotAuthorized("denied"),
    NvrError("timeout"),
    TypeError("bad payload"),
]


@pytest.mark.asyncio()
async def test_update_public_fills_store_and_announces(
    protect_client: ProtectApiClient,
) -> None:
    """A successful fetch fills the store and announces the additions."""
    changes = await _prime(protect_client, True, profiles=False)
    protect_client._fetch_external_arm_profiles = AsyncMock(
        return_value=[_profile(protect_client)]
    )

    pb = await protect_client.update_public()

    assert list(pb.external_arm_profiles) == [PROFILE_ID]
    assert pb.external_arm_profiles[PROFILE_ID].api is protect_client
    assert changes == [_change(added={PROFILE_ID})]


@pytest.mark.asyncio()
@pytest.mark.parametrize("exc", _FAILURES, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("flag", [True, False, None])
async def test_update_public_failed_fetch_never_fails_run(
    protect_client: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
    flag: bool | None,
) -> None:
    """A failed fetch keeps the store only under the external alarm manager."""
    changes = await _prime(protect_client, flag)
    protect_client._fetch_external_arm_profiles = AsyncMock(side_effect=exc)

    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        pb = await protect_client.update_public()

    assert protect_client._public_failed_endpoints == frozenset()
    if flag is True:
        assert list(pb.external_arm_profiles) == [PROFILE_ID]
        assert changes == []
    else:
        assert pb.external_arm_profiles == {}
        assert changes == [_change(removed={PROFILE_ID})]
    records = [r for r in caplog.records if "external-arm-profiles" in r.getMessage()]
    assert len(records) == 1
    expected = logging.WARNING if isinstance(exc, TypeError) else logging.DEBUG
    assert records[0].levelno == expected
    assert bool(records[0].exc_info) is isinstance(exc, TypeError)


@pytest.mark.asyncio()
@pytest.mark.parametrize("flag", [False, None])
async def test_update_public_failed_fetch_on_empty_store_announces_nothing(
    protect_client: ProtectApiClient, flag: bool | None
) -> None:
    """Emptying an already empty store neither writes nor announces."""
    changes = await _prime(protect_client, flag, profiles=False)
    writes = protect_client._public_store_writes.get(STORE)
    protect_client._fetch_external_arm_profiles = AsyncMock(
        side_effect=BadRequest("404")
    )

    pb = await protect_client.update_public()

    assert pb.external_arm_profiles == {}
    assert changes == []
    assert protect_client._public_store_writes.get(STORE) == writes


@pytest.mark.asyncio()
@pytest.mark.parametrize("flag", [True, False, None])
async def test_update_public_failed_nvr_uses_cached_flag(
    protect_client: ProtectApiClient, flag: bool | None
) -> None:
    """With the NVR fetch failing too, the cached NVR decides."""
    changes = await _prime(protect_client, flag)
    protect_client.get_nvr_public = AsyncMock(side_effect=NvrError("down"))
    protect_client._fetch_external_arm_profiles = AsyncMock(
        side_effect=NvrError("down")
    )

    pb = await protect_client.update_public()

    assert protect_client._public_failed_endpoints == frozenset({"nvr"})
    assert pb.uses_external_alarm_manager is flag
    if flag is True:
        assert list(pb.external_arm_profiles) == [PROFILE_ID]
        assert changes == []
    else:
        assert pb.external_arm_profiles == {}
        assert changes == [_change(removed={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_update_public_unexpected_error_elsewhere_still_raises(
    protect_client: ProtectApiClient,
) -> None:
    """Only this label is exempt; other unexpected errors still raise."""
    await _prime(protect_client, True)
    protect_client._fetch_external_arm_profiles = AsyncMock(side_effect=TypeError())
    protect_client.get_cameras_public = AsyncMock(side_effect=ValueError("boom"))

    with pytest.raises(ValueError):
        await protect_client.update_public()

    assert list(protect_client.public_bootstrap.external_arm_profiles) == [PROFILE_ID]


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("failing", "expected"),
    [
        ({"_fetch_external_arm_profiles"}, [True]),
        ({"_fetch_external_arm_profiles", "get_lights_public"}, [False]),
    ],
    ids=["external-only", "with-lights"],
)
async def test_resync_ignores_external_arm_profiles_failure(
    protect_client: ProtectApiClient, failing: set[str], expected: list[bool]
) -> None:
    """A resync fails only for labels other than ``external-arm-profiles``."""
    await _prime(protect_client, True)
    for name in failing:
        setattr(protect_client, name, AsyncMock(side_effect=NvrError("down")))
    results: list[bool] = []
    protect_client.subscribe_public_resync(results.append)

    await protect_client._resync_public_bootstrap()

    assert results == expected


@pytest.mark.asyncio()
@pytest.mark.parametrize("outcome", [[], NvrError("down")], ids=["success", "failure"])
async def test_write_during_gather_keeps_cache(
    protect_client: ProtectApiClient, outcome: Any
) -> None:
    """A store write during the fetch wins over the fetch result."""
    await _prime(protect_client, False)
    release = asyncio.Event()
    started = asyncio.Event()

    async def _fetch() -> list[ExternalArmProfile]:
        started.set()
        await release.wait()
        if isinstance(outcome, Exception):
            raise outcome
        return list(outcome)

    protect_client._fetch_external_arm_profiles = AsyncMock(side_effect=_fetch)
    update = asyncio.create_task(protect_client.update_public())
    await started.wait()
    protect_client.api_request_obj = AsyncMock(return_value=_raw(state="armed"))
    await protect_client.arm_external_arm_profile_public(PROFILE_ID)
    release.set()
    pb = await update

    assert pb.external_arm_profiles[PROFILE_ID].state == "armed"


@pytest.mark.asyncio()
@pytest.mark.parametrize("flag", [None, False])
async def test_refresh_tick_skipped_without_external_alarm_manager(
    protect_client: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
    flag: bool | None,
) -> None:
    """The tick advances past the job without fetching or logging."""
    await _prime(protect_client, flag, profiles=False)
    fetch = AsyncMock(return_value=[_profile(protect_client)])
    protect_client._fetch_external_arm_profiles = fetch
    protect_client._public_refresh_next = 3

    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        assert await _tick(protect_client) is None

    fetch.assert_not_awaited()
    assert protect_client._public_refresh_next == 0
    assert caplog.records == []
    assert protect_client.public_bootstrap.external_arm_profiles == {}


@pytest.mark.asyncio()
async def test_refresh_tick_skipped_without_bootstrap(
    protect_client: ProtectApiClient,
) -> None:
    """A tick after the bootstrap is gone does not fetch."""
    await _prime(protect_client, True)
    protect_client._public_bootstrap = None
    protect_client._public_refresh_next = 3

    assert await _tick(protect_client) is None
    assert protect_client._public_refresh_next == 0


@pytest.mark.asyncio()
async def test_refresh_tick_with_external_alarm_manager(
    protect_client: ProtectApiClient,
) -> None:
    """The tick refetches and announces the change."""
    changes = await _prime(protect_client, True)
    protect_client._fetch_external_arm_profiles = AsyncMock(
        return_value=[_profile(protect_client, state="armed")]
    )
    protect_client._public_refresh_next = 3

    assert await _tick(protect_client) == STORE
    assert protect_client._public_refresh_next == 0
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "exc",
    [NotAuthorized("denied"), BadRequest("404"), NvrError("down")],
    ids=lambda e: type(e).__name__,
)
async def test_refresh_tick_failure_keeps_store(
    protect_client: ProtectApiClient, exc: Exception
) -> None:
    """A failing tick keeps the store."""
    changes = await _prime(protect_client, True)
    protect_client._fetch_external_arm_profiles = AsyncMock(side_effect=exc)
    protect_client._public_refresh_next = 3

    assert await _tick(protect_client) == STORE
    assert list(protect_client.public_bootstrap.external_arm_profiles) == [PROFILE_ID]
    assert changes == []


@pytest.mark.asyncio()
@pytest.mark.parametrize("flag", [True, False, None])
async def test_refresh_public_store_not_gated(
    protect_client: ProtectApiClient, flag: bool | None
) -> None:
    """``refresh_public_store`` fetches whatever the flag says."""
    changes = await _prime(protect_client, flag, profiles=False)
    protect_client._fetch_external_arm_profiles = AsyncMock(
        return_value=[_profile(protect_client)]
    )

    await protect_client.refresh_public_store(STORE)

    assert list(protect_client.public_bootstrap.external_arm_profiles) == [PROFILE_ID]
    assert changes == [_change(added={PROFILE_ID})]


@pytest.mark.asyncio()
@pytest.mark.parametrize("flag", [True, False, None])
async def test_refresh_public_store_failure_raises(
    protect_client: ProtectApiClient, flag: bool | None
) -> None:
    """A failed manual refresh raises and keeps the store."""
    changes = await _prime(protect_client, flag)
    protect_client._fetch_external_arm_profiles = AsyncMock(
        side_effect=BadRequest("404")
    )

    with pytest.raises(BadRequest):
        await protect_client.refresh_public_store(STORE)

    assert list(protect_client.public_bootstrap.external_arm_profiles) == [PROFILE_ID]
    assert changes == []


@pytest.mark.asyncio()
async def test_list_getter_replaces_store(protect_client: ProtectApiClient) -> None:
    """The list getter replaces the store and announces the change."""
    changes = await _prime(protect_client, True)
    protect_client._fetch_external_arm_profiles = AsyncMock(
        return_value=[_profile(protect_client, id="other")]
    )

    profiles = await protect_client.get_external_arm_profiles_public()

    assert [p.id for p in profiles] == ["other"]
    assert list(protect_client.public_bootstrap.external_arm_profiles) == ["other"]
    assert changes == [_change(added={"other"}, removed={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_list_getter_skips_write_after_overlapping_write(
    protect_client: ProtectApiClient,
) -> None:
    """A write during the list request wins over its response."""
    await _prime(protect_client, True)
    release = asyncio.Event()

    async def _list() -> list[ExternalArmProfile]:
        await release.wait()
        return []

    protect_client._fetch_external_arm_profiles = AsyncMock(side_effect=_list)
    getter = asyncio.create_task(protect_client.get_external_arm_profiles_public())
    await asyncio.sleep(0)
    protect_client.api_request_obj = AsyncMock(return_value=_raw(state="armed"))
    await protect_client.arm_external_arm_profile_public(PROFILE_ID)
    release.set()

    assert await getter == []
    store = protect_client.public_bootstrap.external_arm_profiles
    assert store[PROFILE_ID].state == "armed"


@pytest.mark.asyncio()
async def test_list_getter_failure_keeps_store(
    protect_client: ProtectApiClient,
) -> None:
    """A failing list request raises and keeps the store."""
    changes = await _prime(protect_client, True)
    protect_client._fetch_external_arm_profiles = AsyncMock(
        side_effect=NvrError("down")
    )

    with pytest.raises(NvrError):
        await protect_client.get_external_arm_profiles_public()

    assert list(protect_client.public_bootstrap.external_arm_profiles) == [PROFILE_ID]
    assert changes == []


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("method", "state"),
    [
        ("arm_external_arm_profile_public", "armed"),
        ("disarm_external_arm_profile_public", "disarmed"),
    ],
)
async def test_arm_and_disarm_write_store(
    protect_client: ProtectApiClient, method: str, state: str
) -> None:
    """Arm and disarm replace the entry with the response profile."""
    changes = await _prime(protect_client, True)
    cached = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    cached.title = "local edit"
    protect_client.api_request_obj = AsyncMock(
        return_value=_raw(state=state, has_pin=True)
    )

    profile = await getattr(protect_client, method)(PROFILE_ID)

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored is profile
    assert stored.title == "test"
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_single_getter_writes_store(protect_client: ProtectApiClient) -> None:
    """The single getter writes the profile it fetched."""
    changes = await _prime(protect_client, True, profiles=False)
    protect_client.api_request_obj = AsyncMock(return_value=_raw())

    profile = await protect_client.get_external_arm_profile_public(PROFILE_ID)

    assert protect_client.public_bootstrap.external_arm_profiles == {
        PROFILE_ID: profile
    }
    assert changes == [_change(added={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_single_getter_skips_write_after_overlapping_write(
    protect_client: ProtectApiClient,
) -> None:
    """A slow single read cannot roll back a newer write."""
    await _prime(protect_client, True)
    release = asyncio.Event()
    calls = 0

    async def _obj(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await release.wait()
            return _raw(state="disarmed")
        return _raw(state="armed")

    protect_client.api_request_obj = AsyncMock(side_effect=_obj)
    getter = asyncio.create_task(
        protect_client.get_external_arm_profile_public(PROFILE_ID)
    )
    await asyncio.sleep(0)
    await protect_client.arm_external_arm_profile_public(PROFILE_ID)
    release.set()

    assert (await getter).state == "disarmed"
    store = protect_client.public_bootstrap.external_arm_profiles
    assert store[PROFILE_ID].state == "armed"


@pytest.mark.asyncio()
async def test_writers_before_first_update_public(
    protect_client: ProtectApiClient,
) -> None:
    """Every writer works without a bootstrap and writes nothing."""
    changes: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(changes.append)
    protect_client.api_request_list = AsyncMock(return_value=[_raw()])
    protect_client.api_request_obj = AsyncMock(return_value=_raw())

    await protect_client.get_external_arm_profiles_public()
    await protect_client.get_external_arm_profile_public(PROFILE_ID)
    await protect_client.arm_external_arm_profile_public(PROFILE_ID)
    await protect_client.disarm_external_arm_profile_public(PROFILE_ID)

    assert protect_client._public_bootstrap is None
    assert changes == []
    assert protect_client._public_store_writes == {}
