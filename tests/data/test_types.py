from __future__ import annotations

import typing

import pytest

from uiprotect.data.types import ModelType, get_field_type


@pytest.mark.asyncio()
async def test_model_type_from_string():
    assert ModelType.from_string("camera") is ModelType.CAMERA
    assert ModelType.from_string("invalid") is ModelType.UNKNOWN


@pytest.mark.parametrize(
    ("annotation", "origin", "type_"),
    [
        (bytearray, None, bytearray),
        (typing.get_origin(dict[str, int]), None, dict),
        (dict, None, dict),
        # Extract value type from list, set, dict
        (list[int], list, int),
        (set[int], set, int),
        (dict[str, int], dict, int),
        # Extract type from Annotated
        (typing.Annotated[int, "Hello World"], None, int),
        # Remove '| None' from Union and extract remaining value type
        (int | None, None, int),
        (list[int] | None, list, int),
        (typing.Annotated[int, "Hello World"] | None, None, int),
        # Leave 'normal' unions as is
        (int | str, None, int | str),
        (int | str | bytes, None, int | str | bytes),
    ],
)
def test_get_field_type(annotation, origin, type_):
    res = get_field_type(annotation)
    assert origin == res[0]
    assert type_ == res[1]


def test_get_field_type_error():
    with pytest.raises(ValueError, match="Type annotation cannot be None"):
        get_field_type(None)
