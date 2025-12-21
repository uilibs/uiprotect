from __future__ import annotations

import time as time_module
import zoneinfo
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from http.cookies import Morsel
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import jwt
import pytest
from pydantic.fields import FieldInfo

import uiprotect.utils as utils_module
from uiprotect.data import EventType
from uiprotect.data.bootstrap import WSStat
from uiprotect.data.types import (
    Color,
    ModelType,
    SmartDetectAudioType,
    SmartDetectObjectType,
    Version,
    VideoMode,
)
from uiprotect.utils import (
    _cached_ip_address,
    clamp_value,
    convert_smart_audio_types,
    convert_smart_types,
    convert_to_datetime,
    convert_unifi_data,
    convert_video_modes,
    decode_token_cookie,
    dict_diff,
    format_datetime,
    format_duration,
    format_host_for_url,
    from_js_time,
    get_local_timezone,
    get_nested_attr,
    get_nested_attr_as_bool,
    get_response_reason,
    get_top_level_attr_as_bool,
    ip_from_host,
    is_debug,
    is_doorbell,
    is_online,
    local_datetime,
    log_event,
    make_enabled_getter,
    make_required_getter,
    make_value_getter,
    normalize_mac,
    print_ws_stat_summary,
    pybool_to_json_bool,
    run_async,
    serialize_coord,
    serialize_dict,
    serialize_list,
    serialize_point,
    serialize_unifi_obj,
    set_debug,
    set_no_debug,
    timedelta_total_seconds,
    to_camel_case,
    to_js_time,
    to_ms,
    to_snake_case,
    utc_now,
    write_json,
    ws_stat_summmary,
)


class _MockEnum(Enum):
    A = 1
    B = 2
    C = 3


# --- dict_diff tests ---


def test_dict_diff():
    """Test dict_diff with equal, new keys, and changed values."""
    obj = {"a": 1, "b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}
    nested = {
        "a": 1,
        "b": {"b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]},
    }

    # Equal
    assert dict_diff({}, {}) == {}
    assert dict_diff(obj, obj) == {}
    assert dict_diff(nested, nested) == {}
    assert dict_diff(None, {"a": 1}) == {"a": 1}

    # New keys
    assert dict_diff({}, obj) == obj
    assert dict_diff({"a": 1, "b": {}}, {"a": 1, "b": obj}) == {"b": obj}

    # Changed values
    assert dict_diff(
        {"a": 1, "b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]},
        {
            "a": 3,
            "b": 2,
            "c": "test",
            "d": "test",
            "e": "test6",
            "f": [1],
            "g": [1, 2, 3],
        },
    ) == {"a": 3, "c": "test", "d": "test", "e": "test6", "f": [1]}


# --- String conversion tests ---


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("CamelCase", "camel_case"),
        ("CamelCamelCase", "camel_camel_case"),
        ("getHTTPResponseCode", "get_http_response_code"),
        ("HTTPResponseCode", "http_response_code"),
    ],
)
def test_to_snake_case(input_val, expected):
    assert to_snake_case(input_val) == expected


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        ("snake_case", "snakeCase"),
        ("another_test_case", "anotherTestCase"),
        ("already", "already"),
    ],
)
def test_to_camel_case(input_val, expected):
    assert to_camel_case(input_val) == expected


# --- convert_unifi_data tests ---


