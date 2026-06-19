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

Python API and CLI for UniFi Protect (Unofficial).

This module communicates with UniFi Protect surveillance software installed on a UniFi OS Console such as a Ubiquiti CloudKey+ (Cloud Key Gen2 Plus), a UniFi Network Video Recorder (UNVR or UNVR Pro), or a UniFi Dream Machine Pro, SE, or Pro Max.

`uiprotect` is increasingly built on Ubiquiti's official, documented Public Integration API. Where a capability is not yet available there, it falls back to the older private API, which is undocumented and can change as Ubiquiti evolves the software — so those parts may have gaps or shift between firmware releases.

The module is primarily written for the purpose of being used in Home Assistant core [integration for UniFi Protect](https://www.home-assistant.io/integrations/unifiprotect) but might be used for other purposes also.

Full documentation for the project is available at [uiprotect.readthedocs.io](https://uiprotect.readthedocs.io/).

## Requirements

If you want to install `uiprotect` natively, the below are the requirements:

- [UniFi Protect](https://ui.com/camera-security) version 7.1+
  - The library is generally tested against the latest stable version.
- [Python](https://www.python.org/) 3.11+
- POSIX compatible system
- [PyAV](https://pyav.org/) (av) - included as a dependency
  - PyAV is used for audio streaming to camera speakers (talkback feature)

Alternatively you can use the [provided Docker container](#using-docker-container), in which case the only requirement is [Docker](https://docs.docker.com/desktop/) or another OCI compatible orchestrator (such as Kubernetes or podman).

Windows is **not supported**. If you need to use `uiprotect` on Windows, use Docker Desktop and the provided docker container or [WSL](https://docs.microsoft.com/en-us/windows/wsl/install).

## Installation

### From PyPI

`uiprotect` is available on PyPI:

```bash
pip install uiprotect
```

To use the command-line interface, install the `cli` extra (it pulls in `typer`):

```bash
pip install "uiprotect[cli]"
```

### From GitHub

```bash
pip install git+https://github.com/uilibs/uiprotect.git#egg=uiprotect
# with the CLI:
pip install "uiprotect[cli] @ git+https://github.com/uilibs/uiprotect.git"
```

### Using Docker Container

A Docker container is also provided, so you do not need to install/manage Python as well. You can add the following to your `.bashrc` or similar.

```bash
function uiprotect() {
    docker run --rm -it \
      -e UFP_USERNAME=YOUR_USERNAME_HERE \
      -e UFP_PASSWORD=YOUR_PASSWORD_HERE \
      -e UFP_ADDRESS=YOUR_IP_ADDRESS \
      -e UFP_PORT=443 \
      -e UFP_SSL_VERIFY=false \
      -e TZ=America/New_York \
      -v $PWD:/data ghcr.io/uilibs/uiprotect:latest "$@"
}
```

Some notes about the Docker version since it is running inside a container:

- You can update at any time using the command `docker pull ghcr.io/uilibs/uiprotect:latest`
- Your local current working directory (`$PWD`) will automatically be mounted to `/data` inside of the container. For commands that output files, this is the _only_ path you can write to and have the file persist.
- The container supports `linux/amd64` and `linux/arm64` natively. This means it will also work well on macOS or Windows using Docker Desktop.
- `TZ` should be the [Olson timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) for the timezone your UniFi Protect instance is in.
- For more details on `TZ` and other environment variables, check the [command line docs](https://uilibs.github.io/uiprotect/latest/cli/)

## Quickstart

### CLI

> [!WARNING]
> Ubiquiti SSO accounts are not supported and actively discouraged from being used. There is no option to use MFA. You are expected to use local access user. `uiprotect` is not designed to allow you to use your owner account to access the console or to be used over the public internet as both pose a security risk.

> [!NOTE]
> `uiprotect` is increasingly built on Ubiquiti's official Public Integration API, which authenticates with a console-scoped **API key** instead of a username/password — no SSO, MFA, or owner account involved. New functionality targets this path first, and it is expected to become the primary — and eventually the only — supported authentication method. See [Public-only mode](#public-only-mode) below.

```bash
export UFP_USERNAME=YOUR_USERNAME_HERE
export UFP_PASSWORD=YOUR_PASSWORD_HERE
export UFP_ADDRESS=YOUR_IP_ADDRESS
export UFP_PORT=443
# set to true if you have a valid HTTPS certificate for your instance
export UFP_SSL_VERIFY=false

# Alternatively, use an API key for authentication (required for public API operations)
export UFP_API_KEY=YOUR_API_KEY_HERE

uiprotect --help
uiprotect nvr
```

#### Available CLI Commands

**Top-level commands:**

- `uiprotect shell` - Start an interactive Python shell with the API client
- `uiprotect create-api-key <name>` - Create a new API key for authentication
- `uiprotect get-meta-info` - Get metadata information
- `uiprotect generate-sample-data` - Generate sample data for testing
- `uiprotect profile-ws` - Profile WebSocket performance
- `uiprotect decode-ws-msg` - Decode WebSocket messages

**Device management commands:**

- `uiprotect nvr` - NVR information and settings
- `uiprotect events` - Event management and export
- `uiprotect cameras` - Camera management
- `uiprotect lights` - Light device management
- `uiprotect sensors` - Sensor management
- `uiprotect viewers` - Viewer management
- `uiprotect liveviews` - Live view configuration
- `uiprotect chimes` - Chime management
- `uiprotect doorlocks` - Door lock management
- `uiprotect aiports` - AI port management

For more details on any command, use `uiprotect <command> --help`.

### Python

UniFi Protect itself is 100% async, so as such this library is primarily designed to be used in an async context.

The main interface for the library is the `uiprotect.ProtectApiClient`:

```python
from uiprotect import ProtectApiClient

# Initialize with username/password
protect = ProtectApiClient(host, port, username, password, verify_ssl=True)

# Or with API key (required for public API operations)
protect = ProtectApiClient(host, port, username, password, api_key=api_key, verify_ssl=True)

await protect.update() # this will initialize the protect .bootstrap and open a Websocket connection for updates

# get names of your cameras
for camera in protect.bootstrap.cameras.values():
    print(camera.name)

# subscribe to Websocket for updates to UFP
def callback(msg: WSSubscriptionMessage):
    # do stuff

unsub = protect.subscribe_websocket(callback)

# remove subscription
unsub()

```

#### Public-only mode

You can also build a client that does no private login at all — just an API
key. Private-session entry points (`update()`, `authenticate()`,
`get_bootstrap()`) raise `PublicOnlyModeError`; drive everything through
`update_public()`, `subscribe_events()`, `subscribe_devices()`, the
`get_*_public()` / `update_*_public()` methods, and `get_meta_info()`. A
revoked key surfaces as `NotAuthorized`.

```python
from uiprotect import ProtectApiClient

protect = ProtectApiClient.public_only(host, port, api_key=api_key, verify_ssl=True)
await protect.update_public()

# work with the public-API device snapshots
for siren in await protect.get_sirens_public():
    print(siren.name)

# the public API exposes no NVR mac; get_console_mac() resolves it out-of-band
# via the UniFi-OS /api/system endpoint. For new code, prefer the public-API
# primary key (nvr.id) as the device identity rather than the mac.
console_mac = await protect.get_console_mac()
```

## Usage

### Subscribing to events

`ProtectApiClient` exposes two parallel websocket contracts. The raw
`subscribe_events_websocket` continues to deliver `WSSubscriptionMessage`
frames for advanced callers, and the typed `subscribe_events` API
delivers `(ProtectEvent, EventChange)` pairs intended for application
code. The typed path goes through the Public Integration API, so the
`ProtectApiClient` must be configured with an API key and
`update_public()` must have been called at least once before calling
`subscribe_events`. The raw `subscribe_events_websocket` path does not
require an API key.

```python
import logging

from uiprotect import EventChange, ProtectApiClient, ProtectEvent

_LOGGER = logging.getLogger(__name__)

protect = ProtectApiClient(..., api_key="...")
await protect.update_public()

def on_event(event: ProtectEvent, change: EventChange) -> None:
    if change is EventChange.STARTED:
        _LOGGER.info("%s on %s: %s", event.type, event.device_id, event.identity)
    elif change is EventChange.ENDED:
        _LOGGER.info("%s ended after %s", event.type, event.end - event.start)

unsubscribe = protect.subscribe_events(on_event)
# ...
unsubscribe()
```

Notes:

- `subscribe_events` delivers only events whose `EventType` maps to a
  non-`OTHER` `ProtectEventChannel` (detection / sensor / alarm-hub /
  access). Administrative events such as `provision`, `factoryReset` and
  `fwUpdate` are dropped. Callers that need the unfiltered stream
  should use `subscribe_events_websocket`.
- `event.raw` is a permanent escape hatch onto the underlying private-API
  `Event` model when the public contract does not expose the field you
  need. In particular, smart-detect _detected attributes_ (license-plate
  text, face-match name) are **not** available over the public API today,
  so consumers that need them must fall back to the private path via
  `event.raw`.
- `EventChange.UPDATED` may carry no public-visible delta — diff
  `event.raw` if you need to know exactly what changed.
- `protect.active_events(device_id=...)` returns the in-flight set,
  derived directly from the public bootstrap cache. Useful for restoring
  binary-sensor state after a reload — it works before any
  `subscribe_events` call as long as `update_public()` has primed the
  cache.
- All runtime state is sourced from `public_bootstrap`: lifecycle/active
  state from `public_bootstrap.events`, credential-event identity from
  `public_bootstrap.ulp_users` (UniFi Identity), and `event.device_mac`
  from the bootstrap device stores. All are refreshed by `update_public()`
  — including automatically on websocket reconnect — and resolve with
  eventual consistency: an `identity` that resolves to
  `UnknownIdentity(reason="ulp_user_not_cached")` for a freshly-enrolled
  ULP user, or a `device_mac` of `None` for a device not yet in the
  bootstrap, both fill in on the next `update_public()` / reconnect resync.

### Subscribing to device state

`subscribe_devices` is the device-side analog of `subscribe_events`: it
delivers a typed `ProtectDeviceChange` for each `ADDED` / `UPDATED` /
`REMOVED` device over the Public Integration API. Together with
`public_bootstrap` (the device snapshot) and `subscribe_events`
(detection / sensor events), it gives a thin consumer the three
concern-separated primitives it needs without any model-type routing or
merge logic of its own.

Like `subscribe_events`, it requires `update_public()` to have primed the
public bootstrap (the merged public models live in that cache), so call
`update_public()` _before_ subscribing — subscribing first raises
`RuntimeError`. Callers that need the websocket live during priming should
use the raw `subscribe_devices_websocket` instead.

```python
import logging

from uiprotect import DeviceChange, ProtectApiClient, ProtectDeviceChange

_LOGGER = logging.getLogger(__name__)

protect = ProtectApiClient(..., api_key="...")

def on_device(change: ProtectDeviceChange) -> None:
    if change.change is DeviceChange.UPDATED and "state" in change.changed_fields:
        _LOGGER.info("%s -> %s", change.device_id, change.model.state)

await protect.update_public()
unsubscribe = protect.subscribe_devices(on_device)
# ...
unsubscribe()
```

Notes:

- Each change carries the merged `Public*` model in `change.model`
  (`None` for `REMOVED`, where only an id / `modelKey` reference is
  delivered). `change.changed_fields` is populated only for `UPDATED`.
- Single and bulk WS envelopes are expanded transparently to one change
  per device, so consumers never see batched `id` arrays.
- Connection / `state` transitions surface as ordinary `UPDATED`s with
  `state` in `changed_fields` — there is no separate side channel.
- The callback must not raise: an exception is caught and logged but
  otherwise swallowed.
- `change.device_mac` resolves with eventual consistency — a device not
  yet in the bootstrap yields `None` until the next `update_public()` /
  reconnect resync.
- This is device _state_ only. It does not synthesize detection / motion
  (use `subscribe_events`) and there is no adoption concept folded in.

## Roadmap & limitations

The library is moving from the legacy private API to Ubiquiti's official Public Integration API. The private API is considered legacy and is being phased out — new work targets the public API, implemented spec-conformantly: covering the features the spec exposes and staying as close to it as possible. A further goal is to enable a thin [Home Assistant integration](https://www.home-assistant.io/integrations/unifiprotect).

Out of scope: features that are strictly UniFi OS (e.g. managing RAID/disks, creating users) — if ever added, they would live in a separate library — and features that require a Ubiquiti account or Remote Access (e.g. stream sharing).

## Contributing

Please **open an issue and agree on the approach before implementing** anything — it
avoids wasted effort on changes that don't fit the project's direction.

<a id="no-new-private-api-features"></a>

> [!IMPORTANT]
> **This library does not accept new features built on the private API.**
> uiprotect is migrating from the reverse-engineered private API to UniFi's official
> Public Integration API. If a capability is missing from the public API, the right
> path is to request it from Ubiquiti / wait for it to be exposed there — **not** to
> add it on the private path. Issues or PRs that introduce new private-API
> functionality will be closed.

<a id="ai-contributions"></a>

**Using AI? Fine — but you have to drive it.** We use AI tooling ourselves, so an
unreviewed AI-generated PR or issue doesn't save us anything; it just shifts the
review and cleanup cost onto us. AI-assisted contributions are welcome **only when
you genuinely understand the architecture and the project's strategic direction, and
the approach has been agreed in an issue first.**

Where a contribution actually helps is the part AI can't supply — often because it
involves a device none of the maintainers happen to own. We have plenty of UniFi
hardware, just not every model, so testing and validation on a device we don't have,
sanitized payload captures from it, or first-hand knowledge of how it behaves in the
field are genuinely valuable — shaped to fit the architecture (see
[`AGENTS.md`](AGENTS.md)). Raw AI output that skips the prior discussion or ignores
these guidelines just creates review burden and will be closed.

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
- Christopher Bailey ([@AngellusMortis](https://github.com/AngellusMortis/)) for the maintaining the pyunifiprotect package
