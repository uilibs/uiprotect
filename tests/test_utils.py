from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from ipaddress import IPv4Address, IPv6Address
from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic.fields import FieldInfo

from uiprotect.utils import (
    convert_to_datetime,
    convert_unifi_data,
    dict_diff,
    format_host_for_url,
    get_nested_attr,
    get_nested_attr_as_bool,
    get_top_level_attr_as_bool,
    ip_from_host,
    make_enabled_getter,
    make_required_getter,
    make_value_getter,
    to_snake_case,
)


def test_dict_diff_equal():
    assert dict_diff({}, {}) == {}

    obj = {"a": 1, "b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}
    assert dict_diff(obj, obj) == {}

    obj = {
        "a": 1,
        "b": {"b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]},
    }
    assert dict_diff(obj, obj) == {}

    obj = {
        "a": 1,
        "b": {"b": 2, "c": {"c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}},
    }
    assert dict_diff(obj, obj) == {}


def test_dict_diff_new_keys():
    obj = {"a": 1, "b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}
    assert dict_diff({}, obj) == obj
    assert dict_diff({"a": 1, "b": {}}, {"a": 1, "b": obj}) == {"b": obj}

    obj = {
        "a": 1,
        "b": {"b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]},
    }
    assert dict_diff({}, obj) == obj
    assert dict_diff({"a": 1, "b": {}}, {"a": 1, "b": obj}) == {"b": obj}

    obj = {
        "a": 1,
        "b": {"b": 2, "c": {"c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]}},
    }
    assert dict_diff({}, obj) == obj
    assert dict_diff({"a": 1, "b": {}}, {"a": 1, "b": obj}) == {"b": obj}


def test_dict_diff_new_changed():
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

    assert dict_diff(
        {
            "a": 1,
            "b": {"b": 2, "c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]},
        },
        {
            "a": 3,
            "b": {
                "b": 2,
                "c": "test",
                "d": "test",
                "e": "test6",
                "f": [1],
                "g": [1, 2, 3],
            },
        },
    ) == {"a": 3, "b": {"c": "test", "d": "test", "e": "test6", "f": [1]}}

    assert dict_diff(
        {
            "a": 1,
            "b": {
                "b": 2,
                "c": {"c": None, "d": 2.5, "e": "test", "f": [], "g": [1, 2, 3]},
            },
        },
        {
            "a": 3,
            "b": {
                "b": 2,
                "c": {"c": "test", "d": "test", "e": "test6", "f": [1], "g": [1, 2, 3]},
            },
        },
    ) == {"a": 3, "b": {"c": {"c": "test", "d": "test", "e": "test6", "f": [1]}}}


def test_to_snake_case():
    assert to_snake_case("CamelCase") == "camel_case"
    assert to_snake_case("CamelCamelCase") == "camel_camel_case"
    assert to_snake_case("Camel2Camel2Case") == "camel2_camel2_case"
    assert to_snake_case("getHTTPResponseCode") == "get_http_response_code"
    assert to_snake_case("get2HTTPResponseCode") == "get2_http_response_code"
    assert to_snake_case("HTTPResponseCode") == "http_response_code"
    assert to_snake_case("HTTPResponseCodeXYZ") == "http_response_code_xyz"


@pytest.mark.parametrize(
    ("value", "field", "output"),
    [
        (
            "00000000-0000-00 0- 000-000000000000",
            FieldInfo(
                name="id",
                annotation=UUID,
                class_validators=None,
            ),
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
        (
            "00000000-0000-0000-0000-000000000000",
            FieldInfo(
                name="id",
                annotation=UUID,
                class_validators=None,
            ),
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
        (
            UUID("00000000-0000-0000-0000-000000000000"),
            FieldInfo(
                name="id",
                annotation=UUID,
                class_validators=None,
            ),
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
    ],
)
def test_convert_unifi_data(value: Any, field: FieldInfo, output: Any):
    assert convert_unifi_data(value, field) == output


@pytest.mark.asyncio
async def test_valid_float_timestamp():
    timestamp = 1715563200000.0
    expected_datetime = datetime(2024, 5, 13, 1, 20, tzinfo=timezone.utc)
    assert convert_to_datetime(timestamp).timestamp() * 1000 == timestamp
    assert convert_to_datetime(timestamp) == expected_datetime


@pytest.mark.asyncio
async def test_valid_string_timestamp():
    timestamp = "1715563200000"
    expected_datetime = datetime(2024, 5, 13, 1, 20, tzinfo=timezone.utc)
    assert convert_to_datetime(timestamp).timestamp() * 1000 == int(timestamp)
    assert convert_to_datetime(timestamp) == expected_datetime


@pytest.mark.asyncio
async def test_valid_datetime_object():
    # Direct datetime object
    dt = datetime(2024, 6, 11, 12, 0, tzinfo=timezone.utc)
    assert convert_to_datetime(dt) == dt


@pytest.mark.asyncio
async def test_none_input():
    # None input should return None
    assert convert_to_datetime(None) is None


@pytest.mark.asyncio
async def test_invalid_string_input():
    # Invalid string should raise ValueError
    with pytest.raises(ValueError):
        convert_to_datetime("invalid-date")


@pytest.mark.asyncio
async def test_caching():
    # Test if caching is working by calling the function with the same input multiple times
    timestamp = 1715563200.0
    result1 = convert_to_datetime(timestamp)
    result2 = convert_to_datetime(timestamp)
    assert result1 is result2


class _MockEnum(Enum):
    A = 1
    B = 2
    C = 3


@pytest.mark.asyncio
def test_get_nested_attr():
    data = Mock(a=Mock(b=Mock(c=1)), d=3, f=_MockEnum.C)
    assert get_nested_attr(("a", "b", "c"), data) == 1
    assert get_nested_attr(("d",), data) == 3
    assert get_nested_attr(("f",), data) == _MockEnum.C


@pytest.mark.asyncio
def test_get_nested_attr_as_bool():
    data = Mock(a=Mock(b=Mock(c=True)), d=False, f=_MockEnum.C)
    assert get_nested_attr_as_bool(("a", "b", "c"), data) is True
    assert get_nested_attr_as_bool(("d",), data) is False
    assert get_nested_attr_as_bool(("f",), data) is True


@pytest.mark.asyncio
def test_get_top_level_attr_as_bool():
    data = Mock(a=True, b=False, c=True, d=None)
    assert get_top_level_attr_as_bool("a", data) is True
    assert get_top_level_attr_as_bool("b", data) is False
    assert get_top_level_attr_as_bool("c", data) is True
    assert get_top_level_attr_as_bool("d", data) is False


@pytest.mark.asyncio
def test_make_value_getter():
    data = Mock(a=1, b=2, c=3, d=4)
    assert make_value_getter("a")(data) == 1
    assert make_value_getter("b")(data) == 2
    assert make_value_getter("c")(data) == 3
    assert make_value_getter("d")(data) == 4


@pytest.mark.asyncio
def test_make_value_getter_nested():
    data = Mock(b=2, c=Mock(q="x"))
    assert make_value_getter("c.q")(data) == "x"
    assert make_value_getter("b.x")(data) is None


@pytest.mark.asyncio
def test_make_enabled_getter():
    data = Mock(a=True, b=False, c=True, d=False)
    assert make_enabled_getter("a")(data) is True
    assert make_enabled_getter("b")(data) is False
    assert make_enabled_getter("c")(data) is True
    assert make_enabled_getter("d")(data) is False


@pytest.mark.asyncio
def test_make_enabled_getter_nested():
    data = Mock(a=Mock(q=True), q=None, c=Mock(q=False))
    assert make_enabled_getter("a.q")(data) is True
    assert make_enabled_getter("q.q")(data) is None
    assert make_enabled_getter("c.q")(data) is False


@pytest.mark.asyncio
def test_make_required_getter():
    data = Mock(a=1, b=2, c=3, d=_MockEnum.C, e=None)
    assert make_required_getter("a")(data) is True
    assert make_required_getter("b")(data) is True
    assert make_required_getter("c")(data) is True
    assert make_required_getter("d")(data) is True
    assert make_required_getter("e")(data) is False


@pytest.mark.asyncio
def test_make_required_getter_nested():
    data = Mock(a=Mock(q=2), b=Mock(q=0), d=Mock(q=_MockEnum.C))
    assert make_required_getter("a.q")(data) is True
    assert make_required_getter("b.q")(data) is False
    assert make_required_getter("c.q")(data) is True


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        # IPv4 addresses (no brackets)
        (IPv4Address("192.168.1.1"), "192.168.1.1"),
        ("192.168.1.1", "192.168.1.1"),
        ("10.0.0.1", "10.0.0.1"),
        # IPv6 addresses (with brackets)
        (IPv6Address("fe80::1ff:fe23:4567:890a"), "[fe80::1ff:fe23:4567:890a]"),
        ("fe80::1ff:fe23:4567:890a", "[fe80::1ff:fe23:4567:890a]"),
        (
            IPv6Address("2001:0db8:85a3:0000:0000:8a2e:0370:7334"),
            "[2001:db8:85a3::8a2e:370:7334]",
        ),
        ("::1", "[::1]"),
        ("::", "[::]"),
        # Hostnames (unchanged)
        ("example.com", "example.com"),
        ("nvr.local", "nvr.local"),
        ("localhost", "localhost"),
    ],
)
def test_format_host_for_url(host, expected):
    """Test that hosts are correctly formatted for URLs."""
    assert format_host_for_url(host) == expected


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("host", "expected_type", "expected_str"),
    [
        # IPv4 addresses
        ("192.168.1.1", IPv4Address, "192.168.1.1"),
        ("10.0.0.1", IPv4Address, "10.0.0.1"),
        # IPv6 addresses (normalized)
        ("fe80::1ff:fe23:4567:890a", IPv6Address, "fe80::1ff:fe23:4567:890a"),
        (
            "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            IPv6Address,
            "2001:db8:85a3::8a2e:370:7334",
        ),
        ("::1", IPv6Address, "::1"),
        ("::", IPv6Address, "::"),
    ],
)
async def test_ip_from_host(host, expected_type, expected_str):
    """Test that IP addresses are parsed correctly."""
    result = await ip_from_host(host)
    assert isinstance(result, expected_type)
    assert str(result) == expected_str


@pytest.mark.asyncio()
async def test_ip_from_host_localhost():
    """Test that localhost hostname resolves to an IP address."""
    result = await ip_from_host("localhost")
    # localhost can resolve to either IPv4 or IPv6 depending on system configuration
    assert isinstance(result, (IPv4Address, IPv6Address))


@pytest.mark.asyncio()
async def test_ip_from_host_invalid():
    """Test that invalid hostnames raise ValueError."""
    with pytest.raises(ValueError, match="Cannot resolve hostname"):
        await ip_from_host("this-does-not-exist-12345.invalid")
