"""Tests for path-traversal hardening in the backup CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from uiprotect.cli.backup import (
    BackupContext,
    Event,
    _safe_join,
    _safe_slug,
)


def _make_ctx(tmp_path: Path, **overrides: str) -> BackupContext:
    mock_protect = MagicMock()
    defaults = {
        "thumbnail_format": "{camera_slug}thumb.jpg",
        "gif_format": "{camera_slug}animated.gif",
        "event_format": "{camera_slug}video.mp4",
        "title_format": "{camera_name}",
    }
    defaults.update(overrides)
    return BackupContext(
        protect=mock_protect,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=None,
        output_format=MagicMock(),
        output=tmp_path,
        seperator="-",
        thumbnail_format=defaults["thumbnail_format"],
        gif_format=defaults["gif_format"],
        event_format=defaults["event_format"],
        title_format=defaults["title_format"],
        max_download=1,
        page_size=1,
        length_cutoff=None,  # type: ignore[arg-type]
    )


def _make_event(display_name: str) -> tuple[Event, MagicMock]:
    camera = MagicMock()
    camera.display_name = display_name
    event = Event(id="evt-1", camera_mac="aabbccddeeff", event_type="motion")
    event.start_naive = datetime(2024, 1, 1, tzinfo=UTC)
    event.end_naive = None
    return event, camera


def test_safe_slug_strips_traversal_characters() -> None:
    assert _safe_slug("../../etc/passwd", "-") == "etc-passwd"


def test_safe_slug_strips_leading_dots_and_seps() -> None:
    assert _safe_slug("./..//evil", "-") == "evil"


def test_safe_slug_empty_falls_back() -> None:
    assert _safe_slug("../../", "-") == "unknown"
    assert _safe_slug("", "-") == "unknown"


def test_safe_slug_keeps_safe_characters() -> None:
    assert _safe_slug("Front_Door-1.0", "-") == "Front_Door-1.0"


def test_safe_join_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _safe_join(tmp_path, "../etc/passwd")


def test_safe_join_rejects_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _safe_join(tmp_path, "/etc/passwd")


def test_safe_join_allows_paths_inside_base(tmp_path: Path) -> None:
    result = _safe_join(tmp_path, "sub/dir/file.jpg")
    assert result == (tmp_path / "sub/dir/file.jpg").resolve()


def test_file_context_sanitizes_traversal_in_camera_slug(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    event, camera = _make_event("../../etc/foo")
    ctx.protect.bootstrap.get_device_from_mac.return_value = camera

    context = event.get_file_context(ctx)

    assert ".." not in context["camera_slug"]
    assert "/" not in context["camera_slug"]


def test_file_context_preserves_raw_camera_name(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    event, camera = _make_event("Café Front Door")
    ctx.protect.bootstrap.get_device_from_mac.return_value = camera

    context = event.get_file_context(ctx)

    assert context["camera_name"] == "Café Front Door"


def test_thumbnail_path_stays_inside_output_for_malicious_name(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path)
    event, camera = _make_event("../../etc/foo")
    ctx.protect.bootstrap.get_device_from_mac.return_value = camera

    path = event.get_thumbnail_path(ctx)

    assert path.resolve().is_relative_to(tmp_path.resolve())


def test_gif_path_stays_inside_output_for_malicious_name(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    event, camera = _make_event("../../.ssh/authorized_keys")
    ctx.protect.bootstrap.get_device_from_mac.return_value = camera

    path = event.get_gif_path(ctx)

    assert path.resolve().is_relative_to(tmp_path.resolve())


def test_event_path_stays_inside_output_for_malicious_name(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path)
    event, camera = _make_event("/etc/passwd")
    ctx.protect.bootstrap.get_device_from_mac.return_value = camera

    path = event.get_event_path(ctx)

    assert path.resolve().is_relative_to(tmp_path.resolve())


def test_thumbnail_path_rejects_traversal_template(tmp_path: Path) -> None:
    ctx = _make_ctx(
        tmp_path,
        thumbnail_format="../../../etc/{camera_slug}thumb.jpg",
    )
    event, camera = _make_event("cam")
    ctx.protect.bootstrap.get_device_from_mac.return_value = camera

    with pytest.raises(ValueError):
        event.get_thumbnail_path(ctx)


def test_event_path_rejects_traversal_template(tmp_path: Path) -> None:
    ctx = _make_ctx(
        tmp_path,
        event_format="../../{camera_slug}video.mp4",
    )
    event, camera = _make_event("cam")
    ctx.protect.bootstrap.get_device_from_mac.return_value = camera

    with pytest.raises(ValueError):
        event.get_event_path(ctx)
