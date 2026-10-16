"""
Network-free unit tests for the spec-validation check functions.

Each test feeds a hand-built in-memory spec ``dict`` (never the 74 MB fetched
spec, absent in CI) to one check function and pins its ``(errors, warnings)``.
"""

from __future__ import annotations

import enum
from typing import Any, Literal

import orjson
import pytest
import validate_spec  # local import via conftest sys.path insert
from validate_spec import (
    _CHECKS,
    _ENUM_COVERAGE_WAIVERS,
    _EXAMPLE_CALLS,
    _MODELLED_AS_SUBSET,
    _VALUE_RANGE_KEYWORDS,
    _example_kwargs,
    _example_value,
    _inbound_enum_ids,
    _iter_spec_consts,
    _iter_spec_enums,
    _leaf_model,
    _library_enums_by_name,
    _normalize_path,
    _prepare_spec,
    _public_api_coroutines,
    _recorded_calls,
    _resolve_const,
    _resolve_object_props,
    _spec_field_name,
    _union_variants,
    check_completeness,
    check_endpoints,
    check_enum_coverage,
    check_enums,
    check_event_types,
    check_model_fields,
    check_request_bodies,
    covered_endpoints,
    format_summary,
    main,
    run_checks,
)

from uiprotect._public_api import registry
from uiprotect.api import ProtectApiClient
from uiprotect.data import PUBLIC_EVENT_TYPES, PublicChime
from uiprotect.data.public_devices import PublicArmScheduleDict, PublicRingSettings
from uiprotect.data.types import DoorbellMessageType, PublicHdrMode


@pytest.fixture(autouse=True)
def _clear_recorded_calls() -> Any:
    _recorded_calls.cache_clear()
    yield
    _recorded_calls.cache_clear()


def _model_props(cls: Any, name: str) -> dict[str, dict[str, Any]]:
    """Build green spec ``properties`` for one tracked model schema."""
    inv = {v: k for k, v in cls._get_unifi_remaps().items()}
    owned = validate_spec._LIBRARY_OWNED_FIELDS.get(name, set())
    props: dict[str, dict[str, Any]] = {}
    for field_name, field in cls.model_fields.items():
        if field_name in owned:
            continue
        key = inv.get(field_name, field_name)
        leaf = validate_spec._leaf_model(field.annotation)
        props[key] = (
            {"type": "string"}
            if leaf is None
            else {"type": "object", "properties": _model_props(leaf, f"{name}.{key}")}
        )
    return props


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


def _ring_settings_spec(**extra: dict[str, Any]) -> dict[str, Any]:
    """Build a green spec whose ``chime.ringSettings`` is a nested object array."""
    spec = _chime_spec()
    item = {
        "type": "object",
        "properties": {**_model_props(PublicRingSettings, "ringSettings"), **extra},
    }
    spec["components"]["schemas"]["chime"]["properties"]["ringSettings"] = {
        "type": "array",
        "items": item,
    }
    return spec


def test_check_model_fields_nested_all_green() -> None:
    errors, warnings = check_model_fields(_ring_settings_spec())
    assert errors == []
    assert warnings == []


def test_check_model_fields_nested_added_field_warns() -> None:
    spec = _ring_settings_spec(newNestedField={"type": "boolean"})
    errors, warnings = check_model_fields(spec)
    assert errors == []
    assert warnings == [
        "chime.ringSettings: spec field `new_nested_field` has no model counterpart"
    ]


