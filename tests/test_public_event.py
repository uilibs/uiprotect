"""Spec-fixture tests for the public-API ``PublicEvent`` model."""

from __future__ import annotations

from datetime import datetime

import pytest

from uiprotect.data.public_event import (
    PublicEvent,
    PublicEventMetadata,
    PublicFingerprintMetadata,
    PublicNfcMetadata,
)
from uiprotect.data.types import (
    AlarmHubInputStatus,
    AlarmHubTamperStatus,
    EventButtonType,
    ModelType,
    MountType,
    RelayInputCircuitState,
    SensorAlarmType,
    SensorExtremeMetricType,
    SensorStatusType,
    SmartDetectObjectType,
    SmokeTestSource,
)

# Every ``type`` string in the public ``event`` ``oneOf`` discriminator.
_ALL_EVENT_TYPES = [
    "ring",
    "sensorExtremeValues",
    "sensorWaterLeak",
    "sensorTamper",
    "sensorBatteryLow",
    "sensorAlarm",
    "sensorVape",
    "sensorOpened",
    "sensorClosed",
    "sensorSmokeTest",
    "sensorSmokeBatteryLow",
    "sensorSmokeNeedsCleaning",
    "sensorSmokeFault",
    "sensorCoFault",
    "sensorSmokeEndOfLife",
    "sensorMotion",
    "sensorButtonPressed",
    "lightMotion",
    "motion",
    "smartAudioDetect",
    "smartDetectZone",
    "smartDetectLine",
    "smartDetectLoiterZone",
    "relayInputChanged",
    "alarmHubMotion",
    "alarmHubEntryOpened",
    "alarmHubEntryClosed",
    "alarmHubSmoke",
    "alarmHubGlassBreak",
    "alarmHubButtonPress",
    "alarmHubTamper",
    "alarmHubRelaySwitched",
    "alarmHubBatteryLow",
    "alarmHubBatteryConnected",
    "alarmHubDeviceTamper",
    "cameraDigitalInputChanged",
    "nfcCardScanned",
    "fingerprintIdentified",
]


def _minimal(type_str: str, **extra: object) -> dict[str, object]:
    return {
        "id": "evt-1",
        "modelKey": "event",
        "type": type_str,
        "start": 1735689600000,
        "device": "aabbccddeeff00112233aabb",
        **extra,
    }


@pytest.mark.parametrize("type_str", _ALL_EVENT_TYPES)
def test_every_public_event_type_parses(type_str: str) -> None:
    event = PublicEvent.from_unifi_dict(**_minimal(type_str))
    assert event.id == "evt-1"
    assert event.model is ModelType.EVENT
    assert event.type.value == type_str
    assert event.device_id == "aabbccddeeff00112233aabb"
    assert isinstance(event.start, datetime)


def test_event_envelope_fields() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal(
            "smartDetectZone",
            end=1735689601000,
            smartDetectTypes=["person"],
        )
    )
    assert event.end is not None and isinstance(event.end, datetime)
    assert event.smart_detect_types == [SmartDetectObjectType.PERSON]


def test_unknown_smart_detect_type_dropped() -> None:
    """A runtime-generated smart detect type in an event payload is dropped, not fatal."""
    event = PublicEvent.from_unifi_dict(
        **_minimal(
            "smartDetectZone",
            smartDetectTypes=["person", "linecrossing_basic"],
        )
    )
    assert event.smart_detect_types == [SmartDetectObjectType.PERSON]


def test_sensor_extreme_metric_enum_resolves() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal(
            "sensorExtremeValues",
            metadata={
                "sensorType": {"text": "co2"},
                "sensorValue": {"text": 22.5},
                "status": {"text": "high"},
            },
        )
    )
    assert event.metadata is not None
    assert event.metadata.sensor_type is SensorExtremeMetricType.CO2
    assert event.metadata.sensor_value == 22.5
    assert event.metadata.status == "high"
    assert event.sensor_status is SensorStatusType.HIGH


def test_alarm_type_enum_resolves() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal("sensorAlarm", metadata={"alarmType": {"text": "glassBreak"}})
    )
    assert event.metadata is not None
    assert event.metadata.alarm_type is SensorAlarmType.GLASS_BREAK


