"""
Network-free unit tests for the spec-validation check functions.

Each test feeds a hand-built in-memory spec ``dict`` (never the 74 MB fetched
spec, absent in CI) to one check function and pins its ``(errors, warnings)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import orjson
import validate_spec  # local import via conftest sys.path insert
from validate_spec import (
    _leaf_model,
    _resolve_object_props,
    _spec_field_name,
    check_endpoints,
    check_enums,
    check_model_fields,
    check_required,
    format_summary,
    main,
    run_checks,
)

from uiprotect.data import PublicChime

if TYPE_CHECKING:
    import pytest


def _chime_spec(
    *,
    extra: str | None = None,
    drop: str | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal spec whose ``chime`` schema mirrors ``PublicChime`` fields."""
    fields = set(PublicChime.model_fields)
    if drop is not None:
        fields.discard(drop)
    props = {("modelKey" if f == "model" else f): {"type": "string"} for f in fields}
    if extra is not None:
        props[extra] = {"type": "string"}
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required is not None:
        schema["required"] = required
    return {"components": {"schemas": {"chime": schema}}}


# --------------------------------------------------------------------------- #
# check_endpoints
# --------------------------------------------------------------------------- #


def test_check_endpoints_all_covered() -> None:
    spec = {"paths": {"/v1/cameras": {"get": {}, "parameters": []}}}
    errors, warnings = check_endpoints(spec)
    assert errors == []
    assert warnings == []


def test_check_endpoints_new_endpoint_warns() -> None:
    spec = {"paths": {"/v1/teleporter": {"post": {}}}}
    errors, warnings = check_endpoints(spec)
    assert errors == []
    assert len(warnings) == 1
    assert "POST /v1/teleporter" in warnings[0]


# --------------------------------------------------------------------------- #
# check_model_fields
# --------------------------------------------------------------------------- #


def test_check_model_fields_all_green() -> None:
    errors, warnings = check_model_fields(_chime_spec())
    assert errors == []
    assert warnings == []


def test_check_model_fields_removed_field_errors() -> None:
    errors, warnings = check_model_fields(_chime_spec(drop="ring_settings"))
    assert any("ring_settings" in e for e in errors)
    assert warnings == []


def test_check_model_fields_added_field_warns() -> None:
    errors, warnings = check_model_fields(_chime_spec(extra="newServerField"))
    assert errors == []
    assert any("new_server_field" in w for w in warnings)


def test_check_model_fields_missing_schema_skipped() -> None:
    errors, warnings = check_model_fields({"components": {"schemas": {}}})
    assert errors == []
    assert warnings == []


def test_check_model_fields_non_object_schema_errors() -> None:
    spec = {"components": {"schemas": {"chime": {"type": "string"}}}}
    errors, _warnings = check_model_fields(spec)
    assert any("not object-shaped" in e for e in errors)


# --------------------------------------------------------------------------- #
# check_required
# --------------------------------------------------------------------------- #


def test_check_required_optional_field_warns() -> None:
    errors, warnings = check_required(_chime_spec(required=["name"]))
    assert errors == []
    assert any("name" in w for w in warnings)


def test_check_required_required_field_ok() -> None:
    errors, warnings = check_required(_chime_spec(required=["mac"]))
    assert errors == []
    assert warnings == []


def test_check_required_unknown_field_skipped() -> None:
    errors, warnings = check_required(_chime_spec(required=["notAModelField"]))
    assert errors == []
    assert warnings == []


def test_check_required_missing_schema_skipped() -> None:
    errors, warnings = check_required({"components": {"schemas": {}}})
    assert errors == []
    assert warnings == []


# --------------------------------------------------------------------------- #
# check_enums
# --------------------------------------------------------------------------- #


def test_check_enums_new_value_warns() -> None:
    spec = {
        "components": {
            "schemas": {"deviceState": {"enum": ["CONNECTED", "HIBERNATING"]}}
        }
    }
    errors, warnings = check_enums(spec)
    assert errors == []
    assert any("HIBERNATING" in w for w in warnings)


