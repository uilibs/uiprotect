from __future__ import annotations

import asyncio
import base64
import json
import math
import os
from contextlib import suppress
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from shlex import split
from subprocess import run
from tempfile import NamedTemporaryFile
from typing import Any
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
import pytest_asyncio

from tests.sample_data.constants import CONSTANTS
from uiprotect import ProtectApiClient
from uiprotect.data import Camera, ModelType
from uiprotect.data.devices import PTZRange, PTZZoomRange
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType
from uiprotect.utils import _BAD_UUID, set_debug, set_no_debug

UFP_SAMPLE_DIR = os.environ.get("UFP_SAMPLE_DIR")
if UFP_SAMPLE_DIR:
    SAMPLE_DATA_DIRECTORY = Path(UFP_SAMPLE_DIR)
else:
    SAMPLE_DATA_DIRECTORY = Path(__file__).parent / "sample_data"

CHECK_CMD = "ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 {filename}"
LENGTH_CMD = "ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {filename}"

TEST_CAMERA_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists()
TEST_SNAPSHOT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_snapshot.png").exists()
TEST_VIDEO_EXISTS = (
    SAMPLE_DATA_DIRECTORY / "sample_camera_video.mp4"
).exists() or "camera_video_length" not in CONSTANTS
TEST_THUMBNAIL_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_thumbnail.png").exists()
TEST_HEATMAP_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_heatmap.png").exists()
TEST_SMART_TRACK_EXISTS = (
    SAMPLE_DATA_DIRECTORY / "sample_event_smart_track.json"
).exists()
TEST_LIGHT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_light.json").exists()
TEST_SENSOR_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_sensor.json").exists()
TEST_VIEWPORT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_viewport.json").exists()
TEST_BRIDGE_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_bridge.json").exists()
TEST_LIVEVIEW_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_liveview.json").exists()
TEST_DOORLOCK_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_doorlock.json").exists()
TEST_CHIME_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_chime.json").exists()

ANY_NONE = [[None], None, []]


def read_binary_file(name: str, ext: str = "png"):
    with (SAMPLE_DATA_DIRECTORY / f"{name}.{ext}").open("rb") as f:
        return f.read()


def read_json_file(name: str):
    with (SAMPLE_DATA_DIRECTORY / f"{name}.json").open(encoding="utf8") as f:
        return json.load(f)


def read_bootstrap_json_file():
    # tests expect global recording settings to be off
    bootstrap = read_json_file("sample_bootstrap")
    cameras = []
    for camera in bootstrap["cameras"]:
        if camera.get("useGlobal"):
            camera["useGlobal"] = False
        cameras.append(camera)

    bootstrap["cameras"] = cameras
    return bootstrap


def read_camera_json_file():
    # tests expect global recording settings to be off
    camera = read_json_file("sample_camera")
    if camera.get("useGlobal"):
        camera["useGlobal"] = False

    return camera


def get_now():
    return datetime.fromisoformat(CONSTANTS["time"]).replace(microsecond=0)


def get_time():
    return datetime.fromisoformat(CONSTANTS["time"]).replace(microsecond=0).timestamp()


def validate_video_file(filepath: Path, length: int):
    output = run(
        split(CHECK_CMD.format(filename=filepath)),
        check=True,
        capture_output=True,
    )
    assert output.stdout.decode("utf8").strip() == "video"

    output = run(
        split(LENGTH_CMD.format(filename=filepath)),
        check=True,
        capture_output=True,
    )
    # it looks like UFP does not always generate a video of exact length
    assert length - 10 < int(float(output.stdout.decode("utf8").strip())) < length + 10


async def mock_api_request_raw(url: str, *args, **kwargs):
    if url.startswith("thumbnails/") or url.endswith("thumbnail"):
        return read_binary_file("sample_camera_thumbnail")
    if url.startswith("cameras/"):
        return read_binary_file("sample_camera_snapshot")
    if url.startswith("heatmaps/") or url.endswith("heatmap"):
        return read_binary_file("sample_camera_heatmap")
    if url == "video/export":
        return read_binary_file("sample_camera_video", "mp4")
    return b""