@pytest.mark.parametrize(
    ("value", "annotation", "expected"),
    [
        (
            "00000000-0000-00 0- 000-000000000000",
            UUID,
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
        ("", UUID, None),
        (
            UUID("00000000-0000-0000-0000-000000000000"),
            UUID,
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
        ("192.168.1.1", IPv4Address | str, IPv4Address("192.168.1.1")),
        ("invalid-ip", IPv4Address | str, "invalid-ip"),
        ("", IPv4Address | None, None),
        ("::1", IPv6Address | str, IPv6Address("::1")),
        # IPv6 support tests - ensure IPv6 addresses work in IPv4-typed fields
        ("fd00:1:1:1::64", IPv4Address | None, IPv6Address("fd00:1:1:1::64")),
        (
            "fd00:1:1:1::64",
            IPv4Address | IPv6Address | None,
            IPv6Address("fd00:1:1:1::64"),
        ),
        ("192.168.1.1", IPv4Address | IPv6Address | None, IPv4Address("192.168.1.1")),
        ("", IPv6Address | None, None),
        (
            "",
            IPv4Address | IPv6Address | None,
            None,
        ),  # empty string becomes None when str is not in union
        (
            "",
            IPv4Address | IPv6Address | str | None,
            "",
        ),  # empty string kept when str is in union,
        (
            "2001:db8::1",
            IPv4Address | IPv6Address | str | None,
            IPv6Address("2001:db8::1"),
        ),
        ("10.0.0.1", IPv4Address | IPv6Address | str | None, IPv4Address("10.0.0.1")),
        ("hostname.local", IPv4Address | IPv6Address | str | None, "hostname.local"),
        (1705320000000, datetime, datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)),
        (["a", "b"], list[str], ["a", "b"]),
        (["a", "b"], set[str], {"a", "b"}),
        ({"k": "v"}, dict[str, str], {"k": "v"}),
        ({"test": 123}, Any, {"test": 123}),
        ("123.45", Decimal, Decimal("123.45")),
        ("/test", Path, Path("/test")),
        (None, str | None, None),
        (True, bool, True),
        ("camera", ModelType, ModelType.CAMERA),
    ],
)
def test_convert_unifi_data(value, annotation, expected):
    result = convert_unifi_data(value, FieldInfo(annotation=annotation))
    assert result == expected


# --- convert_to_datetime tests ---


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        (1715563200000.0, datetime(2024, 5, 13, 1, 20, tzinfo=timezone.utc)),
        ("1715563200000", datetime(2024, 5, 13, 1, 20, tzinfo=timezone.utc)),
        (
            datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc),
            datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc),
        ),
        (None, None),
    ],
)
def test_convert_to_datetime(input_val, expected):
    assert convert_to_datetime(input_val) == expected


def test_convert_to_datetime_invalid():
    with pytest.raises(ValueError):
        convert_to_datetime("invalid-date")


def test_convert_to_datetime_caching():
    result1 = convert_to_datetime(1715563200.0)
    result2 = convert_to_datetime(1715563200.0)
    assert result1 is result2


# --- Attribute getter tests ---


def test_get_nested_attr():
    data = Mock(a=Mock(b=Mock(c=1)), d=3, f=_MockEnum.C)
    assert get_nested_attr(("a", "b", "c"), data) == 1
    assert get_nested_attr(("d",), data) == 3
    assert get_nested_attr(("f",), data) == _MockEnum.C


def test_get_nested_attr_as_bool():
    data = Mock(a=Mock(b=Mock(c=True)), d=False, f=_MockEnum.C)
    assert get_nested_attr_as_bool(("a", "b", "c"), data) is True
    assert get_nested_attr_as_bool(("d",), data) is False
    assert get_nested_attr_as_bool(("f",), data) is True
    assert get_nested_attr_as_bool(("missing",), Mock(spec=[])) is False


def test_get_top_level_attr_as_bool():
    data = Mock(a=True, b=False, c=None)
    assert get_top_level_attr_as_bool("a", data) is True
    assert get_top_level_attr_as_bool("b", data) is False
    assert get_top_level_attr_as_bool("c", data) is False


def test_make_getters():
    data = Mock(a=1, b=True, c=Mock(q="x"), d=None)
    assert make_value_getter("a")(data) == 1
    assert make_value_getter("c.q")(data) == "x"
    assert make_value_getter("a.x")(data) is None
    assert make_enabled_getter("b")(data) is True
    assert make_required_getter("a")(data) is True
    assert make_required_getter("d")(data) is False


# --- Host/IP tests ---


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (IPv4Address("192.168.1.1"), "192.168.1.1"),
        ("192.168.1.1", "192.168.1.1"),
        (IPv6Address("fe80::1"), "[fe80::1]"),
        ("::1", "[::1]"),
        ("example.com", "example.com"),
    ],
)
def test_format_host_for_url(host, expected):
    assert format_host_for_url(host) == expected


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("host", "expected_type"),
    [
        ("192.168.1.1", IPv4Address),
        ("::1", IPv6Address),
    ],
)
async def test_ip_from_host(host, expected_type):
    result = await ip_from_host(host)
    assert isinstance(result, expected_type)


