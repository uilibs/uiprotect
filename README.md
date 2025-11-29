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

Python API for UniFi Protect (Unofficial)

## Looking for maintainers

This project is looking for maintainers.

## Installation

Install this via pip (or your favorite package manager):

`pip install uiprotect`

## Developer Setup

The recommended way to develop is using the provided **devcontainer** with VS Code:

1. Install [VS Code](https://code.visualstudio.com/) and the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
2. Open the project in VS Code
3. When prompted, click "Reopen in Container" (or use Command Palette: "Dev Containers: Reopen in Container")
4. The devcontainer will automatically set up Python, Poetry, pre-commit hooks, and all dependencies

Alternatively, if you want to develop natively without devcontainer:

```bash
# Install dependencies
poetry install --with dev

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

## Contributors ✨

Thanks goes to these wonderful people ([emoji key](https://allcontributors.org/docs/en/emoji-key)):

<!-- prettier-ignore-start -->
<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- markdownlint-disable -->
<!-- markdownlint-enable -->
<!-- ALL-CONTRIBUTORS-LIST:END -->
<!-- prettier-ignore-end -->

This project follows the [all-contributors](https://github.com/all-contributors/all-contributors) specification. Contributions of any kind welcome!

`uiprotect` is an unofficial API for UniFi Protect. There is no affiliation with Ubiquiti.

This module communicates with UniFi Protect surveillance software installed on a UniFi OS Console such as a Ubiquiti CloudKey+ or UniFi Dream Machine Pro.

The API is not documented by Ubiquiti, so there might be misses and/or frequent changes in this module, as Ubiquiti evolves the software.

The module is primarily written for the purpose of being used in Home Assistant core [integration for UniFi Protect](https://www.home-assistant.io/integrations/unifiprotect) but might be used for other purposes also.

## Documentation

[Full documentation for the project](https://uiprotect.readthedocs.io/).

## Requirements

If you want to install `uiprotect` natively, the below are the requirements:

- [UniFi Protect](https://ui.com/camera-security) version 6.0+
  - Only UniFi Protect version 6 and newer are supported. The library is generally tested against the latest stable version and the latest EA version.
- [Python](https://www.python.org/) 3.10+
- POSIX compatible system
  - Library is only tested on Linux, specifically the latest Debian version available for the official Python Docker images, but there is no reason the library should not work on any Linux distro or macOS.
- [ffmpeg](https://ffmpeg.org/)
  - ffmpeg is primarily only for streaming audio to Protect cameras, this can be considered a soft requirement

Alternatively you can use the [provided Docker container](#using-docker-container), in which case the only requirement is [Docker](https://docs.docker.com/desktop/) or another OCI compatible orchestrator (such as Kubernetes or podman).

Windows is **not supported**. If you need to use `uiprotect` on Windows, use Docker Desktop and the provided docker container or [WSL](https://docs.microsoft.com/en-us/windows/wsl/install).

## Install

### From PyPi

`uiprotect` is available on PyPi:

```bash
pip install uiprotect
```

### From GitHub

```bash
pip install git+https://github.com/uilibs/uiprotect.git#egg=uiprotect
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

## TODO / Planned / Not Implemented

Switching from Protect Private API to the New Public API

Generally any feature missing from the library is planned to be done eventually / nice to have with the following exceptions

### UniFi OS Features

Anything that is strictly a UniFi OS feature. If it is ever done, it will be in a separate library that interacts with this one. Examples include:

- Managing RAID and disks
- Creating and managing users

### Remote Access / Ubiquiti Cloud Features

Some features that require an Ubiquiti Account or "Remote Access" to be enabled are currently not implemented. Examples include:

- Stream sharing
