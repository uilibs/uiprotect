"""Lifecycle/task callback coverage for events plumbing."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import Any

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.events.dispatcher import (
    EVENTS_TTL_SWEEP_INTERVAL,
    EventDispatcher,
)


def _make_client() -> ProtectApiClient:
    return ProtectApiClient(
        host="127.0.0.1",
        port=443,
        username="u",
        password="p",  # noqa: S106
        verify_ssl=False,
        store_sessions=False,
    )


def test_on_sweep_task_done_cancelled_is_noop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Stub:
        def cancelled(self) -> bool:
            return True

        def exception(self) -> BaseException | None:  # pragma: no cover - guard
            raise AssertionError("should not be consulted")

    with caplog.at_level(logging.ERROR, logger="uiprotect.events.dispatcher"):
        EventDispatcher._on_sweep_task_done(_Stub())  # type: ignore[arg-type]
    assert not any("TTL sweep" in r.message for r in caplog.records)


def test_on_sweep_task_done_exception_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boom = RuntimeError("boom")

    class _Stub:
        def cancelled(self) -> bool:
            return False

        def exception(self) -> BaseException | None:
            return boom

    with caplog.at_level(logging.ERROR, logger="uiprotect.events.dispatcher"):
        EventDispatcher._on_sweep_task_done(_Stub())  # type: ignore[arg-type]
    assert any(
        "TTL sweep loop terminated unexpectedly" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_ttl_sweep_loop_swallows_sweep_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    dispatcher = EventDispatcher(api)

    monkeypatch.setattr(
        "uiprotect.events.dispatcher.EVENTS_TTL_SWEEP_INTERVAL",
        timedelta(seconds=0),
    )

    calls: list[int] = []
    second_iteration = asyncio.Event()

    def fake_sweep() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        second_iteration.set()
        return 0

    monkeypatch.setattr(dispatcher, "sweep_stale", fake_sweep)

    with caplog.at_level(logging.ERROR, logger="uiprotect.events.dispatcher"):
        task: Any = asyncio.create_task(dispatcher._ttl_sweep_loop())
        try:
            await asyncio.wait_for(second_iteration.wait(), timeout=1.0)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert len(calls) >= 2
    assert any("TTL sweep iteration failed" in r.message for r in caplog.records)
    assert EVENTS_TTL_SWEEP_INTERVAL is not None
