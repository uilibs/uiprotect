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
    _ENUM_COVERAGE_WAIVERS,
    _EXAMPLE_CALLS,
    _MODELLED_AS_SUBSET,
    _inbound_enum_ids,
    _iter_spec_consts,
    _iter_spec_enums,
    _leaf_model,
    _library_enums_by_name,
    _normalize_path,
    _public_api_coroutines,
    _resolve_const,
    _resolve_object_props,
    _spec_field_name,
    check_completeness,
    check_endpoints,
    check_enum_coverage,
    check_enums,
    check_event_types,
    check_model_fields,
    covered_endpoints,
    format_summary,
    main,
    run_checks,
)

from uiprotect._public_api import registry
from uiprotect.api import ProtectApiClient
from uiprotect.data import PUBLIC_EVENT_TYPES, PublicChime

if TYPE_CHECKING:
    import pytest


def _model_props(cls: Any, name: str) -> dict[str, dict[str, Any]]:
    """Build green spec ``properties`` for one tracked model schema."""
    inv = {v: k for k, v in cls._get_unifi_remaps().items()}
    owned = validate_spec._LIBRARY_OWNED_FIELDS.get(name, set())
    return {
        inv.get(f, f): {"type": "string"} for f in cls.model_fields if f not in owned
    }


def _event_union(props: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the ``event`` ``oneOf``: one variant per modelled public event type."""
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {**props, "type": {"type": "string", "const": value}},
            }
            for value in sorted(event_type.value for event_type in PUBLIC_EVENT_TYPES)
        ]
    }


def _chime_spec(
    *,
    extra: str | None = None,
    drop: str | None = None,
) -> dict[str, Any]:
    """Build a full green spec; ``extra``/``drop`` perturb only the ``chime`` schema."""
    schemas: dict[str, Any] = {}
    for cls, name in validate_spec._MODEL_SCHEMAS:
        props = _model_props(cls, name)
        if name == "chime":
            if drop is not None:
                props.pop(drop, None)
            if extra is not None:
                props[extra] = {"type": "string"}
        if name == "event":
            schemas[name] = _event_union(props)
            continue
        schemas[name] = {"type": "object", "properties": props}
    for enum_cls, name in validate_spec._ENUM_SCHEMAS:
        schemas[name] = {"enum": [m.value for m in enum_cls]}
    return {"components": {"schemas": schemas}}


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


def test_check_endpoints_parametrized_path_normalized() -> None:
    """A declarative endpoint covers the spec path despite differing param names."""
    # Registry template is ``/v1/cameras/{camera_id}``; spec uses ``{id}``.
    spec = {"paths": {"/v1/cameras/{id}": {"get": {}, "patch": {}}}}
    errors, warnings = check_endpoints(spec)
    assert errors == []
    assert warnings == []


def test_check_endpoints_recorded_exception_method_covers() -> None:
    """A hand-written (non-declarative) method's path is covered via its example call."""
    # ``update_camera_public`` is not decorated; the alarm-hub alias GET is only
    # reachable through a recorded example call, never the registry.
    spec = {"paths": {"/v1/alarm-hubs/{id}": {"get": {}}}}
    errors, warnings = check_endpoints(spec)
    assert errors == []
    assert warnings == []


def test_check_endpoints_subscribe_paths_covered() -> None:
    spec = {
        "paths": {
            "/v1/subscribe/events": {"get": {}},
            "/v1/subscribe/devices": {"get": {}},
        }
    }
    _errors, warnings = check_endpoints(spec)
    assert warnings == []


# --------------------------------------------------------------------------- #
# Derived coverage: normalization, completeness, example-call table
# --------------------------------------------------------------------------- #


def test_normalize_path_collapses_params_and_sentinel() -> None:
    assert _normalize_path("/v1/cameras/{camera_id}") == "/v1/cameras/{}"
    assert _normalize_path("/v1/cameras/{id}/snapshot") == "/v1/cameras/{}/snapshot"
    assert (
        _normalize_path(f"/v1/files/{validate_spec._RECORD_SENTINEL}") == "/v1/files/{}"
    )


def test_covered_endpoints_union_sources() -> None:
    covered = covered_endpoints()
    # Declarative (registry), recorded example call, and websocket subscription.
    assert ("GET", "/v1/cameras/{}") in covered
    assert ("PATCH", "/v1/cameras/{}") in covered  # update_camera_public (recorded)
    assert ("GET", "/v1/alarm-hubs/{}") in covered  # get_alarm_hub_public (recorded)
    assert ("GET", "/v1/subscribe/events") in covered
    assert ("GET", "/v1/subscribe/devices") in covered


def test_example_calls_match_nondeclarative_coroutines() -> None:
    """The example-call table is exactly the set of non-declarative public coroutines."""
    declarative = set(registry.for_class(ProtectApiClient.__name__).values())
    expected = _public_api_coroutines() - declarative
    assert set(_EXAMPLE_CALLS) == expected


def test_check_completeness_clean() -> None:
    assert check_completeness() == []


def test_check_completeness_flags_unwired_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping an example call for a non-declarative coroutine surfaces a gap."""
    trimmed = dict(_EXAMPLE_CALLS)
    trimmed.pop("update_camera_public")
    monkeypatch.setattr(validate_spec, "_EXAMPLE_CALLS", trimmed)
    errors = check_completeness()
    assert any("update_camera_public" in e for e in errors)


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


def test_check_model_fields_missing_schema_errors() -> None:
    errors, _warnings = check_model_fields({"components": {"schemas": {}}})
    assert any("tracked schema absent from spec" in e for e in errors)


def test_check_model_fields_non_object_schema_errors() -> None:
    spec = {"components": {"schemas": {"chime": {"type": "string"}}}}
    errors, _warnings = check_model_fields(spec)
    assert any("not object-shaped" in e for e in errors)


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


def test_check_enums_missing_schema_errors() -> None:
    errors, _warnings = check_enums({"components": {"schemas": {}}})
    assert any("tracked schema absent from spec" in e for e in errors)


def test_check_enums_non_enum_schema_errors() -> None:
    spec = {"components": {"schemas": {"deviceState": {"type": "string"}}}}
    errors, _warnings = check_enums(spec)
    assert any("no longer declares `enum`" in e for e in errors)


# --------------------------------------------------------------------------- #
# check_enum_coverage (exact-match + inbound/outbound classification)
# --------------------------------------------------------------------------- #


def _response_spec(schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a component schema and reference it from a GET response (inbound)."""
    return {
        "components": {"schemas": {schema_name: schema}},
        "paths": {
            "/v1/things": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": f"#/components/schemas/{schema_name}"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
    }


def test_iter_spec_enums_collects_named_and_inline() -> None:
    spec = {
        "components": {
            "schemas": {
                "deviceState": {"enum": ["CONNECTED"]},
                "someEvent": {
                    "properties": {
                        "metadata": {
                            "properties": {"text": {"enum": ["zorp", "unknown"]}}
                        }
                    }
                },
            }
        },
        "paths": {
            "/v1/widgets": {"get": {"parameters": [{"schema": {"enum": ["quux"]}}]}}
        },
    }
    found = dict(_iter_spec_enums(spec))
    assert frozenset({"zorp"}) in found  # ``unknown`` stripped
    assert frozenset({"CONNECTED"}) in found
    assert frozenset({"quux"}) in found  # reached through the list branch
    assert found[frozenset({"zorp"})].endswith("metadata.properties.text")


def test_iter_spec_enums_records_each_owning_schema() -> None:
    """The same value-set under two schemas yields one occurrence per schema."""
    spec = {
        "components": {
            "schemas": {
                "alpha": {"properties": {"s": {"enum": ["zorp"]}}},
                "beta": {"properties": {"s": {"enum": ["zorp"]}}},
            }
        }
    }
    owners = {
        validate_spec._enum_owner(path)
        for value_set, path in _iter_spec_enums(spec)
        if value_set == frozenset({"zorp"})
    }
    assert owners == {"alpha", "beta"}


def test_library_enums_by_name_excludes_sentinel() -> None:
    by_name = _library_enums_by_name()
    assert by_name["DeviceState"] == frozenset(
        {"CONNECTED", "CONNECTING", "DISCONNECTED"}
    )
    assert all("unknown" not in value_set for value_set in by_name.values())


def test_check_enum_coverage_exact_match_passes() -> None:
    """A spec enum whose value-set exactly equals a library enum raises nothing."""
    spec = _response_spec(
        "deviceState", {"enum": ["CONNECTED", "CONNECTING", "DISCONNECTED"]}
    )
    assert check_enum_coverage(spec) == ([], [])


def test_check_enum_coverage_subset_collision_flagged() -> None:
    """A value-set that is a coincidental subset of a larger enum is NOT covered."""
    # ``{high}`` is a subset of several library enums (ChannelQuality, LowMedHigh,
    # …) yet equals none of them; exact-match must reject it rather than treat the
    # collision as coverage. It carries no waiver, so the error is unambiguous.
    spec = _response_spec("thing", {"enum": ["high"]})
    errors, warnings = check_enum_coverage(spec)
    assert warnings == []
    assert len(errors) == 1
    assert "['high']" in errors[0]


def test_check_enum_coverage_modelled_as_subset_passes() -> None:
    """A spec enum pinned in ``_MODELLED_AS_SUBSET`` to a superset enum passes."""
    video = next(k for k, v in _MODELLED_AS_SUBSET.items() if v == "VideoMode")
    spec = _response_spec("videoMode", {"enum": sorted(video)})
    assert check_enum_coverage(spec) == ([], [])


def test_check_enum_coverage_mapping_target_shrunk_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pinned lib enum that lost its members (or was renamed) re-surfaces."""
    video = next(k for k, v in _MODELLED_AS_SUBSET.items() if v == "VideoMode")
    monkeypatch.setattr(
        validate_spec, "_library_enums_by_name", lambda: {"VideoMode": frozenset()}
    )
    spec = _response_spec("videoMode", {"enum": sorted(video)})
    errors, warnings = check_enum_coverage(spec)
    assert warnings == []
    assert len(errors) == 1
    assert "enum renamed or members removed" in errors[0]


def test_check_enum_coverage_inbound_unmodelled_flagged() -> None:
    spec = _response_spec(
        "weirdEvent",
        {
            "properties": {
                "metadata": {"properties": {"text": {"enum": ["frob", "baz"]}}}
            }
        },
    )
    errors, warnings = check_enum_coverage(spec)
    assert warnings == []
    assert len(errors) == 1
    assert "frob" in errors[0]
    assert "metadata.properties.text" in errors[0]


def test_check_enum_coverage_outbound_only_not_flagged() -> None:
    """An unmodelled enum reachable only from a request param is waived by direction."""
    spec = {
        "components": {"schemas": {}},
        "paths": {
            "/v1/things": {
                "get": {"parameters": [{"schema": {"enum": ["onlyrequest"]}}]}
            }
        },
    }
    assert check_enum_coverage(spec) == ([], [])


def test_check_enum_coverage_waiver_respected() -> None:
    owner, waived = next(iter(_ENUM_COVERAGE_WAIVERS))
    spec = _response_spec(owner, {"enum": sorted(waived)})
    assert check_enum_coverage(spec) == ([], [])


def test_check_enum_coverage_waiver_does_not_travel_to_another_schema() -> None:
    """A waived value-set on a different owning schema is still flagged."""
    _owner, waived = next(iter(_ENUM_COVERAGE_WAIVERS))
    spec = _response_spec("someOtherSchema", {"enum": sorted(waived)})
    errors, warnings = check_enum_coverage(spec)
    assert warnings == []
    assert len(errors) == 1
    assert "someOtherSchema" in errors[0]


def test_check_enum_coverage_sentinel_only_ignored() -> None:
    spec = _response_spec("thing", {"enum": ["unknown"]})
    assert check_enum_coverage(spec) == ([], [])


def test_inbound_enum_ids_exclude_request_only() -> None:
    """Response-reachable enums are inbound; request-only enums are not."""
    spec = {
        "components": {"schemas": {"resp": {"properties": {"s": {"enum": ["inb"]}}}}},
        "paths": {
            "/v1/things": {
                "post": {
                    "parameters": [{"schema": {"enum": ["outb"]}}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/resp"}
                                }
                            }
                        }
                    },
                }
            }
        },
    }
    inbound = _inbound_enum_ids(spec)
    assert ("resp", frozenset({"inb"})) in inbound
    assert not any(value_set == frozenset({"outb"}) for _owner, value_set in inbound)


def test_check_enum_coverage_outbound_sharing_a_waived_value_set_not_flagged() -> None:
    """An outbound enum whose values collide with a waived inbound one stays waived."""
    owner, waived = next(iter(_ENUM_COVERAGE_WAIVERS))
    spec = _response_spec(owner, {"enum": sorted(waived)})
    spec["paths"]["/v1/things"]["get"]["parameters"] = [
        {"schema": {"enum": sorted(waived)}}
    ]
    assert check_enum_coverage(spec) == ([], [])


def test_check_enum_coverage_component_responses_flagged() -> None:
    spec = _response_spec("thing", {"enum": ["unknown"]})
    spec["components"]["responses"] = {"Thing": {"description": "reused"}}
    errors, warnings = check_enum_coverage(spec)
    assert warnings == []
    assert errors == [
        (
            "spec declares `components.responses`; the inbound enum "
            "classification does not cover reusable responses"
        )
    ]


def test_check_enum_coverage_response_ref_flagged() -> None:
    spec = _response_spec("thing", {"enum": ["unknown"]})
    spec["paths"]["/v1/things"]["get"]["responses"]["200"] = {
        "$ref": "#/components/responses/Thing"
    }
    errors, warnings = check_enum_coverage(spec)
    assert warnings == []
    assert len(errors) == 1
    assert "paths./v1/things.get.responses.200" in errors[0]
    assert "does not cover reusable responses" in errors[0]


# --------------------------------------------------------------------------- #
# const coverage
# --------------------------------------------------------------------------- #


def test_iter_spec_consts_collects_string_consts_only() -> None:
    """String consts are collected per owning schema; numeric consts are skipped."""
    spec = {
        "components": {
            "schemas": {
                "eventModelKey": {"type": "string", "const": "event"},
                "sirenDuration": {"anyOf": [{"type": "number", "const": 5000}]},
            }
        }
    }
    found = dict(_iter_spec_consts(spec))
    assert frozenset({"event"}) in found
    assert not any("5000" in value_set for value_set in found)


def test_check_enum_coverage_const_defined_by_library_enum_passes() -> None:
    """A const whose value some library enum defines needs no exact match."""
    spec = _response_spec("cameraModelKey", {"type": "string", "const": "camera"})
    assert check_enum_coverage(spec) == ([], [])


def test_check_enum_coverage_unmodelled_inbound_const_flagged() -> None:
    spec = _response_spec(
        "teleporterModelKey", {"type": "string", "const": "teleporter"}
    )
    errors, warnings = check_enum_coverage(spec)
    assert warnings == []
    assert len(errors) == 1
    assert "'teleporter'" in errors[0]
    assert "teleporterModelKey" in errors[0]


def test_check_enum_coverage_outbound_only_const_not_flagged() -> None:
    """An unmodelled const reachable only from a request param is waived by direction."""
    spec = {
        "components": {"schemas": {}},
        "paths": {
            "/v1/things": {
                "get": {"parameters": [{"schema": {"const": "onlyrequest"}}]}
            }
        },
    }
    assert check_enum_coverage(spec) == ([], [])


def test_check_enum_coverage_const_waiver_respected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        _ENUM_COVERAGE_WAIVERS, ("teleporter", frozenset({"teleporter"})), "deferred"
    )
    spec = _response_spec("teleporter", {"type": "string", "const": "teleporter"})
    assert check_enum_coverage(spec) == ([], [])


# --------------------------------------------------------------------------- #
# check_event_types
# --------------------------------------------------------------------------- #


def _event_spec(**overrides: Any) -> dict[str, Any]:
    """Green ``event`` union spec, optionally overriding the ``event`` schema."""
    schema = overrides.pop("event", _event_union({}))
    return {"components": {"schemas": {"event": schema, **overrides}}}


def test_check_event_types_green() -> None:
    assert check_event_types(_event_spec()) == ([], [])


def test_check_event_types_spec_type_not_modelled() -> None:
    spec = _event_spec()
    spec["components"]["schemas"]["event"]["oneOf"].append(
        {
            "type": "object",
            "properties": {"type": {"type": "string", "const": "teleport"}},
        }
    )
    errors, warnings = check_event_types(spec)
    assert warnings == []
    assert errors == [
        "event: spec event type `teleport` is absent from `PUBLIC_EVENT_TYPES`"
    ]


def test_check_event_types_modelled_type_absent_from_spec() -> None:
    spec = _event_spec()
    dropped = spec["components"]["schemas"]["event"]["oneOf"].pop()
    missing = dropped["properties"]["type"]["const"]
    errors, _warnings = check_event_types(spec)
    assert len(errors) == 1
    assert f"`PUBLIC_EVENT_TYPES` models `{missing}`" in errors[0]


def test_resolve_const_follows_ref_and_all_of() -> None:
    schemas: dict[str, Any] = {"ringType": {"type": "string", "const": "ring"}}
    assert _resolve_const({"$ref": "#/c/ringType"}, schemas) == "ring"
    assert _resolve_const(
        {"allOf": [{"type": "string"}, {"const": "ring"}]}, schemas
    ) == ("ring")
    assert _resolve_const({"allOf": [{"type": "string"}]}, schemas) is None
    assert _resolve_const({"const": 5000}, schemas) is None
    assert _resolve_const({"$ref": "#/c/absent"}, schemas) is None


def test_check_event_types_resolves_referenced_type_const() -> None:
    """A variant whose ``type`` discriminator is behind a ``$ref`` still resolves."""
    value = sorted(event_type.value for event_type in PUBLIC_EVENT_TYPES)[0]
    spec = {
        "components": {
            "schemas": {
                "event": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {"$ref": "#/components/schemas/ringType"}
                            },
                        }
                    ]
                },
                "ringType": {"type": "string", "const": value},
            }
        }
    }
    errors, _warnings = check_event_types(spec)
    assert not any("declares no `type` const" in e for e in errors)


def test_check_event_types_missing_schema() -> None:
    errors, _warnings = check_event_types({"components": {"schemas": {}}})
    assert errors == ["event: tracked schema absent from spec (server removed it)"]


def test_check_event_types_not_a_union() -> None:
    errors, _warnings = check_event_types(_event_spec(event={"type": "object"}))
    assert errors == ["event: spec schema no longer declares a `oneOf` union"]


def test_check_event_types_variant_without_const() -> None:
    spec = _event_spec(event={"oneOf": [{"type": "object", "properties": {}}]})
    errors, _warnings = check_event_types(spec)
    assert any("declares no `type` const" in e for e in errors)


def test_check_model_fields_event_union_merges_variants() -> None:
    """A field only some variants carry still covers the model; dropping it errors."""
    errors, warnings = check_model_fields(_chime_spec())
    assert (errors, warnings) == ([], [])

    dropped = _chime_spec()
    for variant in dropped["components"]["schemas"]["event"]["oneOf"]:
        variant["properties"].pop("metadata")
    errors, _warnings = check_model_fields(dropped)
    assert any("event: model field `metadata`" in e for e in errors)


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


def test_resolve_object_props_merges_union_variants() -> None:
    """``oneOf`` variants union their properties instead of picking the first."""
    schemas: dict[str, Any] = {
        "alpha": {"type": "object", "properties": {"a": {"type": "string"}}},
        "beta": {"type": "object", "properties": {"b": {"type": "string"}}},
    }
    merged = _resolve_object_props(
        {"oneOf": [{"$ref": "#/c/alpha"}, {"$ref": "#/c/beta"}]}, schemas
    )
    assert merged is not None
    assert set(merged) == {"a", "b"}


def test_resolve_object_props_merges_conflicting_property_recursively() -> None:
    """A property the variants disagree on resolves to the union of both shapes."""
    schemas: dict[str, Any] = {}
    node = {
        "oneOf": [
            {"properties": {"metadata": {"properties": {"a": {"type": "string"}}}}},
            {"properties": {"metadata": {"properties": {"b": {"type": "string"}}}}},
        ]
    }
    merged = _resolve_object_props(node, schemas)
    assert merged is not None
    nested = _resolve_object_props(merged["metadata"], schemas)
    assert nested is not None
    assert set(nested) == {"a", "b"}


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


def test_main_reports_completeness_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    """A non-declarative coroutine with no example call fails the run via main()."""
    trimmed = dict(_EXAMPLE_CALLS)
    trimmed.pop("update_camera_public")
    monkeypatch.setattr(validate_spec, "_EXAMPLE_CALLS", trimmed)
    spec_file = tmp_path / "spec.json"
    spec_file.write_bytes(orjson.dumps(_chime_spec()))
    monkeypatch.setattr(validate_spec, "SPEC_PATH", spec_file)
    assert main() == 1
    assert "update_camera_public" in capsys.readouterr().out