@pytest.mark.parametrize(
    ("retype", "waiver", "expected"),
    [
        (
            False,
            None,
            [
                (
                    "chime.ringSettings: model field `volume` absent from spec "
                    "(server removed/retyped it)"
                )
            ],
        ),
        (False, "_LIBRARY_OWNED_FIELDS", []),
        (False, "_EXTRA_MODEL_FIELDS", []),
        (
            True,
            None,
            [
                (
                    "chime: model field `ring_settings` expects an object but the "
                    "spec retyped it to a scalar"
                )
            ],
        ),
    ],
)
def test_check_model_fields_nested_removed_field(
    monkeypatch: pytest.MonkeyPatch,
    retype: bool,
    waiver: str | None,
    expected: list[str],
) -> None:
    """A nested model field the spec dropped or made scalar errors unless waived."""
    spec = _ring_settings_spec()
    chime = spec["components"]["schemas"]["chime"]["properties"]
    if retype:
        chime["ringSettings"] = {"type": "string"}
    else:
        del chime["ringSettings"]["items"]["properties"]["volume"]
    if waiver is not None:
        monkeypatch.setitem(
            getattr(validate_spec, waiver), "chime.ringSettings", {"volume"}
        )
    errors, warnings = check_model_fields(spec)
    assert errors == expected
    assert warnings == []


def test_check_model_fields_nested_object_on_non_model_field_skipped() -> None:
    spec = _chime_spec()
    spec["components"]["schemas"]["chime"]["properties"]["cameraIds"] = {
        "type": "object",
        "properties": {"unmodelled": {"type": "string"}},
    }
    errors, warnings = check_model_fields(spec)
    assert errors == []
    assert warnings == []


def test_check_model_fields_missing_schema_errors() -> None:
    errors, _warnings = check_model_fields({"components": {"schemas": {}}})
    assert any("tracked schema absent from spec" in e for e in errors)


def test_check_model_fields_non_object_schema_errors() -> None:
    spec = {"components": {"schemas": {"chime": {"type": "string"}}}}
    errors, _warnings = check_model_fields(spec)
    assert any("not object-shaped" in e for e in errors)


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
    assert list(found) == [frozenset({"event"})]
    assert all(isinstance(value, str) for value_set in found for value in value_set)


def test_iter_spec_consts_keeps_the_unknown_const() -> None:
    """``unknown`` in a spec const is a real wire value, not the library sentinel."""
    spec = {"components": {"schemas": {"k": {"type": "string", "const": "unknown"}}}}
    assert list(dict(_iter_spec_consts(spec))) == [frozenset({"unknown"})]
    assert check_enum_coverage(_response_spec("k", {"const": "unknown"})) == ([], [])


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


def test_resolve_const_one_of_resolves_only_on_agreement() -> None:
    """A union of consts resolves when the variants agree, ``None`` when they differ."""
    schemas: dict[str, Any] = {"ringType": {"type": "string", "const": "ring"}}
    agreeing = {
        "oneOf": [
            {"const": "ring", "description": "left"},
            {"$ref": "#/c/ringType"},
        ]
    }
    assert _resolve_const(agreeing, schemas) == "ring"
    assert (
        _resolve_const({"oneOf": [{"const": "ring"}, {"const": "motion"}]}, schemas)
        is None
    )
    assert (
        _resolve_const({"oneOf": [{"const": "ring"}, {"type": "string"}]}, schemas)
        is None
    )


def test_union_variants_flattens_and_rejects_non_unions() -> None:
    schemas: dict[str, Any] = {
        "inner": {"oneOf": [{"const": "a"}, {"const": "b"}]},
    }
    assert _union_variants(
        {"oneOf": [{"$ref": "#/c/inner"}, {"const": "c"}]}, schemas
    ) == [{"const": "a"}, {"const": "b"}, {"const": "c"}]
    assert _union_variants({"type": "object"}, schemas) is None
    assert _union_variants({"$ref": "#/c/absent"}, schemas) is None


def test_check_event_types_resolves_referenced_type_const() -> None:
    """A variant whose ``type`` discriminator is behind a ``$ref`` still resolves."""
    value = min(event_type.value for event_type in PUBLIC_EVENT_TYPES)
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


