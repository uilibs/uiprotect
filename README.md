# Unofficial UniFi Protect Python API and CLI

<p align="center">
  <a href="https://github.com/uilibs/uiprotect/actions/workflows/ci.yml?query=branch%3Amain">
    <img src="https://img.shields.io/github/actions/workflow/status/uilibs/uiprotect/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://uiprotect.readthedocs.io">
    <img src="https://img.shields.io/readthedocs/uiprotect.svg?logo=read-the-docs&logoColor=fff&style=flat-square" alt="Documentation Status">
  </a>
  <a href="https://codecov.io/gh/uilibs/uiprotect">
    <img src="https://img.shields.io/codecov/c/github/uilibs/uiprotect.svg?logo=codecov&logoColor=fff&style=flat-square" alt="Test coverage percentage">
  </a>
  <a href="https://codspeed.io/uilibs/uiprotect?utm_source=badge"><img src="https://img.shields.io/endpoint?url=https://codspeed.io/badge.json" alt="CodSpeed Badge"/></a>
</p>
<p align="center">
  <a href="https://python-poetry.org/">
    <img src="https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json" alt="Poetry">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
  </a>
  <a href="https://github.com/pre-commit/pre-commit">
    <img src="https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square" alt="pre-commit">
  </a>
</p>
<p align="center">
  <a href="https://pypi.org/project/uiprotect/">
    <img src="https://img.shields.io/pypi/v/uiprotect.svg?logo=python&logoColor=fff&style=flat-square" alt="PyPI Version">
  </a>
  <img src="https://img.shields.io/pypi/pyversions/uiprotect.svg?style=flat-square&logo=python&amp;logoColor=fff" alt="Supported Python versions">
  <img src="https://img.shields.io/pypi/l/uiprotect.svg?style=flat-square" alt="License">
</p>

---

**Documentation**: <a href="https://uiprotect.readthedocs.io" target="_blank">https://uiprotect.readthedocs.io </a>

**Source Code**: <a href="https://github.com/uilibs/uiprotect" target="_blank">https://github.com/uilibs/uiprotect </a>

---

## About

