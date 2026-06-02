"""Public-API LinkStation alarm-hub accessor tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from uiprotect.data import (
    AlarmHubBattery,
    AlarmHubCover,
    AlarmHubInput,
    AlarmHubInputType,
    AlarmHubOutput,
    LinkStation,
)

from .conftest import read_json_file


def _load_alarm_hub_fixture() -> dict[str, Any]:
    return read_json_file("sample_link_station_alarm_hub")


def _load_link_station_only_fixture() -> dict[str, Any]:
    data = _load_alarm_hub_fixture()
    data["id"] = "linkstation01linkstation01ls"
    data["isAlarmHub"] = False
    data["alarmHub"] = None
    data["name"] = "Garage Link"
    return data


def test_alarm_hub_armed_returns_wire_string() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    assert ls.alarm_hub_armed == "on"


def test_alarm_hub_battery_is_typed() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    battery = ls.alarm_hub_battery
    assert isinstance(battery, AlarmHubBattery)
    assert battery.charging == "off"
    assert battery.connection == "connected"
    assert battery.voltage == 12.4
    assert battery.battery_status == "ok"


def test_alarm_hub_cover_is_typed() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    cover = ls.alarm_hub_cover
    assert isinstance(cover, AlarmHubCover)
    assert cover.status == "close"
    assert cover.distance == 3


def test_alarm_hub_inputs_keyed_by_int_and_non_numeric_skipped() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    inputs = ls.alarm_hub_inputs
    assert set(inputs) == {0, 1, 2, 3}
    assert all(isinstance(v, AlarmHubInput) for v in inputs.values())

    front = inputs[0]
    assert front.name == "Front Door"
    assert front.enable == "on"
    assert front.type == "no"
    assert front.input_type is AlarmHubInputType.ENTRY
    assert front.last_triggered_at == 1700000010000
    assert front.camera_id == "cam01cam01cam01cam01cam01"

    smoke = inputs[1]
    assert smoke.input_type is AlarmHubInputType.SMOKE
    assert smoke.last_triggered_at is None
    assert smoke.camera_id is None

    unconfigured = inputs[2]
    assert unconfigured.name is None
    assert unconfigured.input_type is None


def test_alarm_hub_input_unknown_type_falls_back() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    future = ls.alarm_hub_inputs[3]
    assert future.input_type is AlarmHubInputType.UNKNOWN


def test_alarm_hub_outputs_keyed_by_int_and_non_numeric_skipped() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    outputs = ls.alarm_hub_outputs
    assert set(outputs) == {0, 1}
    assert all(isinstance(v, AlarmHubOutput) for v in outputs.values())

    siren = outputs[0]
    assert siren.name == "Siren"
    assert siren.enable == "on"
    assert siren.active == "off"
    assert siren.status == "dry"
    assert siren.delay == 0
    assert siren.duration == 30

    minimal = outputs[1]
    assert minimal.name is None
    assert minimal.delay is None
    assert minimal.duration is None


def test_alarm_hub_dict_round_trips_unmodeled_keys() -> None:
    raw = _load_alarm_hub_fixture()
    ls = LinkStation.from_unifi_dict(**deepcopy(raw))
    assert ls.alarm_hub is not None
    assert ls.alarm_hub["buckboost"] == "off"
    assert "connector" in ls.alarm_hub
    assert ls.alarm_hub["connector"]["12v"] == {
        "ch0": {"+": "connected", "-": "connected"}
    }
    assert "currentMeterStatus" in ls.alarm_hub


def test_link_station_without_alarm_hub_accessors_return_empty() -> None:
    ls = LinkStation.from_unifi_dict(**_load_link_station_only_fixture())
    assert ls.is_alarm_hub is False
    assert ls.alarm_hub_armed is None
    assert ls.alarm_hub_battery is None
    assert ls.alarm_hub_cover is None
    assert ls.alarm_hub_inputs == {}
    assert ls.alarm_hub_outputs == {}


def test_alarm_hub_accessors_when_section_absent() -> None:
    data = _load_alarm_hub_fixture()
    data["alarmHub"] = {}
    ls = LinkStation.from_unifi_dict(**data)
    assert ls.is_alarm_hub is True
    assert ls.alarm_hub_armed is None
    assert ls.alarm_hub_battery is None
    assert ls.alarm_hub_cover is None
    assert ls.alarm_hub_inputs == {}
    assert ls.alarm_hub_outputs == {}
