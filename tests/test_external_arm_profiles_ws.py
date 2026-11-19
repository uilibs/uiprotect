"""Tests for ``externalArmProfile`` frames applied to the public store."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import aiohttp
import orjson
import pytest

from tests.conftest import set_no_debug
from uiprotect.data import (
    ExternalArmProfile,
    ExternalArmProfileState,
    ExternalArmScheduleType,
    PublicStoreChange,
)

from .test_public_external_arm_profiles_store import (
    PROFILE_ID,
    STORE,
    _change,
    _prime,
    _profile,
    _raw,
    _tick,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from uiprotect import ProtectApiClient

NEW_ID = "6a1b2c3d4e5f60718293a4b6"
UPDATED_AT = "2026-11-19T07:33:34Z"
MODEL_KEY = {"modelKey": "externalArmProfile"}

_SCHEDULE = {
    "mon": {
        "type": "intervals",
        "entries": [
            {"start": {"hour": 22, "minute": 0}, "end": {"hour": 23, "minute": 59}}
        ],
    },
    "sat": {"type": "all_day"},
}

_ADD_ITEM: dict[str, Any] = {
    "id": NEW_ID,
    "title": "night",
    "alarm_ids": ["alarm-1"],
    "created_at": "2026-11-19T07:30:00Z",
    "state": "disarmed",
    "state_set_at": None,
    "state_promotion_due_at": None,
    "updated_at": None,
    "activation_delay": None,
    "deactivation_delay": None,
    "schedule": None,
    "created_by": "user-1",
    "updated_by": None,
    "active_breach_id": None,
    "has_pin": False,
    **MODEL_KEY,
}


@pytest.fixture(params=[True, False], ids=["debug", "no_debug"])
def debug(request: pytest.FixtureRequest) -> bool:
    if not request.param:
        set_no_debug()
    return bool(request.param)


def _text(payload: Any) -> aiohttp.WSMessage:
    return aiohttp.WSMessage(
        aiohttp.WSMsgType.TEXT, orjson.dumps(payload).decode(), None
    )


def _frame(action: str, **item: Any) -> aiohttp.WSMessage:
    return _text({"type": action, "item": {"id": PROFILE_ID, **item, **MODEL_KEY}})


def _store(client: ProtectApiClient) -> dict[str, ExternalArmProfile]:
    return client.public_bootstrap.external_arm_profiles


def _writes(client: ProtectApiClient) -> int | None:
    return client._public_store_writes.get(STORE)


async def _blocked_fetch(
    client: ProtectApiClient, during: Callable[[], None], *results: list[Any]
) -> AsyncMock:
    """Replace the profile fetch: the first call runs ``during`` mid-request."""
    calls = 0

    async def _fetch() -> list[ExternalArmProfile]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(0)
            during()
        return results[min(calls, len(results)) - 1]

    fetch = AsyncMock(side_effect=_fetch)
    client._fetch_external_arm_profiles = fetch  # type: ignore[method-assign]
    return fetch


@pytest.mark.asyncio()
async def test_add_writes_new_profile_with_client(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An ``add`` stores a profile whose ``arm()`` reaches the client."""
    changes = await _prime(protect_client, True)

    protect_client._process_external_arm_ws_message(
        _text({"type": "add", "item": _ADD_ITEM})
    )

    profile = _store(protect_client)[NEW_ID]
    assert profile.title == "night"
    assert profile.created_by == "user-1"
    assert profile.updated_by is None
    assert changes == [_change(added={NEW_ID})]
    arm = AsyncMock(return_value=profile)
    protect_client.arm_external_arm_profile_public = arm  # type: ignore[method-assign]
    assert await profile.arm() is profile
    arm.assert_awaited_once_with(NEW_ID)