def test_check_event_types_flattens_a_nested_union() -> None:
    """Grouping a family of event variants behind their own ``oneOf`` is not drift."""
    spec = _event_spec()
    variants = spec["components"]["schemas"]["event"]["oneOf"]
    grouped, rest = variants[:5], variants[5:]
    spec["components"]["schemas"]["sensorEvent"] = {"oneOf": grouped}
    spec["components"]["schemas"]["event"]["oneOf"] = [
        {"$ref": "#/components/schemas/sensorEvent"},
        *rest,
    ]
    assert check_event_types(spec) == ([], [])


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
    """A field only ONE variant carries still covers the model; dropping it errors."""
    spec = _chime_spec()
    variants = spec["components"]["schemas"]["event"]["oneOf"]
    for variant in variants[:-1]:
        variant["properties"].pop("metadata")
    assert sum("metadata" in v["properties"] for v in variants) == 1
    assert check_model_fields(spec) == ([], [])

    variants[-1]["properties"].pop("metadata")
    errors, _warnings = check_model_fields(spec)
    assert any("event: model field `metadata`" in e for e in errors)


def test_every_check_is_wired_into_run_checks() -> None:
    """Every check function is reachable from ``run_checks``; nothing is orphaned."""
    wired = {
        check_endpoints,
        check_model_fields,
        check_enums,
        check_enum_coverage,
        check_event_types,
        check_request_bodies,
    }
    assert set(_CHECKS) == wired
    assert len(_CHECKS) == len(wired)


def _no_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub out recorded bodies, which a partial spec does not declare."""
    monkeypatch.setattr(validate_spec, "_recorded_calls", lambda: (frozenset(), {}))


def test_run_checks_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_bodies(monkeypatch)
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
    _no_bodies(monkeypatch)
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


_THING_PATH = "/v1/things/{id}"
_THING_ENDPOINT = ("PATCH", "/v1/things/{}")


def _body_spec(
    schema: dict[str, Any],
    schemas: dict[str, Any] | None = None,
    media: str = "application/json",
) -> dict[str, Any]:
    return {
        "paths": {
            _THING_PATH: {
                "parameters": [],
                "patch": {"requestBody": {"content": {media: {"schema": schema}}}},
            }
        },
        "components": {"schemas": schemas or {}},
    }


def _check_body(
    monkeypatch: pytest.MonkeyPatch,
    spec: dict[str, Any],
    body: Any = None,
    waivers: dict[tuple[str, str, str, str], str] | None = None,
    endpoint: tuple[str, str] = _THING_ENDPOINT,
) -> tuple[list[str], list[str]]:
    bodies = {} if body is None else {endpoint: [body]}
    monkeypatch.setattr(validate_spec, "_recorded_calls", lambda: (frozenset(), bodies))
    monkeypatch.setattr(validate_spec, "_REQUEST_BODY_WAIVERS", waivers or {})
    return check_request_bodies(spec)


def _props(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props}


def test_request_body_all_of_hoisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``allOf`` member's properties and ``required`` move into the parent."""
    schemas = {"thing": {**_props(name={"type": "string"}), "required": ["name"]}}
    spec = _body_spec(
        {
            "allOf": [{"$ref": "#/components/schemas/thing"}],
            "additionalProperties": False,
        },
        schemas,
    )
    assert _check_body(monkeypatch, spec, {"name": "x"}) == ([], [])
    errors, _ = _check_body(monkeypatch, spec, {"name": "x", "bogus": 1})
    assert errors == [f"`PATCH {_THING_PATH}` body `bogus`: not declared by the spec"]
    errors, _ = _check_body(monkeypatch, spec, {})
    assert errors == [
        f"`PATCH {_THING_PATH}` body `name`: required by the spec but not sent"
    ]


