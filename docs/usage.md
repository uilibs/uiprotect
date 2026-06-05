# Usage

Assuming that you've followed the [installation steps](installation.md),
you're now ready to use this package. `uiprotect` is an async library, so the
examples below drive an event loop with `asyncio.run`.

## Command line

Most day-to-day tasks are available through the bundled CLI:

```bash
uiprotect --help
```

See the [Command Line](cli.md) reference for the full list of subcommands.

## Connecting from Python

Instantiate `ProtectApiClient` with your console's address and a local-access
user, call `update()` once to fetch the bootstrap snapshot, then read devices
off the cached `bootstrap`:

```python
import asyncio

from uiprotect import ProtectApiClient


async def main() -> None:
    protect = ProtectApiClient(
        host="10.0.0.1",
        port=443,
        username="YOUR_USERNAME",
        password="YOUR_PASSWORD",
        verify_ssl=False,  # set True if your console has a valid certificate
    )

    # Fetch the bootstrap snapshot (cameras, lights, sensors, NVR, ...).
    await protect.update()

    for camera in protect.bootstrap.cameras.values():
        print(camera.id, camera.name, camera.is_connected)

    await protect.close_session()


asyncio.run(main())
```

!!! warning "About Ubiquiti SSO accounts"

    Ubiquiti SSO (cloud) accounts are not supported. Use a local-access user.
    Driving the cloud owner account over the public Internet is a security
    risk and there is no MFA support.

## Subscribing to events

The typed event stream delivers `(ProtectEvent, EventChange)` pairs. It is
backed by the Public Integration API, so the client must be configured with
an `api_key` and `update_public()` must have run at least once before calling
`subscribe_events`:

```python
import asyncio
import logging

from uiprotect import EventChange, ProtectApiClient, ProtectEvent

_LOGGER = logging.getLogger(__name__)


async def main() -> None:
    protect = ProtectApiClient(
        host="10.0.0.1",
        port=443,
        username="YOUR_USERNAME",
        password="YOUR_PASSWORD",
        api_key="YOUR_API_KEY",
        verify_ssl=False,
    )
    await protect.update_public()

    def on_event(event: ProtectEvent, change: EventChange) -> None:
        if change is EventChange.STARTED:
            _LOGGER.info("%s on %s", event.type, event.device_id)

    unsubscribe = protect.subscribe_events(on_event)
    try:
        await asyncio.sleep(60)
    finally:
        unsubscribe()
        await protect.close_session()
        await protect.close_public_api_session()


asyncio.run(main())
```

The lower-level `subscribe_events_websocket` continues to deliver raw
`WSSubscriptionMessage` frames for advanced callers and does not require an
API key. See the project README for the full notes on the typed event
contract.

## Public vs. private API

`uiprotect` can talk to UniFi Protect two ways, and is actively migrating
from the second to the first:

- **Public Integration API** — Ubiquiti's officially documented REST API
  under `/integration/v1/…`. It authenticates with an **API key** (create one
  with `uiprotect create-api-key NAME`), is stable across firmware releases,
  and is the forward-looking path. The typed `subscribe_events` stream and the
  `*-public` CLI groups (`viewers-public`, `users-public`, `liveviews`, …) are
  driven by this API.
- **Private API** — the reverse-engineered, undocumented endpoints under
  `/api/…` plus the binary WebSocket update stream. It authenticates with
  username/password and powers most of the historical `bootstrap`-based
  surface. It is **not** documented by Ubiquiti, can shift between firmware
  versions, and is being deprecated capability-by-capability as the public
  API gains coverage.

Prefer the public API for new code. Reach for the private API only for
capabilities the public API does not yet expose; treat that as a temporary
escape hatch rather than the default path.