Unofficial Python API and CLI for UniFi Protect, for any UniFi OS console that runs Protect. It is the library behind the Home Assistant [UniFi Protect integration](https://www.home-assistant.io/integrations/unifiprotect) and can be used on its own. uiprotect is not affiliated with or endorsed by Ubiquiti.

The library is moving to Ubiquiti's documented Public Integration API, which authenticates with an [API key](#api-key). Features the public API does not offer use the undocumented private API, which can change between Protect releases.

## Reporting issues and requesting features

<a id="check-the-public-api"></a>

### Check the public API first

The [Public Integration API documentation](https://developer.ui.com/protect/) lists every device field and control the library can support. If a field or control is not there, uiprotect cannot add it as a new feature.

A field is not enough when only some models have the feature: there also has to be a feature flag (under `featureFlags` in the output) or another field that tells which devices support it. Otherwise Home Assistant would offer controls that do nothing on the other models.

To see what your console returns, query it with curl and an [API key](#api-key). `HOST` is the IP address or hostname of your console. The command saves the answer to `cameras.json`.

Linux and macOS:

```bash
curl -k -H "X-API-KEY: API_KEY" -o cameras.json https://HOST/proxy/protect/integration/v1/cameras
```

Windows:

```powershell
curl.exe -k -H "X-API-KEY: API_KEY" -o cameras.json https://HOST/proxy/protect/integration/v1/cameras
```

For other devices, replace `cameras` at the end of the URL with another endpoint from the documentation, such as `lights`, `sensors` or `cameras/CAMERA_ID` for a single camera. Doorbells are cameras. `-k` skips certificate verification. It is needed while the console uses its default self-signed certificate.

Open the file in a text editor and remove MAC addresses, IP addresses and serial numbers before you post it. Never post the command itself, it contains your API key.

Home Assistant diagnostics are no substitute. Their `public_bootstrap` section only contains fields uiprotect already reads, so a field the library does not know yet is missing there. The `bootstrap` section is the private API.

<a id="no-new-private-api-features"></a>

> [!IMPORTANT]
> **This library does not accept new features built on the private API.**
> uiprotect is migrating from the undocumented private API to Ubiquiti's official
> Public Integration API. If a capability is missing from the public API, the right
> path is to request it from Ubiquiti / wait for it to be exposed there — **not** to
> add it on the private path. Issues or PRs that introduce new private-API
> functionality will be closed.

## Requirements

- [UniFi Protect](https://ui.com/camera-security) 7.2+, tested against the latest stable release
- [Python](https://www.python.org/) 3.11+
- [PyAV](https://pyav.org/), installed as a dependency, for talkback audio

Windows is not actively supported and not tested in CI, although it should work. Issues about Windows are welcome as a hint, but there is no promise of a fix. The [Docker container](#using-docker-container) and [WSL](https://docs.microsoft.com/en-us/windows/wsl/install) are the supported options there.

## Installation

### From PyPI

```bash
pip install uiprotect
```

To use the command-line interface, install the `cli` extra:

```bash
pip install "uiprotect[cli]"
```

### From GitHub

```bash
pip install "uiprotect[cli] @ git+https://github.com/uilibs/uiprotect.git"
```

### Using Docker Container

The Docker container needs no local Python. Add this to your `.bashrc` or similar. It passes the [environment variables](#cli) from your shell into the container:

```bash
function uiprotect() {
    docker run --rm -it \
      -e UFP_API_KEY \
      -e UFP_USERNAME \
      -e UFP_PASSWORD \
      -e UFP_ADDRESS \
      -e UFP_PORT \
      -e UFP_SSL_VERIFY \
      -e TZ \
      -v $PWD:/data ghcr.io/uilibs/uiprotect:latest "$@"
}
```

- Update with `docker pull ghcr.io/uilibs/uiprotect:latest`.
- `$PWD` is mounted to `/data`. Files written anywhere else are lost when the container exits.
- Images exist for `linux/amd64` and `linux/arm64`, so Docker Desktop on macOS and Windows works.
- `TZ` is the [time zone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) of your Protect console. The [command line docs](https://uiprotect.readthedocs.io/en/latest/cli/) list the other environment variables.

## Authentication

<a id="api-key"></a>

### API key

Create an API key on the console under **Settings > Control Plane > Integrations** with an administrator account. Ubiquiti's [Getting Started guide](https://developer.ui.com/protect/) describes it under "Obtaining an API Key". There is no read-only key, so treat it like a password.

### Local user

Features the public API does not offer also need a local user with access to Protect.

> [!WARNING]
> UI Account (cloud) logins and MFA are not supported. Use a local-access user, not the owner account.

## Quickstart

### CLI

```bash
export UFP_ADDRESS=YOUR_CONSOLE_IP
export UFP_API_KEY=YOUR_API_KEY
# set to true if the console has a certificate your machine trusts
export UFP_SSL_VERIFY=false

uiprotect cameras list-ids
```

In Windows PowerShell, set the variables with `$env:UFP_API_KEY = "YOUR_API_KEY"` and so on.

With only an API key, the CLI runs in public-only mode, and commands without a public equivalent, such as `uiprotect nvr`, stop with an error. With a local user set as well, the CLI logs in and the device commands also read the private API:

```bash
export UFP_USERNAME=YOUR_USERNAME
export UFP_PASSWORD=YOUR_PASSWORD
```

`uiprotect --help` lists all commands and `uiprotect <command> --help` their options. The [command line docs](https://uiprotect.readthedocs.io/en/latest/cli/) cover them in detail.

### Python

The library is async. Its entry point is `uiprotect.ProtectApiClient`. A client with only an API key uses the public API:

```python
import asyncio

from uiprotect import ProtectApiClient, ProtectDeviceChange


def on_device(change: ProtectDeviceChange) -> None:
    print(change.change, change.device_id, sorted(change.changed_fields))


async def main() -> None:
    protect = ProtectApiClient.public_only(
        "YOUR_CONSOLE_IP", 443, "YOUR_API_KEY", verify_ssl=False
    )
    try:
        await protect.subscribe_devices_and_prime(on_device)
        for camera in protect.public_bootstrap.cameras.values():
            print(camera.id, camera.name)
        await asyncio.sleep(60)
    finally:
        await protect.async_disconnect_ws()
        await protect.close_session()


asyncio.run(main())
```

In this mode the private entry points (`update()`, `authenticate()`, `get_bootstrap()`) raise `PublicOnlyModeError`. A rejected key raises `NotAuthorized` on HTTP calls and turns the websockets to `WebsocketState.AUTH_FAILED`.

For features that still need the private API, pass the local user as well and call both `update()` and `update_public()`:

```python
protect = ProtectApiClient(
    "YOUR_CONSOLE_IP",
    443,
    "YOUR_USERNAME",
    "YOUR_PASSWORD",
    api_key="YOUR_API_KEY",
    verify_ssl=False,
)
```

### Subscriptions

`subscribe_events` delivers typed `(ProtectEvent, EventChange)` pairs for detection, sensor, alarm hub and access events. `subscribe_devices` delivers a `ProtectDeviceChange` for each added, updated or removed device. Devices that already exist are not announced, read them from `public_bootstrap` after priming. Both need a prior `update_public()`. `subscribe_events_and_prime()` and `subscribe_devices_and_prime()` do both in the right order.

Callbacks are plain functions called on the event loop. They must not block and must not be `async def`. Exceptions in a callback are logged and swallowed.

The [usage docs](https://uiprotect.readthedocs.io/en/latest/usage/) describe events, device changes, reconnects and the other public API features in detail.

## Contributing

Please **open an issue and agree on the approach before implementing** anything.

<a id="ai-contributions"></a>

**Using AI is fine, but you have to drive it.** We use AI tools ourselves, so an
unreviewed AI-generated PR or issue only moves the review work to us. AI-assisted
contributions are welcome when you understand the architecture
([`AGENTS.md`](https://github.com/uilibs/uiprotect/blob/main/AGENTS.md)) and the
approach was agreed in an issue first. Anything else will be closed.

What helps most is what AI cannot supply: tests on devices we do not own,
sanitized payloads from them, and first-hand knowledge of how they behave.

### Developer Setup

The recommended way to develop is using the provided **devcontainer** with VS Code:

1. Install [VS Code](https://code.visualstudio.com/) and the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
2. Open the project in VS Code
3. When prompted, click "Reopen in Container" (or use Command Palette: "Dev Containers: Reopen in Container")
4. The devcontainer will automatically set up Python, Poetry, pre-commit hooks, and all dependencies

Alternatively, if you want to develop natively without devcontainer:

```bash
# Install dependencies (--all-extras installs the cli extra for CLI tests)
poetry install --with dev --all-extras

# Install pre-commit hooks
poetry run pre-commit install --install-hooks

# Run tests
poetry run pytest

# Run pre-commit checks manually
poetry run pre-commit run --all-files
```

## History

This project was split off from `pyunifiprotect` because that project changed its license to one that would not be accepted in Home Assistant. This project is committed to keeping the MIT license.

## Credits

- Bjarne Riis ([@briis](https://github.com/briis/)) for the original pyunifiprotect package
- Christopher Bailey ([@AngellusMortis](https://github.com/AngellusMortis/)) for maintaining the pyunifiprotect package
