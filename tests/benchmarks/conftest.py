"""
Fixtures for websocket processing benchmarks.

Builds a fully populated Bootstrap once per session and pre-decodes the
sample websocket message stream into WSPacket objects. Each benchmark then
runs tight loops against already-constructed objects so the measurement
reflects the production hot path rather than fixture overhead.
"""

from __future__ import annotations

import asyncio
import base64
import copy
from typing import TYPE_CHECKING, Any

import pytest

from tests.conftest import (
    SimpleMockWebsocket,
    read_json_file,
    setup_client,
)
from uiprotect import ProtectApiClient
from uiprotect.data import WSPacket

if TYPE_CHECKING:
    from uiprotect.data import Bootstrap


def _build_client() -> ProtectApiClient:
    return ProtectApiClient(
        "127.0.0.1",
        0,
        "username",
        "password",
        ws_timeout=0.1,
        store_sessions=False,
    )


@pytest.fixture(scope="session")
def benchmark_bootstrap() -> Bootstrap:
    """Return a fully bootstrapped client's Bootstrap, shared across tests."""
    loop = asyncio.new_event_loop()
    try:
        client = _build_client()
        loop.run_until_complete(setup_client(client, SimpleMockWebsocket()))
        bootstrap = client.bootstrap
        bootstrap.capture_ws_stats = False
        # The client is intentionally leaked for the session — cleanup_client
        # would tear down the websocket/session that the bootstrap references.
        return bootstrap
    finally:
        loop.close()


@pytest.fixture(scope="session")
def ws_raw_frames() -> list[bytes]:
    """Return the raw websocket frame bytes from the sample stream."""
    messages = read_json_file("sample_ws_messages")
    return [base64.b64decode(entry["raw"]) for entry in messages.values()]


@pytest.fixture(scope="session")
def ws_packets(ws_raw_frames: list[bytes]) -> list[WSPacket]:
    """
    Pre-decoded WSPackets. Frames are eagerly populated so that
    ``process_ws_packet`` measurements exclude both wrapper construction
    and msgpack/json decoding.
    """
    packets: list[WSPacket] = []
    for raw in ws_raw_frames:
        packet = WSPacket(raw)
        # Force decode so later access is a no-op.
        _ = packet.action_frame
        _ = packet.data_frame
        packets.append(packet)
    return packets


@pytest.fixture(scope="session")
def ws_packet_templates(
    ws_packets: list[WSPacket],
) -> list[tuple[Any, Any]]:
    """
    Deep-copied snapshots of each packet's decoded action/data dicts.

    ``process_ws_packet`` mutates these dicts in place during type
    conversion (e.g. ``lastSeen`` int → datetime). Benchmarks use these
    snapshots in an untimed ``setup`` hook to restore fresh state between
    rounds without re-paying decode cost.
    """
    return [
        (copy.deepcopy(p.action_frame.data), copy.deepcopy(p.data_frame.data))
        for p in ws_packets
    ]


def reset_ws_packets(
    packets: list[WSPacket],
    templates: list[tuple[Any, Any]],
) -> None:
    """Restore each pre-decoded packet's dicts from its template snapshot."""
    for packet, (action_data, frame_data) in zip(packets, templates, strict=True):
        packet.action_frame.data = copy.deepcopy(action_data)
        packet.data_frame.data = copy.deepcopy(frame_data)
