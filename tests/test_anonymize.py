from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest

from tests.test_public_devices_models import SENSOR_PAYLOAD
from uiprotect import anonymize
from uiprotect.anonymize import (
    anonymize_data,
    anonymize_ip,
    anonymize_object_id,
    anonymize_peristent_string,
    anonymize_prefixed_event_id,
    anonymize_uuid,
    random_ip,
)
from uiprotect.data.public_devices import (
    AlarmHubInput,
    Fob,
    PublicChime,
    PublicNVR,
    PublicSensor,
    Relay,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from uiprotect.api import ProtectApiClient
    from uiprotect.data import Chime

_WIRELESS = {
    "signalState": {"signalQuality": 85, "signalStrength": -45},
    "batteryStatus": {"percentage": 90, "isLow": False},
    "bridge": None,
}

_STREAMS = {
    "high": "rtsps://192.168.1.10:7441/abcdef123456?enableSrtp",
    "medium": "rtsps://192.168.1.10:7441/secretmediumalias",
    "package": "rtsps://192.168.1.10:7441/packagealias",
}


def test_rtsps_streams_dict_anonymized() -> None:
    result = anonymize_data({"rtspsStreams": dict(_STREAMS)}, name="camera")[
        "rtspsStreams"
    ]

    assert set(result) == set(_STREAMS)
    for quality, url in result.items():
        assert url != _STREAMS[quality]
        parts = urlparse(url)
        assert parts.scheme == "rtsps"
        assert "192.168.1.10" not in url
        assert parts.path.lstrip("/") not in _STREAMS[quality]


def test_rtsps_streams_within_public_camera_dump() -> None:
    dump = {
        "modelKey": "camera",
        "id": "aabbccddeeff00112233",
        "rtspsStreams": dict(_STREAMS),
    }

    result = anonymize_data(dump)

    for quality, url in result["rtspsStreams"].items():
        assert url != _STREAMS[quality]
        assert "192.168.1.10" not in url


def test_rtsps_streams_list_anonymized() -> None:
    result = anonymize_data(list(_STREAMS.values()), name="rtspsStreams")

    for original, url in zip(_STREAMS.values(), result, strict=True):
        assert url != original
        assert "192.168.1.10" not in url
        assert urlparse(url).scheme == "rtsps"


def test_rtsps_streams_preserves_non_string_values() -> None:
    result = anonymize_data(
        {"rtspsStreams": {"high": None, "enabled": True}}, name="camera"
    )

    assert result["rtspsStreams"] == {"high": None, "enabled": True}


def test_import_skips_optional_test_util_dependencies() -> None:
    code = (
        "import sys, uiprotect; "
        "loaded = 'uiprotect.anonymize' in sys.modules; "
        "import uiprotect.anonymize; "
        "print(loaded, 'PIL' in sys.modules, 'uiprotect.test_util' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(anonymize.__file__).parents[1])},
    )

    assert result.stdout.split() == ["True", "False", "False"]


def test_legacy_import_path_is_same_module() -> None:
    from uiprotect.test_util import anonymize as legacy  # noqa: PLC0415

    assert legacy is anonymize
    assert legacy.object_id_mapping is anonymize.object_id_mapping


def _anonymized_ref(model_key: str, raw_id: str) -> str:
    return anonymize_data({"modelKey": model_key, "id": raw_id})["id"]


def _chime_dump() -> dict[str, Any]:
    return PublicChime.from_unifi_dict(
        id="anon-chime",
        modelKey="chime",
        state="CONNECTED",
        mac="AABBCCDDEE03",
        name="Chime",
        cameraIds=["anon-cam-a"],
        ringSettings=[{"cameraId": "anon-cam-a", "volume": 50, "repeatTimes": 1}],
    ).unifi_dict()


def _sensor_dump() -> dict[str, Any]:
    return PublicSensor.from_unifi_dict(
        **{**SENSOR_PAYLOAD, "armProfileIds": ["anon-arm-1"]}
    ).unifi_dict()


def _fob_dump() -> dict[str, Any]:
    return Fob.from_unifi_dict(
        id="anon-fob",
        modelKey="fob",
        state="CONNECTED",
        mac="AABBCCDDEE04",
        awayState="ONLINE",
        buttonLabels="securityActions",
        featureFlags={"buttons": []},
        wirelessConnectionState=_WIRELESS,
        armControlSettings={
            "enabled": True,
            "armProfileId": "anon-arm-1",
            "nightProfileId": "anon-arm-2",
        },
    ).unifi_dict()


def _nvr_dump() -> dict[str, Any]:
    return PublicNVR.from_unifi_dict(
        id="anon-nvr",
        modelKey="nvr",
        name="NVR",
        doorbellSettings={
            "defaultMessageText": "WELCOME",
            "defaultMessageResetTimeoutMs": 60000,
            "customMessages": [],
            "customImages": [],
        },
        armMode={
            "status": "armed",
            "armProfileId": "anon-arm-1",
            "breachEventId": "anon-event-1",
            "breachTriggerEventId": "anon-event-2",
        },
    ).unifi_dict()


def _alarm_hub_input_dump() -> dict[str, Any]:
    return {
        "input": [
            AlarmHubInput.from_unifi_dict(
                enable="on", type="nc", status="normal", cameraId="anon-cam-a"
            ).unifi_dict()
        ]
    }


@pytest.mark.parametrize(
    ("dump", "path", "ref_model_key", "ref_id"),
    [
        (_chime_dump, ("cameraIds", 0), "camera", "anon-cam-a"),
        (_chime_dump, ("ringSettings", 0, "cameraId"), "camera", "anon-cam-a"),
        (_alarm_hub_input_dump, ("input", 0, "cameraId"), "camera", "anon-cam-a"),
        (_sensor_dump, ("armProfileIds", 0), None, "anon-arm-1"),
        (_fob_dump, ("armControlSettings", "armProfileId"), None, "anon-arm-1"),
        (_fob_dump, ("armControlSettings", "nightProfileId"), None, "anon-arm-2"),
        (_nvr_dump, ("armMode", "armProfileId"), None, "anon-arm-1"),
        (_nvr_dump, ("armMode", "breachEventId"), "event", "anon-event-1"),
        (_nvr_dump, ("armMode", "breachTriggerEventId"), "event", "anon-event-2"),
    ],
)
def test_public_reference_ids_follow_referenced_id(
    dump: Callable[[], dict[str, Any]],
    path: tuple[str | int, ...],
    ref_model_key: str | None,
    ref_id: str,
) -> None:
    value: Any = anonymize_data(dump())
    for key in path:
        value = value[key]

    expected = (
        anonymize_object_id(ref_id)
        if ref_model_key is None
        else _anonymized_ref(ref_model_key, ref_id)
    )
    assert value == expected != ref_id


@pytest.mark.parametrize(
    ("key", "model_key"),
    [("cameraId", "camera"), ("liveviewId", "liveview"), ("eventId", "event")],
)
def test_reference_id_keys_follow_referenced_id(key: str, model_key: str) -> None:
    raw_id = f"anon-raw-{key}"

    result = anonymize_data({key: raw_id})

    assert result[key] == _anonymized_ref(model_key, raw_id) != raw_id


def test_action_output_id_follows_output_id() -> None:
    dump = Relay.from_unifi_dict(
        id="anon-relay",
        name="Relay",
        modelKey="relay",
        state="CONNECTED",
        mac="AABBCCDDEE05",
        ledSettings={"isEnabled": True},
        wirelessConnectionState=_WIRELESS,
        outputs=[{"id": 3}],
        inputs=[{"id": 0, "actionOutputId": 3}],
    ).unifi_dict()

    result = anonymize_data(dump)

    assert result["inputs"][0]["actionOutputId"] == result["outputs"][0]["id"]
    assert anonymize_data({"actionOutputId": "out-1"})["actionOutputId"] == (
        anonymize_object_id("out-1")
    )


@pytest.mark.asyncio
async def test_private_chime_camera_ids_follow_camera_id(
    protect_client: ProtectApiClient, chime_obj: Chime | None
) -> None:
    if chime_obj is None:
        pytest.skip("No chime obj found")
    camera = next(iter(protect_client.bootstrap.cameras.values()))
    chime_obj.camera_ids = [camera.id]

    result = anonymize_data(chime_obj.unifi_dict())
    anonymized_camera = anonymize_data(camera.unifi_dict())

    assert result["cameraIds"] == [anonymized_camera["id"]]
    assert camera.id not in result["cameraIds"]


def test_user_fields_anonymized() -> None:
    user = {
        "modelKey": "user",
        "id": "anon-user-1",
        "groups": ["anon-group-1"],
        "firstName": "Jane",
        "lastName": "Doe",
        "name": "Jane Doe",
        "localUsername": "jane",
        "email": "jane@real.test",
        "cloudAccount": {
            "firstName": "Jane",
            "lastName": "Doe",
            "name": "Jane Doe",
            "email": "jane@real.test",
            "user": "anon-user-1",
            "id": "anon-cloud-account-1",
            "cloudId": "anon-cloud-id-1",
        },
        "settings": {"cameraOrder": ["anon-order-cam"]},
        "allPermissions": ["camera:*:anon-perm-cam"],
        "permissions": ["liveview:*:anon-perm-lv"],
    }

    result = anonymize_data(user)

    assert result["id"] == anonymize_object_id("anon-user-1") != "anon-user-1"
    assert result["groups"] == [anonymize_object_id("anon-group-1")]
    assert result["name"] == f"{result['firstName']} {result['lastName']}"
    assert result["firstName"] != "Jane"
    assert result["email"] == f"{result['localUsername']}@example.com"
    cloud = result["cloudAccount"]
    for key in ("firstName", "lastName", "name", "email"):
        assert cloud[key] == result[key]
    assert cloud["user"] == result["id"]
    assert cloud["id"] == anonymize_uuid("anon-cloud-account-1")
    assert cloud["cloudId"] == anonymize_uuid("anon-cloud-id-1")
    uuid.UUID(cloud["cloudId"])
    assert result["settings"]["cameraOrder"] == [anonymize_object_id("anon-order-cam")]
    assert result["allPermissions"] == ["camera:*:anon-perm-cam"]
    assert result["permissions"] == [
        f"liveview:*:{anonymize_object_id('anon-perm-lv')}"
    ]


def test_minimal_user_anonymized() -> None:
    result = anonymize_data(
        {
            "modelKey": "user",
            "id": "anon-user-2",
            "cloudAccount": None,
            "settings": None,
        }
    )

    assert result == {
        "modelKey": "user",
        "id": anonymize_object_id("anon-user-2"),
        "cloudAccount": None,
        "settings": None,
    }


def test_event_fields_anonymized() -> None:
    event = {
        "modelKey": "event",
        "id": "anon-event-3",
        "type": "sensorOpened",
        "thumbnail": "e-anon-event-3",
        "heatmap": "e-anon-event-3",
        "metadata": {
            "sensorId": {"text": "anon-sensor-1"},
            "sensorName": {"text": "Front Door"},
        },
    }

    result = anonymize_data(event)

    assert result["id"] == anonymize_object_id("anon-event-3")
    assert result["type"] == "sensorOpened"
    assert result["thumbnail"] == f"e-{result['id']}"
    assert result["heatmap"] == f"e-{result['id']}"
    assert result["metadata"]["sensorId"]["text"] == anonymize_object_id(
        "anon-sensor-1"
    )
    assert result["metadata"]["sensorName"]["text"] != "Front Door"


def test_event_without_sensor_metadata_anonymized() -> None:
    result = anonymize_data(
        {"modelKey": "event", "id": "anon-event-4", "metadata": {"extra": "x"}}
    )

    assert result["metadata"] == {"extra": "x"}


def test_payload_dict_id_anonymized() -> None:
    result = anonymize_data({"id": "anon-payload-id", "payload": {"note": "x"}})

    assert result == {
        "id": anonymize_object_id("anon-payload-id"),
        "payload": {"note": "x"},
    }


def test_id_without_model_key_unchanged() -> None:
    assert anonymize_data({"id": "anon-plain-id"}) == {"id": "anon-plain-id"}


def test_unknown_model_key_warns() -> None:
    with pytest.warns(UserWarning, match="Unknown modelKey: notAModel"):
        result = anonymize_data({"modelKey": "notAModel", "id": "anon-unknown"})

    assert result["id"] == "anon-unknown"


def test_prefixed_event_id() -> None:
    assert anonymize_prefixed_event_id("e-anon-event-5") == (
        f"e-{anonymize_object_id('anon-event-5')}"
    )


@pytest.mark.parametrize("ip", [None, 7, "0.0.0.0", "127.0.0.1", "255.255.255.255"])  # noqa: S104
def test_anonymize_ip_passthrough(ip: Any) -> None:
    assert anonymize_ip(ip) == ip


def test_anonymize_ip_is_persistent() -> None:
    result = anonymize_ip("192.168.77.1")

    assert result.startswith("192.168.")
    assert anonymize_ip("192.168.77.1") == result


@pytest.mark.parametrize(
    ("ip", "prefix"),
    [
        ("10.1.2.3", "10."),
        ("172.20.1.1", "172."),
        ("192.168.1.1", "192.168."),
        ("172.40.1.1", ""),
        ("8.8.8.8", ""),
        ("not-an-ip", ""),
    ],
)
def test_random_ip(ip: str, prefix: str) -> None:
    result = random_ip(ip)

    octets = [int(octet) for octet in result.split(".")]
    assert len(octets) == 4
    assert result.startswith(prefix)
    assert all(0 <= octet <= 255 for octet in octets)
    if prefix == "172.":
        assert 16 <= octets[1] <= 31


def _is_hex(value: str, length: int) -> bool:
    return len(value) == length and all(c in "0123456789abcdefABCDEF" for c in value)


@pytest.mark.parametrize(
    ("name", "value", "check"),
    [
        (
            "accessKey",
            "anon-access-key",
            lambda r: [len(p) for p in r.split(":")] == [13, 24, 128],
        ),
        ("credentials", "anon-credentials", lambda r: _is_hex(r, 64)),
        ("privateToken", "anon-token", lambda r: len(r) == 192 and r.isalnum()),
        ("host", "192.168.50.1", lambda r: r == anonymize_ip("192.168.50.1")),
        ("connectionHost", "10.9.9.9", lambda r: r == anonymize_ip("10.9.9.9")),
        ("bindAddr", "172.16.5.5", lambda r: r == anonymize_ip("172.16.5.5")),
        ("anonymousDeviceId", "anon-device", lambda r: uuid.UUID(r) is not None),
        ("hardwareId", "anon-hardware", lambda r: uuid.UUID(r) is not None),
        ("rtspAlias", "anon-alias", lambda r: len(r) == 16 and r.isalnum()),
        ("ssid", "anon-ssid", lambda r: len(r) == 16 and r.isalnum()),
        (
            "mac",
            "AABBCCDDEE10",
            lambda r: (
                _is_hex(r, 12) and r == anonymize_peristent_string("AABBCCDDEE10", "")
            ),
        ),
        ("server_id", "anon-server", lambda r: _is_hex(r, 12)),
        (
            "bssid",
            "aa:bb:cc:dd:ee:11",
            lambda r: [len(p) for p in r.split(":")] == [2] * 6,
        ),
        ("latitude", "12.34", lambda r: r == "0.0"),
        ("longitude", "56.78", lambda r: r == "0.0"),
        ("name", "Front Door", lambda r: r != "Front Door"),
        ("name", "Default", lambda r: r == "Default"),
        ("owner", "anon-owner", lambda r: r == anonymize_object_id("anon-owner")),
        (
            "rtsp",
            "rtsp://192.168.1.10:7447/alias",
            lambda r: r.startswith("rtsp://") and ":7447/" in r and "alias" not in r,
        ),
        (
            "rtsp",
            "rtsp://192.168.1.10:554/alias",
            lambda r: r.startswith("rtsp://") and ":554" not in r,
        ),
        (
            "rtsp",
            "rtsp://192.168.1.10/alias",
            lambda r: r.startswith("rtsp://") and "alias" not in r,
        ),
        (
            "other",
            "liveview:*:anon-lv-2",
            lambda r: r == f"liveview:*:{anonymize_object_id('anon-lv-2')}",
        ),
        ("other", "unchanged", lambda r: r == "unchanged"),
        (None, "unchanged", lambda r: r == "unchanged"),
    ],
)
def test_anonymize_value(
    name: str | None, value: str, check: Callable[[str], bool]
) -> None:
    result = anonymize_data(value, name=name)

    assert check(result)
    if name not in {"name", "other", None}:
        assert result != value


@pytest.mark.parametrize("value", [None, 5, True])
def test_anonymize_value_non_string_unchanged(value: Any) -> None:
    assert anonymize_data(value, name="owner") == value


def test_anonymize_list_branches() -> None:
    hosts = anonymize_data(["192.168.60.1", "127.0.0.1", 5], name="hosts")
    ids = anonymize_data(["anon-cam-list"], name="cameras")
    plain = anonymize_data(["liveview:*:anon-lv-3", "keep"], name="other")

    assert hosts == [anonymize_ip("192.168.60.1"), "127.0.0.1", 5]
    assert ids == [anonymize_object_id("anon-cam-list")]
    assert plain == [f"liveview:*:{anonymize_object_id('anon-lv-3')}", "keep"]
