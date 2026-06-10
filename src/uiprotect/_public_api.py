"""
Declarative endpoint decorators for the uniform public-API surface.

These decorators turn the *genuinely uniform* slice of
:class:`uiprotect.api.ProtectApiClient`'s Public Integration API methods into
one-line declarations. The hand-written ``async def`` signature and docstring
are kept (mypy-strict and mkdocstrings rely on them); the decorator supplies the
body — path binding, payload assembly, dispatch through the existing
``api_request_*`` helpers, and model construction.

The module imports nothing from :mod:`uiprotect.data`: model classes arrive as
decorator arguments (``returns=``/``item=``), so it stays import-clean and
circular-import-safe. It depends only on the stdlib plus the public exception
type.
"""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

from .exceptions import BadRequest

_P = ParamSpec("_P")
_R = TypeVar("_R")
_Method = Callable[Concatenate[Any, _P], Awaitable[_R]]

_PLACEHOLDER_RE = re.compile(r"{(\w+)}")
_EMPTY_BODY_MESSAGE = "At least one parameter must be provided"


def _to_camel(name: str) -> str:
    """Convert a snake_case parameter name to camelCase wire key."""
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


class _PublicEndpointRegistry:
    """Write-once per-class table mapping ``(verb, path)`` to a method name."""

    def __init__(self) -> None:
        self._by_class: dict[str, dict[tuple[str, str], str]] = {}

    def register(self, cls_name: str, verb: str, path: str, method_name: str) -> None:
        table = self._by_class.setdefault(cls_name, {})
        key = (verb, path)
        if key in table:
            raise RuntimeError(
                f"Duplicate public endpoint {verb.upper()} {path} on "
                f"{cls_name}: already registered as {table[key]!r}, "
                f"cannot also register {method_name!r}"
            )
        table[key] = method_name

    def for_class(self, cls_name: str) -> dict[tuple[str, str], str]:
        return dict(self._by_class.get(cls_name, {}))

    def all_endpoints(self) -> dict[str, dict[tuple[str, str], str]]:
        return {cls: dict(table) for cls, table in self._by_class.items()}


registry = _PublicEndpointRegistry()


def _build_body(
    sig: inspect.Signature,
    arguments: dict[str, Any],
    placeholders: frozenset[str],
) -> dict[str, Any]:
    """Assemble a flat camelCase JSON body from non-``None`` keyword params."""
    body: dict[str, Any] = {}
    for name, value in arguments.items():
        if name == "self" or name in placeholders:
            continue
        if value is None:
            continue
        body[_to_camel(name)] = value
    return body


def _endpoint(
    verb: str,
    path: str,
    *,
    item: type[Any] | None,
    returns: type[Any] | None,
    has_body: bool,
) -> Callable[[_Method[_P, _R]], _Method[_P, _R]]:
    placeholders = frozenset(_PLACEHOLDER_RE.findall(path))

    def decorator(func: _Method[_P, _R]) -> _Method[_P, _R]:
        sig = inspect.signature(func)
        cls_name = func.__qualname__.rsplit(".", 1)[0]
        registry.register(cls_name, verb, path, func.__name__)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            self = args[0]
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = bound.arguments
            url = path.format(**{name: arguments[name] for name in placeholders})

            if item is not None:
                data = await self.api_request_list(url=url, public_api=True)
                return [item.from_unifi_dict(**entry, api=self) for entry in data]

            if has_body:
                body = _build_body(sig, arguments, placeholders)
                if not body:
                    raise BadRequest(_EMPTY_BODY_MESSAGE)
                result = await self.api_request_obj(
                    url=url, method=verb, json=body, public_api=True
                )
                return returns.from_unifi_dict(**result, api=self)  # type: ignore[union-attr]

            if returns is not None:
                data = await self.api_request_obj(url=url, public_api=True)
                return returns.from_unifi_dict(**data, api=self)

            await self.api_request_raw(url=url, method=verb, public_api=True)
            return None

        wrapper.__public_endpoint__ = (verb, path)  # type: ignore[attr-defined]
        return cast("_Method[_P, _R]", wrapper)

    return decorator


def public_get(
    path: str,
    *,
    item: type[Any] | None = None,
    returns: type[Any] | None = None,
) -> Callable[[_Method[_P, _R]], _Method[_P, _R]]:
    """Declare a GET endpoint: ``item=`` for a list, ``returns=`` for one object."""
    return _endpoint("get", path, item=item, returns=returns, has_body=False)


def public_patch(
    path: str, *, returns: type[Any]
) -> Callable[[_Method[_P, _R]], _Method[_P, _R]]:
    """Declare a flat-body PATCH endpoint; empty body raises ``BadRequest``."""
    return _endpoint("patch", path, item=None, returns=returns, has_body=True)


def public_post(
    path: str,
) -> Callable[[_Method[_P, _R]], _Method[_P, _R]]:
    """Declare a fire-and-forget POST endpoint (path-only, no return value)."""
    return _endpoint("post", path, item=None, returns=None, has_body=False)