def test_request_body_all_of_keeps_non_object_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scalar ``allOf`` member still types the property."""
    schemas = {"level": {"type": "integer"}}
    spec = _body_spec(
        _props(level={"allOf": [{"$ref": "#/components/schemas/level"}], "minimum": 5}),
        schemas,
    )
    assert _check_body(monkeypatch, spec, {"level": 1}) == ([], [])
    errors, _ = _check_body(monkeypatch, spec, {"level": "x"})
    assert errors == [
        f"`PATCH {_THING_PATH}` body `level`: 'x' is not of type 'integer'"
    ]


_RANGE_CASES = {
    "pattern": ({"type": "string", "pattern": "^a$"}, "b"),
    "format": ({"type": "string", "format": "email"}, "b"),
    "minLength": ({"type": "string", "minLength": 5}, "b"),
    "maxLength": ({"type": "string", "maxLength": 1}, "bcd"),
    "minimum": ({"type": "integer", "minimum": 5}, 1),
    "maximum": ({"type": "integer", "maximum": 0}, 1),
    "exclusiveMinimum": ({"type": "integer", "exclusiveMinimum": 1}, 1),
    "exclusiveMaximum": ({"type": "integer", "exclusiveMaximum": 1}, 1),
    "multipleOf": ({"type": "integer", "multipleOf": 5}, 1),
    "minItems": ({"type": "array", "minItems": 2}, [1]),
    "maxItems": ({"type": "array", "maxItems": 0}, [1]),
}


def test_range_cases_cover_every_value_range_keyword() -> None:
    assert set(_RANGE_CASES) == _VALUE_RANGE_KEYWORDS


@pytest.mark.parametrize("keyword", sorted(_RANGE_CASES))
def test_request_body_value_constraint_dropped(
    monkeypatch: pytest.MonkeyPatch, keyword: str
) -> None:
    schema, value = _RANGE_CASES[keyword]
    spec = _body_spec(_props(field=schema))
    assert _check_body(monkeypatch, spec, {"field": value}) == ([], [])


def test_request_body_numeric_const_becomes_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped numeric ``const`` still requires a number."""
    spec = _body_spec(_props(delay={"anyOf": [{"const": 5}, {"const": 10}]}))
    assert _check_body(monkeypatch, spec, {"delay": 1}) == ([], [])
    for bad in ("x", None):
        errors, _ = _check_body(monkeypatch, spec, {"delay": bad})
        assert len(errors) == 1
        assert errors[0].startswith(f"`PATCH {_THING_PATH}` body `delay`: ")


@pytest.mark.parametrize(("const", "bad"), [(True, False), ("ON", "OFF")])
def test_request_body_non_numeric_const_kept(
    monkeypatch: pytest.MonkeyPatch, const: Any, bad: Any
) -> None:
    spec = _body_spec(_props(mode={"const": const}))
    assert _check_body(monkeypatch, spec, {"mode": const}) == ([], [])
    errors, _ = _check_body(monkeypatch, spec, {"mode": bad})
    assert errors == [f"`PATCH {_THING_PATH}` body `mode`: {const!r} was expected"]


def test_request_body_all_of_conflicting_property_keeps_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A property two members define differently must satisfy both."""
    schemas = {
        "a": _props(level={"type": "integer"}),
        "b": _props(level={"type": "string"}),
    }
    for order in (["a", "b"], ["b", "a"]):
        spec = _body_spec(
            {"allOf": [{"$ref": f"#/components/schemas/{name}"} for name in order]},
            schemas,
        )
        errors, _ = _check_body(monkeypatch, spec, {"level": 1})
        assert errors == [
            f"`PATCH {_THING_PATH}` body `level`: 1 is not of type 'string'"
        ]


def test_request_body_all_of_union_member_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``allOf`` with nothing to hoist drops the wrapper's closure."""
    schemas = {
        "mode": {"oneOf": [_props(type={"const": "A"}), _props(type={"const": "B"})]}
    }
    spec = _body_spec(
        _props(
            settings={
                "allOf": [{"$ref": "#/components/schemas/mode"}],
                "additionalProperties": False,
            }
        ),
        schemas,
    )
    assert _check_body(monkeypatch, spec, {"settings": {"type": "A"}}) == ([], [])


