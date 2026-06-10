"""Tests for the ``@superseded_by`` decorator and its registry."""

from __future__ import annotations

import warnings

import pytest

from uiprotect._superseded import (
    SupersededMethod,
    _SupersessionRegistry,
    registry,
    superseded_by,
)


@pytest.mark.asyncio()
async def test_warns_once_and_runs_body():
    calls: list[int] = []

    class Widget:
        @superseded_by("do_thing_public", since="1.2.3")
        async def do_thing(self, value: int) -> int:
            calls.append(value)
            return value * 2

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await Widget().do_thing(21)

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) == 1
    assert "do_thing is deprecated since 1.2.3" in str(deprecations[0].message)
    assert "use do_thing_public instead" in str(deprecations[0].message)
    assert result == 42
    assert calls == [21]


class _Gadget:
    @superseded_by("refresh_public", since="2.0.0")
    async def refresh(self) -> None: ...


def test_registers_record_on_real_registry():
    record = registry.for_class("_Gadget")["refresh"]
    assert record == SupersededMethod(
        class_name="_Gadget",
        method_name="refresh",
        replacement="refresh_public",
        since="2.0.0",
    )
    assert any(
        r.class_name == "_Gadget" and r.method_name == "refresh"
        for r in registry.all_records()
    )


def test_two_methods_same_class_both_register():
    reg = _SupersessionRegistry()
    reg.register(SupersededMethod("C", "a", "a_public", "1.0.0"))
    reg.register(SupersededMethod("C", "b", "b_public", "1.0.0"))
    assert set(reg.for_class("C")) == {"a", "b"}


def test_conflicting_duplicate_raises():
    reg = _SupersessionRegistry()
    reg.register(SupersededMethod("C", "a", "a_public", "1.0.0"))
    with pytest.raises(RuntimeError, match="Conflicting supersession"):
        reg.register(SupersededMethod("C", "a", "other_public", "1.0.0"))


def test_identical_duplicate_is_idempotent():
    reg = _SupersessionRegistry()
    record = SupersededMethod("C", "a", "a_public", "1.0.0")
    reg.register(record)
    reg.register(record)
    assert reg.for_class("C") == {"a": record}


def test_attribute_and_docs_admonition_set():
    class Thing:
        @superseded_by("replace_public", since="3.1.0")
        async def old(self) -> None:
            """Do the old thing."""

    assert Thing.old.__superseded_by__ == ("replace_public", "3.1.0")
    assert Thing.old.__doc__ is not None
    assert "Do the old thing." in Thing.old.__doc__
    assert ".. deprecated:: 3.1.0" in Thing.old.__doc__
    assert ":meth:`replace_public`" in Thing.old.__doc__


def test_admonition_skipped_when_no_docstring():
    class Thing:
        @superseded_by("replace_public", since="3.1.0")
        async def old(self) -> None: ...

    assert Thing.old.__doc__ is None


def test_for_class_returns_copy():
    reg = _SupersessionRegistry()
    reg.register(SupersededMethod("C", "a", "a_public", "1.0.0"))
    reg.for_class("C")["a"] = SupersededMethod("C", "a", "tampered", "9.9.9")
    assert reg.for_class("C")["a"].replacement == "a_public"
