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

Unofficial Python API and CLI for UniFi Protect on a UniFi OS console (Cloud Key Gen2 Plus, UNVR, UNVR Pro, Dream Machine Pro, SE or Pro Max). It is written for the Home Assistant [UniFi Protect integration](https://www.home-assistant.io/integrations/unifiprotect) but can be used on its own.

The library is moving to Ubiquiti's official Public Integration API. Where a capability is not available there yet, it falls back to the undocumented private API, which can change between Protect releases.

## Requirements

- [UniFi Protect](https://ui.com/camera-security) 7.2+, tested against the latest stable release
- [Python](https://www.python.org/) 3.11+
- [PyAV](https://pyav.org/), installed as a dependency, for talkback audio

Windows is not actively supported and not tested in CI, although it should work. Issues about Windows are welcome as a hint, but there is no promise of a fix. The [Docker container](#using-docker-container) and [WSL](https://docs.microsoft.com/en-us/windows/wsl/install) are the supported options there.

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

The Docker container needs no local Python. Add this to your `.bashrc` or similar:

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

- Update with `docker pull ghcr.io/uilibs/uiprotect:latest`.
- `$PWD` is mounted to `/data`. Files written anywhere else are lost when the container exits.
- Images exist for `linux/amd64` and `linux/arm64`, so Docker Desktop on macOS and Windows works.
- `TZ` is the [time zone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) of your Protect console. The [command line docs](https://uiprotect.readthedocs.io/en/latest/cli/) list the other environment variables.

## Quickstart

### CLI

> [!WARNING]
> Ubiquiti SSO accounts and MFA are not supported. Use a local-access user, not the owner account.

> [!NOTE]
> New features use the Public Integration API, which authenticates with an **API key**. The API key is expected to become the only supported login. See [Public-only mode](#public-only-mode).

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

`uiprotect --help` lists all commands and `uiprotect <command> --help` their options. The [command line docs](https://uiprotect.readthedocs.io/en/latest/cli/) cover them in detail.

### Python

The library is async. Its entry point is `uiprotect.ProtectApiClient`:

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

A client with only an API key does no private login. The private entry points
(`update()`, `authenticate()`, `get_bootstrap()`) raise `PublicOnlyModeError`.
Use `update_public()`, `subscribe_events()`, `subscribe_devices()`, the
`get_*_public()` / `update_*_public()` methods and `get_meta_info()` instead. A
revoked key raises `NotAuthorized`.

```python
from uiprotect import ProtectApiClient

protect = ProtectApiClient.public_only(host, port, api_key=api_key, verify_ssl=True)
await protect.update_public()

# work with the public-API device snapshots
for siren in await protect.get_sirens_public():
    print(siren.name)

# resolve the console identity; the mac comes straight off the public NVR.
# For new code, prefer the public-API primary key (nvr.id) as the device
# identity rather than the mac.
console_mac = await protect.resolve_nvr_mac()
```

## Usage

### Subscribing to events

`subscribe_events` delivers typed `(ProtectEvent, EventChange)` pairs. The raw
`subscribe_events_websocket` delivers `WSSubscriptionMessage` frames. Both use
the Public Integration API and need an API key. `subscribe_events` also needs a
prior `update_public()`, so `subscribe_events_and_prime()` does both in the
right order.

```python
import logging

from uiprotect import EventChange, ProtectApiClient, ProtectEvent

_LOGGER = logging.getLogger(__name__)

protect = ProtectApiClient(..., api_key="...")


def on_event(event: ProtectEvent, change: EventChange) -> None:
    if change is EventChange.STARTED:
        _LOGGER.info("%s on %s: %s", event.type, event.device_id, event.identity)
    elif change is EventChange.ENDED:
        _LOGGER.info("%s ended after %s", event.type, event.end - event.start)


# Order-independent: subscribes and primes in the correct order.
unsubscribe = await protect.subscribe_events_and_prime(on_event)
# ...
unsubscribe()
```

Notes:

- Only detection, sensor, alarm hub and access events are delivered.
  Administrative events such as `provision`, `factoryReset` and `fwUpdate` are
  dropped. Use `subscribe_events_websocket` for the unfiltered stream.
- `event.metadata` holds the typed event metadata. `event.raw` is the cached
  `PublicEvent` for fields `ProtectEvent` does not surface. License plate text
  and face names are not in the public API.
- `EventChange.UPDATED` can arrive without a change in the `ProtectEvent`
  fields. The change is then only in `event.raw`.
- `protect.active_events(device_id=...)` returns the running events from the
  cache, for example to restore binary sensors after a reload. It works without
  a subscription once `update_public()` has run.
- Event state, identities (`public_bootstrap.ulp_users`) and `event.device_mac`
  come from `public_bootstrap`. `update_public()` refreshes them, also on every
  websocket reconnect. Until then a newly enrolled user resolves to
  `UnknownIdentity(reason="ulp_user_not_cached")` and a new device has
  `device_mac` `None`.

### Subscribing to device state

`subscribe_devices` delivers a typed `ProtectDeviceChange` for each `ADDED`,
`UPDATED` or `REMOVED` device over the Public Integration API. It needs a prior
`update_public()` and raises `RuntimeError` otherwise. `subscribe_devices_and_prime()`
does both in one call and replays updates that arrive while priming, so none
are missed.

```python
import logging

from uiprotect import DeviceChange, ProtectApiClient, ProtectDeviceChange

_LOGGER = logging.getLogger(__name__)

protect = ProtectApiClient(..., api_key="...")


def on_device(change: ProtectDeviceChange) -> None:
    if change.change is DeviceChange.UPDATED and "state" in change.changed_fields:
        _LOGGER.info("%s -> %s", change.device_id, change.model.state)


# Order-independent: subscribes and primes in the correct order.
unsubscribe = await protect.subscribe_devices_and_prime(on_device)
# ...or the explicit two-step form, which must prime before subscribing:
# await protect.update_public()
# unsubscribe = protect.subscribe_devices(on_device)
unsubscribe()
```

Notes:

- `change.model` is the merged `Public*` model, `None` for `REMOVED`.
  `change.changed_fields` is set only for `UPDATED`.
- Bulk websocket frames are split into one change per device.
- Connection changes arrive as `UPDATED` with `state` in `changed_fields`.
- Exceptions in the callback are logged and swallowed.
- `change.device_mac` is `None` for a device that is not in the cache yet,
  until the next `update_public()` or reconnect.
- Detections and motion are not part of this stream. Use `subscribe_events`.

## Roadmap & limitations

The private API is being phased out. New work targets the public API and stays as close to its spec as possible.

Capabilities, device models and events live in this library, so the [Home Assistant integration](https://www.home-assistant.io/integrations/unifiprotect) carries as little logic of its own as possible.

## Contributing

Please **open an issue and agree on the approach before implementing** anything.

<a id="check-the-public-api"></a>

### Check the public API first

The [Public Integration API documentation](https://developer.ui.com/protect/) lists
every device field and control the library can support. If a field or control is
not there, uiprotect cannot add it.

A field is not enough when only some models have the feature: there also has to
be a feature flag or another field that tells which devices support it. Otherwise
Home Assistant would offer controls that do nothing on the other models.

To see what your own console returns, look at the public API, not the private
bootstrap:

- **Home Assistant diagnostics**: look under `public_bootstrap` (present when an API
  key is configured). The `bootstrap` section is the private API and contains fields
  the public API does not have.
- **curl** with an API key works with any endpoint from the documentation above,
  prefixed with `https://HOST/proxy/protect/integration`, for example the list of
  all cameras (`/v1/cameras`). `-k` skips the check of the console's self-signed
  certificate.

  Linux and macOS:

  ```bash
  curl -k -H "X-API-KEY: API_KEY" https://HOST/proxy/protect/integration/v1/cameras
  ```

  Windows:

  ```powershell
  curl.exe -k -H "X-API-KEY: API_KEY" https://HOST/proxy/protect/integration/v1/cameras
  ```

<a id="no-new-private-api-features"></a>

> [!IMPORTANT]
> **This library does not accept new features built on the private API.**
> uiprotect is migrating from the reverse-engineered private API to UniFi's official
> Public Integration API. If a capability is missing from the public API, the right
> path is to request it from Ubiquiti / wait for it to be exposed there — **not** to
> add it on the private path. Issues or PRs that introduce new private-API
> functionality will be closed.

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
