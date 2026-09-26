"""Tests for uiprotect.unifi_protect_server."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from tests.conftest import MockDatetime

from .common import assert_equal_dump

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient
    from uiprotect.data import Camera


@pytest.mark.asyncio()
async def test_process_events_none(protect_client: ProtectApiClient, camera):
    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().model_copy()

    async def get_events(*args, **kwargs):
        return []

    protect_client.get_events_raw = get_events  # type: ignore[method-assign]

    await protect_client.update()

    assert protect_client.bootstrap.unifi_dict() == bootstrap_before
    assert_equal_dump(get_camera(), camera_before)


def _reset_events(camera: Camera) -> None:
    camera.last_ring_event_id = None
    camera.last_ring = None
    camera.last_motion_event_id = None
    camera.last_motion = None
    camera.last_smart_detect = None
    camera.last_smart_detect_event_id = None
    camera.last_fingerprint_identified_event_id = None
    camera.last_fingerprint_identified = None
    camera.last_nfc_card_scanned_event_id = None
    camera.last_nfc_card_scanned = None
    camera.last_smart_detects = {}
    camera.last_smart_detect_event_ids = {}
    camera._active_smart_detect_events = {}


@pytest.mark.asyncio()
@patch("uiprotect.api.datetime", MockDatetime)
async def test_event_return_none(protect_client: ProtectApiClient, now, camera):
    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    camera = get_camera()

    _reset_events(camera)

    assert camera.last_smart_detect_event is None
    assert camera.last_nfc_card_scanned_event is None
    assert camera.last_fingerprint_identified_event is None