@pytest.mark.parametrize("union", ["oneOf", "anyOf"])
def test_request_body_union_parent_with_properties_stays_open(
    monkeypatch: pytest.MonkeyPatch, union: str
) -> None:
    """A parent declaring properties and a union defers closure to its variants."""
    schema = {
        **_props(type={"type": "string"}),
        union: [_props(type={"const": "A"}, text={"type": "string"})],
    }
    spec = _body_spec(schema)
    assert _check_body(monkeypatch, spec, {"type": "A", "text": "x"}) == ([], [])


def test_request_body_undeclared_nested_key_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An object schema without ``additionalProperties`` is closed."""
    spec = _body_spec(_props(led=_props(isEnabled={"type": "boolean"})))
    errors, _ = _check_body(monkeypatch, spec, {"led": {"isEnabled": True, "x": 1}})
    assert errors == [f"`PATCH {_THING_PATH}` body `led.x`: not declared by the spec"]


def test_request_body_free_form_object_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _body_spec(_props(meta={"type": "object"}))
    assert _check_body(monkeypatch, spec, {"meta": {"any": 1}}) == ([], [])


def test_request_body_wrong_type_and_null_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _body_spec(_props(on={"type": "boolean"}, level={"type": "number"}))
    errors, _ = _check_body(monkeypatch, spec, {"on": "yes", "level": None})
    assert errors == [
        f"`PATCH {_THING_PATH}` body `level`: None is not of type 'number'",
        f"`PATCH {_THING_PATH}` body `on`: 'yes' is not of type 'boolean'",
    ]


def test_request_body_enum_mismatch_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _body_spec(_props(mode={"type": "string", "enum": ["auto", "on"]}))
    assert _check_body(monkeypatch, spec, {"mode": "on"}) == ([], [])
    errors, _ = _check_body(monkeypatch, spec, {"mode": "weird"})
    assert errors == [
        f"`PATCH {_THING_PATH}` body `mode`: 'weird' is not one of ['auto', 'on']"
    ]


def test_request_body_one_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``oneOf`` body matches exactly one closed variant or errors at the root."""
    preset = _props(type={"const": "PRESET"})
    custom = _props(type={"const": "CUSTOM"}, text={"type": "string"})
    spec = _body_spec({"type": "object", "oneOf": [preset, custom]})
    assert _check_body(monkeypatch, spec, {"type": "CUSTOM", "text": "x"}) == ([], [])
    errors, _ = _check_body(monkeypatch, spec, {"type": "PRESET", "text": "x"})
    assert len(errors) == 1
    assert errors[0].startswith(f"`PATCH {_THING_PATH}` body `<body>`: ")
    assert "is not valid under any of the given schemas (" in errors[0]


