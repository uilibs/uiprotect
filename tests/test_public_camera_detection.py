"""Derived detection-state booleans on PublicCamera, driven by the public events WS."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from uiprotect.data import PublicCamera
from uiprotect.data.public_bootstrap import PublicBootstrap
from uiprotect.data.public_event import PublicEvent
from uiprotect.data.types import EventType
from uiprotect.data.websocket import WSAction

from .test_public_devices_models import CAMERA_PAYLOAD


def _bootstrap_with_camera() -> PublicBootstrap:
    pb = PublicBootstrap()
    pb.process_devices_ws_message(Mock(), {"type": "add", "item": dict(CAMERA_PAYLOAD)})
    return pb


def _bootstrap_with_two_cameras() -> PublicBootstrap:
    pb = _bootstrap_with_camera()
    second = dict(CAMERA_PAYLOAD)
    second["id"] = "cam2"
    pb.process_devices_ws_message(Mock(), {"type": "add", "item": second})
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
    assert cam.is_baby_cry_currently_detected is False
    assert cam.is_speaking_currently_detected is False
    assert cam.is_bark_currently_detected is False
    assert cam.is_car_alarm_currently_detected is False
    assert cam.is_car_horn_currently_detected is False
    assert cam.is_glass_break_currently_detected is False


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


def test_overlapping_person_events_stay_on_until_all_end() -> None:
    """Two concurrent smartDetectZone person events keep the person/smart flags set until both close."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="p1",
            type="smartDetectZone",
            start=1000,
            device="cam1",
            smartDetectTypes=["person"],
        ),
    )
    pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="p2",
            type="smartDetectZone",
            start=1100,
            device="cam1",
            smartDetectTypes=["person"],
        ),
    )
    assert cam.is_smart_currently_detected is True
    assert cam.is_person_currently_detected is True

    pb.process_events_ws_message(Mock(), _event("update", id="p1", end=2000))
    assert cam.is_smart_currently_detected is True
    assert cam.is_person_currently_detected is True

    pb.process_events_ws_message(Mock(), _event("update", id="p2", end=2100))
    assert cam.is_smart_currently_detected is False
    assert cam.is_person_currently_detected is False


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


def test_smart_audio_cmonx_start_and_end() -> None:
    """A smartAudioDetect CO event drives the audio + cmonx flags only."""
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
            smartDetectTypes=["alrmCmonx"],
        ),
    )
    assert cam.is_audio_currently_detected is True
    assert cam.is_cmonx_currently_detected is True
    assert cam.is_smoke_currently_detected is False
    assert cam.is_siren_currently_detected is False

    pb.process_events_ws_message(Mock(), _event("update", id="a1", end=2000))
    assert cam.is_audio_currently_detected is False
    assert cam.is_cmonx_currently_detected is False


def test_smart_audio_siren_start_and_end() -> None:
    """A smartAudioDetect siren event drives the audio + siren flags only."""
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
            smartDetectTypes=["alrmSiren"],
        ),
    )
    assert cam.is_audio_currently_detected is True
    assert cam.is_siren_currently_detected is True
    assert cam.is_smoke_currently_detected is False
    assert cam.is_cmonx_currently_detected is False

    pb.process_events_ws_message(Mock(), _event("update", id="a1", end=2000))
    assert cam.is_audio_currently_detected is False
    assert cam.is_siren_currently_detected is False


# Each remaining smart-audio subtype: (wire smartDetectType, flag attribute).
_AUDIO_SUBTYPES = [
    ("alrmBabyCry", "is_baby_cry_currently_detected"),
    ("alrmSpeak", "is_speaking_currently_detected"),
    ("alrmBark", "is_bark_currently_detected"),
    ("alrmBurglar", "is_car_alarm_currently_detected"),
    ("alrmCarHorn", "is_car_horn_currently_detected"),
    ("alrmGlassBreak", "is_glass_break_currently_detected"),
]


@pytest.mark.parametrize(("wire_type", "flag"), _AUDIO_SUBTYPES)
def test_smart_audio_subtype_start_and_end(wire_type: str, flag: str) -> None:
    """Each remaining smart-audio subtype drives the audio + its own flag only."""
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
            smartDetectTypes=[wire_type],
        ),
    )
    assert cam.is_audio_currently_detected is True
    assert getattr(cam, flag) is True
    # No cross-talk with the alarm-audio flags from #1054.
    assert cam.is_smoke_currently_detected is False
    assert cam.is_cmonx_currently_detected is False
    assert cam.is_siren_currently_detected is False

    pb.process_events_ws_message(Mock(), _event("update", id="a1", end=2000))
    assert cam.is_audio_currently_detected is False
    assert getattr(cam, flag) is False


