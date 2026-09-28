"""Opt-in guard: public device models must not declare fields absent from the spec."""

# The spec (``openapi/integration.json``) is gitignored and not fetched in CI, so
# this test skips cleanly when it is absent. Run ``python scripts/fetch_openapi.py``
# (defaults to the latest version on the developer portal) locally to enable it.
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

import orjson
import pytest
from validate_spec import (  # local import via conftest sys.path insert
    SPEC_PATH,
    check_completeness,
    check_enum_coverage,
    run_checks,
)

_SPEC_PATH = SPEC_PATH


@pytest.mark.skipif(not _SPEC_PATH.exists(), reason="openapi/integration.json absent")
def test_spec_validation_has_no_errors() -> None:
    """The full spec-validation check suite reports no errors against the on-disk spec."""
    spec = orjson.loads(_SPEC_PATH.read_bytes())
    errors, _warnings = run_checks(spec)
    assert not errors, "spec drift:\n" + "\n".join(errors)


@pytest.mark.skipif(not _SPEC_PATH.exists(), reason="openapi/integration.json absent")
def test_every_inbound_spec_enum_is_modelled_or_waived() -> None:
    """Every inbound spec enum is exact-matched, pinned to a superset, or waived."""
    spec = orjson.loads(_SPEC_PATH.read_bytes())
    errors, _warnings = check_enum_coverage(spec)
    assert not errors, "unmodelled, unwaived spec enums:\n" + "\n".join(errors)


def test_every_public_coroutine_is_covered() -> None:
    """No public-API coroutine is left out of the derived coverage set (spec-free)."""
    gaps = check_completeness()
    assert not gaps, "uncovered public-API coroutines:\n" + "\n".join(gaps)
