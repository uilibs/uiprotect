from __future__ import annotations

import pytest

from uiprotect.data.types import ModelType


@pytest.mark.asyncio()
async def test_model_type_from_string():
    assert ModelType.from_string("camera") is ModelType.CAMERA
    assert ModelType.from_string("invalid") is ModelType.UNKNOWN