@pytest.mark.asyncio()
async def test_ip_from_host_invalid():
    with pytest.raises(ValueError, match="Cannot resolve hostname"):
        await ip_from_host("this-does-not-exist-12345.invalid")


@pytest.mark.parametrize(
    ("ip", "expected_type"),
    [
        ("192.168.1.1", IPv4Address),
        ("::1", IPv6Address),
        ("not-an-ip", str),
    ],
)
def test_cached_ip_address(ip, expected_type):
    assert isinstance(_cached_ip_address(ip), expected_type)


# --- Time conversion tests ---


@pytest.mark.parametrize(
    ("dt", "expected"),
    [
        (None, None),
        (1234567890000, 1234567890000),
        (datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc), 1705320000000),
    ],
)
def test_to_js_time(dt, expected):
    assert to_js_time(dt) == expected


def test_to_js_time_naive():
    assert isinstance(to_js_time(datetime(2024, 1, 15, 12, 0, 0)), int)


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (None, None),
        (timedelta(seconds=1), 1000),
        (timedelta(minutes=1), 60000),
        (timedelta(hours=1), 3600000),
    ],
)
def test_to_ms(duration, expected):
    assert to_ms(duration) == expected


def test_from_js_time():
    assert from_js_time(1705320000000) == datetime(
        2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc
    )
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert from_js_time(dt) == dt


def test_utc_now():
    result = utc_now()
    assert result.tzinfo == timezone.utc
    assert (datetime.now(tz=timezone.utc) - result).total_seconds() < 1


def test_timedelta_total_seconds():
    assert timedelta_total_seconds(timedelta(hours=1, minutes=30)) == 5400.0


# --- Format tests ---


@pytest.mark.parametrize(
    ("dt", "default", "expected"),
    [
        (None, None, None),
        (None, "N/A", "N/A"),
        (datetime(2024, 1, 15, 12, 30, 45), None, "2024-01-15 12:30:45"),
    ],
)
def test_format_datetime(dt, default, expected):
    assert format_datetime(dt, default) == expected


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (timedelta(seconds=30), "30s"),
        (timedelta(minutes=5), "5m0s"),
        (timedelta(hours=2), "2h0s"),
        (timedelta(hours=1, minutes=30, seconds=45), "1h30m45s"),
        (timedelta(days=1, hours=2), "26h0s"),
    ],
)
def test_format_duration(duration, expected):
    assert format_duration(duration) == expected


# --- Data check tests ---


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"state": "CONNECTED"}, True),
        ({"state": "DISCONNECTED"}, False),
    ],
)
def test_is_online(data, expected):
    assert is_online(data) == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"type": "doorbell"}, True),
        ({"type": "UVC G4 Doorbell"}, True),
        ({"type": "camera"}, False),
    ],
)
def test_is_doorbell(data, expected):
    assert is_doorbell(data) == expected


# --- Serialization tests ---


@pytest.mark.parametrize(
    ("coord", "expected"),
    [
        (0.0, 0),
        (1.0, 1),
        (0.5, 0.5),
    ],
)
def test_serialize_coord(coord, expected):
    assert serialize_coord(coord) == expected


def test_serialize_point():
    assert serialize_point((0.0, 1.0)) == [0, 1]


def test_serialize_list():
    assert serialize_list([1, 2, 3]) == [1, 2, 3]
    assert (
        serialize_list([1, "s", UUID("12345678-1234-5678-1234-567812345678")])[2]
        == "12345678-1234-5678-1234-567812345678"
    )


def test_serialize_dict():
    assert serialize_dict({"test_key": "v"})["testKey"] == "v"
    assert "life_span" in serialize_dict({"life_span": 100})


@pytest.mark.parametrize(
    ("obj", "expected"),
    [
        (_MockEnum.A, 1),
        (IPv4Address("192.168.1.1"), "192.168.1.1"),
        (
            UUID("12345678-1234-5678-1234-567812345678"),
            "12345678-1234-5678-1234-567812345678",
        ),
        (Path("/test"), "/test"),
        (datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc), 1705320000000),
        (timedelta(seconds=1), 1000),
        (Version("1.2.3"), "1.2.3"),
        (zoneinfo.ZoneInfo("UTC"), "UTC"),
        (ModelType.CAMERA, "camera"),
    ],
)
def test_serialize_unifi_obj(obj, expected):
    assert serialize_unifi_obj(obj) == expected


