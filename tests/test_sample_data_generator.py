from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from uiprotect.test_util import SampleDataGenerator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_generate_chime_data_no_device_logs_chime(tmp_path: Path) -> None:
    """The no-chime skip path names chime endpoints, not doorlock."""
    client = AsyncMock()
    client.api_request_list.return_value = []
    messages: list[str] = []

    generator = SampleDataGenerator(
        client=client,
        output=tmp_path,
        anonymize=False,
        wait_time=0,
        log=messages.append,
    )

    await generator.generate_chime_data()

    assert messages == ["No chime found. Skipping chime endpoints..."]
    client.api_request_obj.assert_not_called()