def test_relay_input_state_enum_resolves() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal(
            "relayInputChanged",
            metadata={
                "inputState": {"text": "circuitOpen"},
                "inputChannel": {"text": "0"},
            },
        )
    )
    assert event.metadata is not None
    assert event.metadata.input_state is RelayInputCircuitState.CIRCUIT_OPEN
    assert event.metadata.input_channel == "0"


def test_smoke_test_source_enum_resolves_flat() -> None:
    """``sensorSmokeTest`` ``metadata.source`` is a flat string, not enveloped."""
    event = PublicEvent.from_unifi_dict(
        **_minimal("sensorSmokeTest", metadata={"source": "local"})
    )
    assert event.metadata is not None
    assert event.metadata.source is SmokeTestSource.LOCAL


@pytest.mark.parametrize(
    ("type_str", "metadata", "field", "enum_cls"),
    [
        (
            "sensorExtremeValues",
            {"sensorType": {"text": "unobtanium"}},
            "sensor_type",
            SensorExtremeMetricType,
        ),
        (
            "sensorAlarm",
            {"alarmType": {"text": "unobtanium"}},
            "alarm_type",
            SensorAlarmType,
        ),
        (
            "relayInputChanged",
            {"inputState": {"text": "unobtanium"}},
            "input_state",
            RelayInputCircuitState,
        ),
        (
            "sensorSmokeTest",
            {"source": "unobtanium"},
            "source",
            SmokeTestSource,
        ),
    ],
)
def test_unmodelled_enum_value_coerces_to_unknown(
    type_str: str,
    metadata: dict[str, object],
    field: str,
    enum_cls: type,
) -> None:
    event = PublicEvent.from_unifi_dict(**_minimal(type_str, metadata=metadata))
    assert event.metadata is not None
    assert getattr(event.metadata, field) is enum_cls.UNKNOWN


def test_button_enum_resolves() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal("sensorButtonPressed", metadata={"button": {"text": "panic"}})
    )
    assert event.metadata is not None
    assert event.metadata.button is EventButtonType.PANIC


def test_mount_type_enum_resolves() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal("sensorOpened", metadata={"sensorMountType": {"text": "garage"}})
    )
    assert event.metadata is not None
    assert event.metadata.sensor_mount_type is MountType.GARAGE


def test_sensor_battery_percentage_number_envelope() -> None:
    """``sensorBatteryPercentage`` uses a ``{"number": ...}`` envelope, not ``text``."""
    event = PublicEvent.from_unifi_dict(
        **_minimal(
            "sensorBatteryLow",
            metadata={"sensorBatteryPercentage": {"number": 95}},
        )
    )
    assert event.metadata is not None
    assert event.metadata.sensor_battery_percentage == 95


def test_alarm_hub_string_metadata_collapses() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal(
            "alarmHubMotion",
            metadata={
                "pin": {"text": "0"},
                "deviceId": {"text": "hub-1"},
                "deviceName": {"text": "Front Door"},
            },
        )
    )
    assert event.metadata is not None
    assert event.metadata.pin == "0"
    assert event.metadata.device_id == "hub-1"
    assert event.metadata.device_name == "Front Door"


def test_nfc_and_fingerprint_submodels() -> None:
    nfc = PublicEvent.from_unifi_dict(
        **_minimal("nfcCardScanned", metadata={"nfc": {"ulpId": "ulp-1"}})
    )
    assert nfc.metadata is not None
    assert isinstance(nfc.metadata.nfc, PublicNfcMetadata)
    assert nfc.metadata.nfc.ulp_id == "ulp-1"

    fp = PublicEvent.from_unifi_dict(
        **_minimal("fingerprintIdentified", metadata={"fingerprint": {"ulpId": None}})
    )
    assert fp.metadata is not None
    assert isinstance(fp.metadata.fingerprint, PublicFingerprintMetadata)
    assert fp.metadata.fingerprint.ulp_id is None


def test_malformed_envelope_without_text_is_dropped() -> None:
    """A ``{...}`` value missing its ``text``/``number`` key is discarded, not raised."""
    event = PublicEvent.from_unifi_dict(
        **_minimal("sensorAlarm", metadata={"alarmType": {"unexpected": "x"}})
    )
    assert event.metadata is not None
    assert event.metadata.alarm_type is None