async def mock_api_request(url: str, *args, **kwargs):
    if url == "bootstrap":
        return read_bootstrap_json_file()
    if url == "nvr":
        return read_bootstrap_json_file()["nvr"]
    if url == "events":
        return read_json_file("sample_raw_events")
    if url == "cameras":
        return [read_camera_json_file()]
    if url == "lights":
        return [read_json_file("sample_light")]
    if url == "sensors":
        return [read_json_file("sample_sensor")]
    if url == "viewers":
        return [read_json_file("sample_viewport")]
    if url == "bridges":
        return [read_json_file("sample_bridge")]
    if url == "liveviews":
        return [read_json_file("sample_liveview")]
    if url == "doorlocks":
        return [read_json_file("sample_doorlock")]
    if url == "chimes":
        return [read_json_file("sample_chime")]
    if url.endswith("ptz/preset"):
        return {
            "id": "test-id",
            "name": "Test",
            "slot": 0,
            "ptz": {
                "pan": 100,
                "tilt": 100,
                "zoom": 0,
            },
        }
    if url.endswith("ptz/home"):
        return {
            "id": "test-id",
            "name": "Home",
            "slot": -1,
            "ptz": {
                "pan": 100,
                "tilt": 100,
                "zoom": 0,
            },
        }
    if url.startswith("cameras/"):
        return read_camera_json_file()
    if url.startswith("lights/"):
        return read_json_file("sample_light")
    if url.startswith("sensors/"):
        return read_json_file("sample_sensor")
    if url.startswith("viewers/"):
        return read_json_file("sample_viewport")
    if url.startswith("bridges/"):
        return read_json_file("sample_bridge")
    if url.startswith("liveviews/"):
        return read_json_file("sample_liveview")
    if url.startswith("doorlocks"):
        return read_json_file("sample_doorlock")
    if url.startswith("chimes"):
        return read_json_file("sample_chime")
    if "smartDetectTrack" in url:
        return read_json_file("sample_event_smart_track")

    return {}


class SimpleMockWebsocket:
    is_closed: bool = False
    now: float = 0
    events: dict[str, Any]
    count = 0

    def __init__(self):
        self.events = []

    @property
    def closed(self):
        return self.is_closed

    async def close(self):
        self.is_closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if len(self.events) == 0 or self.is_closed:
            raise StopAsyncIteration

        key = next(iter(self.events.keys()))
        next_time = float(key)
        await asyncio.sleep(next_time - self.now)
        self.now = next_time

        data = self.events.pop(key)
        self.count += 1
        return aiohttp.WSMessage(
            aiohttp.WSMsgType.BINARY,
            base64.b64decode(data["raw"]),
            None,
        )

    async def receive(self, timeout):
        return await self.__anext__()


class MockWebsocket(SimpleMockWebsocket):
    def __init__(self):
        super().__init__()

        self.events = read_json_file("sample_ws_messages")


MockDatetime = Mock()
MockDatetime.now.return_value = get_now()
MockDatetime.utcnow.return_value = get_now()


@pytest.fixture(autouse=True)
def _ensure_debug():
    set_debug()


async def setup_client(
    client: ProtectApiClient,
    websocket: SimpleMockWebsocket,
    timeout: int = 0,
):
    mock_cs = AsyncMock()
    mock_session = AsyncMock()
    mock_session.ws_connect = AsyncMock(return_value=websocket)
    mock_cs.return_value = mock_session

    ws = client._get_websocket()
    ws.timeout = timeout
    ws._get_session = mock_cs  # type: ignore[method-assign]
    client.api_request = AsyncMock(side_effect=mock_api_request)  # type: ignore[method-assign]
    client.api_request_raw = AsyncMock(side_effect=mock_api_request_raw)  # type: ignore[method-assign]
    client.ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    await client.update()

    # make sure global recording settings are disabled for all cameras (test expect it)
    for camera in client.bootstrap.cameras.values():
        camera.use_global = False

    return client


async def cleanup_client(client: ProtectApiClient):
    await client.async_disconnect_ws()
    await client.close_session()


@pytest_asyncio.fixture(name="protect_client")
async def protect_client_fixture():
    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        ws_timeout=0.1,
        store_sessions=False,
    )
    yield await setup_client(client, SimpleMockWebsocket())
    await cleanup_client(client)


@pytest_asyncio.fixture
async def protect_client_no_debug():
    set_no_debug()

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        ws_timeout=0.1,
        store_sessions=False,
    )
    yield await setup_client(client, SimpleMockWebsocket())
    await cleanup_client(client)


