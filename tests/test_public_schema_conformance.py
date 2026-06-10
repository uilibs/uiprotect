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
#
# The resolution helpers and the four check functions live in
# ``scripts/validate_spec.py`` (the source of truth shared with the
# spec-validation workflow); this module imports them so the local hook runs the
# full validation for free when a contributor has fetched the spec.

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from validate_spec import (  # local import via conftest sys.path insert
    _LIBRARY_OWNED_FIELDS,
    SPEC_PATH,
    _leaf_model,
    _resolve_object_props,
    check_completeness,
    run_checks,
)

from uiprotect.data import (
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicSensor,
)
from uiprotect.utils import to_snake_case

if TYPE_CHECKING:
    from uiprotect.data.base import ProtectBaseObject

_SPEC_PATH = SPEC_PATH


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


@pytest.mark.skipif(not _SPEC_PATH.exists(), reason="openapi/integration.json absent")
def test_spec_validation_has_no_errors() -> None:
    """The full spec-validation check suite reports no errors against the on-disk spec."""
    spec = json.loads(_SPEC_PATH.read_text())
    errors, _warnings = run_checks(spec)
    assert not errors, "spec drift:\n" + "\n".join(errors)


def test_every_public_coroutine_is_covered() -> None:
    """No public-API coroutine is left out of the derived coverage set (spec-free)."""
    gaps = check_completeness()
    assert not gaps, "uncovered public-API coroutines:\n" + "\n".join(gaps)
