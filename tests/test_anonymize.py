from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest

from tests.test_public_devices_models import SENSOR_PAYLOAD
from uiprotect import anonymize
from uiprotect.anonymize import anonymize_data, anonymize_object_id
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