@pytest_asyncio.fixture
async def protect_client_ws():
    set_no_debug()

    client = ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        ws_timeout=0.1,
        store_sessions=False,
    )
    yield await setup_client(client, MockWebsocket(), timeout=30)
    await cleanup_client(client)


@pytest_asyncio.fixture
async def smart_dectect_obj(protect_client: ProtectApiClient, raw_events):
    event_dict = None
    for event in raw_events:
        if event["type"] == EventType.SMART_DETECT.value:
            event_dict = event
            break

    if event_dict is None:
        yield None
    else:
        yield Event.from_unifi_dict(api=protect_client, **event_dict)


@pytest_asyncio.fixture
async def nvr_obj(protect_client: ProtectApiClient):
    yield protect_client.bootstrap.nvr


@pytest_asyncio.fixture
async def camera_obj(protect_client: ProtectApiClient):
    if not TEST_CAMERA_EXISTS:
        return None

    return next(iter(protect_client.bootstrap.cameras.values()))


@pytest_asyncio.fixture
async def ptz_camera(protect_client: ProtectApiClient):
    if not TEST_CAMERA_EXISTS:
        return None

    camera = next(iter(protect_client.bootstrap.cameras.values()))
    # G4 PTZ
    camera.is_ptz = True
    camera.feature_flags.is_ptz = True
    camera.feature_flags.focus = PTZRange(
        steps={  # type: ignore[arg-type]
            "max": 1560,
            "min": 0,
            "step": 1,
        },
        degrees={  # type: ignore[arg-type]
            "max": None,
            "min": None,
            "step": None,
        },
    )
    camera.feature_flags.pan = PTZRange(
        steps={  # type: ignore[arg-type]
            "max": 35200,
            "min": 0,
            "step": 1,
        },
        degrees={  # type: ignore[arg-type]
            "max": 360,
            "min": 0,
            "step": 0.1,
        },
    )
    camera.feature_flags.tilt = PTZRange(
        steps={  # type: ignore[arg-type]
            "max": 9777,
            "min": 1,
            "step": 1,
        },
        degrees={  # type: ignore[arg-type]
            "max": 90,
            "min": -20,
            "step": 0.1,
        },
    )
    camera.feature_flags.zoom = PTZZoomRange(
        ratio=22,
        steps={  # type: ignore[arg-type]
            "max": 2010,
            "min": 0,
            "step": 1,
        },
        degrees={  # type: ignore[arg-type]
            "max": None,
            "min": None,
            "step": None,
        },
    )

    protect_client.bootstrap.cameras[camera.id] = camera
    return camera


@pytest_asyncio.fixture
async def light_obj(protect_client: ProtectApiClient):
    if not TEST_LIGHT_EXISTS:
        return None

    return next(iter(protect_client.bootstrap.lights.values()))


@pytest_asyncio.fixture
async def viewer_obj(protect_client: ProtectApiClient):
    if not TEST_VIEWPORT_EXISTS:
        return None

    return next(iter(protect_client.bootstrap.viewers.values()))


@pytest_asyncio.fixture
async def sensor_obj(protect_client: ProtectApiClient):
    if not TEST_SENSOR_EXISTS:
        return None

    return next(iter(protect_client.bootstrap.sensors.values()))


@pytest_asyncio.fixture(name="doorlock_obj")
async def doorlock_obj_fixture(protect_client: ProtectApiClient):
    if not TEST_DOORLOCK_EXISTS:
        return None

    return next(iter(protect_client.bootstrap.doorlocks.values()))


@pytest_asyncio.fixture(name="chime_obj")
async def chime_obj_fixture(protect_client: ProtectApiClient):
    if not TEST_CHIME_EXISTS:
        return None

    return next(iter(protect_client.bootstrap.chimes.values()))


@pytest_asyncio.fixture
async def liveview_obj(protect_client: ProtectApiClient):
    if not TEST_LIVEVIEW_EXISTS:
        return None

    return next(iter(protect_client.bootstrap.liveviews.values()))


@pytest_asyncio.fixture
async def user_obj(protect_client: ProtectApiClient):
    return protect_client.bootstrap.auth_user


@pytest.fixture()
def liveview():
    if not TEST_LIVEVIEW_EXISTS:
        return None

    return read_json_file("sample_liveview")


@pytest.fixture()
def viewport():
    if not TEST_VIEWPORT_EXISTS:
        return None

    return read_json_file("sample_viewport")