def test_request_body_array_item_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Array indices collapse to ``[]`` in errors and unsent-field warnings."""
    slot = _props(mode={"enum": ["motion"]}, extra={"type": "string"})
    spec = _body_spec(_props(slots={"type": "array", "items": slot}))
    errors, warnings = _check_body(monkeypatch, spec, {"slots": [{"mode": "time"}]})
    assert errors == [
        f"`PATCH {_THING_PATH}` body `slots[].mode`: 'time' is not one of ['motion']"
    ]
    assert warnings == [
        f"`PATCH {_THING_PATH}`: spec body field `slots[].extra` is never sent"
    ]


def test_request_body_read_only_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """``readOnly`` properties, direct or via ``$ref``, leave the body and ``required``."""
    schemas = {"thingId": {"type": "string", "readOnly": True}}
    schema = _props(
        id={"$ref": "#/components/schemas/thingId"},
        key={"type": "string", "readOnly": True},
        name={"type": "string"},
    )
    schema["required"] = ["id", "key", "name"]
    spec = _body_spec(schema, schemas)
    assert _check_body(monkeypatch, spec, {"name": "x"}) == ([], [])
    errors, _ = _check_body(monkeypatch, spec, {"name": "x", "id": "y"})
    assert errors == [f"`PATCH {_THING_PATH}` body `id`: not declared by the spec"]


def test_request_body_waived_required_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """A waived finding is neither an error nor an unsent-field warning."""
    schema = _props(id={"type": "string"}, name={"type": "string"})
    schema["required"] = ["id", "name"]
    spec = _body_spec(schema)
    assert _check_body(monkeypatch, spec, {"name": "x"}) == (
        [f"`PATCH {_THING_PATH}` body `id`: required by the spec but not sent"],
        [],
    )
    waivers = {("PATCH", _THING_PATH, "id", "required"): "read schema reused"}
    assert _check_body(monkeypatch, spec, {"name": "x"}, waivers) == ([], [])


def test_request_body_waiver_scoped_to_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``required`` waiver does not hide a type error on the same field."""
    spec = _body_spec(_props(id={"type": "string"}))
    waivers = {("PATCH", _THING_PATH, "id", "required"): "read schema reused"}
    errors, _ = _check_body(monkeypatch, spec, {"id": 5}, waivers)
    assert errors == [f"`PATCH {_THING_PATH}` body `id`: 5 is not of type 'string'"]


def test_request_body_stale_waiver_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _body_spec(_props(name={"type": "string"}))
    waivers = {("PATCH", _THING_PATH, "name", "required"): "no longer needed"}
    errors, warnings = _check_body(monkeypatch, spec, {"name": "x"}, waivers)
    assert errors == []
    assert warnings == [
        (
            f"request-body waiver `PATCH {_THING_PATH}` `name` (required) no "
            "longer triggers (remove it from `_REQUEST_BODY_WAIVERS`)"
        )
    ]


def test_request_body_stale_kwarg_override_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        validate_spec,
        "_EXAMPLE_KWARG_OVERRIDES",
        {"update_chime_public": {"bogus": 1}, "no_such_method": {"x": 1}},
    )
    spec = _body_spec(_props(name={"type": "string"}))
    _, warnings = _check_body(monkeypatch, spec, {"name": "x"})
    assert warnings == [
        f"example kwarg override `{override}` matches no example parameter "
        "(remove it from `_EXAMPLE_KWARG_OVERRIDES`)"
        for override in ("no_such_method(x)", "update_chime_public(bogus)")
    ]


def test_request_body_unsent_field_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _body_spec(
        _props(name={"type": "string"}, led=_props(on={"type": "boolean"}))
    )
    errors, warnings = _check_body(monkeypatch, spec, {"led": {}})
    assert errors == []
    assert warnings == [
        f"`PATCH {_THING_PATH}`: spec body field `led.on` is never sent",
        f"`PATCH {_THING_PATH}`: spec body field `name` is never sent",
    ]


def test_request_body_non_json_media_type_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _body_spec(
        {"type": "string", "format": "binary"}, media="multipart/form-data"
    )
    assert _check_body(monkeypatch, spec) == ([], [])


def test_request_body_never_sent_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _body_spec(_props(name={"type": "string"}))
    assert _check_body(monkeypatch, spec) == (
        [],
        [f"`PATCH {_THING_PATH}`: client never sends a JSON body"],
    )


def test_request_body_undeclared_body_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = {"paths": {_THING_PATH: {"patch": {}}}, "components": {"schemas": {}}}
    errors, _ = _check_body(monkeypatch, spec, {"name": "x"})
    assert errors == [f"`PATCH {_THING_PATH}`: client sends a body the spec omits"]


def test_request_body_to_undeclared_path_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _body_spec(_props(name={"type": "string"}))
    errors, _ = _check_body(
        monkeypatch, spec, {"name": "x"}, endpoint=("POST", "/v1/other")
    )
    assert errors == [
        "`POST /v1/other`: client sends a body to an endpoint the spec omits"
    ]