@pytest.mark.asyncio()
async def test_add_for_stored_id_replaces_and_announces_update(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An ``add`` for a stored id replaces the profile as an update."""
    changes = await _prime(protect_client, True)
    old = _store(protect_client)[PROFILE_ID]

    protect_client._process_external_arm_ws_message(
        _text({"type": "add", "item": {**_ADD_ITEM, "id": PROFILE_ID}})
    )

    assert _store(protect_client)[PROFILE_ID] is not old
    assert _store(protect_client)[PROFILE_ID].title == "night"
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_update_replaces_without_mutating(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An ``update`` overlays the stored profile into a new object."""
    changes = await _prime(protect_client, True)
    old = _store(protect_client)[PROFILE_ID]
    before = old.model_dump()

    protect_client._process_external_arm_ws_message(
        _frame(
            "update",
            state="breached",
            state_set_at="2026-11-18T22:01:53Z",
            active_breach_id=2,
        )
    )

    new = _store(protect_client)[PROFILE_ID]
    assert new is not old
    assert old.model_dump() == before
    assert new.state is ExternalArmProfileState.BREACHED
    assert new.active_breach_id == 2
    assert new.title == "test"
    assert new.api is protect_client
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_update_schedule_replaces_and_null_clears(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """A pushed ``schedule`` replaces the stored one whole; ``null`` clears it."""
    changes = await _prime(protect_client, True)

    protect_client._process_external_arm_ws_message(
        _frame("update", schedule=_SCHEDULE, updated_at=UPDATED_AT)
    )
    protect_client._process_external_arm_ws_message(
        _frame("update", schedule={"tue": {"type": "all_day"}})
    )

    schedule = _store(protect_client)[PROFILE_ID].schedule
    assert schedule is not None
    assert schedule.mon is None
    assert schedule.sat is None
    assert schedule.tue is not None
    assert schedule.tue.type is ExternalArmScheduleType.ALL_DAY

    protect_client._process_external_arm_ws_message(_frame("update", schedule=None))

    assert _store(protect_client)[PROFILE_ID].schedule is None
    assert changes == [_change(updated={PROFILE_ID})] * 3


@pytest.mark.asyncio()
async def test_update_explicit_null_clears_field(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An explicit ``null`` in an update clears the field."""
    changes = await _prime(protect_client, True)

    protect_client._process_external_arm_ws_message(_frame("update", state_set_at=None))

    assert _store(protect_client)[PROFILE_ID].state_set_at is None
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_update_without_change_announces_nothing(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An update repeating the stored values announces nothing."""
    changes = await _prime(protect_client, True)

    protect_client._process_external_arm_ws_message(
        _frame("update", state="disarmed", title="test")
    )

    assert changes == []


@pytest.mark.asyncio()
async def test_update_for_unknown_id_is_ignored(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An update for an id not in the store writes nothing."""
    changes = await _prime(protect_client, True)
    writes = _writes(protect_client)

    protect_client._process_external_arm_ws_message(
        _text({"type": "update", "item": {**_ADD_ITEM, "state": "armed"}})
    )

    assert list(_store(protect_client)) == [PROFILE_ID]
    assert _writes(protect_client) == writes
    assert changes == []


@pytest.mark.asyncio()
async def test_remove_drops_profile(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """A ``remove`` drops the profile and ignores other item keys."""
    changes = await _prime(protect_client, True)

    protect_client._process_external_arm_ws_message(_frame("remove", title=5))

    assert _store(protect_client) == {}
    assert changes == [_change(removed={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_remove_for_unknown_id_bumps_counter(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """A ``remove`` for an unknown id announces nothing but counts as a write."""
    changes = await _prime(protect_client, True)
    writes = _writes(protect_client) or 0

    protect_client._process_external_arm_ws_message(
        _text({"type": "remove", "item": {"id": NEW_ID, **MODEL_KEY}})
    )

    assert list(_store(protect_client)) == [PROFILE_ID]
    assert _writes(protect_client) == writes + 1
    assert changes == []


_VALID_UPDATE = {
    "type": "update",
    "item": {"id": PROFILE_ID, "state": "armed", **MODEL_KEY},
}

_IGNORED_FRAMES: list[Any] = [
    pytest.param(
        aiohttp.WSMessage(aiohttp.WSMsgType.BINARY, orjson.dumps(_VALID_UPDATE), None),
        id="binary",
    ),
    pytest.param(
        aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, "not json", None), id="not-json"
    ),
    pytest.param(_text([_VALID_UPDATE]), id="json-list"),
    pytest.param(_text({"item": _VALID_UPDATE["item"]}), id="no-type"),
    pytest.param(_text({"type": "update"}), id="no-item"),
    pytest.param(_text({"type": "update", "item": "x"}), id="item-not-object"),
    pytest.param(
        _text({"type": "update", "item": {"state": "armed", **MODEL_KEY}}),
        id="no-id",
    ),
    pytest.param(
        _text({"type": "update", "item": {"id": PROFILE_ID, "state": "armed"}}),
        id="no-model-key",
    ),
    pytest.param(
        _text(
            {
                "type": "update",
                "item": {"id": PROFILE_ID, "state": "armed", "modelKey": "camera"},
            }
        ),
        id="other-model-key",
    ),
    pytest.param(
        _text({"type": "patch", "item": _VALID_UPDATE["item"]}), id="unknown-type"
    ),
    pytest.param(
        _text({"type": "remove", "item": {"id": 5, **MODEL_KEY}}), id="id-not-str"
    ),
    pytest.param(
        _text(
            {
                "type": "add",
                "item": {k: v for k, v in _ADD_ITEM.items() if k != "title"},
            }
        ),
        id="add-no-title",
    ),
]
_INVALID_FIELDS: list[tuple[str, Any]] = [
    ("title", None),
    ("title", 5),
    ("state", None),
    ("created_at", "soon"),
    ("schedule", {"mon": {"entries": []}}),
    ("updated_by", 5),
]
for _action in ("add", "update"):
    for _key, _value in _INVALID_FIELDS:
        _IGNORED_FRAMES.append(
            pytest.param(
                _text(
                    {
                        "type": _action,
                        "item": {
                            **(_ADD_ITEM if _action == "add" else {}),
                            "id": PROFILE_ID,
                            _key: _value,
                            **MODEL_KEY,
                        },
                    }
                ),
                id=f"{_action}-{_key}-{_value!r}",
            )
        )


@pytest.mark.asyncio()
@pytest.mark.parametrize("msg", _IGNORED_FRAMES)
async def test_ignored_frames_leave_store_untouched(
    protect_client: ProtectApiClient, debug: bool, msg: aiohttp.WSMessage
) -> None:
    """A frame that cannot be applied changes nothing and breaks nothing."""
    changes = await _prime(protect_client, True)
    old = _store(protect_client)[PROFILE_ID]
    before = old.model_dump()
    writes = _writes(protect_client)

    protect_client._process_external_arm_ws_message(msg)

    assert _store(protect_client) == {PROFILE_ID: old}
    assert old.model_dump() == before
    assert _writes(protect_client) == writes
    assert changes == []

    protect_client._fetch_external_arm_profiles = AsyncMock(  # type: ignore[method-assign]
        return_value=[_profile(protect_client, title="fetched")]
    )
    await protect_client.update_public()
    assert _store(protect_client)[PROFILE_ID].title == "fetched"
    protect_client.api_request_obj = AsyncMock(return_value=_raw(state="armed"))  # type: ignore[method-assign]
    await protect_client.arm_external_arm_profile_public(PROFILE_ID)
    assert _store(protect_client)[PROFILE_ID].state is ExternalArmProfileState.ARMED


@pytest.mark.asyncio()
async def test_ignored_frame_logs_at_debug(
    protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """An invalid profile is logged at debug level."""
    await _prime(protect_client, True)

    with caplog.at_level(logging.DEBUG, logger="uiprotect.api"):
        protect_client._process_external_arm_ws_message(_frame("update", title=5))

    records = [r for r in caplog.records if "external arm" in r.getMessage()]
    assert [r.levelno for r in records] == [logging.DEBUG]


@pytest.mark.asyncio()
async def test_frame_before_bootstrap_is_ignored(
    protect_client: ProtectApiClient,
) -> None:
    """Every frame is ignored until the first ``update_public``."""
    changes: list[PublicStoreChange] = []
    protect_client.subscribe_public_store_changes(changes.append)

    protect_client._process_external_arm_ws_message(
        _text({"type": "add", "item": _ADD_ITEM})
    )
    protect_client._process_external_arm_ws_message(_frame("remove"))

    assert protect_client._public_bootstrap is None
    assert protect_client._public_store_writes == {}
    assert changes == []


def _arm_frame(client: ProtectApiClient) -> Callable[[], None]:
    return lambda: client._process_external_arm_ws_message(
        _frame("update", state="armed")
    )


async def _run_update_public(client: ProtectApiClient) -> None:
    await client.update_public()


async def _run_tick(client: ProtectApiClient) -> None:
    client._public_refresh_next = 3
    assert await _tick(client) == STORE


async def _run_list_getter(client: ProtectApiClient) -> None:
    await client.get_external_arm_profiles_public()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "run",
    [_run_update_public, _run_tick, _run_list_getter],
    ids=["update_public", "periodic-refresh", "list-getter"],
)
async def test_frame_during_fetch_keeps_cache(
    protect_client: ProtectApiClient,
    debug: bool,
    run: Callable[[ProtectApiClient], Awaitable[None]],
) -> None:
    """A frame during an overlapping fetch wins over the fetched list."""
    await _prime(protect_client, True)
    fetch = await _blocked_fetch(
        protect_client, _arm_frame(protect_client), [_profile(protect_client)]
    )

    await run(protect_client)

    fetch.assert_awaited_once()
    assert _store(protect_client)[PROFILE_ID].state is ExternalArmProfileState.ARMED


@pytest.mark.asyncio()
@pytest.mark.parametrize("frame", ["update", "remove-unknown"])
async def test_frame_during_refresh_public_store_refetches(
    protect_client: ProtectApiClient, debug: bool, frame: str
) -> None:
    """A frame during ``refresh_public_store`` makes it fetch once more."""
    await _prime(protect_client, True)
    msg = (
        _frame("update", state="armed")
        if frame == "update"
        else _text({"type": "remove", "item": {"id": NEW_ID, **MODEL_KEY}})
    )
    fetch = await _blocked_fetch(
        protect_client,
        lambda: protect_client._process_external_arm_ws_message(msg),
        [_profile(protect_client, title="first")],
        [_profile(protect_client, title="second")],
    )

    await protect_client.refresh_public_store(STORE)

    assert fetch.await_count == 2
    assert _store(protect_client)[PROFILE_ID].title == "second"


async def _push_updated_by(client: ProtectApiClient) -> list[PublicStoreChange]:
    changes = await _prime(client, True)
    client._process_external_arm_ws_message(
        _frame("update", title="pushed", updated_at=UPDATED_AT, updated_by="user-2")
    )
    changes.clear()
    return changes


async def _rest_update_public(
    client: ProtectApiClient, profile: ExternalArmProfile
) -> None:
    client._fetch_external_arm_profiles = AsyncMock(return_value=[profile])  # type: ignore[method-assign]
    await client.update_public()


async def _rest_refresh(client: ProtectApiClient, profile: ExternalArmProfile) -> None:
    client._fetch_external_arm_profiles = AsyncMock(return_value=[profile])  # type: ignore[method-assign]
    await client.refresh_public_store(STORE)


async def _rest_list(client: ProtectApiClient, profile: ExternalArmProfile) -> None:
    client._fetch_external_arm_profiles = AsyncMock(return_value=[profile])  # type: ignore[method-assign]
    await client.get_external_arm_profiles_public()


_REST_WRITERS = pytest.mark.parametrize(
    "write",
    [_rest_update_public, _rest_refresh, _rest_list],
    ids=["update_public", "refresh_public_store", "list-getter"],
)


@pytest.mark.asyncio()
@_REST_WRITERS
async def test_rest_with_same_updated_at_keeps_updated_by(
    protect_client: ProtectApiClient,
    debug: bool,
    write: Callable[[ProtectApiClient, ExternalArmProfile], Awaitable[None]],
) -> None:
    """A REST copy without the authors keeps the pushed ``updated_by``."""
    changes = await _push_updated_by(protect_client)

    await write(
        protect_client,
        _profile(protect_client, title="pushed", updated_at=UPDATED_AT),
    )

    stored = _store(protect_client)[PROFILE_ID]
    assert stored.updated_by == "user-2"
    assert stored.unifi_dict()["updated_by"] == "user-2"
    assert changes == []


@pytest.mark.asyncio()
async def test_arm_response_with_same_updated_at_keeps_updated_by(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An arm response announces the state change and keeps ``updated_by``."""
    changes = await _push_updated_by(protect_client)
    protect_client.api_request_obj = AsyncMock(  # type: ignore[method-assign]
        return_value=_raw(title="pushed", state="armed", updated_at=UPDATED_AT)
    )

    await protect_client.arm_external_arm_profile_public(PROFILE_ID)

    assert _store(protect_client)[PROFILE_ID].updated_by == "user-2"
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
async def test_rest_with_other_updated_at_drops_updated_by(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """A REST copy edited since the push leaves ``updated_by`` unset."""
    changes = await _push_updated_by(protect_client)

    await _rest_list(protect_client, _profile(protect_client, title="pushed"))

    stored = _store(protect_client)[PROFILE_ID]
    assert "updated_by" not in stored.model_fields_set
    assert stored.updated_by is None
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "updated_at", [None, UPDATED_AT], ids=["no-updated_at", "updated_at"]
)
@_REST_WRITERS
async def test_created_by_from_add_survives_rest(
    protect_client: ProtectApiClient,
    debug: bool,
    write: Callable[[ProtectApiClient, ExternalArmProfile], Awaitable[None]],
    updated_at: str | None,
) -> None:
    """A pushed ``created_by`` survives a REST copy without it."""
    await _prime(protect_client, True)
    protect_client._process_external_arm_ws_message(
        _text({"type": "add", "item": {**_ADD_ITEM, "id": PROFILE_ID}})
    )
    raw = {k: v for k, v in _ADD_ITEM.items() if v is not None and k != "created_by"}
    if updated_at is not None:
        raw["updated_at"] = updated_at

    await write(
        protect_client,
        ExternalArmProfile.from_unifi_dict(
            **{**raw, "id": PROFILE_ID}, api=protect_client
        ),
    )

    assert _store(protect_client)[PROFILE_ID].created_by == "user-1"


@pytest.mark.asyncio()
async def test_created_by_survives_arm_response(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An arm response without ``created_by`` keeps the pushed one."""
    await _prime(protect_client, True)
    protect_client._process_external_arm_ws_message(
        _frame("update", created_by="user-1")
    )
    protect_client.api_request_obj = AsyncMock(return_value=_raw(state="armed"))  # type: ignore[method-assign]

    await protect_client.arm_external_arm_profile_public(PROFILE_ID)

    assert _store(protect_client)[PROFILE_ID].created_by == "user-1"


@pytest.mark.asyncio()
async def test_update_keeps_and_null_clears_updated_by(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """An update without ``updated_by`` keeps it; an explicit ``null`` clears it."""
    await _push_updated_by(protect_client)

    protect_client._process_external_arm_ws_message(_frame("update", state="armed"))
    assert _store(protect_client)[PROFILE_ID].updated_by == "user-2"

    protect_client._process_external_arm_ws_message(_frame("update", updated_by=None))
    assert _store(protect_client)[PROFILE_ID].updated_by is None

    await _rest_list(
        protect_client,
        _profile(protect_client, title="pushed", state="armed", updated_at=UPDATED_AT),
    )
    assert _store(protect_client)[PROFILE_ID].updated_by is None


@pytest.mark.asyncio()
async def test_rest_over_rest_leaves_authors_unset(
    protect_client: ProtectApiClient, debug: bool
) -> None:
    """Without a push, REST writes never add the author fields."""
    await _prime(protect_client, True)

    await _rest_list(protect_client, _profile(protect_client, state="armed"))

    stored = _store(protect_client)[PROFILE_ID]
    assert {"created_by", "updated_by"}.isdisjoint(stored.model_fields_set)
    assert {"created_by", "updated_by"}.isdisjoint(stored.unifi_dict())
