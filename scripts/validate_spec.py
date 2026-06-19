#!/usr/bin/env python3
"""
Validate the public-API client against the Integration OpenAPI spec.

Reads ``openapi/integration.json`` (fetched on demand by
``scripts/fetch_openapi.py``; gitignored, never committed) and reports drift
between Ubiquiti's spec and the hand-maintained client surface:

* spec endpoints with no covering client method — derived from the declarative
  ``@public_*`` decorator registry plus one recorded example call per
  hand-written exception method, never a hand-maintained table (warning),
* model fields the spec dropped or retyped (error) and fields the spec added
  that the model lacks (warning),
* spec enum values absent from the matching library enum (warning).

The library deliberately models every public-API field optional (older firmware
and partial/reference responses omit them), so spec ``required`` vs. model
``optional`` is not checked — it would be guaranteed noise on every run.

Exits non-zero on any error and prints a markdown summary the spec-validation
workflow embeds in a drift issue. The check functions are also imported by
``tests/test_public_schema_conformance.py`` so a contributor who fetches the
spec locally runs the full validation for free.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args

import orjson

# ``scripts/`` is not an importable package, so make ``src/`` importable when
# this file is run directly or imported by the test via a sys.path insert.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from uiprotect._public_api import registry  # noqa: E402
from uiprotect.api import ProtectApiClient  # noqa: E402
from uiprotect.data import (  # noqa: E402
    PublicBridge,
    PublicCamera,
    PublicChime,
    PublicLight,
    PublicLiveview,
    PublicNVR,
    PublicSensor,
    PublicViewer,
)
from uiprotect.data.base import ProtectBaseObject  # noqa: E402
from uiprotect.data.types import DeviceState  # noqa: E402
from uiprotect.utils import to_snake_case  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

SPEC_PATH = Path(__file__).resolve().parents[1] / "openapi" / "integration.json"


# ---------------------------------------------------------------------------
# Endpoint coverage source.
#
# The set of covered endpoints is DERIVED, never hand-maintained:
#
# * Declarative endpoints come straight from the import-time ``@public_get`` /
#   ``@public_patch`` / ``@public_post`` registry — the decorator *is* the
#   implementation, so it cannot drift out of sync with the client.
# * The hand-written exception methods (grouped/validated PATCHes, the
#   alarm-hub URL aliases, file upload, ``update_public``, etc.) are covered by
#   one executable example call each, recorded by spying on
#   ``BaseApiClient.request`` (see ``_record_example_calls``).
# * The two websocket subscriptions are not REST calls; their paths are read
#   straight off the client's ``*_ws_path`` attributes.
#
# A spec endpoint absent from this derived union reads as a new/uncovered
# endpoint and raises a warning. ``check_completeness`` separately asserts every
# public-API coroutine is itself accounted for, so a newly added method that
# nobody wired up cannot silently leave a gap.
# ---------------------------------------------------------------------------

# Registry path templates use Python parameter names (``/v1/cameras/{camera_id}``)
# while the spec uses its own (``/v1/cameras/{id}``); recorded example calls
# inject this sentinel where a path parameter goes. Normalizing every ``{...}``
# placeholder and the sentinel to a bare ``{}`` lets the three sources compare
# equal regardless of the parameter name.
_PATH_PARAM_RE = re.compile(r"\{[^/{}]+\}")
_RECORD_SENTINEL = "__spec_param__"


def _normalize_path(path: str) -> str:
    """Collapse named path placeholders and the record sentinel to a bare ``{}``."""
    return _PATH_PARAM_RE.sub("{}", path).replace(_RECORD_SENTINEL, "{}")


# Public-API coroutines that issue requests but are neither decorated nor named
# ``*_public`` (so the completeness scan would otherwise miss them).
_EXTRA_PUBLIC_COROUTINES = frozenset(
    {
        "get_public_api_camera_snapshot",
        "create_camera_rtsps_streams",
        "get_camera_rtsps_streams",
        "delete_camera_rtsps_streams",
    }
)


# One executable example call per hand-written (non-declarative) public-API
# coroutine. Each is invoked against a throw-away client whose ``request`` is
# spied on, so the call records its ``(verb, path)`` and then short-circuits
# before any network I/O. Path parameters get ``_RECORD_SENTINEL``; PATCH bodies
# get a single field so the "at least one parameter" guards pass.
_S = _RECORD_SENTINEL
_EXAMPLE_CALLS: dict[str, Callable[[ProtectApiClient], Awaitable[Any]]] = {
    "get_public_api_camera_snapshot": lambda c: c.get_public_api_camera_snapshot(_S),
    "create_camera_rtsps_streams": lambda c: c.create_camera_rtsps_streams(_S, "high"),
    "get_camera_rtsps_streams": lambda c: c.get_camera_rtsps_streams(_S),
    "delete_camera_rtsps_streams": lambda c: c.delete_camera_rtsps_streams(_S, "high"),
    "create_talkback_session_public": lambda c: c.create_talkback_session_public(_S),
    "disable_camera_mic_permanently_public": (
        lambda c: c.disable_camera_mic_permanently_public(_S)
    ),
    "update_camera_public": lambda c: c.update_camera_public(_S, name=_S),
    "update_light_public": lambda c: c.update_light_public(_S, name=_S),
    "update_sensor_public": lambda c: c.update_sensor_public(_S, name=_S),
    "update_siren_public": lambda c: c.update_siren_public(_S, name=_S),
    "play_siren_public": lambda c: c.play_siren_public(_S),
    "test_siren_sound_public": lambda c: c.test_siren_sound_public(_S),
    "update_relay_public": lambda c: c.update_relay_public(_S, name=_S),
    "activate_relay_output_public": (
        lambda c: c.activate_relay_output_public(_S, _S, state="on")
    ),
    "test_speaker_sound_public": lambda c: c.test_speaker_sound_public(_S),
    "trigger_alarm_hub_output_public": (
        lambda c: c.trigger_alarm_hub_output_public(_S, _S, enable=True)
    ),
    "get_bridge_public": lambda c: c.get_bridge_public(_S),
    "update_bridge_public": lambda c: c.update_bridge_public(_S, name=_S),
    "get_viewer_public": lambda c: c.get_viewer_public(_S),
    "update_viewer_public": lambda c: c.update_viewer_public(_S, name=_S),
    "get_liveview_public": lambda c: c.get_liveview_public(_S),
    "create_liveview_public": lambda c: c.create_liveview_public(
        name=_S, is_default=False, is_global=False, owner=_S, layout=1, slots=[]
    ),
    "update_liveview_public": lambda c: c.update_liveview_public(_S, name=_S),
    "send_alarm_webhook_public": lambda c: c.send_alarm_webhook_public(_S),
    "get_arm_profiles_public": lambda c: c.get_arm_profiles_public(),
    "create_arm_profile_public": lambda c: c.create_arm_profile_public(
        name=_S,
        automations=[],
        schedules=[],
        record_everything=False,
        activation_delay=0,
    ),
    "update_arm_profile_public": lambda c: c.update_arm_profile_public(_S, name=_S),
    "delete_arm_profile_public": lambda c: c.delete_arm_profile_public(_S),
    "get_arm_manager_settings_public": lambda c: c.get_arm_manager_settings_public(),
    "set_current_arm_profile_public": lambda c: c.set_current_arm_profile_public(_S),
    "enable_arm_alarm_public": lambda c: c.enable_arm_alarm_public(),
    "disable_arm_alarm_public": lambda c: c.disable_arm_alarm_public(),
    "get_files_public": lambda c: c.get_files_public(_S),
    "upload_file_public": lambda c: c.upload_file_public(_S, b"x", "asset.png"),
    "update_public": lambda c: c.update_public(),
}


class _ShortCircuitError(Exception):
    """Raised by the request spy to abort an example call before network I/O."""


async def _record_example_calls() -> set[tuple[str, str]]:
    """Run every example call against a spied client; return recorded ``(verb, path)``."""
    client = ProtectApiClient.public_only("127.0.0.1", 443, api_key="x")
    recorded: set[tuple[str, str]] = set()
    prefix = client.public_api_path

    async def _spy(method: str, url: str, *_args: Any, **_kwargs: Any) -> Any:
        recorded.add((method.upper(), _normalize_path(url.removeprefix(prefix))))
        raise _ShortCircuitError

    client.request = _spy  # type: ignore[method-assign]
    for call in _EXAMPLE_CALLS.values():
        # ``update_public`` gathers its fetches with ``return_exceptions=True``
        # and swallows the sentinel; the others propagate it. Either way the
        # spy has already recorded every path the call reached.
        with contextlib.suppress(_ShortCircuitError):
            await call(client)
    return recorded


def _registry_endpoints() -> set[tuple[str, str]]:
    """Covered ``(VERB, path)`` for every declaratively-decorated endpoint."""
    return {
        (verb.upper(), _normalize_path(path))
        for verb, path in registry.for_class(ProtectApiClient.__name__)
    }


def _subscribe_endpoints() -> set[tuple[str, str]]:
    """The two websocket subscription paths, read off the client's path attributes."""
    prefix = ProtectApiClient.public_api_path
    endpoints: set[tuple[str, str]] = set()
    for attr in ("events_ws_path", "devices_ws_path"):
        path: str = getattr(ProtectApiClient, attr)
        endpoints.add(("GET", _normalize_path(path.removeprefix(prefix))))
    return endpoints


