#!/usr/bin/env python3
"""
Validate the public-API client against the Integration OpenAPI spec.

Reads ``openapi/integration.json`` (fetched on demand by
``scripts/fetch_openapi.py``; gitignored, never committed) and reports drift
between Ubiquiti's spec and the hand-maintained client surface:

* spec endpoints with no covering ``*_public`` client method (warning),
* model fields the spec dropped or retyped (error) and fields the spec added
  that the model lacks (warning),
* spec ``required`` fields that are optional on the model (warning — the
  library deliberately models every public-API field optional, since older
  firmware and partial/reference responses omit them, so this is informational
  rather than a contract violation),
* spec enum values absent from the matching library enum (warning).

Exits non-zero on any error and prints a markdown summary the spec-validation
workflow embeds in a drift issue. The check functions are also imported by
``tests/test_public_schema_conformance.py`` so a contributor who fetches the
spec locally runs the full validation for free.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, get_args

import orjson

# ``scripts/`` is not an importable package, so make ``src/`` importable when
# this file is run directly or imported by the test via a sys.path insert.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

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

SPEC_PATH = Path(__file__).resolve().parents[1] / "openapi" / "integration.json"


# ---------------------------------------------------------------------------
# Endpoint coverage table.
#
# AUTHORITATIVE, HAND-MAINTAINED mapping of every covered spec endpoint to the
# client method that implements it. Adding a new ``*_public`` method (or any
# other public-API call) REQUIRES adding its ``(METHOD, path)`` row here — a
# spec endpoint missing from this table reads as a new/uncovered endpoint and
# raises a warning. Keys use the spec's own path strings (``{id}`` etc.).
# ---------------------------------------------------------------------------
_ENDPOINT_TO_METHOD: dict[tuple[str, str], str] = {
    ("GET", "/v1/meta/info"): "get_meta_info",
    ("GET", "/v1/nvrs"): "get_nvr_public",
    # Cameras
    ("GET", "/v1/cameras"): "get_cameras_public",
    ("GET", "/v1/cameras/{id}"): "get_camera_public",
    ("PATCH", "/v1/cameras/{id}"): "update_camera_public",
    ("GET", "/v1/cameras/{id}/snapshot"): "get_public_api_camera_snapshot",
    ("POST", "/v1/cameras/{id}/rtsps-stream"): "create_camera_rtsps_streams",
    ("GET", "/v1/cameras/{id}/rtsps-stream"): "get_camera_rtsps_streams",
    ("DELETE", "/v1/cameras/{id}/rtsps-stream"): "delete_camera_rtsps_streams",
    ("POST", "/v1/cameras/{id}/talkback-session"): "create_talkback_session_public",
    (
        "POST",
        "/v1/cameras/{id}/disable-mic-permanently",
    ): "disable_camera_mic_permanently_public",
    ("POST", "/v1/cameras/{id}/ptz/goto/{slot}"): "ptz_goto_preset_public",
    ("POST", "/v1/cameras/{id}/ptz/patrol/start/{slot}"): "ptz_patrol_start_public",
    ("POST", "/v1/cameras/{id}/ptz/patrol/stop"): "ptz_patrol_stop_public",
    # Lights
    ("GET", "/v1/lights"): "get_lights_public",
    ("GET", "/v1/lights/{id}"): "get_light_public",
    ("PATCH", "/v1/lights/{id}"): "update_light_public",
    # Chimes
    ("GET", "/v1/chimes"): "get_chimes_public",
    ("GET", "/v1/chimes/{id}"): "get_chime_public",
    ("PATCH", "/v1/chimes/{id}"): "update_chime_public",
    # Sensors
    ("GET", "/v1/sensors"): "get_sensors_public",
    ("GET", "/v1/sensors/{id}"): "get_sensor_public",
    ("PATCH", "/v1/sensors/{id}"): "update_sensor_public",
    # Sirens
    ("GET", "/v1/sirens"): "get_sirens_public",
    ("GET", "/v1/sirens/{id}"): "get_siren_public",
    ("PATCH", "/v1/sirens/{id}"): "update_siren_public",
    ("POST", "/v1/sirens/{id}/play"): "play_siren_public",
    ("POST", "/v1/sirens/{id}/stop"): "stop_siren_public",
    ("POST", "/v1/sirens/{id}/test-sound"): "test_siren_sound_public",
    # Relays
    ("GET", "/v1/relays"): "get_relays_public",
    ("GET", "/v1/relays/{id}"): "get_relay_public",
    ("PATCH", "/v1/relays/{id}"): "update_relay_public",
    (
        "POST",
        "/v1/relays/{id}/outputs/{outputId}/activate",
    ): "activate_relay_output_public",
    # Fobs
    ("GET", "/v1/fobs"): "get_fobs_public",
    ("GET", "/v1/fobs/{id}"): "get_fob_public",
    ("PATCH", "/v1/fobs/{id}"): "update_fob_public",
    # Speakers
    ("GET", "/v1/speakers"): "get_speakers_public",
    ("GET", "/v1/speakers/{id}"): "get_speaker_public",
    ("PATCH", "/v1/speakers/{id}"): "update_speaker_public",
    ("POST", "/v1/speakers/{id}/test-sound"): "test_speaker_sound_public",
    # Link stations / alarm hubs (one device family, two URL aliases)
    ("GET", "/v1/link-stations"): "get_link_stations_public",
    ("GET", "/v1/link-stations/{id}"): "get_link_station_public",
    ("PATCH", "/v1/link-stations/{id}"): "update_link_station_public",
    ("GET", "/v1/alarm-hubs"): "get_alarm_hubs_public",
    ("GET", "/v1/alarm-hubs/{id}"): "get_alarm_hub_public",
    ("PATCH", "/v1/alarm-hubs/{id}"): "update_alarm_hub_public",
    (
        "POST",
        "/v1/alarm-hubs/{id}/outputs/{outputId}/trigger",
    ): "trigger_alarm_hub_output_public",
    # Bridges
    ("GET", "/v1/bridges"): "get_bridges_public",
    ("GET", "/v1/bridges/{id}"): "get_bridge_public",
    ("PATCH", "/v1/bridges/{id}"): "update_bridge_public",
    # Viewers
    ("GET", "/v1/viewers"): "get_viewers_public",
    ("GET", "/v1/viewers/{id}"): "get_viewer_public",
    ("PATCH", "/v1/viewers/{id}"): "update_viewer_public",
    # Liveviews
    ("GET", "/v1/liveviews"): "get_liveviews_public",
    ("POST", "/v1/liveviews"): "create_liveview_public",
    ("GET", "/v1/liveviews/{id}"): "get_liveview_public",
    ("PATCH", "/v1/liveviews/{id}"): "update_liveview_public",
    # Arm profiles / alarm manager
    ("GET", "/v1/arm-profiles"): "get_arm_profiles_public",
    ("POST", "/v1/arm-profiles"): "create_arm_profile_public",
    ("PATCH", "/v1/arm-profiles/{id}"): "update_arm_profile_public",
    ("DELETE", "/v1/arm-profiles/{id}"): "delete_arm_profile_public",
    ("PATCH", "/v1/arm-profiles/settings"): "set_current_arm_profile_public",
    ("POST", "/v1/arm-profiles/enable"): "enable_arm_alarm_public",
    ("POST", "/v1/arm-profiles/disable"): "disable_arm_alarm_public",
    ("POST", "/v1/alarm-manager/webhook/{id}"): "send_alarm_webhook_public",
    # Users
    ("GET", "/v1/users"): "get_users_public",
    ("GET", "/v1/users/{id}"): "get_user_public",
    ("GET", "/v1/ulp-users"): "get_ulp_users_public",
    ("GET", "/v1/ulp-users/{id}"): "get_ulp_user_public",
    # Files
    ("GET", "/v1/files/{fileType}"): "get_files_public",
    ("POST", "/v1/files/{fileType}"): "upload_file_public",
    # WebSocket subscriptions
    ("GET", "/v1/subscribe/events"): "subscribe_events",
    ("GET", "/v1/subscribe/devices"): "subscribe_devices",
}

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
    """Spec endpoints with no row in the coverage table are new-endpoint warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    for path, operations in spec.get("paths", {}).items():
        for method in operations:
            if method not in _HTTP_METHODS:
                continue
            key = (method.upper(), path)
            if key not in _ENDPOINT_TO_METHOD:
                warnings.append(
                    f"new endpoint `{method.upper()} {path}` has no client method "
                    f"(add a row to `_ENDPOINT_TO_METHOD`)"
                )
    return errors, warnings