@pytest.fixture()
def light():
    if not TEST_LIGHT_EXISTS:
        return None

    return read_json_file("sample_light")


@pytest.fixture()
def camera():
    if not TEST_CAMERA_EXISTS:
        return None

    return read_camera_json_file()


@pytest.fixture()
def sensor():
    if not TEST_SENSOR_EXISTS:
        return None

    return read_json_file("sample_sensor")


@pytest.fixture()
def doorlock():
    if not TEST_DOORLOCK_EXISTS:
        return None

    return read_json_file("sample_doorlock")


@pytest.fixture()
def chime():
    if not TEST_CHIME_EXISTS:
        return None

    return read_json_file("sample_chime")


@pytest.fixture()
def bridge():
    if not TEST_BRIDGE_EXISTS:
        return None

    return read_json_file("sample_bridge")


@pytest.fixture()
def liveviews():
    if not TEST_LIVEVIEW_EXISTS:
        return []

    return [read_json_file("sample_liveview")]


@pytest.fixture()
def viewports():
    if not TEST_VIEWPORT_EXISTS:
        return []

    return [read_json_file("sample_viewport")]


@pytest.fixture()
def lights():
    if not TEST_LIGHT_EXISTS:
        return []

    return [read_json_file("sample_light")]


@pytest.fixture()
def cameras():
    if not TEST_CAMERA_EXISTS:
        return []

    return [read_camera_json_file()]


@pytest.fixture()
def sensors():
    if not TEST_SENSOR_EXISTS:
        return []

    return [read_json_file("sample_sensor")]


@pytest.fixture()
def doorlocks():
    if not TEST_DOORLOCK_EXISTS:
        return []

    return [read_json_file("sample_doorlock")]


@pytest.fixture()
def chimes():
    if not TEST_CHIME_EXISTS:
        return []

    return [read_json_file("sample_chime")]


@pytest.fixture()
def bridges():
    if not TEST_BRIDGE_EXISTS:
        return []

    return [read_json_file("sample_bridge")]


@pytest.fixture()
def ws_messages():
    return read_json_file("sample_ws_messages")


@pytest.fixture(name="raw_events")
def raw_events_fixture():
    return read_json_file("sample_raw_events")


@pytest.fixture()
def bootstrap():
    return read_bootstrap_json_file()


@pytest.fixture()
def nvr():
    return read_bootstrap_json_file()["nvr"]


@pytest.fixture()
def smart_track():
    if not TEST_SMART_TRACK_EXISTS:
        return None

    return read_json_file("sample_event_smart_track")


@pytest.fixture()
def now():
    return get_now().replace(tzinfo=timezone.utc)


@pytest.fixture()
def tmp_binary_file():
    tmp_file = NamedTemporaryFile(mode="wb", delete=False)

    yield tmp_file

    with suppress(Exception):
        tmp_file.close()

    os.remove(tmp_file.name)


# new values added for newer versions of UFP (for backwards compat tests)
NEW_FIELDS = {
    # 1.20.1
    "voltage",
    # 1.21.0-beta1
    "timestamp",
    "isWirelessUplinkEnabled",
    "marketName",
    # 1.21.0-beta3
    "isPoorNetwork",
    # 2.0-beta2
    "scopes",
    "streamSharingAvailable",
    "isDbAvailable",
    "isRecordingDisabled",
    "isRecordingMotionOnly",
    # 2.1.1-beta3
    "anonymousDeviceId",  # added to viewport
    "isStacked",
    "isPrimary",
    "lastDriveSlowEvent",
    "isUCoreSetup",
    # 2.2.1-beta2
    "isInsightsEnabled",
    # 2.2.2
    "isDownloadingFW",
    # 2.6.13
    "vaultCameras",
    "homekitSettings",
    # 2.6.17
    "apMgmtIp",
    # 2.7.5
    "fwUpdateState",
    "isWaterproofCaseAttached",
    "deletedAt",
    "deletionType",
    "lastDisconnect",
    # 2.7.15
    "featureFlags",  # added to chime
    # 2.8.14+
    "nvrMac",
    "useGlobal",
    "is2K",
    "is4K",
    "ulpVersion",
    "wanIp",
    "publicIp",
    "isVaultRegistered",
    "hasGateway",
    "corruptionState",
    "countryCode",
    # 2.8.22+
    "guid",
    "userConfiguredAp",
    # 2.9.20+
    "isRestoring",
    "hasRecordings",
    "hardDriveState",
    "isNetworkInstalled",
    "isProtectUpdatable",
    "isUcoreUpdatable",
    # 2.10.10+
    "isPtz",
    # 2.11.13+
    "lastDeviceFWUpdatesCheckedAt",
    "audioSettings",
    # 3.0.22+
    "smartDetection",
    "platform",
    "repeatTimes",
    "ringSettings",
    "speakerTrackList",
    "trackNo",
    "hasHttpsClientOTA",
    "isUCoreStacked",
}

