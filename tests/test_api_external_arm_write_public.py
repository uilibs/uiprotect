"""Create, update and delete of external arm profiles through the public API."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import orjson
import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data import (
    ExternalArmSchedule,
    ExternalArmScheduleDay,
    ExternalArmScheduleInterval,
    ExternalArmScheduleTime,
    ExternalArmScheduleType,
)
from uiprotect.exceptions import BadRequest

from .test_api_external_arm_public import BASE, _mock_request, _profile
from .test_public_external_arm_profiles_store import (
    PROFILE_ID,
    _change,
    _prime,
    no_ws_connect,  # noqa: F401
)

NEW_ID = "6a1b2c3d4e5f60718293a4c0"
PIN = "482915"


@pytest.fixture(name="public_client")
def public_client_fixture() -> ProtectApiClient:
    return ProtectApiClient.public_only("127.0.0.1", 0, api_key="key")


def _sent(request: AsyncMock, method: str, url: str) -> dict[str, Any]:
    request.assert_awaited_once()
    args, kwargs = request.call_args
    assert args == (method, url)
    assert kwargs["public_api"] is True
    body: dict[str, Any] = kwargs["json"]
    return body


def _interval(
    start: tuple[int, int], end: tuple[int, int]
) -> ExternalArmScheduleInterval:
    return ExternalArmScheduleInterval(
        start=ExternalArmScheduleTime(hour=start[0], minute=start[1]),
        end=ExternalArmScheduleTime(hour=end[0], minute=end[1]),
    )


def _all_day() -> ExternalArmScheduleDay:
    return ExternalArmScheduleDay(type=ExternalArmScheduleType.ALL_DAY)


_ALL_DAY = {"type": "all_day"}


@pytest.mark.asyncio()
async def test_create_with_title_only(public_client: ProtectApiClient) -> None:
    """Only ``title`` is sent when nothing else is given."""
    request = _mock_request(public_client, status=201, body=_profile())

    profile = await public_client.create_external_arm_profile_public(title="test")

    assert _sent(request, "post", BASE) == {"title": "test"}
    assert profile.id == PROFILE_ID
    assert profile.api is public_client


@pytest.mark.asyncio()
async def test_create_with_every_field(public_client: ProtectApiClient) -> None:
    """Every field is sent with its snake_case key; ``0`` and ``[]`` are values."""
    request = _mock_request(public_client, status=201, body=_profile())
    schedule = ExternalArmSchedule(
        mon=ExternalArmScheduleDay(
            type=ExternalArmScheduleType.INTERVALS,
            entries=[_interval((22, 0), (24, 0))],
        ),
        sat=_all_day(),
    )

    await public_client.create_external_arm_profile_public(
        title="night",
        activation_delay=0,
        deactivation_delay=0,
        schedule=schedule,
        alarm_ids=[],
        pin_code=PIN,
    )

    assert _sent(request, "post", BASE) == {
        "title": "night",
        "activation_delay": 0,
        "deactivation_delay": 0,
        "schedule": {
            "mon": {
                "type": "intervals",
                "entries": [
                    {
                        "start": {"hour": 22, "minute": 0},
                        "end": {"hour": 24, "minute": 0},
                    }
                ],
            },
            "sat": _ALL_DAY,
        },
        "alarm_ids": [],
        "pin_code": PIN,
    }


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"title": "new"}, {"title": "new"}),
        (
            {"activation_delay": 0, "alarm_ids": []},
            {"activation_delay": 0, "alarm_ids": []},
        ),
        (
            {
                "activation_delay": None,
                "deactivation_delay": None,
                "schedule": None,
                "alarm_ids": None,
                "pin_code": None,
            },
            {
                "activation_delay": None,
                "deactivation_delay": None,
                "schedule": None,
                "alarm_ids": None,
                "pin_code": None,
            },
        ),
        (
            {"deactivation_delay": 5, "alarm_ids": ["a"], "pin_code": PIN},
            {"deactivation_delay": 5, "alarm_ids": ["a"], "pin_code": PIN},
        ),
    ],
    ids=["title", "zero-and-empty", "cleared", "set"],
)
async def test_update_sends_only_given_fields(
    public_client: ProtectApiClient, kwargs: dict[str, Any], expected: dict[str, Any]
) -> None:
    """Omitted fields are not sent; ``None`` is sent as ``null``."""
    request = _mock_request(public_client, body=_profile())

    profile = await public_client.update_external_arm_profile_public(
        PROFILE_ID, **kwargs
    )

    assert _sent(request, "patch", f"{BASE}/{PROFILE_ID}") == expected
    assert profile.id == PROFILE_ID
    assert profile.api is public_client


@pytest.mark.asyncio()
async def test_update_without_fields_raises(public_client: ProtectApiClient) -> None:
    """An update with no field raises before any request."""
    request = _mock_request(public_client, body=_profile())

    with pytest.raises(BadRequest):
        await public_client.update_external_arm_profile_public(PROFILE_ID)

    request.assert_not_called()


@pytest.mark.asyncio()
@pytest.mark.parametrize("title", [None, ""])
@pytest.mark.parametrize("method", ["create", "update"])
async def test_invalid_title_raises(
    public_client: ProtectApiClient, method: str, title: Any
) -> None:
    """``title`` must be a non-empty string on create and update."""
    request = _mock_request(public_client, body=_profile())

    with pytest.raises(BadRequest, match="title"):
        if method == "create":
            await public_client.create_external_arm_profile_public(title=title)
        else:
            await public_client.update_external_arm_profile_public(
                PROFILE_ID, title=title
            )

    request.assert_not_called()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        (
            ExternalArmSchedule(sun=_all_day(), wed=_all_day()),
            {"sun": _ALL_DAY, "wed": _ALL_DAY},
        ),
        (ExternalArmSchedule(sun=_all_day(), mon=None), {"sun": _ALL_DAY}),
    ],
    ids=["some-weekdays", "weekday-set-to-none"],
)
@pytest.mark.parametrize("method", ["create", "update"])
async def test_schedule_drops_null_weekdays(
    public_client: ProtectApiClient,
    method: str,
    schedule: ExternalArmSchedule,
    expected: dict[str, Any],
) -> None:
    """Only weekdays with a value are sent."""
    request = _mock_request(public_client, body=_profile())

    if method == "create":
        await public_client.create_external_arm_profile_public(
            title="t", schedule=schedule
        )
        body = _sent(request, "post", BASE)
    else:
        await public_client.update_external_arm_profile_public(
            PROFILE_ID, schedule=schedule
        )
        body = _sent(request, "patch", f"{BASE}/{PROFILE_ID}")

    assert body["schedule"] == expected


@pytest.mark.parametrize(
    "schedule",
    [ExternalArmSchedule(), ExternalArmSchedule(tue=None)],
    ids=["empty", "only-weekday-none"],
)
@pytest.mark.asyncio()
async def test_empty_schedule_counts_as_none(
    public_client: ProtectApiClient, schedule: ExternalArmSchedule
) -> None:
    """A schedule without weekdays is omitted on create and sent as null on update."""
    request = _mock_request(public_client, body=_profile())
    await public_client.create_external_arm_profile_public(title="t", schedule=schedule)
    assert _sent(request, "post", BASE) == {"title": "t"}

    request = _mock_request(public_client, body=_profile())
    await public_client.update_external_arm_profile_public(
        PROFILE_ID, schedule=schedule
    )
    assert _sent(request, "patch", f"{BASE}/{PROFILE_ID}") == {"schedule": None}


@pytest.mark.asyncio()
async def test_delete_hits_profile_path(public_client: ProtectApiClient) -> None:
    """Delete sends a DELETE without a body."""
    request = _mock_request(public_client, status=204, body=None)

    assert await public_client.delete_external_arm_profile_public(PROFILE_ID) is None

    request.assert_awaited_once()
    args, kwargs = request.call_args
    assert args == ("delete", f"{BASE}/{PROFILE_ID}")
    assert "json" not in kwargs


def _wire_response(status: int, body: bytes = b"") -> Mock:
    response = Mock(
        status=status,
        url="https://127.0.0.1/x",
        reason="reason",
        headers={},
        content_type="application/json",
    )
    response.read = AsyncMock(return_value=body)
    response.json = AsyncMock(side_effect=lambda: orjson.loads(body))
    response.text = AsyncMock(return_value=body.decode())
    return response


@pytest.mark.asyncio()
async def test_delete_with_empty_204(public_client: ProtectApiClient) -> None:
    """An empty 204 body through the real request path does not fail."""
    public_client.get_public_api_session = AsyncMock()  # type: ignore[method-assign]
    do_request = AsyncMock(return_value=_wire_response(204))

    with patch.object(public_client, "_do_request", do_request):
        await public_client.delete_external_arm_profile_public(PROFILE_ID)

    do_request.assert_awaited_once()
    assert do_request.call_args.args[1] == "delete"


_CALLS = {
    "create": lambda c: c.create_external_arm_profile_public(title="t"),
    "update": lambda c: c.update_external_arm_profile_public(PROFILE_ID, title="t"),
    "delete": lambda c: c.delete_external_arm_profile_public(PROFILE_ID),
}


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("status", "error"),
    [(400, "Invalid external arm profile request"), (404, "Not Found")],
)
@pytest.mark.parametrize("method", list(_CALLS))
async def test_errors_raise_and_leave_store(
    protect_client: ProtectApiClient, method: str, status: int, error: str
) -> None:
    """A 400 or 404 raises ``BadRequest`` and leaves the store unchanged."""
    changes = await _prime(protect_client, True)
    before = dict(protect_client.public_bootstrap.external_arm_profiles)
    for name in ("api_request", "api_request_raw", "api_request_obj"):
        protect_client.__dict__.pop(name, None)
    _mock_request(protect_client, status=status, body={"error": error})

    with pytest.raises(BadRequest, match=error):
        await _CALLS[method](protect_client)

    assert protect_client.public_bootstrap.external_arm_profiles == before
    assert changes == []


@pytest.mark.asyncio()
@pytest.mark.parametrize("method", list(_CALLS))
async def test_before_update_public(
    public_client: ProtectApiClient, method: str
) -> None:
    """Without a bootstrap the methods work and nothing is cached."""
    _mock_request(
        public_client, status=204 if method == "delete" else 200, body=_profile()
    )

    await _CALLS[method](public_client)

    assert public_client._public_bootstrap is None


@pytest.mark.asyncio()
async def test_create_adds_to_store(protect_client: ProtectApiClient) -> None:
    """The created profile is added and announced."""
    changes = await _prime(protect_client, True)
    protect_client.api_request_obj = AsyncMock(  # type: ignore[method-assign]
        return_value=_profile(id=NEW_ID, title="new")
    )

    profile = await protect_client.create_external_arm_profile_public(title="new")

    assert protect_client.public_bootstrap.external_arm_profiles[NEW_ID] is profile
    assert changes == [_change(added={NEW_ID})]


@pytest.mark.asyncio()
async def test_update_replaces_store_entry(protect_client: ProtectApiClient) -> None:
    """The updated profile replaces the stored one and is announced."""
    changes = await _prime(protect_client, True)
    protect_client.api_request_obj = AsyncMock(  # type: ignore[method-assign]
        return_value=_profile(title="renamed")
    )

    profile = await protect_client.update_external_arm_profile_public(
        PROFILE_ID, title="renamed"
    )

    stored = protect_client.public_bootstrap.external_arm_profiles[PROFILE_ID]
    assert stored is profile
    assert changes == [_change(updated={PROFILE_ID})]


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("profile_id", "expected"),
    [(PROFILE_ID, [_change(removed={PROFILE_ID})]), (NEW_ID, [])],
    ids=["stored", "unknown"],
)
async def test_delete_removes_from_store(
    protect_client: ProtectApiClient, profile_id: str, expected: list[Any]
) -> None:
    """Delete removes the id; an unknown id announces nothing."""
    changes = await _prime(protect_client, True)
    protect_client.api_request_raw = AsyncMock(return_value=b"")  # type: ignore[method-assign]

    await protect_client.delete_external_arm_profile_public(profile_id)

    assert profile_id not in protect_client.public_bootstrap.external_arm_profiles
    assert changes == expected


@pytest.mark.parametrize(
    "pin",
    [
        "1234\n",
        "١٢٣٤",
        "123",
        "1234567",
        "12a4",
        1234,
    ],
    ids=["trailing-newline", "non-ascii-digits", "short", "long", "letter", "int"],
)
@pytest.mark.parametrize("method", ["create", "update"])
@pytest.mark.asyncio()
async def test_invalid_pin_raises_without_value(
    public_client: ProtectApiClient, method: str, pin: Any
) -> None:
    """An invalid PIN raises before any request and the error omits it."""
    request = _mock_request(public_client, body=_profile())

    with pytest.raises(BadRequest) as exc_info:
        if method == "create":
            await public_client.create_external_arm_profile_public(
                title="t", pin_code=pin
            )
        else:
            await public_client.update_external_arm_profile_public(
                PROFILE_ID, pin_code=pin
            )

    request.assert_not_called()
    text = str(pin).strip()
    assert text not in str(exc_info.value)
    assert text not in repr(exc_info.value)


@pytest.mark.parametrize(
    ("responses", "raises"),
    [
        ([_wire_response(200, orjson.dumps(_profile()))], False),
        ([_wire_response(400, orjson.dumps({"error": "rejected"}))], True),
        (
            [
                _wire_response(503, orjson.dumps({"error": "busy"})),
                _wire_response(200, orjson.dumps(_profile())),
            ],
            False,
        ),
    ],
    ids=["2xx", "4xx", "retried-503"],
)
@pytest.mark.parametrize("method", ["create", "update"])
@pytest.mark.asyncio()
async def test_valid_pin_is_never_logged(
    caplog: pytest.LogCaptureFixture,
    method: str,
    responses: list[Mock],
    raises: bool,
) -> None:
    """A valid PIN appears in no log record and no exception text."""
    client = ProtectApiClient.public_only("127.0.0.1", 0, api_key="key", max_retries=1)
    client.get_public_api_session = AsyncMock()  # type: ignore[method-assign]
    do_request = AsyncMock(side_effect=responses)
    exc: BaseException | None = None

    with (
        caplog.at_level(logging.DEBUG),
        patch.object(client, "_do_request", do_request),
        patch("uiprotect.api.calculate_retry_delay", return_value=0),
    ):
        try:
            if method == "create":
                await client.create_external_arm_profile_public(title="t", pin_code=PIN)
            else:
                await client.update_external_arm_profile_public(
                    PROFILE_ID, pin_code=PIN
                )
        except BadRequest as err:
            exc = err

    assert (exc is not None) is raises
    assert do_request.await_count == len(responses)
    assert do_request.call_args.kwargs["json"]["pin_code"] == PIN
    assert caplog.records
    assert PIN not in caplog.text
    if exc is not None:
        assert PIN not in str(exc)
        assert PIN not in repr(exc)
