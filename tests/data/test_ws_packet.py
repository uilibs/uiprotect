"""Tests for uiprotect.data.websocket."""

from __future__ import annotations

import struct
import zlib

import pytest

from uiprotect.data.websocket import (
    MAX_WS_FRAME,
    WS_HEADER_SIZE,
    WSRawPacketFrame,
)
from uiprotect.exceptions import WSDecodeError


def _frame(payload: bytes, *, deflated: int = 0, payload_format: int = 3) -> bytes:
    header = struct.pack(
        "!bbbbi",
        1,
        payload_format,
        deflated,
        0,
        len(payload),
    )
    return header + payload


def test_decompression_bomb_rejected():
    bomb_input = b"\x00" * (MAX_WS_FRAME + 1)
    bomb = zlib.compress(bomb_input)
    assert len(bomb) < MAX_WS_FRAME

    data = _frame(bomb, deflated=1)

    with pytest.raises(WSDecodeError):
        WSRawPacketFrame.from_binary(data)


def test_oversized_payload_size_rejected():
    payload = b"abc"
    header = struct.pack("!bbbbi", 1, 3, 0, 0, len(payload) + 100)
    data = header + payload

    with pytest.raises(WSDecodeError):
        WSRawPacketFrame.from_binary(data)


def test_negative_payload_size_rejected():
    header = struct.pack("!bbbbi", 1, 3, 0, 0, -1)
    data = header + b"abc"

    with pytest.raises(WSDecodeError):
        WSRawPacketFrame.from_binary(data)


def test_invalid_deflate_stream_rejected():
    data = _frame(b"\x00\x01\x02not-valid-zlib", deflated=1)

    with pytest.raises(WSDecodeError):
        WSRawPacketFrame.from_binary(data)


def test_safe_inflate_under_limit_decodes():
    payload_bytes = b"hello" * 1000
    compressed = zlib.compress(payload_bytes)
    data = _frame(compressed, deflated=1)

    frame = WSRawPacketFrame.from_binary(data)

    assert frame.data == payload_bytes
    assert frame.length == WS_HEADER_SIZE + len(compressed)


def test_uncompressed_frame_passes_through():
    payload = b"raw-bytes"
    data = _frame(payload, deflated=0)

    frame = WSRawPacketFrame.from_binary(data)

    assert frame.data == payload
