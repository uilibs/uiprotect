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
        verify_ssl=True,  # set False only for a self-signed certificate
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
        verify_ssl=True,  # set False only for a self-signed certificate
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


asyncio.run(main())
```

The lower-level `subscribe_websocket` continues to deliver raw
`WSSubscriptionMessage` frames for advanced callers over the private API and
does not require an API key. The parallel `subscribe_events_websocket` drives
the Public Integration API WebSocket and **does** require an API key. See the
project README for the full notes on the typed event contract.

## Camera RTSPS streams

RTSPS stream URLs live on the camera as `PublicCamera.rtsps_streams`. The
library owns their entire lifecycle: `update_public()` primes them, so a
consumer reads the field synchronously and carries no fetch/cache code:

```python
await protect.update_public()

# Read synchronously off the camera — primed by update_public().
camera = protect.public_bootstrap.cameras[camera_id]
streams = camera.rtsps_streams
```

Priming is **always** run by `update_public()`: connected cameras without
streams are fetched under a bounded-concurrency semaphore, best-effort (one
slow/offline camera is skipped, never aborting the rest), and disconnected
cameras are skipped. `get_camera_rtsps_streams(camera_id)` is a flag-free fetch
primitive used internally — it issues a plain GET with no cache side-effects.

The field stays correct from the sources the client controls — stream
create/delete is **not** signalled over the WebSocket, so passive observation
is impossible:

- **Write-through.** `create_camera_rtsps_streams` writes its result onto the
  camera's `rtsps_streams`; `delete_camera_rtsps_streams` drops the deleted
  qualities (and clears the field to `None` once no streams remain).
- **Prime / refresh on connect.** When a public devices-WS frame moves a camera
  to `CONNECTED` (a reconnect or firmware change can rotate the `rtsp_alias`), a
  background fetch is scheduled. A camera that was **offline at `update_public()`
  time** — so skipped by the connected-only prime — is **primed** when it comes
  online mid-session, not left streamless until the next reload. An
  already-populated camera is **refreshed in place** instead. Either way a
  WebSocket reconnect resync also refreshes every populated camera. The field is
  **never emptied** — the old URLs stay readable until the fresh ones land, so
  synchronous consumers reading `camera.rtsps_streams` never observe a spurious
  `None`. It is only ever cleared by a camera `remove` frame (which drops the
  whole camera) or the client's own `delete_camera_rtsps_streams`.

### Public-API request pacing

The Public Integration API enforces a **per-API-key request budget** (observed
~10 requests/second on Protect 7.1.77) and advertises it through draft-8
`RateLimit` response headers. The public WebSocket auth/keepalive draws from the
**same** per-key pool, so an `update_public()` fan-out plus the RTSPS prime can
overshoot the ceiling and knock the live connection off (`1008` "Too many
requests") before the reactive `429` retry recovers.

To stay _under_ the budget instead of recovering _after_ exceeding it, every
`public_api=True` request is paced by a **per-client** limiter (never shared
across consoles). The limiter is **fully header-driven**: it derives its
ceiling from the server's own `RateLimit-Policy` quota — `rate = (quota −
headroom) / window`, which is a steady ~6 requests/second under today's `q=10,
w=1` policy — and reserves a headroom slice for the WebSocket keepalive. As the
remaining budget tightens it slows further (or briefly pauses until the window
resets). Because the budget comes from the headers, the pacing self-adapts if
Ubiquiti changes the server values, and it does nothing on firmware old enough
to predate the limiter middleware (no `RateLimit` headers → no pacing). The
reactive `429` retry stays in place as the universal backstop. The pacing is
automatic and transparent to callers — no configuration is required.

## Public vs. private API

`uiprotect` can talk to UniFi Protect two ways, and is actively migrating
from the second to the first:

- **Public Integration API** — Ubiquiti's officially documented REST API
  under `/integration/v1/…`. It authenticates with an **API key** (create one
  with `uiprotect create-api-key NAME`), is stable across firmware releases,
  and is the forward-looking path. The typed `subscribe_events` stream and the
  public-API CLI groups (`viewers-public`, `users-public`, `liveviews`, …) are
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