@functools.cache
def covered_endpoints() -> frozenset[tuple[str, str]]:
    """Derived union of declarative, recorded, and websocket-subscription endpoints."""
    recorded = asyncio.run(_record_example_calls())
    return frozenset(_registry_endpoints() | recorded | _subscribe_endpoints())


# (model class, spec schema name) pairs validated field-for-field.
_MODEL_SCHEMAS: list[tuple[type[ProtectBaseObject], str]] = [
    (PublicCamera, "camera"),
    (PublicLight, "light"),
    (PublicSensor, "sensor"),
    (PublicChime, "chime"),
    (PublicNVR, "nvr"),
    (PublicViewer, "viewer"),
    (PublicBridge, "bridge"),
    (PublicLiveview, "liveview"),
]

# Spec enum schemas with a known library counterpart. Spec values absent from
# the lib enum are warnings; the lib's ``UNKNOWN`` sentinel is ignored.
_ENUM_SCHEMAS: list[tuple[type[Any], str]] = [
    (DeviceState, "deviceState"),
]

# Library-owned fields populated out-of-band, absent from the spec schema.
_LIBRARY_OWNED_FIELDS: dict[str, set[str]] = {
    "camera": {"rtsps_streams"},
}

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _resolve_object_props(  # noqa: PLR0911  # one return per JSON-schema node kind
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


def _spec_field_name(key: str, remaps: dict[str, str]) -> str:
    """Map a spec property key to its model field name, honoring lib remaps."""
    return remaps.get(key) or to_snake_case(key)


def check_endpoints(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Spec endpoints absent from the derived covered set are new-endpoint warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    covered = covered_endpoints()
    for path, operations in spec.get("paths", {}).items():
        for method in operations:
            if method not in _HTTP_METHODS:
                continue
            if (method.upper(), _normalize_path(path)) not in covered:
                warnings.append(
                    f"new endpoint `{method.upper()} {path}` has no covering client "
                    f"method (declarative decorator or recorded example call)"
                )
    return errors, warnings


def _public_api_coroutines() -> set[str]:
    """Names of every public-API coroutine on ``ProtectApiClient``."""
    return {
        name
        for name, member in inspect.getmembers(
            ProtectApiClient, inspect.iscoroutinefunction
        )
        if name.endswith("_public")
        or hasattr(member, "__public_endpoint__")
        or name in _EXTRA_PUBLIC_COROUTINES
    }


def check_completeness() -> list[str]:
    """
    Every public-API coroutine must be covered, declaratively or by example call.

    The endpoint coverage set is only as complete as the example-call table, so
    this guards the table itself: a newly added public method that nobody wired
    up surfaces here instead of silently leaving its endpoint uncovered. Spec-
    independent — it checks the client against itself, not against the spec.
    """
    declarative = set(registry.for_class(ProtectApiClient.__name__).values())
    accounted = declarative | set(_EXAMPLE_CALLS)
    missing = _public_api_coroutines() - accounted
    return [
        f"public-API coroutine `{name}` has no declarative decorator and no "
        f"recorded example call (add one to `_EXAMPLE_CALLS`)"
        for name in sorted(missing)
    ]


def check_model_fields(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Compare spec schema properties against public model fields, both directions."""
    errors: list[str] = []
    warnings: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    for cls, schema_name in _MODEL_SCHEMAS:
        if schema_name not in schemas:
            errors.append(
                f"{schema_name}: tracked schema absent from spec "
                f"(server removed/renamed it)"
            )
            continue
        props = _resolve_object_props({"$ref": f"#/.../{schema_name}"}, schemas)
        if props is None:
            errors.append(f"{schema_name}: spec schema is not object-shaped")
            continue
        remaps = cls._get_unifi_remaps()
        spec_fields = {_spec_field_name(key, remaps) for key in props}
        model_fields = set(cls.model_fields)
        owned = _LIBRARY_OWNED_FIELDS.get(schema_name, set())

        removed = model_fields - spec_fields - owned
        errors.extend(
            f"{schema_name}: model field `{name}` absent from spec "
            f"(server removed/retyped it)"
            for name in sorted(removed)
        )
        added = spec_fields - model_fields
        warnings.extend(
            f"{schema_name}: spec field `{name}` has no model counterpart"
            for name in sorted(added)
        )
    return errors, warnings


def check_enums(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Spec enum values absent from the matching library enum are warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    for enum_cls, schema_name in _ENUM_SCHEMAS:
        schema = schemas.get(schema_name)
        if schema is None:
            errors.append(
                f"{schema_name}: tracked schema absent from spec "
                f"(server removed/renamed it)"
            )
            continue
        if "enum" not in schema:
            errors.append(
                f"{schema_name}: tracked enum schema no longer declares `enum`"
            )
            continue
        lib_values = {member.value for member in enum_cls}
        warnings.extend(
            f"{schema_name}: spec enum value `{value}` absent from "
            f"`{enum_cls.__name__}`"
            for value in schema["enum"]
            if value not in lib_values
        )
    return errors, warnings


_CHECKS = (check_endpoints, check_model_fields, check_enums)


def run_checks(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Run every check and return the merged ``(errors, warnings)``."""
    errors: list[str] = []
    warnings: list[str] = []
    for check in _CHECKS:
        e, w = check(spec)
        errors.extend(e)
        warnings.extend(w)
    return errors, warnings


def format_summary(
    errors: list[str], warnings: list[str], version: str | None = None
) -> str:
    """Render a markdown summary of the validation result."""
    header = "## Public-API spec conformance"
    if version:
        header += f" — Protect {version}"
    lines = [header, ""]
    if not errors and not warnings:
        lines.append("No drift: client surface matches the spec.")
        return "\n".join(lines)
    if errors:
        lines.append(f"### Errors ({len(errors)})")
        lines.extend(f"- {item}" for item in errors)
        lines.append("")
    if warnings:
        lines.append(f"### Warnings ({len(warnings)})")
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines).rstrip()


def main() -> int:
    """Load the on-disk spec, run all checks, print a summary, exit non-zero on error."""
    if not SPEC_PATH.exists():
        print(
            f"spec not found at {SPEC_PATH}; run `python scripts/fetch_openapi.py` first",
            file=sys.stderr,
        )
        return 2
    spec = orjson.loads(SPEC_PATH.read_bytes())
    version = spec.get("info", {}).get("version")
    errors, warnings = run_checks(spec)
    errors.extend(check_completeness())
    print(format_summary(errors, warnings, version))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
