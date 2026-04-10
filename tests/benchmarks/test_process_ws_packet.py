"""
Benchmarks for Bootstrap.process_ws_packet.

Websocket packet processing is the hottest path in uiprotect — every Protect
event flows through it and historically this path has regressed silently.
These benchmarks exercise the dispatch pipeline against a real recorded
message stream.

The timed region calls ``process_ws_packet`` only. Packet wrapper
construction and JSON decoding are paid once at session setup; an untimed
``setup`` hook restores the decoded dicts between rounds to undo the
in-place mutation (e.g. ``lastSeen`` int → datetime) that would otherwise
corrupt state across iterations.

The tests are async so ``process_ws_packet``'s error recovery path — which
schedules refreshes via ``asyncio.create_task`` — has a running loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.benchmarks.conftest import reset_ws_packets
from uiprotect.data import ModelType

if TYPE_CHECKING:
    from pytest_codspeed import BenchmarkFixture

    from uiprotect.data import Bootstrap, WSPacket


_SUBSCRIBED_MODELS: set[ModelType] = {
    ModelType.EVENT,
    ModelType.CAMERA,
    ModelType.LIGHT,
    ModelType.VIEWPORT,
    ModelType.SENSOR,
    ModelType.LIVEVIEW,
}

_ROUNDS = 5


@pytest.mark.asyncio
async def test_process_ws_packet_all(
    benchmark: BenchmarkFixture,
    benchmark_bootstrap: Bootstrap,
    ws_packets: list[WSPacket],
    ws_packet_templates: list[tuple[Any, Any]],
) -> None:
    """Process every recorded packet with no model filter."""
    bootstrap = benchmark_bootstrap
    bootstrap.capture_ws_stats = False
    process = bootstrap.process_ws_packet

    def _setup() -> None:
        reset_ws_packets(ws_packets, ws_packet_templates)

    def _run() -> None:
        for packet in ws_packets:
            process(packet)

    benchmark.pedantic(_run, setup=_setup, rounds=_ROUNDS)


@pytest.mark.asyncio
async def test_process_ws_packet_filtered(
    benchmark: BenchmarkFixture,
    benchmark_bootstrap: Bootstrap,
    ws_packets: list[WSPacket],
    ws_packet_templates: list[tuple[Any, Any]],
) -> None:
    """Process every recorded packet with the default HA subscription filter."""
    bootstrap = benchmark_bootstrap
    bootstrap.capture_ws_stats = False
    process = bootstrap.process_ws_packet
    models = _SUBSCRIBED_MODELS

    def _setup() -> None:
        reset_ws_packets(ws_packets, ws_packet_templates)

    def _run() -> None:
        for packet in ws_packets:
            process(packet, models)

    benchmark.pedantic(_run, setup=_setup, rounds=_ROUNDS)


@pytest.mark.asyncio
async def test_process_ws_packet_with_stats(
    benchmark: BenchmarkFixture,
    benchmark_bootstrap: Bootstrap,
    ws_packets: list[WSPacket],
    ws_packet_templates: list[tuple[Any, Any]],
) -> None:
    """Process every recorded packet with WS stats capture enabled."""
    bootstrap = benchmark_bootstrap
    bootstrap.capture_ws_stats = True
    process = bootstrap.process_ws_packet

    def _setup() -> None:
        bootstrap.clear_ws_stats()
        reset_ws_packets(ws_packets, ws_packet_templates)

    def _run() -> None:
        for packet in ws_packets:
            process(packet)

    try:
        benchmark.pedantic(_run, setup=_setup, rounds=_ROUNDS)
    finally:
        bootstrap.capture_ws_stats = False
        bootstrap.clear_ws_stats()


@pytest.mark.asyncio
async def test_process_ws_packet_ignore_stats(
    benchmark: BenchmarkFixture,
    benchmark_bootstrap: Bootstrap,
    ws_packets: list[WSPacket],
    ws_packet_templates: list[tuple[Any, Any]],
) -> None:
    """Process every recorded packet with ignore_stats set."""
    bootstrap = benchmark_bootstrap
    bootstrap.capture_ws_stats = False
    process = bootstrap.process_ws_packet

    def _setup() -> None:
        reset_ws_packets(ws_packets, ws_packet_templates)

    def _run() -> None:
        for packet in ws_packets:
            process(packet, None, True)

    benchmark.pedantic(_run, setup=_setup, rounds=_ROUNDS)
