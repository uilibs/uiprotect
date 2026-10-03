# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_CHIME_EXISTS

if TYPE_CHECKING:
    from uiprotect.data import Chime


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play(chime_obj: Chime | None):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    await chime_obj.play()

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json=None,
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play_with_options(chime_obj: Chime | None):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    chime_obj.volume = 100
    chime_obj.repeat_times = 1
    chime_obj.api.api_request.reset_mock()

    await chime_obj.play(volume=50)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json={
            "volume": 50,
            "repeatTimes": 1,
        },
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play_buzzer(chime_obj: Chime | None):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    await chime_obj.play_buzzer()

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-buzzer",
        method="post",
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_set_name(chime_obj: Chime) -> None:
    chime_obj.api.api_request.reset_mock()
    chime_obj.name = "Old"

    await chime_obj.set_name("New")

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={"name": "New"},
    )
