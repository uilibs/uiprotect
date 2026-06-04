"""Opt-in field-conformance guard for public device models vs the OpenAPI spec."""

# The spec (``openapi/integration.json``) is gitignored and not fetched in CI, so
# this test skips cleanly when it is absent. Run ``python scripts/fetch_openapi.py``
# locally to enable it.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from uiprotect.data import (
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicSensor,
)
from uiprotect.utils import to_snake_case

_SPEC_PATH = Path(__file__).resolve().parents[1] / "openapi" / "integration.json"


def _resolve_fields(schemas: dict[str, Any], name: str) -> set[str]:
    """Return the wire property names of ``name`` after ``$ref``/``allOf`` decomposition."""
    props: dict[str, Any] = {}

    def walk(node: dict[str, Any]) -> None:
        if "$ref" in node:
            walk(schemas[node["$ref"].split("/")[-1]])
        elif "allOf" in node:
            for sub in node["allOf"]:
                walk(sub)
        else:
            props.update(node.get("properties", {}))

    walk(schemas[name])
    return set(props)


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
def test_public_model_matches_spec(cls: type, schema_name: str) -> None:
    """``model_fields`` (mapped to wire keys) equals the resolved spec property set."""
    schemas = json.loads(_SPEC_PATH.read_text())["components"]["schemas"]
    spec_fields = {to_snake_case(key) for key in _resolve_fields(schemas, schema_name)}
    # ``modelKey`` is remapped to the ``model`` field on ProtectModel.
    model_fields = {"model_key" if f == "model" else f for f in cls.model_fields}
    spec_fields = {"model_key" if f == "model_key" else f for f in spec_fields}
    assert model_fields == spec_fields