def test_check_enums_known_values_ok() -> None:
    spec = {
        "components": {
            "schemas": {
                "deviceState": {"enum": ["CONNECTED", "CONNECTING", "DISCONNECTED"]}
            }
        }
    }
    errors, warnings = check_enums(spec)
    assert errors == []
    assert warnings == []


def test_check_enums_missing_schema_skipped() -> None:
    errors, warnings = check_enums({"components": {"schemas": {}}})
    assert errors == []
    assert warnings == []


# --------------------------------------------------------------------------- #
# run_checks / format_summary / resolution helpers / main
# --------------------------------------------------------------------------- #


def test_run_checks_aggregates() -> None:
    spec = {
        "paths": {"/v1/teleporter": {"post": {}}},
        "components": {"schemas": _chime_spec()["components"]["schemas"]},
    }
    errors, warnings = run_checks(spec)
    assert errors == []
    assert any("teleporter" in w for w in warnings)


def test_format_summary_no_drift() -> None:
    out = format_summary([], [], version="7.1.77")
    assert "No drift" in out
    assert "7.1.77" in out


def test_format_summary_errors_and_warnings() -> None:
    out = format_summary(["boom"], ["heads up"])
    assert "Errors (1)" in out
    assert "Warnings (1)" in out
    assert "boom" in out
    assert "heads up" in out


def test_spec_field_name_remap() -> None:
    remaps = {"modelKey": "model"}
    assert _spec_field_name("modelKey", remaps) == "model"
    assert _spec_field_name("cameraIds", remaps) == "camera_ids"


def test_resolve_object_props_branches() -> None:
    schemas: dict[str, Any] = {
        "thing": {"type": "object", "properties": {"a": {"type": "string"}}},
    }
    assert _resolve_object_props({"$ref": "#/c/thing"}, schemas) == {
        "a": {"type": "string"}
    }
    assert _resolve_object_props(
        {"allOf": [{"$ref": "#/c/thing"}, {"type": "string"}]}, schemas
    ) == {"a": {"type": "string"}}
    assert _resolve_object_props({"allOf": [{"type": "string"}]}, schemas) is None
    assert _resolve_object_props(
        {"oneOf": [{"type": "string"}, {"$ref": "#/c/thing"}]}, schemas
    ) == {"a": {"type": "string"}}
    assert _resolve_object_props({"oneOf": [{"type": "string"}]}, schemas) is None
    assert _resolve_object_props(
        {"type": "array", "items": {"$ref": "#/c/thing"}}, schemas
    ) == {"a": {"type": "string"}}
    assert _resolve_object_props({"type": "string"}, schemas) is None


def test_leaf_model_unwraps_optional_and_list() -> None:
    assert _leaf_model(PublicChime) is PublicChime
    assert _leaf_model(list[PublicChime]) is PublicChime
    assert _leaf_model(PublicChime | None) is PublicChime
    assert _leaf_model(int) is None


def test_main_missing_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(validate_spec, "SPEC_PATH", tmp_path / "absent.json")
    assert main() == 2


def test_main_green_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    spec = _chime_spec()
    spec["info"] = {"version": "7.1.77"}
    spec_file = tmp_path / "spec.json"
    spec_file.write_bytes(orjson.dumps(spec))
    monkeypatch.setattr(validate_spec, "SPEC_PATH", spec_file)
    assert main() == 0
    assert "7.1.77" in capsys.readouterr().out


def test_main_error_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    spec = _chime_spec(drop="ring_settings")
    spec_file = tmp_path / "spec.json"
    spec_file.write_bytes(orjson.dumps(spec))
    monkeypatch.setattr(validate_spec, "SPEC_PATH", spec_file)
    assert main() == 1
    assert "ring_settings" in capsys.readouterr().out
