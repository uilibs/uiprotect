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
* spec enum values absent from the matching library enum (warning),
* inbound spec enums and ``const`` discriminators with no library counterpart
  (error),
* spec ``event`` union types absent from ``PUBLIC_EVENT_TYPES``, or modelled
  types the spec no longer declares (error).
* JSON request bodies the client sends that fail the spec's ``requestBody``
  schema under Draft 2020-12 validation (error), and spec body fields the
  client never sends (warning).

The library deliberately models every public-API field optional (older firmware
and partial/reference responses omit them), so spec ``required`` vs. response
model ``optional`` is not checked — it would be guaranteed noise on every run.

Exits non-zero on any error and prints a markdown summary the spec-validation
workflow embeds in a drift issue. The check functions are also imported by
``tests/test_public_schema_conformance.py`` so a contributor who fetches the
spec locally runs the full validation for free.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import functools
import importlib
import inspect
import json
import pkgutil
import re
import sys
from datetime import timedelta
from pathlib import Path
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

import orjson
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

# ``scripts/`` is not an importable package, so make ``src/`` importable when
# this file is run directly or imported by the test via a sys.path insert.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from uiprotect import data as uiprotect_data  # noqa: E402
from uiprotect._public_api import registry  # noqa: E402
from uiprotect.api import ProtectApiClient  # noqa: E402
from uiprotect.data import (  # noqa: E402
    PUBLIC_EVENT_TYPES,
    ArmProfile,
    Fob,
    LinkStation,
    PublicBridge,
    PublicCamera,
    PublicChime,
    PublicEvent,
    PublicLight,
    PublicLiveview,
    PublicNVR,
    PublicPosTransactionResponse,
    PublicSensor,
    PublicUlpUser,
    PublicUser,
    PublicViewer,
    Relay,
    Siren,
    Speaker,
)
from uiprotect.data.base import ProtectBaseObject  # noqa: E402
from uiprotect.data.types import DeviceState, DoorbellMessageType  # noqa: E402
from uiprotect.utils import to_snake_case  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

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
_PLACEHOLDER_NAME_RE = re.compile(r"\{(\w+)\}")
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


# One example call per hand-written (non-declarative) public-API coroutine,
# given as its positional path arguments; every remaining parameter gets a
# type-correct value from ``_example_value``. Each call runs against a throw-away
# client whose ``request`` is spied on, so it records its ``(verb, path)`` and
# JSON body, then short-circuits before any network I/O. Passing every
# parameter also keeps ``update_liveview_public`` from fetching the liveview.
_S = _RECORD_SENTINEL
_EXAMPLE_CALLS: dict[str, tuple[Any, ...]] = {
    "get_public_api_camera_snapshot": (_S,),
    "create_camera_rtsps_streams": (_S,),
    "get_camera_rtsps_streams": (_S,),
    "delete_camera_rtsps_streams": (_S,),
    "create_talkback_session_public": (_S,),
    "disable_camera_mic_permanently_public": (_S,),
    "update_camera_public": (_S,),
    "update_light_public": (_S,),
    "update_sensor_public": (_S,),
    "update_siren_public": (_S,),
    "play_siren_public": (_S,),
    "test_siren_sound_public": (_S,),
    "update_relay_public": (_S,),
    "activate_relay_output_public": (_S, _S),
    "test_speaker_sound_public": (_S,),
    "trigger_alarm_hub_output_public": (_S, _S),
    "get_bridge_public": (_S,),
    "update_bridge_public": (_S,),
    "get_viewer_public": (_S,),
    "update_viewer_public": (_S,),
    "get_liveviews_public": (),
    "get_liveview_public": (_S,),
    "create_liveview_public": (),
    "update_liveview_public": (_S,),
    "send_alarm_webhook_public": (_S,),
    "get_arm_profiles_public": (),
    "create_arm_profile_public": (),
    "update_arm_profile_public": (_S,),
    "delete_arm_profile_public": (_S,),
    "get_arm_manager_settings_public": (),
    "set_current_arm_profile_public": (_S,),
    "enable_arm_alarm_public": (),
    "disable_arm_alarm_public": (),
    "get_files_public": (_S,),
    "upload_file_public": (_S,),
    "update_public": (),
}

# Keyword arguments an example call cannot derive from the signature alone;
# ``None`` leaves the parameter unset.
_EXAMPLE_KWARG_OVERRIDES: dict[str, dict[str, Any]] = {
    # Rejected on update with ``BadRequest``.
    "update_liveview_public": {"is_default": None, "owner": None},
    # ``text`` is only valid with the custom-message and image variants.
    "update_camera_public": {
        "lcd_message": {
            "type": DoorbellMessageType.CUSTOM_MESSAGE,
            "text": _S,
            "resetAt": 1,
        }
    },
}

_SCALAR_EXAMPLES: dict[Any, Any] = {
    bool: True,
    int: 1,
    float: 1.5,
    str: _S,
    bytes: b"x",
    timedelta: timedelta(seconds=1),
}


@functools.cache
def _type_namespace() -> dict[str, Any]:
    """Names the client's ``TYPE_CHECKING``-only annotations resolve against."""
    namespace: dict[str, Any] = {}
    for module in (*_iter_data_modules(uiprotect_data), uiprotect_data):
        namespace.update(vars(module))
    return namespace


def _type_hints(obj: Any) -> dict[str, Any]:
    """Resolved annotations of a function or ``TypedDict``."""
    return get_type_hints(obj, localns=_type_namespace())


