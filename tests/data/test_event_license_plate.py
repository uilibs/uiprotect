# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr, arg-type"

from __future__ import annotations

from typing import TYPE_CHECKING

from uiprotect.data.nvr import (
    Event,
    EventDetectedThumbnail,
    EventMetadata,
    EventThumbnailGroup,
    LicensePlateMetadata,
)
from uiprotect.data.types import SmartDetectObjectType

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient


def test_event_license_plate_from_sample_data(
    raw_events: list[dict], protect_client: ProtectApiClient
):
    lpr_events = [
        e
        for e in raw_events
        if SmartDetectObjectType.LICENSE_PLATE.value in e.get("smartDetectTypes", [])
    ]

    if not lpr_events:
        return  # Skip if no LPR events in sample data

    # Parse first LPR event
    event = Event.from_unifi_dict(**lpr_events[0], api=protect_client)

    # Should extract license plate from detectedThumbnails
    assert len(event.license_plates) > 0
    assert isinstance(event.license_plates[0], str)
    assert len(event.license_plates[0]) > 0


def test_event_face_not_returned_as_license_plate(
    raw_events: list[dict], protect_client: ProtectApiClient
):
    face_events = [
        e
        for e in raw_events
        if SmartDetectObjectType.FACE.value in e.get("smartDetectTypes", [])
        and SmartDetectObjectType.LICENSE_PLATE.value
        not in e.get("smartDetectTypes", [])
    ]

    if not face_events:
        return  # Skip if no face events in sample data

    # Parse first face event
    event = Event.from_unifi_dict(**face_events[0], api=protect_client)

    # Should NOT return face name as license plate
    assert event.license_plates == []


def test_event_face_name_from_sample_data(
    raw_events: list[dict], protect_client: ProtectApiClient
):
    face_events = [
        e
        for e in raw_events
        if SmartDetectObjectType.FACE.value in e.get("smartDetectTypes", [])
    ]

    # Find face event with matched name
    face_event_with_name = None
    for e in face_events:
        if e.get("metadata", {}).get("detectedThumbnails"):
            for thumb in e["metadata"]["detectedThumbnails"]:
                if thumb.get("type") == "face" and thumb.get("group", {}).get(
                    "matchedName"
                ):
                    face_event_with_name = e
                    break
        if face_event_with_name:
            break

    if not face_event_with_name:
        return  # Skip if no face events with matched name

    # Parse face event
    event = Event.from_unifi_dict(**face_event_with_name, api=protect_client)

    # Should extract face name from detectedThumbnails
    assert len(event.face_names) > 0
    assert isinstance(event.face_names[0], str)
    assert len(event.face_names[0]) > 0


def test_event_license_plate_legacy_format():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            license_plate=LicensePlateMetadata.model_construct(
                name="ABC123",
                confidence_level=85,
            )
        ),
    )

    assert event.license_plates == ["ABC123"]


def test_event_license_plate_new_format():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="XYZ789",
                        confidence=92,
                    ),
                )
            ]
        ),
    )

    assert event.license_plates == ["XYZ789"]


def test_event_license_plate_legacy_fallback():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            license_plate=LicensePlateMetadata.model_construct(
                name="LEGACY",
                confidence_level=85,
            ),
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="NEWER",
                        confidence=92,
                    ),
                )
            ],
        ),
    )

    assert event.license_plates == ["LEGACY", "NEWER"]


def test_event_license_plate_no_lpr_in_smart_detect_types():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.PERSON],  # No LICENSE_PLATE
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="ABC123",
                        confidence=92,
                    ),
                )
            ]
        ),
    )

    # Should return empty list because LICENSE_PLATE not in smart_detect_types
    assert event.license_plates == []


def test_event_license_plate_face_recognition_not_returned():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.FACE],  # Face, not LPR
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="John Doe",
                        confidence=90,
                    ),
                )
            ]
        ),
    )

    # Should return empty list because it's a face event, not LPR
    assert event.license_plates == []


def test_event_license_plate_mixed_event_types():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[
            SmartDetectObjectType.PERSON,
            SmartDetectObjectType.LICENSE_PLATE,
            SmartDetectObjectType.FACE,
        ],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="person",
                    cropped_id="thumb_1",
                ),
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_2",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="LPR123",
                        confidence=88,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_3",
                    group=EventThumbnailGroup.model_construct(
                        id="group_2",
                        matched_name="Jane Doe",
                        confidence=85,
                    ),
                ),
            ]
        ),
    )

    # Both properties should work independently
    assert event.license_plates == ["LPR123"]
    assert event.face_names == ["Jane Doe"]


def test_event_license_plate_no_matched_name():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name=None,  # Unrecognized plate
                        confidence=60,
                    ),
                )
            ]
        ),
    )

    assert event.license_plates == []


def test_event_license_plate_no_metadata():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=None,
    )

    assert event.license_plates == []


def test_event_license_plate_no_detected_thumbnails():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=None,
        ),
    )

    assert event.license_plates == []


def test_event_license_plate_empty_detected_thumbnails():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[],
        ),
    )

    assert event.license_plates == []


def test_event_license_plate_vehicle_without_group():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=None,  # No group
                )
            ]
        ),
    )

    assert event.license_plates == []


def test_event_face_name_basic():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.FACE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="John Doe",
                        confidence=90,
                    ),
                )
            ]
        ),
    )

    assert event.face_names == ["John Doe"]


def test_event_face_name_no_face_in_smart_detect_types():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.PERSON],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="John Doe",
                        confidence=90,
                    ),
                )
            ]
        ),
    )

    assert event.face_names == []


def test_event_face_name_unknown_face():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.FACE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name=None,
                        confidence=60,
                    ),
                )
            ]
        ),
    )

    assert event.face_names == []


def test_event_face_name_license_plate_not_returned():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[
            SmartDetectObjectType.LICENSE_PLATE,
            SmartDetectObjectType.FACE,
        ],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="ABC123",
                        confidence=92,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_2",
                    group=EventThumbnailGroup.model_construct(
                        id="group_2",
                        matched_name="Jane Doe",
                        confidence=85,
                    ),
                ),
            ]
        ),
    )

    assert event.face_names == ["Jane Doe"]
    assert event.license_plates == ["ABC123"]


def test_event_face_names_multiple():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.FACE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="Alice Smith",
                        confidence=95,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_2",
                    group=EventThumbnailGroup.model_construct(
                        id="group_2",
                        matched_name="Bob Jones",
                        confidence=88,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_3",
                    group=EventThumbnailGroup.model_construct(
                        id="group_3",
                        matched_name=None,
                        confidence=70,
                    ),
                ),
            ]
        ),
    )

    assert event.face_names == ["Alice Smith", "Bob Jones"]


def test_event_face_names_empty():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.PERSON],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="person",
                    cropped_id="thumb_1",
                )
            ]
        ),
    )

    assert event.face_names == []


def test_event_license_plates_multiple():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="ABC123",
                        confidence=95,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_2",
                    group=EventThumbnailGroup.model_construct(
                        id="group_2",
                        matched_name="XYZ789",
                        confidence=88,
                    ),
                ),
            ]
        ),
    )

    assert event.license_plates == ["ABC123", "XYZ789"]


def test_event_license_plates_legacy_and_new():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            license_plate=LicensePlateMetadata.model_construct(
                name="LEGACY1",
                confidence_level=85,
            ),
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="NEW123",
                        confidence=92,
                    ),
                )
            ],
        ),
    )

    assert event.license_plates == ["LEGACY1", "NEW123"]


def test_event_license_plates_empty():
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.VEHICLE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                )
            ]
        ),
    )

    assert event.license_plates == []
