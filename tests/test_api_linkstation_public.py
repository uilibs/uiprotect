"""Public-API LinkStation alarm-hub accessor tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from uiprotect.data import (
    AlarmHubBattery,
    AlarmHubBatteryStatus,
    AlarmHubConnectionState,
    AlarmHubCover,
    AlarmHubCoverStatus,
    AlarmHubInput,
    AlarmHubInputContactType,
    AlarmHubInputStatus,
    AlarmHubInputType,
    AlarmHubOutput,
    AlarmHubOutputStatus,
    LinkStation,
    OnOffState,
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


def test_alarm_hub_armed_returns_typed_state() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    assert ls.alarm_hub_armed is OnOffState.ON


def test_alarm_hub_armed_unknown_value_coerces() -> None:
    data = _load_alarm_hub_fixture()
    data["alarmHub"]["armed"] = "partial"
    ls = LinkStation.from_unifi_dict(**data)
    assert ls.alarm_hub_armed is OnOffState.UNKNOWN


def test_alarm_hub_armed_missing_field_returns_none() -> None:
    data = _load_alarm_hub_fixture()
    del data["alarmHub"]["armed"]
    ls = LinkStation.from_unifi_dict(**data)
    assert ls.alarm_hub_armed is None


def test_alarm_hub_battery_is_typed() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    battery = ls.alarm_hub_battery
    assert isinstance(battery, AlarmHubBattery)
    assert battery.charging is OnOffState.OFF
    assert battery.connection is AlarmHubConnectionState.CONNECTED
    assert battery.voltage == 12.4
    assert battery.battery_status is AlarmHubBatteryStatus.OK


def test_alarm_hub_cover_is_typed() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    cover = ls.alarm_hub_cover
    assert isinstance(cover, AlarmHubCover)
    assert cover.status is AlarmHubCoverStatus.CLOSE
    assert cover.distance == 3


def test_alarm_hub_battery_sparse_payload_when_disconnected() -> None:
    # When the backup battery is disconnected the hub emits only ``connection``
    # (observed on real hardware). The ``battery`` object has no ``required``
    # array in the OpenAPI spec, so every sub-field must be optional.
    data = _load_alarm_hub_fixture()
    data["alarmHub"]["battery"] = {"connection": "disconnected"}
    ls = LinkStation.from_unifi_dict(**data)
    battery = ls.alarm_hub_battery
    assert isinstance(battery, AlarmHubBattery)
    assert battery.connection is AlarmHubConnectionState.DISCONNECTED
    assert battery.charging is None
    assert battery.voltage is None
    assert battery.battery_status is None


def test_alarm_hub_cover_sparse_payload() -> None:
    # ``cover`` likewise has no ``required`` array in the spec.
    data = _load_alarm_hub_fixture()
    data["alarmHub"]["cover"] = {"distance": 66}
    ls = LinkStation.from_unifi_dict(**data)
    cover = ls.alarm_hub_cover
    assert isinstance(cover, AlarmHubCover)
    assert cover.distance == 66
    assert cover.status is None


def test_alarm_hub_inputs_keyed_by_int_and_non_numeric_skipped() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    inputs = ls.alarm_hub_inputs
    assert set(inputs) == {0, 1, 2, 3}
    assert all(isinstance(v, AlarmHubInput) for v in inputs.values())

    front = inputs[0]
    assert front.name == "Front Door"
    assert front.enable is OnOffState.ON
    assert front.type is AlarmHubInputContactType.NO
    assert front.status is AlarmHubInputStatus.NORMAL
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


def test_alarm_hub_status_enums_coerce_unknown_values() -> None:
    data = _load_alarm_hub_fixture()
    data["alarmHub"]["battery"]["batteryStatus"] = "future-state"
    data["alarmHub"]["battery"]["charging"] = "trickle"
    data["alarmHub"]["battery"]["connection"] = "intermittent"
    data["alarmHub"]["cover"]["status"] = "ajar"
    data["alarmHub"]["input"]["0"]["status"] = "supervised"
    data["alarmHub"]["input"]["0"]["enable"] = "pending"
    data["alarmHub"]["input"]["0"]["type"] = "eolr"
    data["alarmHub"]["output"]["0"]["status"] = "shorted"
    data["alarmHub"]["output"]["0"]["enable"] = "scheduled"
    data["alarmHub"]["output"]["0"]["active"] = "pulsing"
    ls = LinkStation.from_unifi_dict(**data)

    battery = ls.alarm_hub_battery
    assert battery is not None
    assert battery.battery_status is AlarmHubBatteryStatus.UNKNOWN
    assert battery.charging is OnOffState.UNKNOWN
    assert battery.connection is AlarmHubConnectionState.UNKNOWN

    cover = ls.alarm_hub_cover
    assert cover is not None
    assert cover.status is AlarmHubCoverStatus.UNKNOWN

    front_input = ls.alarm_hub_inputs[0]
    assert front_input.status is AlarmHubInputStatus.UNKNOWN
    assert front_input.enable is OnOffState.UNKNOWN
    assert front_input.type is AlarmHubInputContactType.UNKNOWN

    siren_output = ls.alarm_hub_outputs[0]
    assert siren_output.status is AlarmHubOutputStatus.UNKNOWN
    assert siren_output.enable is OnOffState.UNKNOWN
    assert siren_output.active is OnOffState.UNKNOWN


def test_alarm_hub_outputs_keyed_by_int_and_non_numeric_skipped() -> None:
    ls = LinkStation.from_unifi_dict(**_load_alarm_hub_fixture())
    outputs = ls.alarm_hub_outputs
    assert set(outputs) == {0, 1}
    assert all(isinstance(v, AlarmHubOutput) for v in outputs.values())

    siren = outputs[0]
    assert siren.name == "Siren"
    assert siren.enable is OnOffState.ON
    assert siren.active is OnOffState.OFF
    assert siren.status is AlarmHubOutputStatus.DRY
    assert siren.delay == 0
    assert siren.duration == 30

    minimal = outputs[1]
    assert minimal.name is None
    assert minimal.status is AlarmHubOutputStatus.WET
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
