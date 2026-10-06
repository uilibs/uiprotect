from __future__ import annotations

import asyncio
import base64
import json
import math
import os
from copy import deepcopy
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import aiofiles
import aiohttp
import av
import pytest
import pytest_asyncio

from tests.sample_data.constants import CONSTANTS
from uiprotect import ProtectApiClient
from uiprotect.data import NVR, Camera, ModelType
from uiprotect.data.nvr import Event
from uiprotect.data.types import EventType
from uiprotect.utils import DEBUG_ENV, is_debug, set_debug

if TYPE_CHECKING:
    from collections.abc import Iterator

# ``scripts/`` is not an importable package; expose it so tests can import the
# spec-validation helpers (``scripts/validate_spec.py``).
import sys

_SCRIPTS_DIR = str(Path(__file__).resolve().parents[1] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from blockbuster import BlockBuster, blockbuster_ctx
except ImportError:
    BlockBuster = None  # type: ignore[assignment,misc]
    blockbuster_ctx = None  # type: ignore[assignment]

_BENCHMARKS_DIR = "tests/benchmarks"

# Tests that perform sync IO inside the asyncio event loop and trip
# blockbuster. Marked xfail so CI is green; pop entries as they get
# fixed so the underlying blocking call is gone for good.
_KNOWN_BLOCKING: frozenset[str] = frozenset()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Mark known-blocking tests xfail so CI is green while we work through them."""
    if blockbuster_ctx is None:
        return
    marker = pytest.mark.xfail(
        reason="blockbuster: blocking call in asyncio path, to be fixed",
        strict=False,
    )
    for item in items:
        if item.nodeid in _KNOWN_BLOCKING:
            item.add_marker(marker)


@pytest.fixture(autouse=True)
def blockbuster(
    request: pytest.FixtureRequest,
) -> Iterator[BlockBuster | None]:
    """Fail any test that performs a blocking call inside the asyncio loop."""
    if blockbuster_ctx is None or _BENCHMARKS_DIR in str(request.node.fspath):
        yield None
        return
    with blockbuster_ctx() as bb:
        yield bb


UFP_SAMPLE_DIR = os.environ.get("UFP_SAMPLE_DIR")
if UFP_SAMPLE_DIR:
    SAMPLE_DATA_DIRECTORY = Path(UFP_SAMPLE_DIR)
else:
    SAMPLE_DATA_DIRECTORY = Path(__file__).parent / "sample_data"

TEST_CAMERA_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists()
TEST_SNAPSHOT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_snapshot.png").exists()
TEST_PUBLIC_API_SNAPSHOT_EXISTS = (
    SAMPLE_DATA_DIRECTORY / "sample_public_api_camera_snapshot.png"
).exists()
TEST_VIDEO_EXISTS = (
    SAMPLE_DATA_DIRECTORY / "sample_camera_video.mp4"
).exists() or "camera_video_length" not in CONSTANTS
TEST_THUMBNAIL_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_thumbnail.png").exists()
TEST_SMART_TRACK_EXISTS = (
    SAMPLE_DATA_DIRECTORY / "sample_event_smart_track.json"
).exists()
TEST_LIGHT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_light.json").exists()
TEST_SENSOR_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_sensor.json").exists()
TEST_VIEWPORT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_viewport.json").exists()
TEST_BRIDGE_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_bridge.json").exists()
TEST_LIVEVIEW_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_liveview.json").exists()
TEST_CHIME_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_chime.json").exists()


def set_no_debug() -> None:
    """Turn the UFP_DEBUG flag off."""
    os.environ[DEBUG_ENV] = str(False)
    is_debug.cache_clear()


ANY_NONE = [[None], None, []]


@cache
def _read_binary_file_cached(name: str, ext: str) -> bytes:
    with (SAMPLE_DATA_DIRECTORY / f"{name}.{ext}").open("rb") as f:
        return f.read()


def read_binary_file(name: str, ext: str = "png") -> bytes:
    return _read_binary_file_cached(name, ext)


@cache
def _read_json_file_cached(name: str) -> Any:
    with (SAMPLE_DATA_DIRECTORY / f"{name}.json").open(encoding="utf8") as f:
        return json.load(f)


def read_json_file(name: str) -> Any:
    return deepcopy(_read_json_file_cached(name))


# Preload sample data at module import (outside the asyncio loop) so the
# read_*_file helpers never touch the disk from inside a test or fixture
# and trip blockbuster.
for _path in SAMPLE_DATA_DIRECTORY.glob("*.json"):
    _read_json_file_cached(_path.stem)
for _ext in ("png", "mp4"):
    for _path in SAMPLE_DATA_DIRECTORY.glob(f"*.{_ext}"):
        _read_binary_file_cached(_path.stem, _ext)
CONSTANTS.data()  # force the sample_constants.json read out of any loop


async def async_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` without blocking the event loop."""
    async with aiofiles.open(path, "wb") as f:
        await f.write(data)


async def async_read_bytes(path: Path) -> bytes:
    """Read ``path`` as bytes without blocking the event loop."""
    async with aiofiles.open(path, "rb") as f:
        return await f.read()


async def async_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` without blocking the event loop."""
    async with aiofiles.open(path, "w") as f:
        await f.write(text)


async def async_read_text(path: Path) -> str:
    """Read ``path`` as text without blocking the event loop."""
    async with aiofiles.open(path) as f:
        return await f.read()


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
    """Validate video file using PyAV."""
    with av.open(str(filepath)) as container:
        # Check that video stream exists
        assert len(container.streams.video) > 0, "No video stream found"

        # Check duration (in seconds)
        # container.duration is in av.time_base units (microseconds, 1000000/sec)
        # so we divide by av.time_base to convert to seconds
        duration = float(container.duration) / av.time_base if container.duration else 0
        # it looks like UFP does not always generate a video of exact length
        assert length - 10 < duration < length + 10


async def mock_api_request_raw(url: str, *args, **kwargs):
    if url.startswith("thumbnails/") or url.endswith("thumbnail"):
        return read_binary_file("sample_camera_thumbnail")
    if url.startswith("cameras/"):
        return read_binary_file("sample_camera_snapshot")
    if url.startswith("/v1/cameras/"):
        return read_binary_file("sample_public_api_camera_snapshot")
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
    await client.close_public_api_session()


@pytest_asyncio.fixture
async def simple_api_client():
    """Create a simple ProtectApiClient for unit testing without mocked bootstrap."""
    client = ProtectApiClient("test.com", 443, "username", "password")
    yield client
    await cleanup_client(client)


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
        ws_receive_timeout=0.1,
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
    return get_now().replace(tzinfo=UTC)


@pytest.fixture()
def tmp_binary_file():
    with NamedTemporaryFile(mode="wb", delete=False) as tmp_file:
        yield tmp_file

    Path(tmp_file.name).unlink()


# new values added for newer versions of UFP (for backwards compat tests)
NEW_FIELDS = {
    # 1.20.1
    "voltage",
    # 1.21.0-beta1
    "timestamp",
    "marketName",
    # 2.2.1-beta2
    "isInsightsEnabled",
    # 2.7.15
    "featureFlags",  # added to chime
    # 2.8.14+
    "useGlobal",
    # 2.10.10+
    "isPtz",
    # 3.0.22+
    "smartDetection",
    "platform",
    "repeatTimes",
    "ringSettings",
    # 5.0.33+
    "isThirdPartyCamera",
}

NEW_CAMERA_FEATURE_FLAGS = {
    "audio",
    "hotplug",
    "smartDetectAudioTypes",
    "lensType",
    # 2.7.18+
    "isDoorbell",
    # 2.10.10+
    "isPtz",
    # 4.73.71+
    "supportNfc",
    "hasFingerprintSensor",
}

NEW_ISP_SETTINGS = {
    # 3.0.22+
    "hdrMode",
    "icrCustomValue",
}

OLD_FIELDS = {
    # remove in 2.7.12
    "avgMotions",
    # removed in 2.10.11
    "eventStats",
    # removed in 3.0.22
    "pirSettings",
}

# wire keys the private models no longer parse, by nested path
_DROPPED_RECORDING_SETTINGS_KEYS = {
    "prePaddingSecs",
    "postPaddingSecs",
    "minMotionEventTrigger",
    "endMotionEventDelay",
    "suppressIlluminationSurge",
    "geofencing",
    "motionAlgorithm",
    "useNewMotionAlgorithm",
    "inScheduleMode",
    "outScheduleMode",
    "retentionDurationMs",
    "smartDetectPostPaddingSecs",
    "smartDetectPrePaddingSecs",
    "createAccessEvent",
}
_DROPPED_DEVICE_KEYS: dict[tuple[str, ...], set[str]] = {
    (): {
        "lastSeen",
        "hardwareRevision",
        "connectedSince",
        "latestFirmwareVersion",
        "firmwareBuild",
        "isProvisioned",
        "isAttemptingToConnect",
        "fwUpdateState",
        "isRestoring",
        "lastDisconnect",
        "anonymousDeviceId",
        "isDownloadingFW",
        "nvrMac",
        "guid",
    },
    ("bluetoothConnectionState",): {"experienceScore"},
    ("wifiConnectionState",): {
        "frequency",
        "ssid",
        "bssid",
        "txRate",
        "apName",
        "experience",
        "connectivity",
    },
}
DROPPED_KEYS: dict[str, dict[tuple[str, ...], set[str]]] = {
    ModelType.CAMERA.value: {
        (): {
            "isDeleting",
            "isProbingForWifi",
            "isLiveHeatmapEnabled",
            "videoReconfigurationInProgress",
            "hasWifi",
            "audioBitrate",
            "canManage",
            "isManaged",
            "isPoorNetwork",
            "isWirelessUplinkEnabled",
            "homekitSettings",
            "apMgmtIp",
            "isWaterproofCaseAttached",
            "is2K",
            "is4K",
            "userConfiguredAp",
            "hasRecordings",
            "audioSettings",
            "isPairedWithAiPort",
            "isAdoptedByAccessApp",
            "isMicEnabled",
            "lenses",
            "motionZones",
            "smartDetectZones",
        },
        ("ispSettings",): {
            "aeMode",
            "irLedLevel",
            "icrSensitivity",
            "contrast",
            "hue",
            "saturation",
            "sharpness",
            "denoise",
            "isFlippedVertical",
            "isFlippedHorizontal",
            "isAutoRotateEnabled",
            "isLdcEnabled",
            "is3dnrEnabled",
            "isExternalIrEnabled",
            "isAggressiveAntiFlickerEnabled",
            "isPauseMotionEnabled",
            "dZoomCenterX",
            "dZoomCenterY",
            "dZoomScale",
            "dZoomStreamId",
            "focusMode",
            "focusPosition",
            "touchFocusX",
            "touchFocusY",
            "mountPosition",
            "icrSwitchMode",
            "spotlightDuration",
            "brightness",
        },
        ("osdSettings",): {"overlayLocation"},
        ("ledSettings",): {"blinkRate", "welcomeLed", "floodLed"},
        ("recordingSettings",): _DROPPED_RECORDING_SETTINGS_KEYS,
        ("talkbackSettings",): {
            "typeIn",
            "bindAddr",
            "filterAddr",
            "filterPort",
            "quality",
        },
        ("stats",): {"wifi", "wifiQuality", "wifiStrength"},
        ("stats", "video"): {
            "recordingEnd",
            "recordingEndLQ",
            "timelapseStart",
            "timelapseEnd",
            "timelapseStartLQ",
            "timelapseEndLQ",
        },
        ("featureFlags",): {
            "canAdjustIrLedLevel",
            "canMagicZoom",
            "canTouchFocus",
            "hasAccelerometer",
            "hasAec",
            "hasBluetooth",
            "hasExternalIr",
            "hasIcrSensitivity",
            "hasLdc",
            "hasLineIn",
            "hasRtc",
            "hasSdCard",
            "hasWifi",
            "hasAutoICROnly",
            "videoModeMaxFps",
            "hasMotionZones",
            "motionAlgorithms",
            "hasSquareEventThumbnail",
            "privacyMaskCapability",
            "audioCodecs",
            "mountPositions",
            "hasInfrared",
            "lensModel",
            "hasColorLcdScreen",
            "hasLineCrossing",
            "hasLineCrossingCounting",
            "hasLiveviewTracking",
            "hasFlash",
            "audioStyle",
            "hasVerticalFlip",
            "flashRange",
            "focus",
            "supportFullHdSnapshot",
            "pan",
            "tilt",
            "zoom",
        },
        ("featureFlags", "hotplug"): {"standaloneAdoption"},
        ("featureFlags", "hotplug", "extender"): {
            "hasFlash",
            "hasIR",
            "hasRadar",
            "flashRange",
        },
    },
    ModelType.LIGHT.value: {
        (): {"isLocating", "lightOnSettings", "isCameraPaired"},
        ("lightDeviceSettings",): {"luxSensitivity", "ledLevel", "pirDuration"},
        ("lightModeSettings",): {"enableAt"},
    },
    ModelType.SENSOR.value: {
        (): {"motionDetectedAt", "openStatusChangedAt"},
        ("motionSettings",): {"sensitivityWhenArmed"},
        ("humiditySettings",): {"margin", "lowThreshold", "highThreshold"},
        ("lightSettings",): {"margin", "lowThreshold", "highThreshold"},
        ("temperatureSettings",): {"margin", "lowThreshold", "highThreshold"},
    },
    ModelType.VIEWPORT.value: {(): {"streamLimit", "softwareVersion"}},
    ModelType.CHIME.value: {
        (): {
            "isProbingForWifi",
            "isWirelessUplinkEnabled",
            "apMgmtIp",
            "userConfiguredAp",
            "hasHttpsClientOTA",
            "speakerTrackList",
        },
        ("featureFlags",): {"hasWifi", "hasHttpsClientOTA"},
    },
    ModelType.EVENT.value: {
        (): {
            "heatmap",
            "deletedAt",
            "deletionType",
            "subCategory",
            "isFavorite",
            "favoriteObjectIds",
        },
        ("metadata",): {"clientPlatform", "appUpdate", "sensorName", "sensorType"},
    },
    ModelType.NVR.value: {
        (): {
            "canAutoUpdate",
            "isStatsGatheringEnabled",
            "ucoreVersion",
            "hardwarePlatform",
            "lastUpdateAt",
            "isStation",
            "enableAutomaticBackups",
            "enableStatsReporting",
            "releaseChannel",
            "enableBridgeAutoAdoption",
            "hardwareId",
            "hostType",
            "hostShortname",
            "isHardware",
            "isWirelessUplinkEnabled",
            "timeFormat",
            "temperatureUnit",
            "recordingRetentionDurationMs",
            "enableCrashReporting",
            "disableAudio",
            "cameraUtilization",
            "isRecycling",
            "disableAutoLink",
            "skipFirmwareUpdate",
            "locationSettings",
            "isAway",
            "isSetup",
            "maxCameraCapacity",
            "streamSharingAvailable",
            "isDbAvailable",
            "isRecordingDisabled",
            "isRecordingMotionOnly",
            "uiVersion",
            "ssoChannel",
            "isStacked",
            "isPrimary",
            "lastDriveSlowEvent",
            "isUCoreSetup",
            "vaultCameras",
            "corruptionState",
            "countryCode",
            "hasGateway",
            "isVaultRegistered",
            "publicIp",
            "ulpVersion",
            "wanIp",
            "hardDriveState",
            "isNetworkInstalled",
            "isProtectUpdatable",
            "isUcoreUpdatable",
            "lastDeviceFWUpdatesCheckedAt",
            "isUCoreStacked",
            "network",
        },
        ("ports",): {
            "http",
            "https",
            "playback",
            "ump",
            "rtsp",
            "rtmp",
            "devicesWss",
            "cameraHttps",
            "liveWs",
            "liveWss",
            "tcpStreams",
            "emsCLI",
            "emsLiveFLV",
            "cameraEvents",
            "tcpBridge",
            "ucore",
            "discoveryClient",
            "piongw",
            "emsJsonCLI",
            "stacking",
            "aiFeatureConsole",
        },
        ("systemInfo",): {"tmpfs"},
        ("systemInfo", "storage"): {
            "isRecycling",
            "available",
            "size",
            "devices",
            "capability",
        },
        ("systemInfo", "ustorage"): {"space"},
        ("doorbellSettings",): {"defaultMessageResetTimeoutMs"},
        ("storageStats",): {"remainingCapacity", "recordingSpace"},
        ("featureFlags",): {
            "notificationsV2",
            "homekitPaired",
            "ulpRoleManagement",
            "detectionLabels",
            "hasTwoWayAudioMediaStreams",
            "beta",
            "dev",
        },
        ("smartDetection",): {"faceRecognition", "licensePlateRecognition"},
        ("globalCameraSettings", "recordingSettings"): (
            _DROPPED_RECORDING_SETTINGS_KEYS
        ),
    },
    ModelType.USER.value: {
        (): {
            "lastLoginIp",
            "lastLoginTime",
            "isOwner",
            "enableNotifications",
            "hasAcceptedInvite",
            "scopes",
            "localUsername",
            "location",
        },
        ("cloudAccount",): {"location", "profileImg"},
        ("featureFlags",): {"notificationsV2"},
    },
    ModelType.KEYRING.value: {(): {"lastActivity", "deviceType", "deviceId"}},
    ModelType.ULP_USER.value: {(): {"avatar"}},
}
_DEVICE_MODEL_TYPES = {
    ModelType.CAMERA.value,
    ModelType.LIGHT.value,
    ModelType.VIEWPORT.value,
    ModelType.SENSOR.value,
    ModelType.BRIDGE.value,
    ModelType.CHIME.value,
}


def strip_dropped_keys(obj_type: str, data: dict[str, Any]) -> None:
    """Remove wire keys the private model for obj_type no longer parses."""
    paths = dict(DROPPED_KEYS.get(obj_type, {}))
    if obj_type in _DEVICE_MODEL_TYPES:
        for path, keys in _DROPPED_DEVICE_KEYS.items():
            paths[path] = paths.get(path, set()) | keys
    elif obj_type == ModelType.NVR.value:
        paths[()] = paths[()] | {"lastSeen", "hardwareRevision", "anonymousDeviceId"}
    for path, keys in paths.items():
        node: Any = data
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict):
            for key in keys:
                node.pop(key, None)


pytest.register_assert_rewrite("tests.common")


def compare_objs(obj_type, expected, actual):
    expected = deepcopy(expected)
    actual = deepcopy(actual)
    strip_dropped_keys(obj_type, expected)

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
        assert len(expected["privacyZones"]) == len(actual["privacyZones"])

        expected["privacyZones"] = actual["privacyZones"] = []
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
        exp_settings["enableMotionDetection"] = exp_settings.get(
            "enableMotionDetection",
        )
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
            if "minBitrate" not in channel:
                actual["channels"][index].pop("minBitrate", None)
            if "maxBitrate" not in channel:
                actual["channels"][index].pop("maxBitrate", None)
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
        if "email" not in expected and "email" in actual and actual["email"] is None:
            actual.pop("email", None)
    elif obj_type == ModelType.EVENT.value:
        expected.pop("partition", None)
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
    elif obj_type == ModelType.SENSOR.value:
        del expected["bridgeCandidates"]
        actual.pop("host", None)
        expected.pop("host", None)
    elif obj_type == ModelType.CHIME.value:
        del expected["apMac"]
        del expected["apRssi"]
        del expected["elementInfo"]
    elif obj_type == ModelType.NVR.value:
        del expected["errorCode"]
        del expected["wifiSettings"]
        del expected["smartDetectAgreement"]
        expected.pop("dbRecoveryOptions", None)
        expected.pop("portStatus", None)
        expected.pop("cameraCapacity", None)
        expected.pop("deviceFirmwareSettings", None)
        # removed fields
        expected["ports"].pop("cameraTcp", None)

        expected["globalCameraSettings"] = expected.get("globalCameraSettings")
        if expected["globalCameraSettings"]:
            expected["globalCameraSettings"].pop("recordingSchedulesV2", None)

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
                if (
                    estimate is not None
                    and actual_estimate is not None
                    and math.isclose(estimate, actual_estimate, rel_tol=0.01)
                ):
                    actual_ustor["disks"][index]["estimate"] = estimate

    if "bridge" not in expected and "bridge" in actual and actual["bridge"] is None:
        actual.pop("bridge", None)

    # sometimes uptime comes back as a str...
    if "uptime" in expected and expected["uptime"] is not None:
        expected["uptime"] = int(expected["uptime"])

    for key in NEW_FIELDS.intersection(actual.keys()):
        if key not in expected:
            del actual[key]

    for key in OLD_FIELDS.intersection(expected.keys()):
        del expected[key]

    assert expected == actual


@pytest.fixture()
def _disable_camera_validation():
    Camera.model_config["validate_assignment"] = False

    yield

    Camera.model_config["validate_assignment"] = True


@pytest.fixture()
def _disable_nvr_validation():
    original_validate_assignment = NVR.model_config.get("validate_assignment", True)
    NVR.model_config["validate_assignment"] = False

    yield

    NVR.model_config["validate_assignment"] = original_validate_assignment


class MockTalkback:
    def __init__(self) -> None:
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.run_until_complete = AsyncMock()
