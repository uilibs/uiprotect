# Notes for LLM contributors

A short orientation file for an LLM working in this repo. Skim
before making changes; keep edits consistent with what's described
here. Read [README.md](README.md) for the user-facing intro and
[CONTRIBUTING.md](CONTRIBUTING.md) for the human-facing
contributor guide.

## What this project is

`uiprotect` is an unofficial async Python client + CLI for the
UniFi Protect surveillance NVR. It is the library that the Home
Assistant `unifiprotect` integration is built on top of, and it
is the de-facto Python binding for talking to a UniFi Protect
console — Ubiquiti does not publish an official one. Public API
is exported from the top-level `uiprotect` package; the main
entry point is `uiprotect.ProtectApiClient` in `src/uiprotect/api.py`.

There is no upstream protocol owner. The wire format is whatever
the UniFi Protect server in front of you serves: a partially
documented REST API plus a binary WebSocket update stream. Both
shift across firmware releases, and the test corpus under
`tests/sample_data/` is the closest thing to a reference. Behaviour
changes that depend on a specific Protect firmware version should
say so in the commit message.

The project was forked from `pyunifiprotect` after that project
relicensed away from MIT; staying MIT-licensed is a hard
requirement so the Home Assistant core integration can keep
depending on it.

## Code style

- **Docstrings: terse, default to single-line.** A docstring is
  the function's _contract_, not its narrative. Almost every
  docstring should be one line — `"""Summary."""` — describing
  what the function does and what the caller can pass. Multi-line
  is the exception, only justified when there is non-obvious
  caller-visible behaviour the type signature and parameter names
  don't already convey. Ruff is configured with most of the `D`
  family disabled (`D100`–`D107`, `D2xx`, `D4xx`) precisely so
  that missing docstrings on internal helpers don't flag — only
  add one when it earns its keep.

  **What does NOT belong in docstrings or comments:**
  - Rationale / motivation / "why we used to do X" — that's the
    PR description and the commit message. Git already remembers.
  - Cross-references to issue numbers ("closes #N", "follow-up
    to #M") — the PR body carries those.
  - Restatement of the function body in prose. If the next line
    of the docstring is just describing what the next line of
    code does, delete the docstring line.
  - Test docstrings retelling the production-side story. A test
    docstring should name what the test pins, in one sentence —
    not re-explain the bug, the fix, or the surrounding flow.

- **Comments**: same bar. Default to writing no comments. Add
  one only when the _why_ is non-obvious: a hidden constraint, a
  subtle invariant, a workaround for a specific Protect firmware
  quirk, behaviour that would surprise a reader. Firmware-version
  citations are useful when the reason for a branch is "this
  server returns the field, that one doesn't" — leave those in.
  If removing the comment wouldn't confuse a future reader, don't
  write it.

  **Don't remove existing comments** unless the code they
  describe is gone — the original author left them for a reason,
  often a specific Protect firmware regression.

- **Don't pad commits, docstrings, or comments with cross-
  references** to old codepaths or issue numbers unless there's
  a clear reason a future reader needs that link.

- **Method order**: public API at the top, private helpers
  (`_underscore_prefixed`) at the bottom. The supported surface
  is what `src/uiprotect/__init__.py` re-exports plus the public
  attributes on `ProtectApiClient`, `Bootstrap`, and the device /
  NVR model classes. Anything else is internal and can change
  between releases.

- **Line length**: 88 (ruff `line-length = 88`, not the more
  common 100/110). `requires-python = ">=3.11"`,
  `target-version = "py311"` for ruff; pyupgrade runs `--py311-plus`.

- **Imports**: ruff/isort sorted, `known_first_party = ["uiprotect", "tests"]`.
  Prefer `from __future__ import annotations` in new modules so
  modern type syntax works without runtime forward-reference
  juggling, especially given the pydantic model graph.

- **Pydantic v2 only.** Models live under `src/uiprotect/data/`
  and are built on pydantic v2 (`pydantic >= 2.13.4`). Do not
  reintroduce v1 idioms (`.dict()`, `Config` inner class,
  `validator` decorator) when touching this code — match the v2
  style already present (`model_dump()`, `model_config`,
  `field_validator`). The pinned-floor on pydantic is deliberate;
  do not loosen it without checking what changed across versions.

- **`orjson` for serialisation.** The codebase uses `orjson`
  everywhere it serialises or parses Protect payloads. Don't
  reach for stdlib `json` in hot paths; match the existing
  `orjson.loads` / `orjson.dumps` usage.

- **Async-only public surface.** UniFi Protect itself is async,
  and so is this library. New public functions on
  `ProtectApiClient` and friends should be `async def`. Don't
  introduce sync wrappers around async I/O; callers that need
  sync should drive the event loop themselves.

- **Typed strictly.** mypy runs with `disallow_untyped_defs`,
  `disallow_incomplete_defs`, `check_untyped_defs`,
  `no_implicit_optional`, `warn_unreachable`, and
  `warn_unused_ignores`, and is wired into pre-commit through
  `.bin/run-mypy` against `src/uiprotect/`. New code under
  `src/uiprotect/` must type-check cleanly; tests are exempted
  via the `tests.*` override. Don't paper over a real type error
  with `# type: ignore` — `warn_unused_ignores` will eventually
  catch you, and the right answer is almost always a tighter
  annotation upstream.

## Commit / PR conventions

- **Conventional Commits PR title, lowercase subject.** PRs are
  squash-merged, so the **PR title** becomes the commit on `main`
  and is the only string that needs to parse as a Conventional
  Commit. The repo enforces this via the `pr-title` CI job in
  `ci.yml` using `amannn/action-semantic-pull-request`. The
  _type_ prefix is required: `feat:`, `fix:`, `chore:`, `ci:`,
  `docs:`, `refactor:`, `test:`, `perf:`, `build:`, etc., and
  the subject (text after `type(scope):`) must start lowercase
  (enforced by `subjectPattern: ^(?![A-Z]).+$`). Per-commit
  messages on the PR branch are **not** linted — they get
  collapsed at squash-merge. `python-semantic-release` excludes
  `chore*` and `ci*` from the changelog (see
  `[tool.semantic_release.changelog]` in `pyproject.toml`), so
  use those prefixes for housekeeping and reserve
  `feat`/`fix`/`perf` for user-visible changes that should land
  in `CHANGELOG.md`.
- **No `Co-Authored-By` trailers from automated agents.** Project
  preference; releases are cut by `python-semantic-release` from
  the commit log, and a trailer from an LLM ends up in the
  generated changelog.
- Imperative-mood subject after the type prefix ("fix(api):
  handle empty bootstrap", not "fix(api): handled empty bootstrap").
  Scopes in parentheses are encouraged where useful
  (`api`, `cli`, `data`, `websocket`, `stream`).
- The repo **does** ship a PR template at
  [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md).
  Fill out the "Description of change" section in prose and tick
  the checklist items that apply (write `N/A` rather than
  silently leaving rows blank). Reference closing issues with
  `Fixes #NNNN` so the issue auto-closes on merge.
- Pre-commit runs ruff (lint + format), mypy, prettier,
  poetry-check, and the standard hygiene hooks (trailing
  whitespace, end-of-file fixer, debug-statements,
  detect-private-key, check-toml/xml). Run pre-commit locally
  before pushing; the CI lint job is just `pre-commit run -a`,
  so a green local run = a green CI lint job. The `pre-commit.ci`
  bot fixes formatting drift automatically with a
  `chore(pre-commit.ci): auto fixes` commit, so don't bother
  hand-fixing whitespace-only failures.
- **Releases are automated.** `python-semantic-release` cuts
  releases from `main` based on commit type prefixes — `feat`
  bumps minor, `fix`/`perf` bump patch, a `BREAKING CHANGE:`
  footer (or `!` after the type) bumps major. Mis-typed commits
  ship the wrong version. If a change is user-visible, type it
  honestly.

## Running tests

Requires Python >=3.11. **Install all extras to run the full suite** — the
`cli` extra provides Pillow, typer and rich. Without it the CLI/Pillow test
modules (`tests/test_api.py`, `tests/test_cli.py`, `tests/test_dunder_main.py`)
are skipped via `pytest.importorskip` rather than run, so a bare install
silently exercises a reduced suite:

```bash
poetry install --all-extras
poetry run pytest
```

The default `addopts` in `pyproject.toml` already pass
`-v -Wdefault --cov=uiprotect --cov-report=term-missing:skip-covered -n=auto`
and `pythonpath = ["src"]`, so a bare `pytest` produces a
coverage-aware, xdist-parallel run. `pytest-asyncio` is used in
the default per-test mode (no auto mode); async tests are marked
explicitly with `@pytest.mark.asyncio`.

**Every PR must reach 100% patch coverage.** Each line you add or
change under `src/uiprotect/` has to be exercised by a test —
check the `--cov-report=term-missing:skip-covered` output and confirm
none of the diff's lines appear as missing before pushing. Don't ship a
change with uncovered new code; if a line is genuinely
unreachable, mark it `# pragma: no cover` with a one-line reason
rather than leaving it untested. This applies to automated
contributions too: a PR that adds production code without the
tests to cover it is incomplete.

The test suite is fixture-driven: `tests/sample_data/` holds
captured bootstrap JSON / WebSocket frames from real Protect
consoles and `tests/conftest.py` loads them into the mock client.
When fixing a bug that depends on a specific server response,
add a fixture or extend an existing one rather than mocking ad-hoc
in the test — the goal is for the corpus to grow alongside
firmware drift. See [TESTDATA.md](TESTDATA.md) for how the corpus
is generated.

CodSpeed benchmarks live under `tests/benchmarks/` and run in CI
through the CodSpeed integration. Don't regress benchmark numbers
on hot paths (`api.py` request building, `data/convert.py`,
`websocket.py` decode) without flagging the trade-off in the PR
body.

`tests/test_cli.py` covers the typer-based CLI surface. If you
add a new subcommand under `src/uiprotect/cli/`, extend the CLI
tests as well — the CLI tests are how we catch import-time
regressions that would otherwise only fire for users on
`uiprotect --help`.

The CI matrix runs CPython 3.11 – 3.14 across Linux/macOS, and a
separate live-data leg can run against a real Protect NVR on a
self-hosted runner — see [LIVE_DATA_CI.md](LIVE_DATA_CI.md). The
live leg is optional and is not gated for typical PRs.

## Useful entry points

| Path                                     | What                                                                             |
| ---------------------------------------- | -------------------------------------------------------------------------------- |
| `src/uiprotect/__init__.py`              | Public package — re-exports `ProtectApiClient` and key exceptions                |
| `src/uiprotect/api.py`                   | `ProtectApiClient` — REST surface, auth, bootstrap, subscribe, request plumbing  |
| `src/uiprotect/websocket.py`             | `Websocket` — the long-lived update connection that drives live state            |
| `src/uiprotect/stream.py`                | PyAV-backed audio streaming to camera speakers (talkback)                        |
| `src/uiprotect/utils.py`                 | Shared helpers: URL building, time parsing, type coercion, dict diffing          |
| `src/uiprotect/exceptions.py`            | Public exception hierarchy raised from `ProtectApiClient`                        |
| `src/uiprotect/data/__init__.py`         | Pydantic model re-exports — the typed surface most callers consume               |
| `src/uiprotect/data/base.py`             | `ProtectBaseObject` / `ProtectModel` base classes shared by every Protect model  |
| `src/uiprotect/data/bootstrap.py`        | `Bootstrap` — the cached snapshot returned by `protect.bootstrap`                |
| `src/uiprotect/data/devices.py`          | Camera / Light / Sensor / Viewer / Chime / Doorlock / AiPort device models       |
| `src/uiprotect/data/nvr.py`              | `NVR`, `Event`, `Liveview`, related top-level models                             |
| `src/uiprotect/data/user.py`             | User / permission / cloud-account models                                         |
| `src/uiprotect/data/websocket.py`        | WebSocket frame decoder + `WSSubscriptionMessage` definition                     |
| `src/uiprotect/data/convert.py`          | Raw-JSON → pydantic-model conversion entry point used by API + WS paths          |
| `src/uiprotect/data/types.py`            | Enums, typed dicts, and protocol-level constants                                 |
| `src/uiprotect/data/public_bootstrap.py` | Public-API bootstrap shape (parallels `bootstrap.py` for the newer API)          |
| `src/uiprotect/data/public_devices.py`   | Public-API device models                                                         |
| `src/uiprotect/cli/`                     | typer-based CLI — one module per device family plus `base.py` for shared options |
| `src/uiprotect/test_util/`               | Helpers used by `generate-sample-data`; not part of the public API               |
| `tests/`                                 | Pytest suite                                                                     |
| `tests/sample_data/`                     | Captured Protect bootstrap / WS / event JSON used as fixtures                    |
| `tests/benchmarks/`                      | CodSpeed benchmarks                                                              |
| `tests/conftest.py`                      | Fixture wiring: builds a mock `ProtectApiClient` from `sample_data/`             |
| `templates/`                             | Rich templates used by the CLI for human-readable output                         |

## API strategy

The project is migrating from the **private API** (reverse-engineered,
undocumented endpoints under `/api/…` and the binary WebSocket stream;
models in `src/uiprotect/data/devices.py`) to the **Public Integration
API** (Ubiquiti's officially documented REST API under
`/integration/v1/…`; models in `src/uiprotect/data/public_devices.py`
and `src/uiprotect/data/public_bootstrap.py`; tests under
`tests/test_api_*_public.py`).

**Do not implement new features on the private API.** If a capability
is missing from the public API, the right answer is to wait for or
request the public endpoint — not to add it via the private path.
Derive shapes from the existing public models and tests in this repo.

**Public-only client mode.** `ProtectApiClient` can be constructed with
only an API key and no private credentials —
`ProtectApiClient.public_only(host, port, api_key=...)`, or by passing
`api_key=` with `username`/`password` omitted. In that mode
`is_public_only` is `True` and the private-session entry points
(`authenticate`, `ensure_authenticated`, `update`, `get_bootstrap`)
raise `PublicOnlyModeError`; only the Public Integration API surface is
available (`update_public`, `subscribe_events`, `subscribe_devices`, the
`*_public` getters/setters, `get_meta_info`). A revoked/invalid/missing
key surfaces as `NotAuthorized` across REST and the public websockets.
`MetaInfo.version` parses `applicationVersion` into a `Version`
comparable to the private `NVR.version` min-version gate. API-key
_provisioning_ (`create_api_key`) is private-API and out of scope for
public-only clients — the key is supplied pre-provisioned.

**Deprecate private-API counterparts when the public API is feature-
complete for a given capability.** Once a device method or endpoint is
fully covered by the public API, mark the corresponding private-API
method with a `DeprecationWarning` pointing to the public replacement.

**Remove private-API code that the Home Assistant integration no longer
uses.** Before removing a private-API method or model, check whether
the latest released version of the HA integration still references it:
search `homeassistant/components/unifiprotect/` in the
`home-assistant/core` GitHub repository. If the symbol does not
appear there, it is safe to remove.

## Public Integration API spec

The OpenAPI spec is not committed (Ubiquiti's IP). Fetch it on demand — no
auth or console access needed:

```bash
python scripts/fetch_openapi.py                    # latest release
python scripts/fetch_openapi.py --version 7.0.104  # pin to a version
```

Output: `openapi/integration.json` (gitignored) — request/response shapes,
required fields, enums, and allowed HTTP methods for every `/integration/v1/…`
endpoint. If the file is absent, run the script first.

### Spec conformance validation

`scripts/validate_spec.py` checks the public-API client against a fetched
spec and reports drift: spec endpoints with no covering `*_public` method
(warning), model fields the spec dropped/retyped (error) or added (warning),
new values on a named, tracked enum (warning), and any spec enum — named **or**
inline — that is not faithfully typed in the library (warning). The enum-
coverage check walks the whole spec keyed by value-set (the `unknown` forward-
compat sentinel ignored on both sides) and counts a value-set covered only when
it *equals* a single library enum, or is explicitly pinned in
`_MODELLED_AS_SUBSET` to one named superset enum the public models already type
the field with — never a coincidental subset of *any* enum, which is the value-
set collision an earlier any-subset check let slip. Enums are classified
inbound (reachable from a response the library deserializes) vs. outbound-only
(request param/body) by `$ref` reachability: outbound-only enums are waived by
direction, while an inbound enum left untyped needs an explicit, documented
entry in `_ENUM_COVERAGE_WAIVERS`. The default is to model; waivers are the rare
exception. Spec `required` vs. model `optional` is not
checked — the library models every public-API field optional by design, so it
would be guaranteed noise. It exits non-zero on any error and prints a markdown
summary. Reproduce locally with:

```bash
python scripts/fetch_openapi.py --version "$(cat openapi/.validated-version)"
python scripts/validate_spec.py
```

The only committed artifact is `openapi/.validated-version` — a bare version
string (no IP) whose git history records when conformance last moved forward.
`tests/test_public_schema_conformance.py` runs the same checks when a spec is
present and skips cleanly when it is absent (the CI default); the logic itself
is unit-tested network-free against in-memory mock specs in
`tests/test_validate_spec.py`. The `.github/workflows/spec-validation.yml`
cron runs the full validation at most once per Protect release — opening a
marker-bump PR when green or a single drift issue when red — and short-circuits
on a firmware-API check before downloading anything while the marker is current
or a drift issue is already open. Endpoint coverage is **derived, not hand-
maintained**: the declarative `@public_*` decorator registry
(`uiprotect._public_api.registry`) covers every uniform endpoint, and the
hand-written exception methods are covered by one recorded example call each
(`_EXAMPLE_CALLS` — a request spy captures `(verb, path)` then short-circuits).
`check_completeness` asserts every public-API coroutine is accounted for, so a
new method that nobody wired up fails the suite instead of silently leaving its
endpoint uncovered.

## Reporting security issues

Suspected security vulnerabilities go through GitHub's [private
vulnerability reporting][gh-report], not public issues or pull
requests. The policy is spelled out in [SECURITY.md](SECURITY.md).
The library holds credentials for users' UniFi Protect consoles,
so a bug class disclosed in a public PR title is a credible
information leak even before a patch ships. If a user describes
what sounds like a vulnerability in chat, point them at that
route instead of opening a public issue, PR, or commit that
names the bug class and the affected code path.

[gh-report]: https://github.com/uilibs/uiprotect/security/advisories/new

## Things not to do

- **Don't relicense or pull in non-MIT dependencies.** Staying
  MIT is the reason this fork exists; an incompatible licence
  would break the Home Assistant integration that depends on
  this library.
- **Don't break pydantic v2 compatibility.** No v1 idioms
  (`.dict()`, `Config` inner class, `validator` decorator) when
  editing model code — match the v2 style already in the
  `src/uiprotect/data/` tree.
- **Don't introduce sync wrappers around async I/O.** The public
  surface is async; callers needing sync drive the loop
  themselves.
- **Don't paper over typing errors with `# type: ignore`.** mypy
  runs with `warn_unused_ignores`, so a bare ignore will rot.
  Fix the upstream annotation instead.
- **Don't add `Co-Authored-By` trailers from automated agents
  to commits** in this repo. `python-semantic-release` reads the
  commit log when generating the changelog and the trailer
  leaks into release notes.
- **Don't introduce a PR title that violates Conventional
  Commits.** The `pr-title` CI job will reject it, and because
  the PR title is what lands on `main` at squash-merge time, a
  mis-typed title bumps the wrong version on the next
  semantic-release run.
- **Don't reach for stdlib `json` in hot paths.** The codebase
  uses `orjson` everywhere; match the existing style.
- **Don't hand-edit `CHANGELOG.md`.** It is generated by
  `python-semantic-release` from commit messages; manual edits
  are overwritten on the next release.
- **Don't commit captured Protect data without scrubbing.**
  Bootstrap and event JSON from a real NVR contains
  `authUserId`, `accessKey`, and user records; see
  [TESTDATA.md](TESTDATA.md) for the keys that must be removed
  before a sample lands in `tests/sample_data/`.
- **Don't drop Python 3.11 support without coordination.**
  `requires-python = ">=3.11"` is set deliberately; the Home
  Assistant integration's minimum tracks this floor.
- **Don't store mutable state (caches, dedupe sets, etc.)
  module-globally or as a class-level mutable default.** One
  process can run multiple `ProtectApiClient` instances against
  different consoles (e.g. several Home Assistant config
  entries), so per-instance state must live on the instance —
  `self.…`, the `Bootstrap`/`PublicBootstrap` snapshot, or a
  per-client dataclass field (use `field(default_factory=…)`),
  never a module global or shared class attribute. A global
  cache leaks and collides across NVRs and is invisible in
  single-console tests.
