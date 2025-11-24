# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr, arg-type"

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from uiprotect.data.nvr import (
    Event,
    EventDetectedThumbnail,
    EventMetadata,
    EventThumbnailGroup,
)
from uiprotect.data.types import SmartDetectObjectType

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient


def test_get_detected_thumbnail_with_clock_best_wall(
    protect_client: ProtectApiClient,
):
    """Test that get_detected_thumbnail returns the thumbnail with clockBestWall."""
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    clock_best_wall=None,
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="ABC123",
                        confidence=75,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_2",
                    clock_best_wall=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    group=EventThumbnailGroup.model_construct(
                        id="group_2",
                        matched_name="XYZ789",
                        confidence=92,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_3",
                    clock_best_wall=None,
                    group=EventThumbnailGroup.model_construct(
                        id="group_3",
                        matched_name="DEF456",
                        confidence=85,
                    ),
                ),
            ]
        ),
    )

    thumbnail = event.get_detected_thumbnail()
    assert thumbnail is not None
    assert thumbnail.cropped_id == "thumb_2"
    assert thumbnail.group is not None
    assert thumbnail.group.matched_name == "XYZ789"


def test_get_detected_thumbnail_no_metadata():
    """Test that get_detected_thumbnail returns None when no metadata."""
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=None,
    )

    assert event.get_detected_thumbnail() is None


def test_get_detected_thumbnail_no_detected_thumbnails():
    """Test that get_detected_thumbnail returns None when no detected thumbnails."""
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=None,
        ),
    )

    assert event.get_detected_thumbnail() is None


def test_get_detected_thumbnail_empty_list():
    """Test that get_detected_thumbnail returns None when detected thumbnails is empty."""
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[],
        ),
    )

    assert event.get_detected_thumbnail() is None


def test_get_detected_thumbnail_no_clock_best_wall():
    """Test that get_detected_thumbnail returns None when no thumbnail has clockBestWall."""
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.LICENSE_PLATE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_1",
                    clock_best_wall=None,
                ),
                EventDetectedThumbnail.model_construct(
                    type="vehicle",
                    cropped_id="thumb_2",
                    clock_best_wall=None,
                ),
            ]
        ),
    )

    assert event.get_detected_thumbnail() is None


def test_get_detected_thumbnail_first_with_clock_best_wall():
    """Test that get_detected_thumbnail returns first thumbnail with clockBestWall."""
    event = Event.model_construct(
        id="test_event",
        type="smartDetect",
        smart_detect_types=[SmartDetectObjectType.FACE],
        metadata=EventMetadata.model_construct(
            detected_thumbnails=[
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_1",
                    clock_best_wall=None,
                ),
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_2",
                    clock_best_wall=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    group=EventThumbnailGroup.model_construct(
                        id="group_1",
                        matched_name="Alice",
                        confidence=90,
                    ),
                ),
                EventDetectedThumbnail.model_construct(
                    type="face",
                    cropped_id="thumb_3",
                    clock_best_wall=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
                    group=EventThumbnailGroup.model_construct(
                        id="group_2",
                        matched_name="Bob",
                        confidence=95,
                    ),
                ),
            ]
        ),
    )

    thumbnail = event.get_detected_thumbnail()
    assert thumbnail is not None
    assert thumbnail.cropped_id == "thumb_2"
    assert thumbnail.group is not None
    assert thumbnail.group.matched_name == "Alice"


def test_get_detected_thumbnail_from_real_data(
    raw_events: list[dict], protect_client: ProtectApiClient
):
    """Test get_detected_thumbnail with real event data."""
    events_with_thumbs = [
        e for e in raw_events if e.get("metadata", {}).get("detectedThumbnails")
    ]

    if not events_with_thumbs:
        return  # Skip if no events with thumbnails

    # Parse first event with thumbnails
    event = Event.from_unifi_dict(**events_with_thumbs[0], api=protect_client)

    # Should return the thumbnail with clockBestWall
    thumbnail = event.get_detected_thumbnail()
    assert thumbnail is not None
    assert thumbnail.clock_best_wall is not None


def test_event_thumbnail_attributes_get_value(
    raw_events: list[dict], protect_client: ProtectApiClient
):
    """Test EventThumbnailAttributes.get_value() helper method."""
    events_with_attrs = [
        e
        for e in raw_events
        if any(
            t.get("attributes")
            for t in e.get("metadata", {}).get("detectedThumbnails", [])
        )
    ]

    if not events_with_attrs:
        return  # Skip if no events with attributes

    event = Event.from_unifi_dict(**events_with_attrs[0], api=protect_client)
    thumbnail = event.get_detected_thumbnail()

    assert thumbnail is not None
    assert thumbnail.attributes is not None

    # Test get_value with EventThumbnailAttribute objects
    # Check if color exists (common for LPR events)
    if hasattr(thumbnail.attributes, "color"):
        color = thumbnail.attributes.get_value("color")
        assert color is not None
        assert isinstance(color, str)

    # Check if vehicleType exists (common for LPR events)
    if hasattr(thumbnail.attributes, "vehicleType"):
        vehicle_type = thumbnail.attributes.get_value("vehicleType")
        assert vehicle_type is not None
        assert isinstance(vehicle_type, str)

    # Test get_value with non-EventThumbnailAttribute fields
    # zone is list[int], not EventThumbnailAttribute
    if hasattr(thumbnail.attributes, "zone"):
        zone_value = thumbnail.attributes.get_value("zone")
        assert zone_value is None  # Should be None because it's not EventThumbnailAttribute

    # Test get_value with non-existent field
    nonexistent = thumbnail.attributes.get_value("nonexistent_field_12345")
    assert nonexistent is None
