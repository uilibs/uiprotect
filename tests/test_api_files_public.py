"""Tests for the Public API file (device asset) endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import aiohttp
import orjson
import pytest

from uiprotect.data import PublicFile
from uiprotect.exceptions import NvrError

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient


@pytest.mark.asyncio()
async def test_get_files_public_calls_correct_url(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_list = AsyncMock(return_value=[])

    result = await protect_client.get_files_public()

    assert result == []
    protect_client.api_request_list.assert_called_once_with(
        url="/v1/files/animations", public_api=True
    )


@pytest.mark.asyncio()
async def test_get_files_public_accepts_custom_file_type(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_list = AsyncMock(return_value=[])

    await protect_client.get_files_public("future-type")

    protect_client.api_request_list.assert_called_once_with(
        url="/v1/files/future-type", public_api=True
    )


@pytest.mark.asyncio()
async def test_get_files_public_parses_list(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    payload = [
        {
            "name": "abc.png",
            "type": "animations",
            "path": "/files/animations/abc.png",
            "originalName": "welcome.png",
        },
        {
            "name": "def.png",
            "type": "animations",
            "path": "/files/animations/def.png",
        },
    ]
    protect_client_no_debug.api_request_list = AsyncMock(return_value=payload)

    files = await protect_client_no_debug.get_files_public()

    assert [f.name for f in files] == ["abc.png", "def.png"]
    assert files[0].original_name == "welcome.png"
    assert files[1].original_name is None
    assert all(isinstance(f, PublicFile) for f in files)


@pytest.mark.asyncio()
async def test_upload_file_public_sends_multipart(
    protect_client: ProtectApiClient,
) -> None:
    response = orjson.dumps(
        {
            "name": "abc.png",
            "type": "animations",
            "path": "/files/animations/abc.png",
            "originalName": "welcome.png",
        }
    )
    protect_client.api_request_raw = AsyncMock(return_value=response)

    payload = b"\x89PNG\r\n\x1a\n"
    await protect_client.upload_file_public(
        "animations",
        payload,
        original_name="welcome.png",
    )

    protect_client.api_request_raw.assert_called_once()
    call_kwargs = protect_client.api_request_raw.call_args.kwargs
    assert call_kwargs["url"] == "/v1/files/animations"
    assert call_kwargs["method"] == "post"
    assert call_kwargs["public_api"] is True

    form = call_kwargs["data"]
    assert isinstance(form, aiohttp.FormData)
    # ``aiohttp.FormData._fields`` is a list of (option-dict, headers-dict, value)
    # tuples. The shape is stable across aiohttp 3.x.
    assert len(form._fields) == 1
    options, _headers, value = form._fields[0]
    assert options["name"] == "file"
    assert options["filename"] == "welcome.png"
    assert value == payload


@pytest.mark.asyncio()
async def test_upload_file_public_parses_response(
    protect_client_no_debug: ProtectApiClient,
) -> None:
    response = orjson.dumps(
        {
            "name": "abc.png",
            "type": "animations",
            "path": "/files/animations/abc.png",
            "originalName": "welcome.png",
        }
    )
    protect_client_no_debug.api_request_raw = AsyncMock(return_value=response)

    result = await protect_client_no_debug.upload_file_public(
        "animations",
        b"\x89PNG\r\n\x1a\n",
        original_name="welcome.png",
    )

    assert isinstance(result, PublicFile)
    assert result.name == "abc.png"
    assert result.type == "animations"
    assert result.original_name == "welcome.png"


@pytest.mark.asyncio()
async def test_upload_file_public_raises_on_empty_response(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_raw = AsyncMock(return_value=None)

    with pytest.raises(NvrError, match="Empty response"):
        await protect_client.upload_file_public(
            "animations",
            b"\x89PNG\r\n\x1a\n",
            original_name="welcome.png",
        )


@pytest.mark.asyncio()
async def test_upload_file_public_accepts_custom_content_type(
    protect_client: ProtectApiClient,
) -> None:
    response = orjson.dumps(
        {
            "name": "abc.wav",
            "type": "animations",
            "path": "/files/animations/abc.wav",
        }
    )
    protect_client.api_request_raw = AsyncMock(return_value=response)

    await protect_client.upload_file_public(
        "animations",
        b"RIFF",
        original_name="ding.wav",
        content_type="audio/wave",
    )

    form = protect_client.api_request_raw.call_args.kwargs["data"]
    _options, headers, _value = form._fields[0]
    assert headers.get("Content-Type") == "audio/wave"