def check_model_fields(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Compare spec schema properties against public model fields, both directions."""
    errors: list[str] = []
    warnings: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    for cls, schema_name in _MODEL_SCHEMAS:
        if schema_name not in schemas:
            continue  # private-only model or schema renamed — skip, don't crash
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


def check_required(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Spec ``required`` fields that are optional on the model are warnings.

    The library deliberately models every public-API field optional (older
    firmware and partial/reference responses omit them), so a required-vs-
    optional mismatch is informational, not a contract violation — it never
    blocks the green marker-bump path.
    """
    errors: list[str] = []
    warnings: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    for cls, schema_name in _MODEL_SCHEMAS:
        schema = schemas.get(schema_name)
        if schema is None:
            continue
        remaps = cls._get_unifi_remaps()
        for key in schema.get("required", []):
            name = _spec_field_name(key, remaps)
            field = cls.model_fields.get(name)
            if field is None:
                continue  # missing field already flagged by check_model_fields
            if not field.is_required():
                warnings.append(
                    f"{schema_name}: spec requires `{key}` but model field "
                    f"`{name}` is optional"
                )
    return errors, warnings


def check_enums(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Spec enum values absent from the matching library enum are warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    for enum_cls, schema_name in _ENUM_SCHEMAS:
        schema = schemas.get(schema_name)
        if schema is None or "enum" not in schema:
            continue
        lib_values = {member.value for member in enum_cls}
        warnings.extend(
            f"{schema_name}: spec enum value `{value}` absent from "
            f"`{enum_cls.__name__}`"
            for value in schema["enum"]
            if value not in lib_values
        )
    return errors, warnings


_CHECKS = (check_endpoints, check_model_fields, check_required, check_enums)


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
    print(format_summary(errors, warnings, version))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