def test_serialize_unifi_obj_color():
    assert serialize_unifi_obj(Color("#FF0000")) in ("#FF0000", "#F00")


def test_serialize_unifi_obj_with_unifi_dict():
    obj = Mock()
    obj.unifi_dict = Mock(return_value={"key": "value"})
    assert serialize_unifi_obj(obj) == {"key": "value"}


# --- Utility function tests ---


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [
        (0.5, 0.1, 0.5),
        (0.55, 0.1, 0.5),
        (1.3, 0.25, 1.25),
    ],
)
def test_clamp_value(value, step, expected):
    assert clamp_value(value, step) == expected


@pytest.mark.parametrize(
    ("mac", "expected"),
    [
        ("AA:BB:CC:DD:EE:FF", "aabbccddeeff"),
        ("AA-BB-CC-DD-EE-FF", "aabbccddeeff"),
        ("AABBCCDDEEFF", "aabbccddeeff"),
    ],
)
def test_normalize_mac(mac, expected):
    assert normalize_mac(mac) == expected


def test_pybool_to_json_bool():
    assert pybool_to_json_bool(True) == "true"
    assert pybool_to_json_bool(False) == "false"


# --- Debug flag tests ---


def test_debug_flags():
    set_no_debug()
    assert is_debug() is False
    set_debug()
    assert is_debug() is True
    set_no_debug()


# --- run_async tests ---


def test_run_async():
    async def coro() -> int:
        return 42

    assert run_async(coro()) == 42


# --- Smart type conversion tests ---


def test_convert_smart_types():
    result = convert_smart_types(["person", "vehicle", "invalid"])
    assert SmartDetectObjectType.PERSON in result
    assert SmartDetectObjectType.VEHICLE in result
    assert len(result) == 2


def test_convert_smart_audio_types():
    result = convert_smart_audio_types(["alrmSmoke", "invalid"])
    assert SmartDetectAudioType.SMOKE in result
    assert len(result) == 1


def test_convert_video_modes():
    result = convert_video_modes(["default", "highFps", "invalid"])
    assert VideoMode.DEFAULT in result
    assert VideoMode.HIGH_FPS in result
    assert len(result) == 2


# --- get_response_reason tests ---


@pytest.mark.asyncio()
async def test_get_response_reason():
    # JSON with error key
    resp = AsyncMock(reason="Bad", json=AsyncMock(return_value={"error": "Invalid"}))
    assert await get_response_reason(resp) == "Invalid"

    # JSON without error key
    resp = AsyncMock(reason="Bad", json=AsyncMock(return_value={"msg": "err"}))
    assert "msg" in await get_response_reason(resp)

    # Text fallback
    resp = AsyncMock(
        reason="Bad",
        json=AsyncMock(side_effect=Exception()),
        text=AsyncMock(return_value="Text"),
    )
    assert await get_response_reason(resp) == "Text"

    # Reason fallback
    resp = AsyncMock(
        reason="Error",
        json=AsyncMock(side_effect=Exception()),
        text=AsyncMock(side_effect=Exception()),
    )
    assert await get_response_reason(resp) == "Error"


# --- decode_token_cookie tests ---


def test_decode_token_cookie():
    # Valid token
    payload: dict[str, Any] = {"sub": "user", "exp": int(time_module.time()) + 3600}
    token = jwt.encode(payload, "secret", algorithm="HS256")
    morsel: Morsel[str] = Morsel()
    morsel.set("token", token, token)
    assert decode_token_cookie(morsel)["sub"] == "user"

    # Expired token
    payload = {"sub": "user", "exp": int(time_module.time()) - 3600}
    token = jwt.encode(payload, "secret", algorithm="HS256")
    morsel.set("token", token, token)
    assert decode_token_cookie(morsel) is None

    # Invalid token
    morsel.set("token", "invalid", "invalid")
    assert decode_token_cookie(morsel) is None


# --- local_datetime tests ---


def test_local_datetime():
    assert local_datetime(None).tzinfo is not None
    assert (
        local_datetime(datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)).tzinfo
        is not None
    )
    assert local_datetime(datetime(2024, 1, 15, 12, 0, 0)).tzinfo is not None


