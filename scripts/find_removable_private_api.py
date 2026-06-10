#!/usr/bin/env python3
"""
Report private-API methods that are safe to remove.

Reads the supersession registry (populated by importing ``uiprotect``), and for
each ``@superseded_by`` method whose replacement is a genuine public-API
counterpart (the replacement name ends in ``_public``), greps the released
Home-Assistant integration for call sites. A method with zero references is
reported as removable. Private→private deprecations (replacement not ending in
``_public``) are skipped — they have no public-parity removal criterion.

Fails safe: a search error never marks a symbol removable, and the raw evidence
(query + matching URLs) is always emitted so a human verifies before any code is
deleted. The script only *finds* removal candidates; it never deletes code.

Requires only stdlib plus the ``gh`` CLI for the GitHub code search.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

HA_REPO = "home-assistant/core"
HA_PATH = "homeassistant/components/unifiprotect"

# (count, evidence_urls) for a deprecated method's call sites in the HA integration.
Searcher = Callable[[str], "tuple[int, list[str]]"]


@dataclass(frozen=True)
class RemovalResult:
    method: str
    replacement: str
    since: str
    ha_references: int
    evidence: list[str] = field(default_factory=list)
    removable: bool = False
    error: str | None = None


def _code_search_query(method_name: str) -> str:
    """Build a scoped GitHub code-search query for a method's call sites."""
    return f'repo:{HA_REPO} path:{HA_PATH} ".{method_name}("'


def gh_code_search(method_name: str) -> tuple[int, list[str]]:
    """Search the released HA integration for ``.method_name(`` call sites via ``gh``."""
    query = _code_search_query(method_name)
    proc = subprocess.run(
        ["gh", "api", "-X", "GET", "search/code", "-f", f"q={query}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh code search failed for {method_name!r}: {proc.stderr.strip()}"
        )
    payload = json.loads(proc.stdout)
    count = int(payload.get("total_count", 0))
    urls = [item.get("html_url", "") for item in payload.get("items", [])]
    return count, urls


def find_removable(
    records: Sequence[Any],
    searcher: Searcher,
) -> list[RemovalResult]:
    """Probe each public-supersession record for remaining HA references."""
    results: list[RemovalResult] = []
    for rec in records:
        if not rec.replacement.endswith("_public"):
            # Private→private deprecation: no public-parity removal criterion.
            continue
        try:
            count, evidence = searcher(rec.method_name)
        except Exception as exc:  # fail safe — never mark removable on a search error
            results.append(
                RemovalResult(
                    method=rec.method_name,
                    replacement=rec.replacement,
                    since=rec.since,
                    ha_references=-1,
                    error=str(exc),
                )
            )
            continue
        results.append(
            RemovalResult(
                method=rec.method_name,
                replacement=rec.replacement,
                since=rec.since,
                ha_references=count,
                evidence=evidence,
                removable=count == 0,
            )
        )
    return results


def render_report(results: list[RemovalResult]) -> str:
    """Render a Markdown report; the body doubles as a removal-issue description."""
    lines = ["# Private-API removal candidates", ""]
    removable = [r for r in results if r.removable]
    if not removable:
        lines.append("No symbols are currently safe to remove.")
    for r in results:
        if r.error is not None:
            lines.append(
                f"- ⚠️ `{r.method}` — search error, skipped (not removable): {r.error}"
            )
            continue
        if r.removable:
            lines.append(
                f"- ✅ **safe to remove**: `{r.method}` "
                f"(deprecated since {r.since}, superseded by `{r.replacement}`)"
            )
        else:
            lines.append(
                f"- ❌ `{r.method}` — {r.ha_references} reference(s) remain in "
                f"`{HA_PATH}`"
            )
        lines.append(f"  - query: `{_code_search_query(r.method)}`")
        lines.extend(f"  - {url}" for url in r.evidence)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="seconds to wait between code searches (code search is rate-limited)",
    )
    args = parser.parse_args(argv)

    import uiprotect.data.devices  # noqa: F401, PLC0415  populate registry at import
    from uiprotect._superseded import registry  # noqa: PLC0415

    def searcher(method_name: str) -> tuple[int, list[str]]:
        time.sleep(args.sleep)
        return gh_code_search(method_name)

    results = find_removable(registry.all_records(), searcher)
    print(render_report(results))
    return 1 if any(r.removable for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