NEW_CAMERA_FEATURE_FLAGS = {
    "audio",
    "audioCodecs",
    "hasInfrared",
    "hotplug",
    "smartDetectAudioTypes",
    "lensType",
    # 2.7.18+
    "isDoorbell",
    # 2.8.22+
    "lensModel",
    # 2.9.20+
    "hasColorLcdScreen",
    "hasLineCrossing",
    "hasLineCrossingCounting",
    "hasLiveviewTracking",
    # 2.10.10+
    "hasFlash",
    "isPtz",
    # 2.11.13+
    "audioStyle",
    "hasVerticalFlip",
    # 3.0.22+
    "flashRange",
}

NEW_ISP_SETTINGS = {
    # 3.0.22+
    "hdrMode",
    "icrCustomValue",
    "icrSwitchMode",
    "spotlightDuration",
}

NEW_NVR_FEATURE_FLAGS = {
    # 2.8.14+
    "ulpRoleManagement",
}

OLD_FIELDS = {
    # remove in 2.7.12
    "avgMotions",
    # removed in 2.10.11
    "eventStats",
    # removed in 3.0.22
    "pirSettings",
}


def compare_objs(obj_type, expected, actual):
    expected = deepcopy(expected)
    actual = deepcopy(actual)

    # TODO: fields not supported yet
    if obj_type == ModelType.CAMERA.value:
        # fields does not always exist (G4 Instant)
        expected.pop("apMac", None)
        # field no longer exists on newer cameras
        expected.pop("elementInfo", None)
        del expected["apRssi"]
        del expected["lastPrivacyZonePositionId"]
        expected.pop("recordingSchedules", None)
        del expected["smartDetectLines"]
        expected.pop("streamSharing", None)
        expected.pop("stopStreamLevel", None)
        expected.pop("uplinkDevice", None)
        expected.pop("recordingSchedulesV2", None)
        expected["stats"].pop("battery", None)
        expected["recordingSettings"].pop("enablePirTimelapse", None)
        expected["featureFlags"].pop("hasBattery", None)

        # do not compare detect zones because float math sucks
        assert len(expected["motionZones"]) == len(actual["motionZones"])
        assert len(expected["privacyZones"]) == len(actual["privacyZones"])
        assert len(expected["smartDetectZones"]) == len(actual["smartDetectZones"])

        expected["motionZones"] = actual["motionZones"] = []
        expected["privacyZones"] = actual["privacyZones"] = []
        expected["smartDetectZones"] = actual["smartDetectZones"] = []
        if "isColorNightVisionEnabled" not in expected["ispSettings"]:
            actual["ispSettings"].pop("isColorNightVisionEnabled", None)

        if (
            "audioTypes" in actual["smartDetectSettings"]
            and "audioTypes" not in expected["smartDetectSettings"]
        ):
            del actual["smartDetectSettings"]["audioTypes"]
        if (
            "autoTrackingObjectTypes" in actual["smartDetectSettings"]
            and "autoTrackingObjectTypes" not in expected["smartDetectSettings"]
        ):
            del actual["smartDetectSettings"]["autoTrackingObjectTypes"]

        exp_settings = expected["recordingSettings"]
        act_settings = actual["recordingSettings"]
        exp_settings["enableMotionDetection"] = exp_settings.get(
            "enableMotionDetection",
        )
        if act_settings and "inScheduleMode" not in exp_settings:
            del act_settings["inScheduleMode"]
        if "outScheduleMode" in act_settings and "outScheduleMode" not in exp_settings:
            del act_settings["outScheduleMode"]
        if "retentionDurationMs" not in exp_settings:
            act_settings.pop("retentionDurationMs", None)
        if "smartDetectPostPadding" not in exp_settings:
            act_settings.pop("smartDetectPostPadding", None)
        if "smartDetectPrePadding" not in exp_settings:
            act_settings.pop("smartDetectPrePadding", None)

        for flag in NEW_CAMERA_FEATURE_FLAGS:
            if flag not in expected["featureFlags"]:
                del actual["featureFlags"][flag]

        for setting in NEW_ISP_SETTINGS:
            if setting not in expected["ispSettings"]:
                del actual["ispSettings"][setting]

        # ignore changes to motion for live tests
        assert isinstance(actual["isMotionDetected"], bool)
        expected["isMotionDetected"] = actual["isMotionDetected"]

        for index, channel in enumerate(expected["channels"]):
            if "bitrate" not in channel:
                actual["channels"][index].pop("bitrate", None)
            if "autoBitrate" not in channel:
                actual["channels"][index].pop("autoBitrate", None)
            if "autoFps" not in channel:
                actual["channels"][index].pop("autoFps", None)

    elif obj_type == ModelType.USER.value:
        expected.pop("settings", None)
        expected.pop("cloudProviders", None)
        del expected["alertRules"]
        del expected["notificationsV2"]
        expected.pop("notifications", None)
        # lastLoginIp/lastLoginTime is not always present
        if "lastLoginIp" not in expected:
            actual.pop("lastLoginIp", None)
        if "lastLoginTime" not in expected:
            actual.pop("lastLoginTime", None)
        if "email" not in expected and "email" in actual and actual["email"] is None:
            actual.pop("email", None)
    elif obj_type == ModelType.EVENT.value:
        expected.pop("partition", None)
        expected.pop("deletionType", None)
        expected.pop("description", None)
        if "category" in expected and expected["category"] is None:
            expected.pop("category", None)

        exp_thumbnails = expected.get("metadata", {}).pop("detectedThumbnails", [])
        act_thumbnails = actual.get("metadata", {}).pop("detectedThumbnails", [])

        for index, exp_thumb in enumerate(exp_thumbnails):
            if "attributes" not in exp_thumb:
                del act_thumbnails[index]["attributes"]
            if "clockBestWall" not in exp_thumb:
                del act_thumbnails[index]["clockBestWall"]
        assert exp_thumbnails == act_thumbnails

        expected_keys = (expected.get("metadata") or {}).keys()
        actual_keys = (actual.get("metadata") or {}).keys()
        # delete all extra metadata keys, many of which are not modeled
        for key in set(expected_keys).difference(actual_keys):
            del expected["metadata"][key]
    elif obj_type in {ModelType.SENSOR.value, ModelType.DOORLOCK.value}:
        del expected["bridgeCandidates"]
        actual.pop("host", None)
        expected.pop("host", None)
    elif obj_type == ModelType.CHIME.value:
        del expected["apMac"]
        del expected["apRssi"]
        del expected["elementInfo"]
    elif obj_type == ModelType.NVR.value:
        # TODO: fields that still need implemented
        del expected["errorCode"]
        del expected["wifiSettings"]
        del expected["smartDetectAgreement"]
        expected.pop("dbRecoveryOptions", None)
        expected.pop("portStatus", None)
        expected.pop("cameraCapacity", None)
        expected.pop("deviceFirmwareSettings", None)
        # removed fields
        expected["ports"].pop("cameraTcp", None)

        expected["ports"]["piongw"] = expected["ports"].get("piongw")
        expected["ports"]["stacking"] = expected["ports"].get("stacking")
        expected["ports"]["emsJsonCLI"] = expected["ports"].get("emsJsonCLI")
        expected["ports"]["aiFeatureConsole"] = expected["ports"].get(
            "aiFeatureConsole",
        )
        expected["globalCameraSettings"] = expected.get("globalCameraSettings")
        if expected["globalCameraSettings"]:
            settings = expected["globalCameraSettings"]["recordingSettings"]
            settings["retentionDurationMs"] = settings.get(
                "retentionDurationMs",
            )

            # TODO:
            expected["globalCameraSettings"].pop("recordingSchedulesV2", None)

        if (
            "homekitPaired" in actual["featureFlags"]
            and "homekitPaired" not in expected["featureFlags"]
        ):
            del actual["featureFlags"]["homekitPaired"]
        if (
            "detectionLabels" in actual["featureFlags"]
            and "detectionLabels" not in expected["featureFlags"]
        ):
            del actual["featureFlags"]["detectionLabels"]
        if (
            "hasTwoWayAudioMediaStreams" in actual["featureFlags"]
            and "hasTwoWayAudioMediaStreams" not in expected["featureFlags"]
        ):
            del actual["featureFlags"]["hasTwoWayAudioMediaStreams"]

        if "capability" not in expected["systemInfo"]["storage"]:
            actual["systemInfo"]["storage"].pop("capability", None)

        # float math...
        cpu_fields = ["averageLoad", "temperature"]
        for key in cpu_fields:
            if math.isclose(
                expected["systemInfo"]["cpu"][key],
                actual["systemInfo"]["cpu"][key],
                rel_tol=0.01,
            ):
                expected["systemInfo"]["cpu"][key] = actual["systemInfo"]["cpu"][key]

        if expected["systemInfo"].get("ustorage") is not None:
            actual_ustor = actual["systemInfo"]["ustorage"]
            expected_ustor = expected["systemInfo"]["ustorage"]

            expected_ustor.pop("sdcards", None)

            for index, disk in enumerate(expected_ustor["disks"]):
                actual_disk = actual_ustor["disks"][index]
                estimate = disk.get("estimate")
                actual_estimate = actual_disk.get("estimate")
                if estimate is not None and actual_estimate is not None:
                    if math.isclose(estimate, actual_estimate, rel_tol=0.01):
                        actual_ustor["disks"][index]["estimate"] = estimate

            for index, device in enumerate(expected_ustor["space"]):
                actual_device = actual_ustor["space"][index]
                estimate = device.get("estimate")
                actual_estimate = actual_device.get("estimate")
                if estimate is not None and actual_estimate is not None:
                    if math.isclose(estimate, actual_estimate, rel_tol=0.01):
                        actual_ustor["space"][index]["estimate"] = estimate
                if "space_type" not in device:
                    del actual_device["space_type"]
                if "size" in device:
                    actual_device["size"] = actual_device.pop("size", None)
                # TODO field
                if "reasons" in device:
                    del device["reasons"]

        for flag in NEW_NVR_FEATURE_FLAGS:
            if flag not in expected["featureFlags"]:
                del actual["featureFlags"][flag]

    if "bridge" not in expected and "bridge" in actual and actual["bridge"] is None:
        actual.pop("bridge", None)

    if "bluetoothConnectionState" in expected:
        expected["bluetoothConnectionState"]["experienceScore"] = expected[
            "bluetoothConnectionState"
        ].get(
            "experienceScore",
        )

    if "wifiConnectionState" in expected:
        expected["wifiConnectionState"]["bssid"] = expected["wifiConnectionState"].get(
            "bssid",
        )
        expected["wifiConnectionState"]["txRate"] = expected["wifiConnectionState"].get(
            "txRate",
        )
        expected["wifiConnectionState"]["experience"] = expected[
            "wifiConnectionState"
        ].get("experience")
        expected["wifiConnectionState"]["apName"] = expected["wifiConnectionState"].get(
            "apName",
        )
        expected["wifiConnectionState"]["connectivity"] = expected[
            "wifiConnectionState"
        ].get("connectivity")

    # sometimes uptime comes back as a str...
    if "uptime" in expected and expected["uptime"] is not None:
        expected["uptime"] = int(expected["uptime"])

    # force hardware revision to str to make sure types line up
    if "hardwareRevision" in expected and expected["hardwareRevision"] is not None:
        expected["hardwareRevision"] = str(expected["hardwareRevision"])
        actual["hardwareRevision"] = str(actual["hardwareRevision"])

    # edge case with broken UUID from Protect
    if (
        "guid" in expected
        and expected["guid"] == _BAD_UUID
        and actual["guid"] == "00000000-0000-0000-0000-000000000000"
    ):
        actual["guid"] = expected["guid"]

    for key in NEW_FIELDS.intersection(actual.keys()):
        if key not in expected:
            del actual[key]

    for key in OLD_FIELDS.intersection(expected.keys()):
        del expected[key]

    assert expected == actual


@pytest.fixture()
def _disable_camera_validation():
    Camera.__config__.validate_assignment = False

    yield

    Camera.__config__.validate_assignment = True


class MockTalkback:
    is_error: bool = False
    stdout: list[str] = []
    stderr: list[str] = []

    def __init__(self) -> None:
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.run_until_complete = AsyncMock()
