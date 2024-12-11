from __future__ import annotations

import typing

import pytest

from uiprotect.data.types import ModelType, extract_type_shape


@pytest.mark.asyncio()
async def test_model_type_from_string():
    assert ModelType.from_string("camera") is ModelType.CAMERA
    assert ModelType.from_string("invalid") is ModelType.UNKNOWN


def test_extract_type_shape():
    type_, shape = extract_type_shape(bytearray)
    assert type_ is bytearray
    assert shape == 1
    type_, shape = extract_type_shape(typing.get_origin(dict[str, int]))
    assert type_ is dict
    assert shape == 1
    type_, shape = extract_type_shape(dict)
    assert type_ is dict
    assert shape == 1
    with pytest.raises(ValueError, match="Type annotation cannot be None"):
        extract_type_shape(None)
