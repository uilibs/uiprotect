"""External (global) alarm-manager arm profile model."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from tests.conftest import read_json_file, set_no_debug
from uiprotect.data import (
    ExternalArmProfile,
    ExternalArmProfileState,
    ExternalArmSchedule,
    ExternalArmScheduleType,
    ModelType,
)

_SCHEDULED_PROFILE: dict[str, Any] = {
    "id": "6a1b2c3d4e5f60718293a4b6",
    "title": "night",
    "alarm_ids": ["alarm-1", "alarm-2"],
    "created_at": "2026-06-11T12:33:12Z",
    "state": "armed",
    "state_set_at": "2026-11-18T21:59:50Z",
    "updated_at": "2026-11-12T18:25:47Z",
    "activation_delay": 30,
    "deactivation_delay": 45,
    "schedule": {
        "mon": {
            "type": "intervals",
            "entries": [
                {
                    "start": {"hour": 22, "minute": 0},
                    "end": {"hour": 23, "minute": 30},
                },
                {
                    "start": {"hour": 0, "minute": 0},
                    "end": {"hour": 6, "minute": 15},
                },
            ],
        },
        "sat": {"type": "all_day"},
        "sun": {"type": "all_day"},
    },
    "created_by": "user-1",
    "updated_by": "user-2",
    "has_pin": True,
}


@pytest.fixture(params=[True, False], ids=["debug", "no_debug"])
def debug(request: pytest.FixtureRequest) -> bool:
    if not request.param:
        set_no_debug()
    return bool(request.param)


def _parse(payload: dict[str, Any]) -> ExternalArmProfile:
    return ExternalArmProfile.from_unifi_dict(**deepcopy(payload))


def test_rest_payload_round_trip(debug: bool) -> None:
    """A REST profile parses and serialises back to the exact input."""
    payload = read_json_file("sample_external_arm_profiles")[0]
    profile = _parse(payload)

    assert profile.title == "test"
    assert profile.alarm_ids == []
    assert profile.created_at == datetime(2026, 6, 11, 12, 33, 12, tzinfo=UTC)
    assert profile.state is ExternalArmProfileState.DISARMED
    assert profile.has_pin is False
    assert profile.activation_delay is None
    assert profile.active_breach_id is None
    assert profile.schedule is None
    assert profile.model is ModelType.EXTERNAL_ARM_PROFILE
    assert profile.unifi_dict() == payload


def test_scheduled_profile_round_trip(debug: bool) -> None:
    """Delays and a mixed ``intervals`` / ``all_day`` schedule round-trip."""
    profile = _parse(_SCHEDULED_PROFILE)

    assert profile.activation_delay == 30
    assert profile.deactivation_delay == 45
    assert profile.schedule is not None
    mon = profile.schedule.mon
    assert mon is not None
    assert mon.type is ExternalArmScheduleType.INTERVALS
    assert mon.entries is not None
    assert mon.entries[0].start.hour == 22
    assert mon.entries[0].end.minute == 30
    assert profile.schedule.sat is not None
    assert profile.schedule.sat.type is ExternalArmScheduleType.ALL_DAY
    assert profile.schedule.sat.entries is None
    assert profile.schedule.tue is None
    assert profile.unifi_dict() == _SCHEDULED_PROFILE


def test_nanosecond_timestamp_truncates_to_microseconds(debug: bool) -> None:
    """A nanosecond ``state_promotion_due_at`` parses to microsecond precision."""
    payload = {
        **_SCHEDULED_PROFILE,
        "state": "arming",
        "state_promotion_due_at": "2026-11-18T22:01:50.862502418Z",
    }
    profile = _parse(payload)

    assert profile.state_promotion_due_at == datetime(
        2026, 11, 18, 22, 1, 50, 862502, tzinfo=UTC
    )
    assert (
        profile.unifi_dict()["state_promotion_due_at"] == "2026-11-18T22:01:50.862502Z"
    )


def test_websocket_item_with_explicit_nulls(debug: bool) -> None:
    """A websocket ``add`` item with ``modelKey`` and explicit nulls round-trips."""
    item = {
        "id": "6a1b2c3d4e5f60718293a4b7",
        "modelKey": "externalArmProfile",
        "title": "away",
        "alarm_ids": ["alarm-1"],
        "created_at": "2026-11-18T22:00:00Z",
        "state": "breached",
        "state_set_at": "2026-11-18T22:05:00Z",
        "state_promotion_due_at": None,
        "activation_delay": None,
        "deactivation_delay": None,
        "schedule": None,
        "updated_at": None,
        "created_by": None,
        "updated_by": None,
        "active_breach_id": 17,
        "has_pin": False,
    }
    profile = _parse(item)

    assert profile.model is ModelType.EXTERNAL_ARM_PROFILE
    assert profile.state is ExternalArmProfileState.BREACHED
    assert profile.active_breach_id == 17
    assert profile.state_promotion_due_at is None
    assert profile.schedule is None
    assert profile.updated_at is None
    assert profile.unifi_dict() == item


def test_update_item_merges_changed_fields(debug: bool) -> None:
    """An ``update`` item with only ``title`` and ``updated_at`` merges in place."""
    profile = _parse(_SCHEDULED_PROFILE)
    update = {
        "id": _SCHEDULED_PROFILE["id"],
        "modelKey": "externalArmProfile",
        "title": "renamed",
        "updated_at": "2026-11-19T08:00:00Z",
    }

    profile.update_from_dict(ExternalArmProfile.unifi_dict_to_dict(update))

    assert profile.title == "renamed"
    assert profile.updated_at == datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
    assert profile.unifi_dict() == {
        **_SCHEDULED_PROFILE,
        "modelKey": "externalArmProfile",
        "title": "renamed",
        "updated_at": "2026-11-19T08:00:00Z",
    }


def test_update_item_schedule_replaces_stored_schedule(debug: bool) -> None:
    """A merged ``schedule`` replaces the stored one, dropping missing weekdays."""
    profile = _parse(_SCHEDULED_PROFILE)
    new_schedule = {
        "mon": {"type": "all_day"},
        "sat": {
            "type": "intervals",
            "entries": [
                {"start": {"hour": 1, "minute": 0}, "end": {"hour": 2, "minute": 0}}
            ],
        },
    }
    update = {
        "id": _SCHEDULED_PROFILE["id"],
        "modelKey": "externalArmProfile",
        "schedule": deepcopy(new_schedule),
    }

    profile.update_from_dict(ExternalArmProfile.unifi_dict_to_dict(update))

    assert isinstance(profile.schedule, ExternalArmSchedule)
    assert profile.schedule.sun is None
    assert profile.schedule.mon is not None
    assert profile.schedule.mon.type is ExternalArmScheduleType.ALL_DAY
    assert profile.schedule.mon.entries is None
    assert profile.unifi_dict()["schedule"] == new_schedule


def test_update_item_clears_schedule(debug: bool) -> None:
    """A ``null`` ``schedule`` in an update clears the stored schedule."""
    profile = _parse(_SCHEDULED_PROFILE)

    profile.update_from_dict(
        ExternalArmProfile.unifi_dict_to_dict(
            {"id": _SCHEDULED_PROFILE["id"], "schedule": None}
        )
    )

    assert profile.schedule is None


def test_invalid_schedule_update_keeps_stored_schedule() -> None:
    """A schedule update that fails validation leaves the stored schedule intact."""
    profile = _parse(_SCHEDULED_PROFILE)
    stored = profile.schedule

    with pytest.raises(ValidationError):
        profile.update_from_dict(
            ExternalArmProfile.unifi_dict_to_dict(
                {"id": _SCHEDULED_PROFILE["id"], "schedule": {"mon": {"entries": []}}}
            )
        )

    assert profile.schedule is stored


def test_unknown_values_and_extra_keys(debug: bool) -> None:
    """Unknown ``state`` / schedule ``type`` map to ``UNKNOWN``; extra keys drop."""
    payload = {
        **read_json_file("sample_external_arm_profiles")[0],
        "state": "disarming",
        "schedule": {"wed": {"type": "weekdays_only", "extra": 1}},
        "new_field": {"nested": True},
    }
    profile = _parse(payload)

    assert profile.state is ExternalArmProfileState.UNKNOWN
    assert profile.schedule is not None
    assert profile.schedule.wed is not None
    assert profile.schedule.wed.type is ExternalArmScheduleType.UNKNOWN
    serialised = profile.unifi_dict()
    assert "new_field" not in serialised
    assert serialised["schedule"] == {"wed": {"type": "unknown"}}