@pytest.mark.parametrize(("wire_type", "flag"), _AUDIO_SUBTYPES)
def test_smart_audio_subtype_emits_transition(wire_type: str, flag: str) -> None:
    """Each remaining smart-audio subtype emits its own start/end transitions."""
    pb = _bootstrap_with_camera()

    updates = pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="a1",
            type="smartAudioDetect",
            start=1000,
            device="cam1",
            smartDetectTypes=[wire_type],
        ),
    ).model_updates
    assert len(updates) == 1
    assert updates[0].changed_data == {
        "is_audio_currently_detected": True,
        flag: True,
    }

    updates = pb.process_events_ws_message(
        Mock(), _event("update", id="a1", end=2000)
    ).model_updates
    assert len(updates) == 1
    assert updates[0].changed_data == {
        "is_audio_currently_detected": False,
        flag: False,
    }


def test_detection_state_is_isolated_per_camera() -> None:
    """An event for one camera never leaks into another camera's flags."""
    pb = _bootstrap_with_two_cameras()
    cam1 = pb.cameras["cam1"]
    cam2 = pb.cameras["cam2"]

    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )
    assert cam1.is_motion_detected is True
    assert cam2.is_motion_detected is False

    pb.process_events_ws_message(
        Mock(), _event("add", id="m2", type="motion", start=1100, device="cam2")
    )
    pb.process_events_ws_message(Mock(), _event("update", id="m1", end=2000))
    assert cam1.is_motion_detected is False
    assert cam2.is_motion_detected is True


def test_eviction_clears_stuck_open_detection() -> None:
    """An open event evicted from the bounded cache turns its flag back off."""
    pb = _bootstrap_with_camera()
    pb.max_event_cache_size = 1
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )
    assert cam.is_motion_detected is True

    # A second cached event evicts the open motion event; without eviction-aware
    # sync the flag would stay stuck on and the active set would grow unbounded.
    pb.process_events_ws_message(
        Mock(), _event("add", id="r1", type="ring", start=1100, device="cam1")
    )
    assert cam.is_motion_detected is False
    assert cam._active_detection_events == {}


def test_evicted_open_event_close_update_is_a_noop() -> None:
    """A close update arriving after eviction cannot resurrect the flag."""
    pb = _bootstrap_with_camera()
    pb.max_event_cache_size = 1
    cam = pb.cameras["cam1"]

    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )
    pb.process_events_ws_message(
        Mock(), _event("add", id="r1", type="ring", start=1100, device="cam1")
    )
    pb.process_events_ws_message(Mock(), _event("update", id="m1", end=2000))
    assert cam.is_motion_detected is False


def test_event_without_device_is_tolerated() -> None:
    """An event carrying no ``device`` neither raises on add nor on remove."""
    pb = _bootstrap_with_camera()
    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000)
    )
    assert pb.cameras["cam1"].is_motion_detected is False

    pb.process_events_ws_message(Mock(), _event("remove", id="m1"))
    assert pb.cameras["cam1"].is_motion_detected is False


def test_license_plate_state_not_exposed() -> None:
    """License-plate recognition is deliberately out of scope on the public model."""
    assert not hasattr(PublicCamera, "is_license_plate_currently_detected")


# ---------------------------------------------------------------------------
# Detection-state model updates (process_events_ws_message third return value)
# ---------------------------------------------------------------------------


def test_motion_start_emits_transition() -> None:
    """An open motion event yields a single ``is_motion_detected: True`` update."""
    pb = _bootstrap_with_camera()
    updates = pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    ).model_updates
    assert len(updates) == 1
    assert updates[0].action is WSAction.UPDATE
    assert updates[0].old_obj is None
    assert updates[0].new_obj is pb.cameras["cam1"]
    assert updates[0].new_update_id == "cam1"
    assert updates[0].changed_data == {"is_motion_detected": True}


def test_motion_end_emits_off_transition() -> None:
    """The motion close frame yields a ``is_motion_detected: False`` update."""
    pb = _bootstrap_with_camera()
    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )

    updates = pb.process_events_ws_message(
        Mock(), _event("update", id="m1", end=2000)
    ).model_updates
    assert len(updates) == 1
    assert updates[0].changed_data == {"is_motion_detected": False}