def test_metadata_round_trips_and_strips_none() -> None:
    md = PublicEventMetadata(
        sensor_type=SensorExtremeMetricType.CO2,
        sensor_value=22.5,
        status="high",
        sensor_battery_percentage=95,
    )
    wire = md.unifi_dict()
    assert wire == {
        "sensorType": {"text": "co2"},
        "sensorValue": {"text": 22.5},
        "status": {"text": "high"},
        "sensorBatteryPercentage": {"number": 95},
    }


def test_event_round_trips_metadata() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal("sensorAlarm", metadata={"alarmType": {"text": "smoke"}})
    )
    assert event.unifi_dict()["metadata"]["alarmType"] == {"text": "smoke"}


def test_tamper_status_resolves_and_is_type_scoped() -> None:
    """``alarmHubDeviceTamper`` narrows ``metadata.status`` to its own enum."""
    event = PublicEvent.from_unifi_dict(
        **_minimal("alarmHubDeviceTamper", metadata={"status": {"text": "tampered"}})
    )
    assert event.metadata is not None
    assert event.metadata.status == "tampered"
    assert event.tamper_status is AlarmHubTamperStatus.TAMPERED
    assert event.sensor_status is None
    assert event.alarm_hub_input_status is None


def test_alarm_hub_input_status_resolves_and_is_type_scoped() -> None:
    """An alarm-hub zone event narrows ``metadata.status`` to ``AlarmHubInputStatus``."""
    event = PublicEvent.from_unifi_dict(
        **_minimal("alarmHubMotion", metadata={"status": {"text": "alarm"}})
    )
    assert event.alarm_hub_input_status is AlarmHubInputStatus.ALARM
    assert event.sensor_status is None
    assert event.tamper_status is None


def test_sensor_status_is_type_scoped() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal("sensorExtremeValues", metadata={"status": {"text": "high"}})
    )
    assert event.sensor_status is SensorStatusType.HIGH
    assert event.alarm_hub_input_status is None
    assert event.tamper_status is None


@pytest.mark.parametrize(
    ("type_str", "attr"),
    [
        ("sensorExtremeValues", "sensor_status"),
        ("alarmHubMotion", "alarm_hub_input_status"),
        ("alarmHubDeviceTamper", "tamper_status"),
    ],
)
def test_status_accessor_none_without_metadata(type_str: str, attr: str) -> None:
    event = PublicEvent.from_unifi_dict(**_minimal(type_str))
    assert getattr(event, attr) is None

    with_empty = PublicEvent.from_unifi_dict(**_minimal(type_str, metadata={}))
    assert getattr(with_empty, attr) is None


@pytest.mark.parametrize(
    ("type_str", "attr", "enum_cls"),
    [
        ("sensorExtremeValues", "sensor_status", SensorStatusType),
        ("alarmHubMotion", "alarm_hub_input_status", AlarmHubInputStatus),
        ("alarmHubDeviceTamper", "tamper_status", AlarmHubTamperStatus),
    ],
)
def test_status_accessor_coerces_unknown_value(
    type_str: str, attr: str, enum_cls: type
) -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal(type_str, metadata={"status": {"text": "unobtanium"}})
    )
    assert getattr(event, attr) is enum_cls.UNKNOWN


def test_status_round_trips_unmodelled_alarm_hub_value() -> None:
    """A free-form alarm-hub status survives the round trip verbatim."""
    event = PublicEvent.from_unifi_dict(
        **_minimal("alarmHubSmoke", metadata={"status": {"text": "restoredish"}})
    )
    assert event.unifi_dict()["metadata"]["status"] == {"text": "restoredish"}


def test_camera_digital_input_metadata() -> None:
    event = PublicEvent.from_unifi_dict(
        **_minimal(
            "cameraDigitalInputChanged",
            metadata={
                "inputState": {"text": "circuitOpen"},
                "inputToken": {"text": "AlarmIn_0"},
                "inputChannel": {"text": "0"},
            },
        )
    )
    assert event.metadata is not None
    assert event.metadata.input_state is RelayInputCircuitState.CIRCUIT_OPEN
    assert event.metadata.input_token == "AlarmIn_0"  # noqa: S105
    assert event.unifi_dict()["metadata"]["inputToken"] == {"text": "AlarmIn_0"}


def test_new_event_enum_values() -> None:
    assert SensorExtremeMetricType("nox") is SensorExtremeMetricType.NOX
    assert EventButtonType("main") is EventButtonType.MAIN