def test_get_local_timezone(monkeypatch):
    tz = get_local_timezone()
    assert tz is not None

    monkeypatch.setattr(utils_module, "TIMEZONE_GLOBAL", None)
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert get_local_timezone() is not None
    monkeypatch.setattr(utils_module, "TIMEZONE_GLOBAL", None)


# --- WS stat tests ---


def test_ws_stat_summary():
    with pytest.raises(ValueError, match="No stats"):
        ws_stat_summmary([])

    stats = [
        WSStat(
            model="camera",
            action="update",
            keys=["name"],
            keys_set=["name"],
            size=100,
            filtered=False,
        ),
        WSStat(
            model="camera",
            action="update",
            keys=["name"],
            keys_set=["name"],
            size=50,
            filtered=False,
        ),
        WSStat(
            model="light",
            action="add",
            keys=["id"],
            keys_set=["id"],
            size=30,
            filtered=True,
        ),
    ]
    unfiltered, _percent, _keys, models, _actions = ws_stat_summmary(stats)
    assert len(unfiltered) == 2
    assert models["camera"] == 2


def test_print_ws_stat_summary():
    stats = [
        WSStat(
            model="camera",
            action="update",
            keys=["name"],
            keys_set=["name"],
            size=100,
            filtered=False,
        )
    ]
    lines: list[str] = []
    print_ws_stat_summary(stats, output=lines.append)
    assert "camera: 1" in lines[0]


# --- write_json tests ---


@pytest.mark.asyncio()
async def test_write_json(tmp_path: Path):
    path = tmp_path / "test.json"
    await write_json(path, {"key": "value"})
    assert path.exists()
    assert '"key": "value"' in path.read_text()


# --- log_event tests ---


def test_log_event():
    # Non-smart event
    event = Mock(type=EventType.MOTION, model_dump=Mock(return_value={}))
    log_event(event)

    # Smart event without camera
    event = Mock(
        type=EventType.SMART_DETECT, model_dump=Mock(return_value={}), camera=None
    )
    log_event(event)

    # Smart event with camera and end
    camera = Mock(mac="AA:BB:CC:DD:EE:FF")
    camera.name = "Cam"
    event = Mock(
        type=EventType.SMART_DETECT,
        model_dump=Mock(return_value={}),
        camera=camera,
        end=datetime.now(tz=timezone.utc),
        smart_detect_types=[SmartDetectObjectType.PERSON],
        id="e1",
    )
    log_event(event)

    # Smart detect event (new)
    camera = Mock(
        mac="AA:BB:CC:DD:EE:FF",
        is_smart_detected=True,
        is_recording_enabled=True,
        smart_detect_settings=Mock(object_types=[SmartDetectObjectType.PERSON]),
        get_last_smart_detect_event=Mock(return_value=None),
    )
    camera.name = "Cam"
    event = Mock(
        type=EventType.SMART_DETECT,
        model_dump=Mock(return_value={}),
        camera=camera,
        end=None,
        smart_detect_types=[SmartDetectObjectType.PERSON],
        id="e2",
    )
    log_event(event)

    # Smart audio detect
    camera = Mock(
        mac="AA:BB:CC:DD:EE:FF",
        is_smart_detected=True,
        is_recording_enabled=True,
        smart_detect_settings=Mock(audio_types=[SmartDetectAudioType.SMOKE]),
        get_last_smart_audio_detect_event=Mock(return_value=None),
    )
    camera.name = "Cam"
    smart_type = Mock(audio_type=SmartDetectAudioType.SMOKE)
    event = Mock(
        type=EventType.SMART_AUDIO_DETECT,
        model_dump=Mock(return_value={}),
        camera=camera,
        end=None,
        smart_detect_types=[smart_type],
        id="e3",
    )
    log_event(event)

    # Smart audio detect without audio_type
    smart_type = Mock(audio_type=None)
    camera = Mock(mac="AA:BB:CC:DD:EE:FF")
    camera.name = "Cam"
    event = Mock(
        type=EventType.SMART_AUDIO_DETECT,
        model_dump=Mock(return_value={}),
        camera=camera,
        end=None,
        smart_detect_types=[smart_type],
        id="e4",
    )
    log_event(event)
