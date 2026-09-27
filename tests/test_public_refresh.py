"""Tests for the periodic refresh of the websocket-less public stores."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from uiprotect import ProtectApiClient
from uiprotect.api import (
    _PUBLIC_REFRESH_JOBS,
    DEVICE_UPDATE_INTERVAL,
    PUBLIC_REFRESH_INTERVAL,
)
from uiprotect.data import PublicStoreChange
from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from uiprotect.websocket import WebsocketState

from .test_api_public import _mock_update_public_endpoints
from .test_public_store_changes import PROFILE_ID, _profile, _profile_raw, _ulp_user

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from uiprotect.data import PublicStoreName


@pytest.fixture
def client(protect_client: ProtectApiClient) -> ProtectApiClient:
    _mock_update_public_endpoints(protect_client)
    return protect_client


def _delay(client: ProtectApiClient) -> float:
    timer = client._public_refresh_timer
    assert timer is not None
    return timer.when() - asyncio.get_running_loop().time()


async def _tick(client: ProtectApiClient) -> PublicStoreName | None:
    """Fire the pending tick; return the store it refreshed, if any."""
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


def _blocking_fetch() -> tuple[AsyncMock, asyncio.Event]:
    release = asyncio.Event()
    result: list[Any] = []

    async def _fetch() -> list[Any]:
        await release.wait()
        return result

    return AsyncMock(side_effect=_fetch), release


def test_default_interval_matches_device_update_interval() -> None:
    assert PUBLIC_REFRESH_INTERVAL == DEVICE_UPDATE_INTERVAL


@pytest.mark.parametrize("interval", [0, -1.0, float("nan"), float("inf"), True, False])
def test_invalid_interval_rejected(interval: float) -> None:
    with pytest.raises(BadRequest):
        ProtectApiClient("h", 443, "u", "p", public_refresh_interval=interval)


@pytest.mark.asyncio()
async def test_public_only_uses_default_interval() -> None:
    client = ProtectApiClient.public_only("h", 443, api_key="k")
    _mock_update_public_endpoints(client)
    try:
        await client.update_public()
        assert _delay(client) == pytest.approx(PUBLIC_REFRESH_INTERVAL / 2, abs=0.5)
    finally:
        await client.close_session()


@pytest.mark.asyncio()
async def test_real_timer_keeps_refreshing_every_store() -> None:
    client = ProtectApiClient.public_only(
        "h", 443, api_key="k", public_refresh_interval=0.02
    )
    _mock_update_public_endpoints(client)
    try:
        await client.update_public()
        for _ in range(200):
            if (
                client._fetch_arm_profiles.await_count >= 3
                and client.get_ulp_users_public.await_count >= 3
            ):
                break
            await asyncio.sleep(0.01)
        assert client._fetch_arm_profiles.await_count >= 3
        assert client.get_ulp_users_public.await_count >= 3
    finally:
        await client.close_session()


@pytest.mark.asyncio()
@pytest.mark.parametrize(("interval", "expected"), [(60.0, 30.0), (10.0, 5.0)])
async def test_tick_spacing_scales_with_interval(
    interval: float, expected: float
) -> None:
    client = ProtectApiClient.public_only(
        "h", 443, api_key="k", public_refresh_interval=interval
    )
    _mock_update_public_endpoints(client)
    try:
        await client.update_public()
        assert _delay(client) == pytest.approx(expected, abs=0.5)
        await _tick(client)
        assert _delay(client) == pytest.approx(expected, abs=0.5)
    finally:
        await client.close_session()


@pytest.mark.asyncio()
async def test_private_constructor_passes_interval() -> None:
    client = ProtectApiClient("h", 443, "u", "p", public_refresh_interval=40.0)
    _mock_update_public_endpoints(client)
    try:
        await client.update_public()
        assert _delay(client) == pytest.approx(20.0, abs=0.5)
    finally:
        await client.close_session()


@pytest.mark.asyncio()
async def test_none_disables_refresh() -> None:
    client = ProtectApiClient.public_only(
        "h", 443, api_key="k", public_refresh_interval=None
    )
    _mock_update_public_endpoints(client)
    try:
        await client.update_public()
        assert client._public_refresh_timer is None
    finally:
        await client.close_session()


@pytest.mark.asyncio()
async def test_jobs_run_round_robin(client: ProtectApiClient) -> None:
    await client.update_public()
    assert [await _tick(client) for _ in range(4)] == [
        "arm_profiles",
        "ulp_users",
        "arm_profiles",
        "ulp_users",
    ]
    assert client._fetch_arm_profiles.await_count == 3
    assert client.get_ulp_users_public.await_count == 3


@pytest.mark.asyncio()
async def test_repeated_update_public_keeps_one_timer(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    timer = client._public_refresh_timer
    await client.update_public()
    assert client._public_refresh_timer is timer


@pytest.mark.asyncio()
async def test_failed_update_public_does_not_arm(client: ProtectApiClient) -> None:
    client.get_nvr_public = AsyncMock(side_effect=ValueError("boom"))
    with pytest.raises(ValueError):
        await client.update_public()
    assert client._public_refresh_timer is None


@pytest.mark.asyncio()
async def test_tick_refreshes_and_notifies_only_on_change(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    changes: list[PublicStoreChange] = []
    client.subscribe_public_store_changes(changes.append)

    client._fetch_arm_profiles = AsyncMock(return_value=[_profile(client)])
    await _tick(client)
    assert changes == [
        PublicStoreChange(
            "arm_profiles", frozenset({PROFILE_ID}), frozenset(), frozenset()
        )
    ]
    await _tick(client)
    client._fetch_arm_profiles = AsyncMock(return_value=[_profile(client)])
    await _tick(client)
    assert len(changes) == 1
    assert list(client.public_bootstrap.arm_profiles) == [PROFILE_ID]


@pytest.mark.asyncio()
async def test_refresh_removes_missing_entries(client: ProtectApiClient) -> None:
    client._fetch_arm_profiles = AsyncMock(return_value=[_profile(client)])
    await client.update_public()
    changes: list[PublicStoreChange] = []
    client.subscribe_public_store_changes(changes.append)

    client._fetch_arm_profiles = AsyncMock(return_value=[])
    await _tick(client)
    assert client.public_bootstrap.arm_profiles == {}
    assert changes == [
        PublicStoreChange(
            "arm_profiles", frozenset(), frozenset({PROFILE_ID}), frozenset()
        )
    ]


@pytest.mark.asyncio()
async def test_failed_refresh_keeps_cache(client: ProtectApiClient) -> None:
    client._fetch_arm_profiles = AsyncMock(return_value=[_profile(client)])
    await client.update_public()
    client._fetch_arm_profiles = AsyncMock(side_effect=NvrError("down"))
    assert await _tick(client) == "arm_profiles"
    assert list(client.public_bootstrap.arm_profiles) == [PROFILE_ID]


@pytest.mark.asyncio()
async def test_refresh_not_gated_on_startup_failure(client: ProtectApiClient) -> None:
    client._fetch_arm_profiles = AsyncMock(side_effect=NvrError("timeout"))
    await client.update_public()
    assert "arm-profiles" in client._public_failed_endpoints

    client._fetch_arm_profiles = AsyncMock(return_value=[_profile(client)])
    assert await _tick(client) == "arm_profiles"
    assert list(client.public_bootstrap.arm_profiles) == [PROFILE_ID]


@pytest.mark.asyncio()
async def test_tick_skipped_while_update_public_runs(client: ProtectApiClient) -> None:
    await client.update_public()
    client._fetch_arm_profiles.reset_mock()
    async with client._public_update_lock:
        assert await _tick(client) is None
    client._fetch_arm_profiles.assert_not_awaited()
    assert client._public_refresh_timer is not None
    assert await _tick(client) == "ulp_users"


@pytest.mark.asyncio()
async def test_update_public_during_fetch_drops_tick_result(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    release = asyncio.Event()

    async def _stale() -> list[Any]:
        await release.wait()
        return [_profile(client)]

    client._fetch_arm_profiles = AsyncMock(side_effect=_stale)
    client._run_public_refresh_tick()
    task = client._public_refresh_tasks["arm_profiles"]
    await asyncio.sleep(0)

    client._fetch_arm_profiles = AsyncMock(return_value=[])
    await client.update_public()
    release.set()
    await task
    assert client.public_bootstrap.arm_profiles == {}


@pytest.mark.asyncio()
async def test_tick_finishing_during_update_public_defers_to_it(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    tick_release = asyncio.Event()
    update_release = asyncio.Event()
    calls = 0

    async def _fetch() -> list[Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await tick_release.wait()
            return [_profile(client)]
        await update_release.wait()
        return []

    client._fetch_arm_profiles = AsyncMock(side_effect=_fetch)
    client._run_public_refresh_tick()
    task = client._public_refresh_tasks["arm_profiles"]
    await asyncio.sleep(0)

    update = asyncio.create_task(client.update_public())
    while calls < 2:
        await asyncio.sleep(0)
    tick_release.set()
    await task
    update_release.set()
    await update
    assert client.public_bootstrap.arm_profiles == {}


@pytest.mark.asyncio()
async def test_setter_write_during_fetch_drops_tick_result(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    release = asyncio.Event()

    async def _stale() -> list[Any]:
        await release.wait()
        return []

    client._fetch_arm_profiles = AsyncMock(side_effect=_stale)
    client._run_public_refresh_tick()
    task = client._public_refresh_tasks["arm_profiles"]
    await asyncio.sleep(0)

    client.api_request_obj = AsyncMock(return_value=_profile_raw())
    await client.create_arm_profile_public(
        name="Night",
        automations=["a1"],
        schedules=[{"start": "0 22 * * *", "end": "0 6 * * *"}],
        record_everything=True,
        activation_delay=60000,
    )
    release.set()
    await task
    assert list(client.public_bootstrap.arm_profiles) == [PROFILE_ID]


@pytest.mark.asyncio()
async def test_running_job_skips_only_its_own_turn(client: ProtectApiClient) -> None:
    await client.update_public()
    fetch, release = _blocking_fetch()
    client._fetch_arm_profiles = fetch
    client.get_ulp_users_public = AsyncMock(return_value=[_ulp_user(client)])

    client._run_public_refresh_tick()
    running = client._public_refresh_tasks["arm_profiles"]
    await asyncio.sleep(0)
    assert await _tick(client) == "ulp_users"
    assert await _tick(client) is None
    assert client._public_refresh_tasks["arm_profiles"] is running
    assert fetch.await_count == 1
    assert list(client.public_bootstrap.ulp_users) == ["ulp-1"]
    release.set()
    await running


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "teardown",
    ["close_session", "close_public_api_session", "async_disconnect_ws"],
)
async def test_teardown_cancels_timer_and_running_job(
    client: ProtectApiClient, teardown: str
) -> None:
    await client.update_public()
    fetch, _release = _blocking_fetch()
    client._fetch_arm_profiles = fetch
    client._run_public_refresh_tick()
    running = client._public_refresh_tasks["arm_profiles"]
    timer = client._public_refresh_timer
    assert timer is not None
    await asyncio.sleep(0)

    await getattr(client, teardown)()

    assert timer.cancelled()
    assert client._public_refresh_timer is None
    assert running.cancelled()
    assert client._public_refresh_tasks == {}


@pytest.mark.asyncio()
async def test_teardown_then_update_public_rearms(client: ProtectApiClient) -> None:
    await client.update_public()
    await client.async_disconnect_ws()
    await client.update_public()
    assert client._public_refresh_timer is not None


async def _in_flight_update(client: ProtectApiClient) -> tuple[asyncio.Task[Any], Any]:
    release = asyncio.Event()

    async def _nvr() -> Any:
        await release.wait()
        return nvr

    nvr = await client.get_nvr_public()
    client.get_nvr_public = AsyncMock(side_effect=_nvr)
    update = asyncio.create_task(client.update_public())
    await asyncio.sleep(0)
    return update, release


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "teardown",
    ["close_session", "close_public_api_session", "async_disconnect_ws"],
)
async def test_update_public_in_flight_across_teardown_does_not_arm(
    client: ProtectApiClient, teardown: str
) -> None:
    update, release = await _in_flight_update(client)
    await getattr(client, teardown)()
    release.set()
    await update
    assert client._public_refresh_timer is None


@pytest.mark.asyncio()
async def test_update_public_finishing_while_teardown_awaits_does_not_arm(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    update, release = await _in_flight_update(client)
    finished_during_teardown = False

    async def _fetch() -> list[Any]:
        nonlocal finished_during_teardown
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            release.set()
            await update
            finished_during_teardown = True
            raise
        return []  # pragma: no cover

    client._fetch_arm_profiles = AsyncMock(side_effect=_fetch)
    # The in-flight update holds the lock; bypass the skip to start a job.
    client._public_refresh_tasks["arm_profiles"] = asyncio.create_task(
        client._refresh_public_store(_PUBLIC_REFRESH_JOBS[0], None)
    )
    await asyncio.sleep(0)

    await client.close_public_api_session()

    assert finished_during_teardown
    assert client._public_refresh_timer is None


@pytest.mark.asyncio()
async def test_update_public_started_while_teardown_awaits_does_not_arm(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    started_during_teardown = False
    calls = 0

    async def _fetch() -> list[Any]:
        nonlocal started_during_teardown, calls
        calls += 1
        if calls > 1:
            return []
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await client.update_public()
            started_during_teardown = True
            raise
        return []  # pragma: no cover

    client._fetch_arm_profiles = AsyncMock(side_effect=_fetch)
    client._run_public_refresh_tick()
    await asyncio.sleep(0)

    await client.close_public_api_session()

    assert started_during_teardown
    assert client._public_refresh_timer is None
    assert client._public_refresh_closing == 0
    await client.update_public()
    assert client._public_refresh_timer is not None


@pytest.mark.asyncio()
async def test_overlapping_teardowns_do_not_arm(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    started_during_teardown = False
    calls = 0

    async def _fetch() -> list[Any]:
        nonlocal started_during_teardown, calls
        calls += 1
        if calls > 1:
            return []
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await client.close_public_api_session()
            await client.update_public()
            started_during_teardown = True
            raise
        return []  # pragma: no cover

    client._fetch_arm_profiles = AsyncMock(side_effect=_fetch)
    client._run_public_refresh_tick()
    await asyncio.sleep(0)

    await client.close_public_api_session()

    assert started_during_teardown
    assert client._public_refresh_timer is None
    assert client._public_refresh_closing == 0
    await client.update_public()
    assert client._public_refresh_timer is not None


@pytest.mark.asyncio()
async def test_close_public_api_session_cancels_resync_follow_up(
    client: ProtectApiClient,
) -> None:
    await client.update_public()
    client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    release = asyncio.Event()
    nvr = await client.get_nvr_public()

    async def _nvr() -> Any:
        await release.wait()
        return nvr

    client.get_nvr_public = AsyncMock(side_effect=_nvr)
    client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    resync = client._public_resync_task
    assert resync is not None
    await asyncio.sleep(0)
    client._on_devices_websocket_state_change(WebsocketState.CONNECTED)
    assert client._public_resync_pending

    await client.close_public_api_session()
    release.set()
    await asyncio.sleep(0.05)

    assert resync.cancelled()
    assert client._public_resync_task is None
    assert client._public_refresh_timer is None


def _fail_then_recover(
    exc: BaseException,
) -> Callable[[ProtectApiClient], Awaitable[None]]:
    async def _run(client: ProtectApiClient) -> None:
        client._fetch_arm_profiles = AsyncMock(side_effect=exc)
        await _tick(client)
        await _tick(client)
        await _tick(client)
        await _tick(client)
        client._fetch_arm_profiles = AsyncMock(return_value=[])
        await _tick(client)
        await _tick(client)
        await _tick(client)

    return _run


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("exc", "traceback"),
    [
        (NvrError("down"), False),
        (TimeoutError(), False),
        (NotAuthorized("revoked"), False),
        (ValueError("bad payload"), True),
    ],
)
async def test_failure_warns_once_and_recovery_logs_once(
    client: ProtectApiClient,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
    traceback: bool,
) -> None:
    await client.update_public()
    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        await _fail_then_recover(exc)(client)

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "arm-profiles" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert bool(warnings[0].exc_info) is traceback
    recovered = [r for r in caplog.records if "recovered" in r.getMessage()]
    assert len(recovered) == 1
    assert recovered[0].levelno == logging.INFO


@pytest.mark.asyncio()
async def test_failure_of_one_store_does_not_suppress_other(
    client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    await client.update_public()
    client._fetch_arm_profiles = AsyncMock(side_effect=NvrError("down"))
    client.get_ulp_users_public = AsyncMock(side_effect=NvrError("down"))
    with caplog.at_level(logging.WARNING, logger="uiprotect.api"):
        await _tick(client)
        await _tick(client)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert any("arm-profiles" in w for w in warnings)
    assert any("ulp-users" in w for w in warnings)


@pytest.mark.asyncio()
async def test_ulp_users_not_authorized_is_tolerated(
    client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    await client.update_public()
    client.public_bootstrap.ulp_users["ulp-1"] = _ulp_user(client)
    client.get_ulp_users_public = AsyncMock(side_effect=NotAuthorized("no identity"))
    await _tick(client)
    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        assert await _tick(client) == "ulp_users"

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "not authorized" in caplog.text
    assert list(client.public_bootstrap.ulp_users) == ["ulp-1"]
    assert "ulp-users" not in client._public_refresh_failing


@pytest.mark.asyncio()
async def test_missing_endpoint_logs_at_debug(
    client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    await client.update_public()
    client._fetch_arm_profiles = AsyncMock(side_effect=BadRequest("not found"))
    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        assert await _tick(client) == "arm_profiles"

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "arm-profiles endpoint unavailable" in caplog.text
    assert "arm-profiles" not in client._public_refresh_failing
