from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from pydantic.v1.config import BaseConfig
from pydantic.v1.fields import ModelField

from uiprotect.utils import (
    convert_to_datetime,
    convert_unifi_data,
    dict_diff,
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
            ModelField(
                name="id",
                type_=UUID,
                class_validators=None,
                model_config=BaseConfig,
            ),
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
        (
            "00000000-0000-0000-0000-000000000000",
            ModelField(
                name="id",
                type_=UUID,
                class_validators=None,
                model_config=BaseConfig,
            ),
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
        (
            UUID("00000000-0000-0000-0000-000000000000"),
            ModelField(
                name="id",
                type_=UUID,
                class_validators=None,
                model_config=BaseConfig,
            ),
            UUID("00000000-0000-0000-0000-000000000000"),
        ),
    ],
)
def test_convert_unifi_data(value: Any, field: ModelField, output: Any):
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
