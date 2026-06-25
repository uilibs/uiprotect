"""Derived detection-state booleans on PublicCamera, driven by the public events WS."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from uiprotect.data import PublicCamera
from uiprotect.data.public_bootstrap import PublicBootstrap

from .test_public_devices_models import CAMERA_PAYLOAD


def _bootstrap_with_camera() -> PublicBootstrap:
    pb = PublicBootstrap()
    pb.process_devices_ws_message(Mock(), {"type": "add", "item": dict(CAMERA_PAYLOAD)})
    return pb


def _event(action: str, **item: Any) -> dict[str, Any]:
    return {"type": action, "item": {"modelKey": "event", **item}}


def test_no_active_events_all_false() -> None:
    """A freshly cached camera reports every detection flag as ``False``."""
    cam = _bootstrap_with_camera().cameras["cam1"]
    assert cam.is_motion_detected is False
    assert cam.is_smart_currently_detected is False
    assert cam.is_person_currently_detected is False
    assert cam.is_vehicle_currently_detected is False
    assert cam.is_animal_currently_detected is False
    assert cam.is_audio_currently_detected is False
    assert cam.is_smoke_currently_detected is False
    assert cam.is_cmonx_currently_detected is False
    assert cam.is_siren_currently_detected is False


def test_motion_event_start_and_end() -> None:
    """An open motion event sets ``is_motion_detected``; its end clears it."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(),
        _event("add", id="m1", type="motion", start=1000, device="cam1"),
    )
    assert cam.is_motion_detected is True

    pb.process_events_ws_message(Mock(), _event("update", id="m1", end=2000))
    assert cam.is_motion_detected is False


def test_smart_detect_person_start_and_end() -> None:
    """A smartDetectZone person event drives the smart + person flags only."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="s1",
            type="smartDetectZone",
            start=1000,
            device="cam1",
            smartDetectTypes=["person"],
        ),
    )
    assert cam.is_smart_currently_detected is True
    assert cam.is_person_currently_detected is True
    assert cam.is_vehicle_currently_detected is False
    assert cam.is_animal_currently_detected is False

    pb.process_events_ws_message(Mock(), _event("update", id="s1", end=2000))
    assert cam.is_smart_currently_detected is False
    assert cam.is_person_currently_detected is False


def test_smart_detect_line_drives_smart_flags() -> None:
    """A ``smartDetectLine`` event drives the smart/person flags like ``smartDetectZone``."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="l1",
            type="smartDetectLine",
            start=1000,
            device="cam1",
            smartDetectTypes=["person"],
        ),
    )
    assert cam.is_smart_currently_detected is True
    assert cam.is_person_currently_detected is True

    pb.process_events_ws_message(Mock(), _event("update", id="l1", end=2000))
    assert cam.is_smart_currently_detected is False
    assert cam.is_person_currently_detected is False


def test_smart_audio_smoke_start_and_end() -> None:
    """A smartAudioDetect smoke event drives the audio + smoke flags only."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="a1",
            type="smartAudioDetect",
            start=1000,
            device="cam1",
            smartDetectTypes=["alrmSmoke"],
        ),
    )
    assert cam.is_audio_currently_detected is True
    assert cam.is_smoke_currently_detected is True
    assert cam.is_cmonx_currently_detected is False
    assert cam.is_siren_currently_detected is False

    pb.process_events_ws_message(Mock(), _event("update", id="a1", end=2000))
    assert cam.is_audio_currently_detected is False
    assert cam.is_smoke_currently_detected is False


def test_overlapping_motion_events_stay_on_until_all_end() -> None:
    """Two concurrent motion events keep the flag set until both close."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )
    pb.process_events_ws_message(
        Mock(), _event("add", id="m2", type="motion", start=1100, device="cam1")
    )
    assert cam.is_motion_detected is True

    pb.process_events_ws_message(Mock(), _event("update", id="m1", end=2000))
    assert cam.is_motion_detected is True

    pb.process_events_ws_message(Mock(), _event("update", id="m2", end=2100))
    assert cam.is_motion_detected is False


def test_remove_frame_clears_active_detection() -> None:
    """A server ``remove`` frame clears an active detection."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )
    assert cam.is_motion_detected is True

    pb.process_events_ws_message(Mock(), _event("remove", id="m1"))
    assert cam.is_motion_detected is False


def test_born_closed_event_does_not_turn_flag_on() -> None:
    """An event that arrives already-ended never flips a sustained-state flag."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="m1",
            type="motion",
            start=1000,
            end=1000,
            device="cam1",
        ),
    )
    assert cam.is_motion_detected is False


def test_event_for_unknown_camera_is_ignored() -> None:
    """An event for a device not in the camera store does not raise."""
    pb = _bootstrap_with_camera()
    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="ghost")
    )
    assert pb.cameras["cam1"].is_motion_detected is False


def test_non_detection_event_type_ignored() -> None:
    """A non-detection event type (e.g. ring) leaves all flags clear."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]
    pb.process_events_ws_message(
        Mock(), _event("add", id="r1", type="ring", start=1000, device="cam1")
    )
    assert cam.is_motion_detected is False
    assert cam.is_smart_currently_detected is False


def test_unknown_event_update_is_a_noop() -> None:
    """An ``update`` for an unseen, un-promotable event id touches no camera state."""
    pb = _bootstrap_with_camera()
    pb.process_events_ws_message(Mock(), _event("update", id="ghost-evt", end=2000))
    assert pb.cameras["cam1"].is_motion_detected is False


def test_active_detection_set_is_per_instance() -> None:
    """Two cameras maintain independent active-event sets."""
    cam_a = PublicCamera.model_construct()
    cam_b = PublicCamera.model_construct()
    cam_a._active_detection_events["m1"] = Mock()
    assert cam_b._active_detection_events == {}


def test_license_plate_state_not_exposed() -> None:
    """License-plate recognition is deliberately out of scope on the public model."""
    assert not hasattr(PublicCamera, "is_license_plate_currently_detected")