def _is_specific(annotation: Any) -> bool:
    """Whether a union arm pins the wire value tighter than a bare scalar."""
    if get_origin(annotation) is Literal or is_typeddict(annotation):
        return True
    return isinstance(annotation, type) and issubclass(
        annotation, enum.Enum | ProtectBaseObject
    )


def _example_value(annotation: Any) -> Any:  # noqa: PLR0911
    """A type-correct value for ``annotation``; raises for an unsupported type."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        arms = [arm for arm in get_args(annotation) if arm is not type(None)]
        return _example_value(next((a for a in arms if _is_specific(a)), arms[0]))
    if origin is Literal:
        return get_args(annotation)[0]
    if origin is list:
        return [_example_value(get_args(annotation)[0])]
    if is_typeddict(annotation):
        return {
            key: _example_value(hint) for key, hint in _type_hints(annotation).items()
        }
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return next(m for m in annotation if m.value != _ENUM_SENTINEL)
    if isinstance(annotation, type) and issubclass(annotation, ProtectBaseObject):
        return annotation(
            **{
                name: _example_value(field.annotation)
                for name, field in annotation.model_fields.items()
            }
        )
    if annotation in _SCALAR_EXAMPLES:
        return _SCALAR_EXAMPLES[annotation]
    raise TypeError(f"no example value for annotation {annotation!r}")


def _example_params(name: str) -> list[str]:
    """Parameter names of client method ``name``, ``self`` excluded."""
    func = getattr(ProtectApiClient, name)
    return [p for p in inspect.signature(func).parameters if p != "self"]


def _example_kwargs(name: str, skip: int) -> dict[str, Any]:
    """Example kwargs for client method ``name`` past its first ``skip`` arguments."""
    hints = _type_hints(getattr(ProtectApiClient, name))
    params = _example_params(name)[skip:]
    kwargs: dict[str, Any] = {}
    for param in params:
        try:
            kwargs[param] = _example_value(hints[param])
        except TypeError as err:
            raise TypeError(f"{name}({param}): {err}") from err
    overrides = _EXAMPLE_KWARG_OVERRIDES.get(name, {})
    kwargs.update({k: v for k, v in overrides.items() if k in params})
    return kwargs


def _model_arms(annotation: Any) -> list[type[ProtectBaseObject]]:
    """Model types in ``annotation`` constructible without arguments."""
    arms = get_args(annotation) if get_origin(annotation) in (Union, UnionType) else ()
    return [
        arm
        for arm in arms or (annotation,)
        if isinstance(arm, type)
        and issubclass(arm, ProtectBaseObject)
        and not any(field.is_required() for field in arm.model_fields.values())
    ]


def _defaults_only(name: str, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    """``kwargs`` once per model-typed parameter, with that model left at defaults."""
    hints = _type_hints(getattr(ProtectApiClient, name))
    return [
        {**kwargs, param: arm()}
        for param in kwargs
        for arm in _model_arms(hints[param])
    ]


def _stale_kwarg_overrides() -> list[str]:
    """``method(parameter)`` for every override that matches no example parameter."""
    planned = set(_EXAMPLE_CALLS) | set(
        registry.for_class(ProtectApiClient.__name__).values()
    )
    return [
        f"{name}({param})"
        for name, overrides in _EXAMPLE_KWARG_OVERRIDES.items()
        for param in overrides
        if name not in planned or param not in _example_params(name)
    ]


_Endpoint = tuple[str, str]
_ExampleCall = tuple[str, tuple[Any, ...], dict[str, Any]]


def _example_call_plan() -> list[_ExampleCall]:
    """``(method, args, kwargs)`` per example call and decorated body endpoint."""
    calls = [
        (name, args, _example_kwargs(name, len(args)))
        for name, args in _EXAMPLE_CALLS.items()
    ]
    for (verb, path), name in registry.for_class(ProtectApiClient.__name__).items():
        if verb in ("patch", "post"):
            kwargs = _example_kwargs(name, 0)
            kwargs.update(dict.fromkeys(_PLACEHOLDER_NAME_RE.findall(path), _S))
            calls.append((name, (), kwargs))
    plan: list[_ExampleCall] = []
    for name, args, kwargs in calls:
        plan.append((name, args, kwargs))
        plan.extend((name, args, other) for other in _defaults_only(name, kwargs))
    return plan


class _ShortCircuitError(Exception):
    """Raised by the request spy to abort an example call before network I/O."""


async def _record_example_calls(
    plan: list[_ExampleCall],
) -> tuple[set[_Endpoint], dict[_Endpoint, list[Any]]]:
    """Run ``plan`` against a spied client; return recorded paths and JSON bodies."""
    client = ProtectApiClient.public_only("127.0.0.1", 443, api_key="x")
    recorded: set[_Endpoint] = set()
    bodies: dict[_Endpoint, list[Any]] = {}
    prefix = client.public_api_path

    async def _spy(method: str, url: str, *_args: Any, **kwargs: Any) -> Any:
        endpoint = (method.upper(), _normalize_path(url.removeprefix(prefix)))
        recorded.add(endpoint)
        if kwargs.get("json") is not None:
            bodies.setdefault(endpoint, []).append(kwargs["json"])
        raise _ShortCircuitError

    client.request = _spy  # type: ignore[method-assign]
    for name, args, kwargs in plan:
        # ``update_public`` gathers its fetches with ``return_exceptions=True``
        # and swallows the sentinel; the others propagate it. Either way the
        # spy has already recorded every path the call reached.
        with contextlib.suppress(_ShortCircuitError):
            await getattr(client, name)(*args, **kwargs)
    return recorded, bodies


@functools.cache
def _recorded_calls() -> tuple[frozenset[_Endpoint], dict[_Endpoint, list[Any]]]:
    """Cached ``_record_example_calls`` result: recorded paths and JSON bodies."""
    recorded, bodies = asyncio.run(_record_example_calls(_example_call_plan()))
    return frozenset(recorded), bodies


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


def covered_endpoints() -> frozenset[tuple[str, str]]:
    """Derived union of declarative, recorded, and websocket-subscription endpoints."""
    recorded, _bodies = _recorded_calls()
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
    (Siren, "siren"),
    (Relay, "relay"),
    (Speaker, "speaker"),
    (Fob, "fob"),
    (LinkStation, "linkStation"),
    (PublicUser, "user"),
    (PublicUlpUser, "ulpUser"),
    (ArmProfile, "armProfile"),
    # ``event`` is a ``oneOf`` union; its variants are merged into one property
    # map, matching the single all-optional ``PublicEvent`` model.
    (PublicEvent, "event"),
    (PublicPosTransactionResponse, "posTransactionResponse"),
]

# Spec enum schemas with a known library counterpart. Spec values absent from
# the lib enum are warnings; the lib's ``UNKNOWN`` sentinel is ignored.
_ENUM_SCHEMAS: list[tuple[type[Any], str]] = [
    (DeviceState, "deviceState"),
]

# The library's forward-compat sentinel value, ignored on both sides of the
# enum-coverage comparison so a lib enum that models ``UNKNOWN`` still counts as
# covering a spec enum regardless of whether either side lists a literal
# ``unknown``.
_ENUM_SENTINEL = "unknown"

# Spec enums whose value-set is a strict *subset* of a single, explicitly named
# library enum that the public models already type the field with. The library
# enum is a forward-compatible superset — it also carries values from the
# private API or newer firmware (e.g. ``VideoMode``'s ``homekit``) — so an exact
# value-set match is impossible by design, yet the field IS faithfully typed.
# Each entry is pinned to ONE named enum and verified ``spec ⊆ lib`` at runtime,
# so a coincidental value-set collision can never satisfy it (that was the v1
# any-subset false-negative). A spec value that grows beyond the named enum
# changes the value-set, breaks the key match, and re-surfaces the enum as an
# unmodelled warning.
_MODELLED_AS_SUBSET: dict[frozenset[str], str] = {
    frozenset(
        {"default", "highFps", "sport", "slowShutter", "lprReflex", "lprNoneReflex"}
    ): "VideoMode",
    frozenset({"neutral", "low", "safe", "high"}): "SensorStatusType",
    frozenset(
        {"animal", "face", "licensePlate", "package", "person", "vehicle"}
    ): "SmartDetectObjectType",
    frozenset(
        {
            "alrmBabyCry",
            "alrmBark",
            "alrmBurglar",
            "alrmCarHorn",
            "alrmCmonx",
            "alrmGlassBreak",
            "alrmSiren",
            "alrmSmoke",
            "alrmSpeak",
        }
    ): "SmartDetectAudioType",
}

# Inbound spec enums (reachable from a response the library deserializes)
# intentionally left untyped, kept opaque pending a dedicated modelling effort.
# Outbound-only enums (request param / body) need no entry — they are waived by
# direction. Each waiver is keyed by ``(owning component schema, value-set)`` —
# the value-set alone would let a waiver for a generic set like ``{closed,
# open}`` silently cover an unrelated future enum on another schema. Waivers are
# the rare, documented exception: the default is to model.
_ENUM_COVERAGE_WAIVERS: dict[tuple[str, frozenset[str]], str] = {
    # ``alarmHubStatus`` electrical internals (input power, current-meter,
    # terminal and e-fuse status). Kept as opaque ``additionalProperties`` — a
    # private value space deferred to a separate modelling effort.
    (
        "alarmHubStatus",
        frozenset({"high", "low"}),
    ): "alarm-hub inputPower status (deferred)",
    (
        "alarmHubStatus",
        frozenset({"alert", "normal"}),
    ): "alarm-hub criticalAlarm status (deferred)",
    (
        "alarmHubStatus",
        frozenset({"fault", "normal", "warning"}),
    ): "alarm-hub efuse status (deferred)",
    (
        "alarmHubStatus",
        frozenset({"closed", "open"}),
    ): "alarm-hub input idleSubState (deferred)",
    (
        "alarmHubStatus",
        frozenset(
            {"cut", "disabled", "idle", "not-connected", "short", "tamper", "triggered"}
        ),
    ): "alarm-hub plusPinStatus (deferred)",
    (
        "alarmHubStatus",
        frozenset(
            {
                "cut",
                "disabled",
                "idle",
                "not-connected",
                "partially-connected",
                "short",
                "tamper",
                "triggered",
            }
        ),
    ): "alarm-hub terminalStatus (deferred)",
    (
        "alarmHubStatus",
        frozenset({"high-current", "none", "over-current"}),
    ): "alarm-hub output efuseAlert (deferred)",
    (
        "alarmHubStatus",
        frozenset({"dry-contact", "powered-12v"}),
    ): "alarm-hub output mode (deferred)",
    (
        "alarmHubStatus",
        frozenset({"active", "disabled", "off"}),
    ): "alarm-hub output statusLabel (deferred)",
    (
        "alarmHubStatus",
        frozenset({"+", "-", "com", "nc", "no"}),
    ): "alarm-hub output wiredPins (deferred)",
    (
        "alarmHubStatus",
        frozenset({"connected", "not-connected", "partially-connected"}),
    ): "alarm-hub auxiliaryPower status (deferred)",
}

# Library-owned fields populated out-of-band, absent from the spec schema.
# Fields the library owns that no spec revision lists (computed convenience).
_LIBRARY_OWNED_FIELDS: dict[str, set[str]] = {
    "camera": {"rtsps_streams"},
    "event.metadata": {"status_text"},
}

# Model fields not present in the spec schema; excluded from the drift error.
_EXTRA_MODEL_FIELDS: dict[str, set[str]] = {
    "camera": {"device_type", "device_guid"},
    "light": {"device_type", "device_guid"},
    "sensor": {"device_type", "device_guid"},
    "chime": {"device_type", "device_guid"},
    "nvr": {"device_type", "device_guid"},
    "viewer": {"device_type", "device_guid"},
    "bridge": {"device_type", "device_guid"},
    # ``alarmHubDeviceTamper`` ``userName`` first appears in the 7.3 spec.
    "event.metadata": {"user_name"},
    # Fob arm-control/keypad settings and link-station Thread state first
    # appear in the 7.3 spec.
    "fob": {"arm_control_settings", "keypad_settings"},
    "fob.featureFlags": {"has_keypad"},
    "linkStation": {"thread_state"},
}

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _merge_variants(
    variants: list[dict[str, Any]], schemas: dict[str, Any]
) -> dict[str, dict[str, Any]] | None:
    """Union the object variants of an ``allOf`` / ``oneOf`` into one property map."""
    merged: dict[str, dict[str, Any]] = {}
    is_object = False
    for sub in variants:
        resolved = _resolve_object_props(sub, schemas)
        if resolved is None:
            continue
        is_object = True
        for key, schema in resolved.items():
            previous = merged.get(key)
            if previous is not None and previous != schema:
                # A property several variants disagree on (the per-event-type
                # ``metadata`` blocks) is itself a union; re-wrap it so a
                # recursive resolve merges those the same way.
                merged[key] = {"oneOf": [previous, schema]}
            else:
                merged[key] = schema
    return merged if is_object else None


def _resolve_object_props(
    node: dict[str, Any], schemas: dict[str, Any]
) -> dict[str, dict[str, Any]] | None:
    """Return ``{property: schema}`` for an object node, ``None`` for scalar leaves."""
    if "$ref" in node:
        return _resolve_object_props(schemas[node["$ref"].split("/")[-1]], schemas)
    if "allOf" in node:
        return _merge_variants(node["allOf"], schemas)
    if "oneOf" in node:
        return _merge_variants(node["oneOf"], schemas)
    if node.get("type") == "array":
        return _resolve_object_props(node.get("items", {}), schemas)
    if "properties" in node:
        return dict(node["properties"])
    return None


def _resolve_const(node: dict[str, Any], schemas: dict[str, Any]) -> str | None:
    """
    Follow ``$ref`` / ``allOf`` / ``oneOf`` to the string ``const`` a node declares.

    A ``oneOf`` resolves only when every variant agrees on the same value — which
    is what ``_merge_variants`` produces when several union members declare the
    same discriminator with differing siblings. Genuine disagreement (or a
    variant carrying no const at all) returns ``None``.
    """
    if "$ref" in node:
        return _resolve_const(schemas.get(node["$ref"].split("/")[-1], {}), schemas)
    if "allOf" in node:
        for sub in node["allOf"]:
            const = _resolve_const(sub, schemas)
            if const is not None:
                return const
        return None
    if "oneOf" in node:
        consts = {_resolve_const(sub, schemas) for sub in node["oneOf"]}
        return consts.pop() if len(consts) == 1 else None
    value = node.get("const")
    return value if isinstance(value, str) else None


def _union_variants(
    node: dict[str, Any], schemas: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """Flatten a ``$ref``/``oneOf`` chain into its leaf variants, ``None`` if not a union."""
    if "$ref" in node:
        return _union_variants(schemas.get(node["$ref"].split("/")[-1], {}), schemas)
    variants = node.get("oneOf")
    if not variants:
        return None
    leaves: list[dict[str, Any]] = []
    for sub in variants:
        nested = _union_variants(sub, schemas)
        leaves.extend(nested if nested is not None else [sub])
    return leaves


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
    """Return the model field name for a spec key after remap + snake-case normalization."""
    return to_snake_case(remaps.get(key) or key)


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
        for model, model_props, path in walk_models(cls, props, schemas, schema_name):
            remaps = model._get_unifi_remaps()
            spec_fields = {_spec_field_name(key, remaps) for key in model_props}
            model_fields = set(model.model_fields)
            removed = (
                model_fields
                - spec_fields
                - _LIBRARY_OWNED_FIELDS.get(path, set())
                - _EXTRA_MODEL_FIELDS.get(path, set())
            )
            errors.extend(
                f"{path}: model field `{name}` absent from spec "
                f"(server removed/retyped it)"
                for name in sorted(removed)
            )
            warnings.extend(
                f"{path}: spec field `{name}` has no model counterpart"
                for name in sorted(spec_fields - model_fields)
            )
            errors.extend(
                f"{path}: model field `{name}` expects an object but the spec "
                f"retyped it to a scalar"
                for name in _scalar_retyped_fields(model, model_props, schemas)
            )
    return errors, warnings


def _scalar_retyped_fields(
    cls: type[ProtectBaseObject],
    props: dict[str, dict[str, Any]],
    schemas: dict[str, Any],
) -> list[str]:
    """Model-typed fields whose spec schema no longer resolves to an object."""
    remaps = cls._get_unifi_remaps()
    retyped: list[str] = []
    for key, prop_schema in props.items():
        name = _spec_field_name(key, remaps)
        field = cls.model_fields.get(name)
        if (
            field is not None
            and _leaf_model(field.annotation) is not None
            and _resolve_object_props(prop_schema, schemas) is None
        ):
            retyped.append(name)
    return sorted(retyped)


def walk_models(
    cls: type[ProtectBaseObject],
    props: dict[str, dict[str, Any]],
    schemas: dict[str, Any],
    path: str,
) -> Iterator[tuple[type[ProtectBaseObject], dict[str, dict[str, Any]], str]]:
    """Yield ``(cls, props, path)`` for a model and every nested object-backed model."""
    yield cls, props, path
    remaps = cls._get_unifi_remaps()
    for key, prop_schema in props.items():
        nested_props = _resolve_object_props(prop_schema, schemas)
        if nested_props is None:
            continue
        field = cls.model_fields.get(_spec_field_name(key, remaps))
        if field is None:
            continue
        leaf = _leaf_model(field.annotation)
        if leaf is not None:
            yield from walk_models(leaf, nested_props, schemas, f"{path}.{key}")


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


def _iter_data_modules(data_pkg: Any) -> list[Any]:
    """Import and return every submodule of the ``uiprotect.data`` package."""
    return [
        importlib.import_module(info.name)
        for info in pkgutil.walk_packages(data_pkg.__path__, f"{data_pkg.__name__}.")
    ]


@functools.cache
def _library_enum_classes() -> list[type[enum.Enum]]:
    """Every ``enum.Enum`` declared under the ``uiprotect.data`` package."""
    return [
        obj
        for module in (uiprotect_data, *_iter_data_modules(uiprotect_data))
        for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, enum.Enum)
    ]


def _library_enums_by_name() -> dict[str, frozenset[str]]:
    """Value-set (minus the sentinel) of every ``enum.Enum`` under ``uiprotect.data``."""
    out: dict[str, frozenset[str]] = {}
    for obj in _library_enum_classes():
        value_set = frozenset(str(m.value) for m in obj) - {_ENUM_SENTINEL}
        if value_set:
            out[obj.__name__] = value_set
    return out


def _library_enum_values() -> frozenset[str]:
    """
    Every value any library enum defines, sentinel included.

    The const rule compares against this rather than the sentinel-stripped
    per-enum sets: a spec ``const`` of ``unknown`` is a real wire value, and an
    enum declaring an ``unknown`` member does define it.
    """
    return frozenset(str(m.value) for obj in _library_enum_classes() for m in obj)


def _enum_owner(path: str) -> str:
    """Component schema an enum occurrence belongs to (the raw path elsewhere)."""
    parts = path.split(".")
    if len(parts) > 2 and parts[0] == "components":
        return parts[2]
    return path


def _enum_value_set(node: dict[str, Any]) -> frozenset[str]:
    """Value-set of a node's ``enum`` array, sentinel stripped."""
    values = node.get("enum")
    if not isinstance(values, list):
        return frozenset()
    return frozenset(str(value) for value in values) - {_ENUM_SENTINEL}