def test_request_body_unsent_across_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    """A field is unsent only when no recorded body carries it."""
    spec = _body_spec(_props(a={"type": "string"}, b={"type": "string"}))
    bodies = {_THING_ENDPOINT: [{"a": "x"}, {"b": "x"}]}
    monkeypatch.setattr(validate_spec, "_recorded_calls", lambda: (frozenset(), bodies))
    monkeypatch.setattr(validate_spec, "_REQUEST_BODY_WAIVERS", {})
    assert check_request_bodies(spec) == ([], [])


def test_prepare_spec_dangling_ref_raises() -> None:
    spec = {"components": {"schemas": {"a": {"allOf": [{"$ref": "#/c/missing"}]}}}}
    with pytest.raises(ValueError, match="dangling"):
        _prepare_spec(spec)


def test_prepare_spec_self_reference_terminates() -> None:
    spec = {"components": {"schemas": {"loop": {"allOf": [{"$ref": "#/c/loop"}]}}}}
    prepared = _prepare_spec(spec)
    assert prepared["components"]["schemas"]["loop"] == {
        "allOf": [{"$ref": "#/c/loop"}]
    }


class _WithUnknown(enum.Enum):
    UNKNOWN = "unknown"
    FIRST = "first"


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (bool, True),
        (int, 1),
        (float, 1.5),
        (str, validate_spec._S),
        (_WithUnknown, _WithUnknown.FIRST),
        (Literal["on", "off"], "on"),
        (Literal["on"] | None, "on"),
        (list[int], [1]),
        (str | PublicHdrMode | None, PublicHdrMode.AUTO),
        (str | None, validate_spec._S),
        (PublicArmScheduleDict, {"start": validate_spec._S, "end": validate_spec._S}),
    ],
)
def test_example_value(annotation: Any, expected: Any) -> None:
    assert _example_value(annotation) == expected


def test_example_value_model_sets_every_field() -> None:
    value = _example_value(PublicRingSettings)
    assert isinstance(value, PublicRingSettings)
    assert all(getattr(value, name) is not None for name in type(value).model_fields)


def test_example_value_unsupported_raises() -> None:
    with pytest.raises(TypeError, match="no example value"):
        _example_value(dict[str, int])


def test_example_kwargs_names_unsupported_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def method(self: Any, extra: dict[str, Any] | None = None) -> None: ...

    monkeypatch.setattr(ProtectApiClient, "my_method", method, raising=False)
    with pytest.raises(TypeError, match=r"^my_method\(extra\): no example value"):
        _example_kwargs("my_method", 0)


def test_recorded_paths_use_sentinel_for_decorated_placeholders() -> None:
    recorded, _bodies = _recorded_calls()
    assert ("POST", "/v1/cameras/{}/ptz/goto/{}") in recorded


def test_recorded_bodies_include_defaults_only_model() -> None:
    """A model-typed parameter is also sent with every optional field unset."""
    _recorded, bodies = _recorded_calls()
    lights = bodies[("PATCH", "/v1/lights/{}")]
    assert {"isIndicatorEnabled": False} in [b["lightDeviceSettings"] for b in lights]
    assert {} in [b["lightModeSettings"] for b in lights]


def test_recorded_bodies_cover_hand_written_and_decorated() -> None:
    """Bodies are captured from hand-written calls and decorated endpoints alike."""
    _recorded, bodies = _recorded_calls()
    (chime,) = bodies[("PATCH", "/v1/chimes/{}")]
    assert set(chime) == {"name", "cameraIds", "ringSettings"}
    (liveview,) = bodies[("PATCH", "/v1/liveviews/{}")]
    assert set(liveview) == {"name", "isGlobal", "layout", "slots"}
    (camera,) = bodies[("PATCH", "/v1/cameras/{}")]
    assert camera["lcdMessage"]["type"] is DoorbellMessageType.CUSTOM_MESSAGE
