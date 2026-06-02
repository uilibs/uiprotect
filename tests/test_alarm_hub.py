"""
Tests for the typed Alarm Hub accessors on :class:`LinkStation`.

The ``alarmHub`` payload is intentionally stored as an opaque ``dict`` on
:attr:`LinkStation.alarm_hub` (its low-level electrical maps use keys such as
``"12v"``/``"+"``/``"-"`` that are not valid Python identifiers).  These tests
cover the *additive* typed accessors that parse the useful, well-formed slice
of that payload (armed state, battery, tamper cover, wired inputs/zones and
outputs) on demand, without disturbing the raw dict.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from uiprotect.data import (
    AlarmHubBattery,
    AlarmHubCover,
    AlarmHubInput,
    AlarmHubInputType,
    AlarmHubOutput,
    LinkStation,
)

ALARM_HUB_ID = "66d025b301ebc903e80003f0"

# Real-shaped (anonymised) alarm hub payload. Includes unmodeled keys
# (``buckboost``, the per-input ``resistor``/``trigger`` fields, ...) to prove
# they are preserved on the opaque dict and ignored by the typed accessors.
_ALARM_HUB_FIXTURE: dict[str, Any] = {
    "id": ALARM_HUB_ID,
    "modelKey": "linkstation",
    "state": "CONNECTED",
    "name": "Alarm Hub",
    "mac": "AABBCCDDEEFF",
    "isAlarmHub": True,
    "ledSettings": {"isEnabled": True},
    "lastEvent": 1780415883894,
    "alarmHub": {
        "armed": "off",
        "buckboost": "on",  # unmodeled — must survive on the opaque dict
        "battery": {
            "batteryStatus": "ok",
            "connection": "connected",
            "voltage": 12.061495,
        },
        "cover": {"distance": 72, "status": "close"},
        "output": {
            "0": {
                "active": "off",
                "delay": 0,
                "duration": 5000,
                "enable": "on",
                "status": "dry",
            },
            "1": {
                "active": "off",
                "delay": 0,
                "duration": 5000,
                "enable": "on",
                "status": "dry",
            },
        },
        "input": {
            # Unconfigured zone: no inputType / name on the wire.
            "0": {
                "enable": "on",
                "type": "no",
                "status": "normal",
                "resistor": 2.2,
                "trigger": 3,
            },
            "16": {
                "enable": "on",
                "type": "nc",
                "status": "normal",
                "name": "24 Hour Tamper",
                "inputType": "EMERGENCY_BUTTON",
                "lastTriggeredAt": 1780317024117,
            },
            "24": {
                "enable": "on",
                "type": "nc",
                "status": "normal",
                "name": "Hallway",
                "inputType": "MOTION",
                "lastTriggeredAt": 1780414495310,
                "cameraId": None,
                "powerReset": False,
            },
            "25": {
                "enable": "on",
                "type": "nc",
                "status": "normal",
                "inputType": "ENTRY",
                "lastTriggeredAt": 1780317516764,
                "cameraId": None,
            },
            "28": {
                "enable": "on",
                "type": "nc",
                "status": "normal",
                "name": "Kitchen",
                "inputType": "MOTION",
                "lastTriggeredAt": 1780415831259,
                "cameraId": "61b3a6a3009a1403870009c6",
            },
            # Forward-compat: an input type added by future firmware.
            "30": {
                "enable": "on",
                "type": "no",
                "status": "normal",
                "inputType": "SOMETHING_NEW",
            },
        },
    },
}

_LINK_STATION_FIXTURE: dict[str, Any] = {
    "id": ALARM_HUB_ID,
    "modelKey": "linkstation",
    "state": "CONNECTED",
    "name": "Garage Link",
    "mac": "AABBCCDDEEFF",
    "isAlarmHub": False,
    "ledSettings": {"isEnabled": True},
    "lastEvent": None,
    "alarmHub": None,
}


def _hub() -> LinkStation:
    return LinkStation.from_unifi_dict(**deepcopy(_ALARM_HUB_FIXTURE))


def test_alarm_hub_armed() -> None:
    assert _hub().alarm_hub_armed == "off"


def test_alarm_hub_battery() -> None:
    battery = _hub().alarm_hub_battery
    assert isinstance(battery, AlarmHubBattery)
    assert battery.battery_status == "ok"
    assert battery.connection == "connected"
    assert battery.voltage == pytest.approx(12.061495)


def test_alarm_hub_cover() -> None:
    cover = _hub().alarm_hub_cover
    assert isinstance(cover, AlarmHubCover)
    assert cover.status == "close"
    assert cover.distance == 72


def test_alarm_hub_outputs_keyed_by_int() -> None:
    outputs = _hub().alarm_hub_outputs
    assert set(outputs) == {0, 1}
    assert all(isinstance(o, AlarmHubOutput) for o in outputs.values())
    out0 = outputs[0]
    assert out0.active == "off"
    assert out0.status == "dry"
    assert out0.enable == "on"
    assert out0.delay == 0
    assert out0.duration == 5000


def test_alarm_hub_inputs_keyed_by_int() -> None:
    inputs = _hub().alarm_hub_inputs
    assert set(inputs) == {0, 16, 24, 25, 28, 30}
    assert all(isinstance(i, AlarmHubInput) for i in inputs.values())


def test_alarm_hub_input_configured_zone() -> None:
    zone = _hub().alarm_hub_inputs[24]
    assert zone.name == "Hallway"
    assert zone.input_type is AlarmHubInputType.MOTION
    assert zone.type == "nc"
    assert zone.status == "normal"
    assert zone.last_triggered_at == 1780414495310
    assert zone.camera_id is None


def test_alarm_hub_input_with_camera() -> None:
    assert _hub().alarm_hub_inputs[28].camera_id == "61b3a6a3009a1403870009c6"


def test_alarm_hub_input_emergency_button() -> None:
    assert _hub().alarm_hub_inputs[16].input_type is AlarmHubInputType.EMERGENCY_BUTTON


def test_alarm_hub_input_entry() -> None:
    assert _hub().alarm_hub_inputs[25].input_type is AlarmHubInputType.ENTRY


def test_alarm_hub_unconfigured_input_has_no_type() -> None:
    assert _hub().alarm_hub_inputs[0].input_type is None
    assert _hub().alarm_hub_inputs[0].name is None


def test_alarm_hub_unknown_input_type_coerces_to_unknown() -> None:
    # Forward-compat: a value not in the enum must coerce to UNKNOWN, not raise.
    assert _hub().alarm_hub_inputs[30].input_type is AlarmHubInputType.UNKNOWN


def test_alarm_hub_opaque_dict_preserved() -> None:
    # The additive accessors must not strip unmodeled keys from the raw payload.
    hub = _hub()
    assert hub.alarm_hub is not None
    assert hub.alarm_hub["buckboost"] == "on"
    # Unmodeled per-input keys must survive untouched on the raw payload.
    assert hub.alarm_hub["input"]["0"]["resistor"] == 2.2
    assert hub.alarm_hub["input"]["24"]["powerReset"] is False


def test_link_station_accessors_are_empty_when_not_hub() -> None:
    ls = LinkStation.from_unifi_dict(**deepcopy(_LINK_STATION_FIXTURE))
    assert ls.alarm_hub is None
    assert ls.alarm_hub_armed is None
    assert ls.alarm_hub_battery is None
    assert ls.alarm_hub_cover is None
    assert ls.alarm_hub_inputs == {}
    assert ls.alarm_hub_outputs == {}


@pytest.mark.parametrize(
    "alarm_hub",
    [
        pytest.param({}, id="absent"),
        # Empty objects must read the same as absent ("no meaningful data").
        pytest.param(
            {"battery": {}, "cover": {}, "input": {}, "output": {}}, id="empty"
        ),
    ],
)
def test_alarm_hub_accessors_when_sections_empty(alarm_hub: dict[str, Any]) -> None:
    fixture = deepcopy(_LINK_STATION_FIXTURE)
    fixture["isAlarmHub"] = True
    fixture["alarmHub"] = alarm_hub
    hub = LinkStation.from_unifi_dict(**fixture)
    assert hub.alarm_hub_armed is None
    assert hub.alarm_hub_battery is None
    assert hub.alarm_hub_cover is None
    assert hub.alarm_hub_inputs == {}
    assert hub.alarm_hub_outputs == {}


def test_alarm_hub_non_integer_channel_keys_are_skipped() -> None:
    # Forward-compat: a non-numeric key must be skipped, not raise.
    fixture = deepcopy(_LINK_STATION_FIXTURE)
    fixture["isAlarmHub"] = True
    fixture["alarmHub"] = {
        "input": {"0": {"type": "no"}, "meta": {"type": "no"}},
        "output": {"1": {"status": "dry"}, "summary": {"status": "dry"}},
    }
    hub = LinkStation.from_unifi_dict(**fixture)
    assert set(hub.alarm_hub_inputs) == {0}
    assert set(hub.alarm_hub_outputs) == {1}