def test_person_start_emits_both_smart_and_person() -> None:
    """A person smartDetect start flips both the smart and person flags in one message."""
    pb = _bootstrap_with_camera()
    updates = pb.process_events_ws_message(
        Mock(),
        _event(
            "add",
            id="p1",
            type="smartDetectZone",
            start=1000,
            device="cam1",
            smartDetectTypes=["person"],
        ),
    ).model_updates
    assert len(updates) == 1
    assert updates[0].changed_data == {
        "is_smart_currently_detected": True,
        "is_person_currently_detected": True,
    }


def test_overlapping_motion_emits_no_second_transition() -> None:
    """A second overlapping motion event does not re-emit an update."""
    pb = _bootstrap_with_camera()
    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )

    updates = pb.process_events_ws_message(
        Mock(), _event("add", id="m2", type="motion", start=1100, device="cam1")
    ).model_updates
    assert updates == []


def test_non_detection_event_emits_no_transition() -> None:
    """A non-detection event type produces no update."""
    pb = _bootstrap_with_camera()
    updates = pb.process_events_ws_message(
        Mock(), _event("add", id="r1", type="ring", start=1000, device="cam1")
    ).model_updates
    assert updates == []


def test_eviction_emits_off_transition() -> None:
    """An open event evicted from the cache emits a flag-off update."""
    pb = _bootstrap_with_camera()
    pb.max_event_cache_size = 1
    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )

    # The ring event evicts the open motion event in the same frame.
    updates = pb.process_events_ws_message(
        Mock(), _event("add", id="r1", type="ring", start=1100, device="cam1")
    ).model_updates
    assert len(updates) == 1
    assert updates[0].new_obj is pb.cameras["cam1"]
    assert updates[0].changed_data == {"is_motion_detected": False}


def test_remove_frame_emits_off_transition() -> None:
    """A server ``remove`` frame for an open event emits a flag-off update."""
    pb = _bootstrap_with_camera()
    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )

    updates = pb.process_events_ws_message(
        Mock(), _event("remove", id="m1")
    ).model_updates
    assert len(updates) == 1
    assert updates[0].changed_data == {"is_motion_detected": False}


def test_drain_skips_camera_removed_after_snapshot() -> None:
    """A camera dropped from the cache after its pre-frame snapshot yields no update."""
    pb = _bootstrap_with_camera()
    # Snapshot a camera, then remove it before the post-frame diff runs.
    pb._detection_state_before["cam1"] = pb.cameras["cam1"]._detection_state()
    del pb.cameras["cam1"]

    assert pb._drain_detection_updates() == []


def test_transition_state_does_not_leak_across_frames() -> None:
    """A transition reported on one frame is not re-reported on the next."""
    pb = _bootstrap_with_camera()
    first = pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    ).model_updates
    assert first
    # Re-applying the same open motion event is a no-op flip — no fresh update.
    second = pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    ).model_updates
    assert second == []


def test_transition_isolated_to_affected_camera() -> None:
    """Only the camera owning the event reports an update."""
    pb = _bootstrap_with_two_cameras()
    updates = pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    ).model_updates
    assert len(updates) == 1
    assert updates[0].new_obj is pb.cameras["cam1"]


def test_net_transition_when_event_starts_and_evicts_same_frame() -> None:
    """A frame that nets out to no change (start then self-evict) emits nothing."""
    pb = _bootstrap_with_camera()
    pb.max_event_cache_size = 0
    updates = pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    ).model_updates
    assert pb.cameras["cam1"].is_motion_detected is False
    assert updates == []


def test_detection_state_memoized_until_mutation() -> None:
    """Repeated reads share one cached dict; each mutation yields a fresh object."""
    pb = _bootstrap_with_camera()
    cam = pb.cameras["cam1"]

    first = cam._detection_state()
    assert cam._detection_state() is first

    pb.process_events_ws_message(
        Mock(), _event("add", id="m1", type="motion", start=1000, device="cam1")
    )
    after_add = cam._detection_state()
    assert after_add is not first
    assert cam._detection_state() is after_add

    pb.process_events_ws_message(Mock(), _event("update", id="m1", end=2000))
    after_end = cam._detection_state()
    assert after_end is not after_add


def test_snapshot_stays_distinct_from_post_mutation_state() -> None:
    """A snapshot captured before a mutation is a distinct, unmutated object."""
    cam = PublicCamera.model_construct()
    before = cam._detection_state()

    cam._apply_detection_event(
        PublicEvent.model_construct(id="m1", type=EventType.MOTION, end=None)
    )
    after = cam._detection_state()

    assert after is not before
    assert before["is_motion_detected"] is False
    assert after["is_motion_detected"] is True
