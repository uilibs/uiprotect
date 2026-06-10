"""Tests for the private-API removal-candidate finder (network-free)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from uiprotect._superseded import SupersededMethod

_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "find_removable_private_api.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("_find_removable", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_removable_when_zero_references():
    records = [
        SupersededMethod(
            "Chime", "set_volume", "set_volume_for_camera_public", "12.2.0"
        )
    ]
    results = mod.find_removable(records, lambda _name: (0, []))
    assert len(results) == 1
    assert results[0].removable is True
    assert results[0].ha_references == 0


def test_not_removable_when_references_remain():
    records = [
        SupersededMethod(
            "Chime", "set_volume", "set_volume_for_camera_public", "12.2.0"
        )
    ]
    results = mod.find_removable(records, lambda _name: (3, ["http://example/x"]))
    assert results[0].removable is False
    assert results[0].ha_references == 3


def test_private_to_private_replacement_is_skipped():
    records = [SupersededMethod("Camera", "set_hdr", "set_hdr_mode", "3.0.0")]
    results = mod.find_removable(records, lambda _name: (0, []))
    assert results == []


def test_search_error_fails_safe():
    def boom(_name: str):
        raise RuntimeError("rate limited")

    records = [
        SupersededMethod(
            "Chime", "set_volume", "set_volume_for_camera_public", "12.2.0"
        )
    ]
    results = mod.find_removable(records, boom)
    assert results[0].removable is False
    assert results[0].error == "rate limited"
    assert results[0].ha_references == -1


def test_render_report_marks_safe_and_includes_query():
    records = [
        SupersededMethod(
            "Chime", "set_volume", "set_volume_for_camera_public", "12.2.0"
        )
    ]
    report = mod.render_report(mod.find_removable(records, lambda _name: (0, [])))
    assert "safe to remove" in report
    assert "`set_volume`" in report
    assert ".set_volume(" in report


def test_render_report_no_removable():
    records = [
        SupersededMethod(
            "Chime", "set_volume", "set_volume_for_camera_public", "12.2.0"
        )
    ]
    report = mod.render_report(mod.find_removable(records, lambda _name: (2, [])))
    assert "No symbols are currently safe to remove." in report


def test_gh_code_search_parses_payload():
    completed = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": '{"total_count": 1, "items": [{"html_url": "http://x"}]}',
            "stderr": "",
        },
    )()
    with patch.object(mod.subprocess, "run", return_value=completed):
        count, urls = mod.gh_code_search("set_volume")
    assert count == 1
    assert urls == ["http://x"]


def test_gh_code_search_raises_on_failure():
    completed = type("P", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
    with (
        patch.object(mod.subprocess, "run", return_value=completed),
        pytest.raises(RuntimeError, match="gh code search failed"),
    ):
        mod.gh_code_search("set_volume")


def test_main_dispatch_exit_codes():
    records = [
        SupersededMethod(
            "Chime", "set_volume", "set_volume_for_camera_public", "12.2.0"
        )
    ]
    with (
        patch.object(
            mod,
            "find_removable",
            return_value=mod.find_removable(records, lambda _n: (0, [])),
        ),
        patch.object(mod.time, "sleep"),
        patch.object(mod, "gh_code_search", return_value=(0, [])),
    ):
        assert mod.main(["--sleep", "0"]) == 1
    with (
        patch.object(
            mod,
            "find_removable",
            return_value=mod.find_removable(records, lambda _n: (5, [])),
        ),
        patch.object(mod.time, "sleep"),
        patch.object(mod, "gh_code_search", return_value=(5, [])),
    ):
        assert mod.main(["--sleep", "0"]) == 0
