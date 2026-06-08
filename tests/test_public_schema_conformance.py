"""Opt-in guard: public device models must not declare fields absent from the spec."""

# The spec (``openapi/integration.json``) is gitignored and not fetched in CI, so
# this test skips cleanly when it is absent. Run ``python scripts/fetch_openapi.py``
# (defaults to the latest release) locally to enable it.
#
# The check is a subset assertion (model fields ⊆ spec fields), NOT strict
# equality: it catches phantom fields — model fields with no counterpart in the
# public contract, the regression this guard exists to prevent — while staying
# robust across spec releases. The public spec is append-only in practice, so a
# model targeting the latest shape stays a subset of any newer spec; and fields
# added in a release after our minimum-supported Protect version are modelled as
# optional, so "spec has a field the model doesn't" is expected, not a failure.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest

from uiprotect.data import (
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicSensor,
)
from uiprotect.data.base import ProtectBaseObject
from uiprotect.utils import to_snake_case

_SPEC_PATH = Path(__file__).resolve().parents[1] / "openapi" / "integration.json"


def _resolve_object_props(
    node: dict[str, Any], schemas: dict[str, Any]
) -> dict[str, dict[str, Any]] | None:
    """Return ``{property: schema}`` for an object node, ``None`` for scalar leaves."""
    if "$ref" in node:
        return _resolve_object_props(schemas[node["$ref"].split("/")[-1]], schemas)
    if "allOf" in node:
        merged: dict[str, dict[str, Any]] = {}
        is_object = False
        for sub in node["allOf"]:
            resolved = _resolve_object_props(sub, schemas)
            if resolved is not None:
                merged.update(resolved)
                is_object = True
        return merged if is_object else None
    if "oneOf" in node:
        for sub in node["oneOf"]:
            resolved = _resolve_object_props(sub, schemas)
            if resolved is not None:
                return resolved
        return None
    if node.get("type") == "array":
        return _resolve_object_props(node.get("items", {}), schemas)
    if "properties" in node:
        return dict(node["properties"])
    return None


def _leaf_model(annotation: Any) -> type[ProtectBaseObject] | None:
    """Unwrap ``Optional`` / ``list`` to the ``ProtectBaseObject`` leaf, if any."""
    if isinstance(annotation, type) and issubclass(annotation, ProtectBaseObject):
        return annotation
    for arg in get_args(annotation):
        leaf = _leaf_model(arg)
        if leaf is not None:
            return leaf
    return None


# Library-owned fields populated out-of-band, absent from the spec schema, keyed by spec path.
_LIBRARY_OWNED_FIELDS: dict[str, set[str]] = {
    "camera": {"rtsps_streams"},
}


def _assert_matches(
    cls: type[ProtectBaseObject],
    node: dict[str, Any],
    schemas: dict[str, Any],
    path: str,
) -> None:
    """Assert ``cls.model_fields`` is a subset of the spec property set (no phantom fields), recursively."""
    props = _resolve_object_props(node, schemas)
    assert props is not None, f"{path}: spec schema is not object-shaped"

    # ``modelKey`` is remapped to the ``model`` field on ProtectModel.
    spec_fields = {to_snake_case(key) for key in props}
    model_fields = {"model_key" if f == "model" else f for f in cls.model_fields}
    phantom = model_fields - spec_fields - _LIBRARY_OWNED_FIELDS.get(path, set())
    assert not phantom, (
        f"{path}: model declares field(s) absent from the spec: {sorted(phantom)}"
    )

    for key, prop_schema in props.items():
        if _resolve_object_props(prop_schema, schemas) is None:
            continue  # scalar / enum leaf — nothing nested to compare
        field = cls.model_fields.get(to_snake_case(key))
        if field is None:
            continue
        leaf = _leaf_model(field.annotation)
        if leaf is not None:
            _assert_matches(leaf, prop_schema, schemas, f"{path}.{key}")


@pytest.mark.skipif(not _SPEC_PATH.exists(), reason="openapi/integration.json absent")
@pytest.mark.parametrize(
    ("cls", "schema_name"),
    [
        (PublicCamera, "camera"),
        (PublicLight, "light"),
        (PublicSensor, "sensor"),
        (PublicChime, "chime"),
    ],
)
def test_public_model_matches_spec(
    cls: type[ProtectBaseObject], schema_name: str
) -> None:
    """``model_fields`` is a subset of the resolved spec property set, including nested leaves."""
    schemas = json.loads(_SPEC_PATH.read_text())["components"]["schemas"]
    _assert_matches(
        cls, {"$ref": f"#/components/schemas/{schema_name}"}, schemas, schema_name
    )
