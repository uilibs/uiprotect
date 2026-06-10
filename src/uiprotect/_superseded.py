"""
Declarative supersession registry for deprecated private-API methods.

``@superseded_by("replacement", since="X.Y.Z")`` marks a private-API method
whose capability is now covered by a public-API counterpart. Unlike the endpoint
decorators in :mod:`uiprotect._public_api`, this decorator *wraps* the method
rather than replacing its body — it emits one standardized
``DeprecationWarning`` and then runs the original body, because these methods
carry real logic (``queue_update`` callbacks, ``save_device``, validation). It
also appends a ``.. deprecated::`` admonition to the rendered docs and registers
``(class, method, replacement, since)`` in a write-once per-class table that the
removal-automation workflow reads.

The module imports nothing from :mod:`uiprotect.data`: the replacement is always
a string, never a class, so it stays import-clean and circular-import-safe — the
same property the endpoint registry relies on.
"""

from __future__ import annotations

import functools
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

_P = ParamSpec("_P")
_R = TypeVar("_R")
_Method = Callable[Concatenate[Any, _P], Awaitable[_R]]


@dataclass(frozen=True)
class SupersededMethod:
    """A private-API method superseded by a public-API replacement."""

    class_name: str
    method_name: str
    replacement: str
    since: str


class _SupersessionRegistry:
    """Write-once per-class table mapping a method name to its supersession."""

    def __init__(self) -> None:
        self._by_class: dict[str, dict[str, SupersededMethod]] = {}

    def register(self, record: SupersededMethod) -> None:
        table = self._by_class.setdefault(record.class_name, {})
        existing = table.get(record.method_name)
        if existing is not None:
            if existing == record:
                # Idempotent on an identical re-registration (e.g. module
                # re-import under runpy); only a conflicting record is an error.
                return
            raise RuntimeError(
                f"Conflicting supersession for {record.class_name}."
                f"{record.method_name}: already registered as {existing!r}, "
                f"cannot also register {record!r}"
            )
        table[record.method_name] = record

    def for_class(self, cls_name: str) -> dict[str, SupersededMethod]:
        return dict(self._by_class.get(cls_name, {}))

    def all_records(self) -> list[SupersededMethod]:
        return [
            record for table in self._by_class.values() for record in table.values()
        ]


registry = _SupersessionRegistry()


def _append_admonition(doc: str | None, replacement: str, since: str) -> str | None:
    """Append a standardized ``.. deprecated::`` block to a docstring."""
    if not doc:
        return doc
    if ".. deprecated::" in doc:
        # Guard against double-appending if the module is re-imported.
        return doc
    admonition = f".. deprecated:: {since}\n    Use :meth:`{replacement}` instead."
    return f"{doc}\n\n{admonition}"


def superseded_by(
    replacement: str, *, since: str
) -> Callable[[_Method[_P, _R]], _Method[_P, _R]]:
    """Mark a private-API method as superseded by ``replacement`` since ``since``."""

    def decorator(func: _Method[_P, _R]) -> _Method[_P, _R]:
        cls_name = func.__qualname__.rsplit(".", 1)[0]
        record = SupersededMethod(
            class_name=cls_name,
            method_name=func.__name__,
            replacement=replacement,
            since=since,
        )
        registry.register(record)
        message = (
            f"{cls_name}.{func.__name__} is deprecated since {since}; "
            f"use {replacement} instead."
        )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return await func(*args, **kwargs)

        wrapper.__superseded_by__ = (replacement, since)  # type: ignore[attr-defined]
        wrapper.__doc__ = _append_admonition(wrapper.__doc__, replacement, since)
        return cast("_Method[_P, _R]", wrapper)

    return decorator
