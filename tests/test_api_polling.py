"""Tests for uiprotect.unifi_protect_server."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from tests.conftest import MockDatetime
from uiprotect.data import Camera, EventType
from uiprotect.utils import to_js_time

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient


@pytest.mark.asyncio()
async def test_process_events_none(protect_client: ProtectApiClient, camera):
    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    async def get_events(*args, **kwargs):
        return []

    protect_client.get_events_raw = get_events  # type: ignore[method-assign]

    await protect_client.update()

    assert protect_client.bootstrap.unifi_dict() == bootstrap_before
    assert get_camera() == camera_before


def _reset_events(camera: Camera) -> None:
    camera.last_ring_event_id = None
    camera.last_ring = None
    camera.last_motion_event_id = None
    camera.last_motion = None
    camera.last_smart_detect = None
    camera.last_smart_detect_event_id = None
    camera.last_smart_detects = {}
    camera.last_smart_detect_event_ids = {}


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_process_events_ring(protect_client: ProtectApiClient, now, camera):
    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera_before = get_camera().copy()

    expected_event_id = "bf9a241afe74821ceffffd05"

    async def get_events(*args, **kwargs):
        return [
            {
                "id": expected_event_id,
                "type": "ring",
                "start": to_js_time(now - timedelta(seconds=1)),
                "end": to_js_time(now),
                "score": 0,
                "smartDetectTypes": [],
                "smartDetectEvents": [],
                "camera": camera["id"],
                "partition": None,
                "user": None,
                "metadata": {},
                "thumbnail": f"e-{expected_event_id}",
                "heatmap": f"e-{expected_event_id}",
                "modelKey": "event",
            },
        ]

    protect_client.get_events_raw = get_events  # type: ignore[method-assign]

    await protect_client.update()  # fetch initial bootstrap
    await protect_client.poll_events()  # process events since bootstrap

    camera = get_camera()

    event = camera.last_ring_event
    _reset_events(camera)
    _reset_events(camera_before)

    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.RING
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_process_events_motion(protect_client: ProtectApiClient, now, camera):
    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera_before = get_camera().copy()

    expected_event_id = "bf9a241afe74821ceffffd05"

    async def get_events(*args, **kwargs):
        return [
            {
                "id": expected_event_id,
                "type": "motion",
                "start": to_js_time(now - timedelta(seconds=30)),
                "end": to_js_time(now),
                "score": 0,
                "smartDetectTypes": [],
                "smartDetectEvents": [],
                "camera": camera["id"],
                "partition": None,
                "user": None,
                "metadata": {},
                "thumbnail": f"e-{expected_event_id}",
                "heatmap": f"e-{expected_event_id}",
                "modelKey": "event",
            },
        ]

    protect_client.get_events_raw = get_events  # type: ignore[method-assign]

    await protect_client.update()  # fetch initial bootstrap
    await protect_client.poll_events()  # process events since bootstrap

    camera_before.is_motion_detected = False
    camera = get_camera()

    event = camera.last_motion_event
    _reset_events(camera)
    _reset_events(camera_before)

    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.MOTION
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"
    assert event.start == (now - timedelta(seconds=30))


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_process_events_smart(protect_client: ProtectApiClient, now, camera):
    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera_before = get_camera().copy()

    expected_event_id = "bf9a241afe74821ceffffd05"

    async def get_events(*args, **kwargs):
        return [
            {
                "id": expected_event_id,
                "type": "smartDetectZone",
                "start": to_js_time(now - timedelta(seconds=30)),
                "end": to_js_time(now),
                "score": 0,
                "smartDetectTypes": ["person"],
                "smartDetectEvents": [],
                "camera": camera["id"],
                "partition": None,
                "user": None,
                "metadata": {},
                "thumbnail": f"e-{expected_event_id}",
                "heatmap": f"e-{expected_event_id}",
                "modelKey": "event",
            },
        ]

    protect_client.get_events_raw = get_events  # type: ignore[method-assign]

    await protect_client.update()  # fetch initial bootstrap
    await protect_client.poll_events()  # process events since bootstrap

    camera = get_camera()

    smart_event = camera.last_smart_detect_event
    assert camera.last_smart_detect == smart_event.start

    _reset_events(camera)
    _reset_events(camera_before)

    assert camera.dict() == camera_before.dict()
    assert smart_event.id == expected_event_id
    assert smart_event.type == EventType.SMART_DETECT
    assert smart_event.thumbnail_id == f"e-{expected_event_id}"
    assert smart_event.heatmap_id == f"e-{expected_event_id}"
    assert smart_event.start == (now - timedelta(seconds=30))
    assert smart_event.end == now
