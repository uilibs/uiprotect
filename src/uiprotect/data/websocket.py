"""Classes for decoding/encoding data from UniFi OS Websocket"""

from __future__ import annotations

import base64
import enum
import struct
import zlib
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

import orjson

from .._compat import cached_property
from ..exceptions import WSDecodeError, WSEncodeError
from .types import ProtectWSPayloadFormat

if TYPE_CHECKING:
    from .base import ProtectModelWithId

WS_HEADER_SIZE = 8


@dataclass(slots=True)
class WSPacketFrameHeader:
    packet_type: int
    payload_format: int
    deflated: int
    unknown: int
    payload_size: int


@enum.unique
class WSAction(str, enum.Enum):
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"


@dataclass(slots=True)
class WSSubscriptionMessage:
    action: WSAction
    new_update_id: str
    changed_data: dict[str, Any]
    new_obj: ProtectModelWithId | None = None
    old_obj: ProtectModelWithId | None = None


_PACKET_STRUCT = struct.Struct("!bbbbi")


class BaseWSPacketFrame:
    unpack = _PACKET_STRUCT.unpack
    pack = _PACKET_STRUCT.pack

    data: Any
    position: int = 0
    header: WSPacketFrameHeader | None = None
    payload_format: ProtectWSPayloadFormat = ProtectWSPayloadFormat.NodeBuffer
    is_deflated: bool = False
    length: int = 0

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} header={self.header} data={self.data}>"

    def set_data_from_binary(self, data: bytes) -> None:
        self.data = data
        if self.header is not None and self.header.deflated:
            self.data = zlib.decompress(self.data)

    def get_binary_from_data(self) -> bytes:
        raise NotImplementedError

    @staticmethod
    @cache
    def klass_from_format(format_raw: int) -> type[BaseWSPacketFrame]:
        payload_format = ProtectWSPayloadFormat(format_raw)

        if payload_format == ProtectWSPayloadFormat.JSON:
            return WSJSONPacketFrame

        return WSRawPacketFrame

    @staticmethod
    def from_binary(
        data: bytes,
        position: int = 0,
        klass: type[WSRawPacketFrame] | None = None,
    ) -> BaseWSPacketFrame:
        """
        Decode a unifi updates websocket frame.

        The format of the frame is
        b: packet_type
        b: payload_format
        b: deflated
        b: unknown
        i: payload_size
        """
        header_end = position + WS_HEADER_SIZE
        payload_size: int
        try:
            (
                packet_type,
                payload_format,
                deflated,
                unknown,
                payload_size,
            ) = BaseWSPacketFrame.unpack(
                data[position:header_end],
            )
        except struct.error as e:
            raise WSDecodeError from e

        if klass is None:
            frame = WSRawPacketFrame.klass_from_format(payload_format)()
        else:
            frame = klass()
            frame.payload_format = ProtectWSPayloadFormat(payload_format)

        frame.header = WSPacketFrameHeader(
            packet_type=packet_type,
            payload_format=payload_format,
            deflated=deflated,
            unknown=unknown,
            payload_size=payload_size,
        )
        frame.length = WS_HEADER_SIZE + payload_size
        frame.is_deflated = bool(deflated)
        frame_end = header_end + payload_size
        frame.set_data_from_binary(data[header_end:frame_end])

        return frame

    @property
    def packed(self) -> bytes:
        if self.header is None:
            raise WSEncodeError("No header to encode")

        data = self.get_binary_from_data()
        header = self.pack(
            self.header.packet_type,
            self.header.payload_format,
            self.header.deflated,
            self.header.unknown,
            len(data),
        )

        return header + data


class WSRawPacketFrame(BaseWSPacketFrame):
    data: bytes = b""

    def get_binary_from_data(self) -> bytes:
        data = self.data
        if self.is_deflated:
            data = zlib.compress(data)

        return data


class WSJSONPacketFrame(BaseWSPacketFrame):
    data: dict[str, Any] = {}
    payload_format: ProtectWSPayloadFormat = ProtectWSPayloadFormat.NodeBuffer

    def set_data_from_binary(self, data: bytes) -> None:
        if self.header is not None and self.header.deflated:
            data = zlib.decompress(data)

        self.data = orjson.loads(data)

    def get_binary_from_data(self) -> bytes:
        data = self.json
        if self.is_deflated:
            data = zlib.compress(data)

        return data

    @property
    def json(self) -> bytes:
        return orjson.dumps(self.data)


class WSPacket:
    """Class to handle a unifi protect websocket packet."""

    _raw: bytes
    _raw_encoded: str | None = None

    _action_frame: BaseWSPacketFrame | None = None
    _data_frame: BaseWSPacketFrame | None = None

    def __init__(self, data: bytes) -> None:
        self._raw = data

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} action_frame={self.action_frame} data_frame={self.data_frame}>"

    def decode(self) -> None:
        data = self._raw
        self._action_frame = WSRawPacketFrame.from_binary(data)
        length = self._action_frame.length
        self._data_frame = WSRawPacketFrame.from_binary(data, length)

    @cached_property
    def action_frame(self) -> BaseWSPacketFrame:
        if self._action_frame is None:
            self.decode()
        if TYPE_CHECKING:
            assert self._action_frame is not None
            assert self._data_frame is not None
        self.__dict__["data_frame"] = self._data_frame
        return self._action_frame

    @cached_property
    def data_frame(self) -> BaseWSPacketFrame:
        if self._data_frame is None:
            self.decode()
        if TYPE_CHECKING:
            assert self._action_frame is not None
            assert self._data_frame is not None
        self.__dict__["action_frame"] = self._action_frame
        return self._data_frame

    @property
    def raw(self) -> bytes:
        return self._raw

    @raw.setter
    def raw(self, data: bytes) -> None:
        self._raw = data
        self._action_frame = None
        self._data_frame = None
        self._raw_encoded = None
        self.__dict__.pop("data_frame", None)
        self.__dict__.pop("action_frame", None)

    @property
    def raw_base64(self) -> str:
        if self._raw_encoded is None:
            self._raw_encoded = base64.b64encode(self._raw).decode("utf-8")

        return self._raw_encoded

    def pack_frames(self) -> bytes:
        self._raw_encoded = None
        self._raw = self.action_frame.packed + self.data_frame.packed

        return self._raw