def _const_value_set(node: dict[str, Any]) -> frozenset[str]:
    """
    One-value set for a node's string ``const``.

    Unlike an ``enum`` array, ``unknown`` is kept: in a spec ``const`` it is a
    real wire value the server pins, not the library's forward-compat sentinel.

    Non-string consts are skipped: they enumerate allowed *numbers*
    (``sirenDuration``, ``activationDelay``), which the library models as plain
    ints rather than as an enum.
    """
    value = node.get("const")
    return frozenset({value}) if isinstance(value, str) else frozenset()


def _node_value_sets(node: dict[str, Any]) -> tuple[frozenset[str], ...]:
    """Every non-empty value-set a single schema node declares."""
    return tuple(
        value_set
        for value_set in (_enum_value_set(node), _const_value_set(node))
        if value_set
    )


def _iter_spec_value_sets(
    spec: dict[str, Any],
    extract: Callable[[dict[str, Any]], frozenset[str]],
) -> list[tuple[frozenset[str], str]]:
    """Every value-set ``extract`` finds in the spec, once per owning schema."""
    found: dict[tuple[str, frozenset[str]], str] = {}

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            key = extract(node)
            if key:
                found.setdefault((_enum_owner(path), key), path)
            for key_name, child in node.items():
                _walk(child, f"{path}.{key_name}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                _walk(child, f"{path}[{index}]")

    _walk(spec.get("components", {}).get("schemas", {}), "components.schemas")
    _walk(spec.get("paths", {}), "paths")
    return sorted(
        ((key[1], path) for key, path in found.items()), key=lambda item: item[1]
    )


def _iter_spec_enums(spec: dict[str, Any]) -> list[tuple[frozenset[str], str]]:
    """Every enum value-set in the spec (named or inline), once per owning schema."""
    return _iter_spec_value_sets(spec, _enum_value_set)


def _iter_spec_consts(spec: dict[str, Any]) -> list[tuple[frozenset[str], str]]:
    """Every string ``const`` in the spec, once per owning schema."""
    return _iter_spec_value_sets(spec, _const_value_set)


def _reachable_enum_ids(
    roots: list[tuple[Any, str]], schemas: dict[str, Any]
) -> set[tuple[str, frozenset[str]]]:
    """Enum occurrence identities reachable from ``roots``, following ``$ref``."""
    out: set[tuple[str, frozenset[str]]] = set()
    seen_refs: set[str] = set()

    def _walk(node: Any, path: str, owner: str | None) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.split("/")[-1]
                if name not in seen_refs:
                    seen_refs.add(name)
                    _walk(schemas.get(name, {}), f"components.schemas.{name}", name)
                return
            for key in _node_value_sets(node):
                out.add((owner if owner is not None else path, key))
            for key_name, child in node.items():
                _walk(child, f"{path}.{key_name}", owner)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                _walk(child, f"{path}[{index}]", owner)

    for root, root_path in roots:
        _walk(root, root_path, None)
    return out


def _reusable_response_error(spec: dict[str, Any]) -> str | None:
    """Reject reusable responses — ``_inbound_enum_ids`` does not resolve them."""
    unsupported = "the inbound enum classification does not cover reusable responses"
    if spec.get("components", {}).get("responses"):
        return f"spec declares `components.responses`; {unsupported}"
    for path, operations in spec.get("paths", {}).items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            for code, response in operation.get("responses", {}).items():
                if isinstance(response, dict) and "$ref" in response:
                    return (
                        f"response `paths.{path}.{method}.responses.{code}` is a "
                        f"`$ref`; {unsupported}"
                    )
    return None


def _inbound_enum_ids(spec: dict[str, Any]) -> set[tuple[str, frozenset[str]]]:
    """Enum occurrence identities reachable from any response body schema."""
    schemas = spec.get("components", {}).get("schemas", {})
    roots: list[tuple[Any, str]] = [
        (
            media["schema"],
            f"paths.{path}.{method}.responses.{code}.content.{media_type}.schema",
        )
        for path, operations in spec.get("paths", {}).items()
        if isinstance(operations, dict)
        for method, operation in operations.items()
        if isinstance(operation, dict)
        for code, response in operation.get("responses", {}).items()
        if isinstance(response, dict)
        for media_type, media in response.get("content", {}).items()
        if isinstance(media, dict) and "schema" in media
    ]
    return _reachable_enum_ids(roots, schemas)


def check_enum_coverage(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Every inbound spec enum and ``const`` must be modelled or explicitly waived.

    Coverage is decided on the value-set alone — an exact match proves some
    library enum carries those values, not that the owning model field is
    annotated with it.

    The ``const`` half is weaker still, and is a **lint for new vocabulary, not
    a conformance check**. A const declares a single value, so no library enum
    can ever *equal* its value-set; it is treated as covered when any library
    enum anywhere defines the value. A const that changes from one value the
    library already knows to another is therefore invisible here — only a value
    no enum defines at all is reported. ``check_event_types`` closes that gap
    for the ``event`` union's ``type`` const and nothing else: the remaining
    const occurrences (``*ModelKey``, ``WSAction`` ``type``, the ``lightMode``
    and ``enableAt`` discriminators) have no equivalent per-axis pin.
    """
    errors: list[str] = []
    reusable = _reusable_response_error(spec)
    if reusable is not None:
        return [reusable], []
    lib_by_name = _library_enums_by_name()
    exact_sets = set(lib_by_name.values())
    const_values = _library_enum_values()
    inbound = _inbound_enum_ids(spec)

    def _reportable(value_set: frozenset[str], path: str) -> bool:
        """Inbound occurrence carrying no waiver; outbound-only is waived by direction."""
        identity = (_enum_owner(path), value_set)
        return identity not in _ENUM_COVERAGE_WAIVERS and identity in inbound

    for value_set, path in _iter_spec_enums(spec):
        if value_set in exact_sets:
            continue
        mapped = _MODELLED_AS_SUBSET.get(value_set)
        if mapped is not None:
            missing = value_set - lib_by_name.get(mapped, frozenset())
            if not missing:
                continue
            errors.append(
                f"spec enum at `{path}` is mapped to `{mapped}` in "
                f"`_MODELLED_AS_SUBSET` but `{mapped}` no longer defines value(s) "
                f"{sorted(missing)} (enum renamed or members removed)"
            )
            continue
        if _reportable(value_set, path):
            errors.append(
                f"inbound spec enum at `{path}` (values {sorted(value_set)}) is not "
                f"modelled by any library enum, not mapped in `_MODELLED_AS_SUBSET`, "
                f"and not waived in `_ENUM_COVERAGE_WAIVERS`"
            )
    errors.extend(
        f"inbound spec const at `{path}` (value {min(value_set)!r}) is not "
        f"defined by any library enum and not waived in `_ENUM_COVERAGE_WAIVERS`"
        for value_set, path in _iter_spec_consts(spec)
        if not value_set <= const_values and _reportable(value_set, path)
    )
    return errors, []


def check_event_types(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    ``PUBLIC_EVENT_TYPES`` must equal the ``type`` consts of the ``event`` union.

    ``EventType`` has no ``unknown`` member, so an event type the spec declares
    and the library does not raises on parse and the event is dropped; both
    directions are therefore errors.

    Nested unions are flattened first: the server is free to group a family of
    event schemas behind its own ``oneOf`` without that being drift.
    """
    errors: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    schema = schemas.get("event")
    if schema is None:
        return ["event: tracked schema absent from spec (server removed it)"], []
    variants = _union_variants(schema, schemas)
    if not variants:
        return ["event: spec schema no longer declares a `oneOf` union"], []
    spec_types: set[str] = set()
    for index, variant in enumerate(variants):
        props = _resolve_object_props(variant, schemas) or {}
        const = _resolve_const(props.get("type", {}), schemas)
        if const is not None:
            spec_types.add(const)
        else:
            errors.append(
                f"event: `oneOf[{index}]` "
                f"({variant.get('$ref', '<inline>')}) declares no `type` const"
            )
    modelled = {event_type.value for event_type in PUBLIC_EVENT_TYPES}
    errors.extend(
        f"event: spec event type `{value}` is absent from `PUBLIC_EVENT_TYPES`"
        for value in sorted(spec_types - modelled)
    )
    errors.extend(
        f"event: `PUBLIC_EVENT_TYPES` models `{value}`, absent from the spec "
        f"`event` union (server removed it)"
        for value in sorted(modelled - spec_types)
    )
    return errors, []


_VALUE_RANGE_KEYWORDS = frozenset(
    {
        "pattern",
        "format",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
    }
)
# Keywords whose value is instance data, not a subschema; never walked.
_DATA_KEYWORDS = frozenset({"const", "default", "enum", "example", "examples"})


def _is_numeric_const(key: str, value: Any) -> bool:
    """Whether ``key: value`` is a numeric ``const``."""
    return (
        key == "const"
        and isinstance(value, int | float)
        and not isinstance(value, bool)
    )


_JSON_MEDIA_TYPE = "application/json"

# Request-body findings the spec raises against a correct client, keyed by
# ``(VERB, spec path, body field, validator keyword)``. A waiver the spec no
# longer triggers is reported as a warning so the table cannot rot.
_REQUEST_BODY_WAIVERS: dict[tuple[str, str, str, str], str] = {
    (verb, path, field, "required"): (
        "the spec reuses the read `liveview` schema for writes; the console "
        "rejects or ignores this field"
    )
    for verb, path, fields in (
        ("POST", "/v1/liveviews", ("id", "modelKey")),
        ("PATCH", "/v1/liveviews/{id}", ("id", "modelKey", "isDefault", "owner")),
    )
    for field in fields
}


def _merge_member(out: dict[str, Any], member: dict[str, Any]) -> None:
    """Merge an object ``allOf`` member's properties and ``required`` into ``out``."""
    out.setdefault("type", "object")
    props = out.setdefault("properties", {})
    for name, sub in member["properties"].items():
        if name not in props:
            props[name] = sub
        elif props[name] != sub:
            props[name] = {"allOf": [props[name], sub]}
    required = [*out.get("required", []), *member.get("required", [])]
    if required:
        out["required"] = list(dict.fromkeys(required))


def _close_object(out: dict[str, Any], deref: Callable[[Any], Any]) -> None:
    """Drop ``readOnly`` properties from ``out`` and close it to undeclared keys."""
    props = out["properties"]
    read_only = {
        name
        for name, sub in props.items()
        if sub.get("readOnly") or deref(sub).get("readOnly")
    }
    if read_only:
        out["properties"] = {k: v for k, v in props.items() if k not in read_only}
        out["required"] = [k for k in out.get("required", []) if k not in read_only]
    # A free-form map declares no properties and a union closes its variants.
    if out["properties"] and "oneOf" not in out and "anyOf" not in out:
        out.setdefault("additionalProperties", False)


def _prepare_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``spec`` prepared for strict Draft 2020-12 request-body validation."""
    raw = spec.get("components", {}).get("schemas", {})
    prepared: dict[str, Any] = {}

    def _component(name: str) -> dict[str, Any]:
        if name not in raw:
            raise ValueError(f"dangling $ref to component schema {name!r}")
        if name not in prepared:
            # Placeholder first so a schema that reaches itself terminates.
            prepared[name] = {}
            prepared[name] = _prepare(raw[name])
        return prepared[name]

    def _deref(node: Any) -> Any:
        ref = node.get("$ref") if isinstance(node, dict) else None
        return _component(ref.split("/")[-1]) if isinstance(ref, str) else node

    # The spec writes bodies as ``{"allOf": [{"$ref": ...}],
    # "additionalProperties": false}``, which strict JSON Schema reads as "no
    # properties allowed".
    def _hoist(out: dict[str, Any]) -> None:
        kept: list[Any] = []
        for member in out.pop("allOf"):
            target = _deref(member)
            if not isinstance(target, dict) or "properties" not in target:
                kept.append(member)
                continue
            _merge_member(out, target)
        if kept:
            out["allOf"] = kept
            if "properties" not in out and out.get("additionalProperties") is False:
                del out["additionalProperties"]

    def _prepare(node: Any) -> Any:
        if isinstance(node, list):
            return [_prepare(item) for item in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        dropped_const = False
        for key, value in node.items():
            if _is_numeric_const(key, value):
                dropped_const = True
            elif key in _VALUE_RANGE_KEYWORDS:
                continue
            elif key in _DATA_KEYWORDS:
                out[key] = value
            elif key == "properties" and isinstance(value, dict):
                out[key] = {name: _prepare(sub) for name, sub in value.items()}
            else:
                out[key] = _prepare(value)
        if dropped_const and "type" not in out:
            out["type"] = "number"
        if isinstance(out.get("allOf"), list):
            _hoist(out)
        if "properties" in out:
            _close_object(out, _deref)
        return out

    components = {**spec.get("components", {}), "schemas": prepared}
    for name in raw:
        _component(name)
    return {**spec, "paths": _prepare(spec.get("paths", {})), "components": components}


def _join_field(prefix: str, name: str) -> str:
    """Dotted body-field path."""
    return f"{prefix}.{name}" if prefix else name


def _field_path(parts: Iterable[Any]) -> str:
    """Render a validator error path, collapsing array indices to ``[]``."""
    out = ""
    for part in parts:
        out = f"{out}[]" if isinstance(part, int) else _join_field(out, part)
    return out


def _body_errors(
    validator: Draft202012Validator, body: Any
) -> set[tuple[str, str, str]]:
    """``(field, validator keyword, message)`` for every way ``body`` breaks the schema."""
    found: set[tuple[str, str, str]] = set()
    for error in validator.iter_errors(body):
        base = _field_path(error.absolute_path)
        keyword = str(error.validator)
        if keyword == "required":
            found.update(
                (_join_field(base, name), keyword, "required by the spec but not sent")
                for name in error.validator_value
                if name not in error.instance
            )
        elif keyword == "additionalProperties":
            declared = error.schema.get("properties", {})
            found.update(
                (_join_field(base, name), keyword, "not declared by the spec")
                for name in error.instance
                if name not in declared
            )
        else:
            message = error.message
            if (cause := best_match(error.context)) is not None:
                message = f"{message} ({cause.message})"
            found.add((base or "<body>", keyword, message))
    return found


def _unsent_fields(
    schema: dict[str, Any], body: Any, schemas: dict[str, Any], prefix: str = ""
) -> set[str]:
    """Spec properties the client body never carries, nested objects included."""
    props = _resolve_object_props(schema, schemas)
    if props is None:
        return set()
    items = body if isinstance(body, list) else [body]
    if isinstance(body, list):
        prefix = f"{prefix}[]"
    sent = [item for item in items if isinstance(item, dict)]
    unsent: set[str] = set()
    for name, sub in props.items():
        field = _join_field(prefix, name)
        values = [item[name] for item in sent if name in item]
        if not values:
            unsent.add(field)
        for value in values:
            unsent |= _unsent_fields(sub, value, schemas, field)
    return unsent


def check_request_bodies(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Validate every JSON body the client sends against the spec's ``requestBody``."""
    errors: set[str] = set()
    warnings: set[str] = set()
    prepared = _prepare_spec(spec)
    components = prepared["components"]
    _recorded, bodies = _recorded_calls()
    declared: set[_Endpoint] = set()
    triggered: set[tuple[str, str, str, str]] = set()
    waived = {waiver[:3] for waiver in _REQUEST_BODY_WAIVERS}
    for path, operations in prepared.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in _HTTP_METHODS:
                continue
            verb = method.upper()
            endpoint = (verb, _normalize_path(path))
            declared.add(endpoint)
            sent = bodies.get(endpoint, [])
            request_body = operation.get("requestBody")
            if request_body is None:
                if sent:
                    errors.add(f"`{verb} {path}`: client sends a body the spec omits")
                continue
            media = request_body.get("content", {}).get(_JSON_MEDIA_TYPE)
            if media is None:
                continue
            if not sent:
                warnings.add(f"`{verb} {path}`: client never sends a JSON body")
                continue
            schema = media.get("schema", {})
            validator = Draft202012Validator({**schema, "components": components})
            # aiohttp's default ``json_serialize`` is ``json.dumps``.
            wires = [json.loads(json.dumps(body)) for body in sent]
            failed: set[str] = set()
            for wire in wires:
                for field, keyword, message in _body_errors(validator, wire):
                    failed.add(field)
                    waiver = (verb, path, field, keyword)
                    if waiver in _REQUEST_BODY_WAIVERS:
                        triggered.add(waiver)
                    else:
                        errors.add(f"`{verb} {path}` body `{field}`: {message}")
            unsent = set.intersection(
                *(_unsent_fields(schema, wire, components["schemas"]) for wire in wires)
            )
            warnings.update(
                f"`{verb} {path}`: spec body field `{field}` is never sent"
                for field in unsent - failed
                if (verb, path, field) not in waived
            )
    errors.update(
        f"`{verb} {path}`: client sends a body to an endpoint the spec omits"
        for verb, path in set(bodies) - declared
    )
    warnings.update(
        f"request-body waiver `{verb} {path}` `{field}` ({keyword}) no longer "
        f"triggers (remove it from `_REQUEST_BODY_WAIVERS`)"
        for verb, path, field, keyword in set(_REQUEST_BODY_WAIVERS) - triggered
    )
    warnings.update(
        f"example kwarg override `{override}` matches no example parameter "
        f"(remove it from `_EXAMPLE_KWARG_OVERRIDES`)"
        for override in _stale_kwarg_overrides()
    )
    return sorted(errors), sorted(warnings)


_CHECKS = (
    check_endpoints,
    check_model_fields,
    check_enums,
    check_enum_coverage,
    check_event_types,
    check_request_bodies,
)


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
