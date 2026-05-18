# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub's
[private vulnerability reporting][gh-report] for this repository.
That route sends the report directly to the maintainers and lets
us coordinate a fix, a CVE, and a release before public
disclosure.

**Do not** open a regular GitHub issue, a pull request, or post
to a public channel (mailing list, chat room, Stack Overflow,
etc.) for a suspected vulnerability. The library holds
credentials for users' UniFi Protect consoles, so a bug class
disclosed in a public PR title is a credible information leak
even before a patch ships. If you are unsure whether something
is a vulnerability, use the private report — we would rather see
a false alarm than a public one.

We aim to acknowledge new reports within a few business days.

[gh-report]: https://github.com/uilibs/uiprotect/security/advisories/new

## Supported versions

Security fixes are released against the latest version on PyPI.
Older releases are not maintained — please upgrade to the
current release before reporting, and confirm the issue still
reproduces there.

## Scope

`uiprotect` is an async Python client for the UniFi Protect
surveillance NVR. It authenticates against a Protect console
with the user's credentials and parses REST responses plus a
binary WebSocket update stream whose wire formats are not
publicly documented and shift across firmware releases. In-scope
issues include:

- Memory-safety, parsing, or denial-of-service issues triggered
  by crafted server responses reaching `ProtectApiClient`, the
  WebSocket decoder in `data/websocket.py`, the JSON →
  pydantic-model conversion in `data/convert.py`, or any of the
  pydantic models under `src/uiprotect/data/`.
- Credential or session-token handling bugs: logging or
  serialising credentials, leaking the API token into logs or
  exceptions, TLS validation that can be silently disabled, or
  authentication state surviving where it should be cleared.
- Logic bugs that cause the client to act on behalf of a
  different user, expose data across NVR accounts, or persist
  credentials to disk in unexpected locations.
- Issues in the build / packaging pipeline (wheel contents,
  release flow) that could lead to a compromised wheel on PyPI.

Out of scope:

- Risks inherent to handing the library credentials for a UniFi
  Protect console — it is a client that drives the Protect API
  on the user's behalf and inherits whatever permissions those
  credentials carry.
- Vulnerabilities in the upstream UniFi Protect server itself,
  or in Ubiquiti firmware. Report those to Ubiquiti through
  their published security channels, not here.
- Misconfiguration of a downstream application that uses the
  library (for example, the Home Assistant `unifiprotect`
  integration).
