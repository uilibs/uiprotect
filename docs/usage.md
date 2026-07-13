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
`subscribe_events`. The example below primes then subscribes; to avoid
encoding that ordering yourself, call `subscribe_events_and_prime()` (or
`subscribe_devices_and_prime()` for device state), which connects the
WebSocket and primes in the correct order in a single call. With the combined
helper, frames that arrive while `update_public()` is priming are buffered
and replayed onto the fresh snapshot, so the already-connected subscriber
does not miss an update from the prime window; with the explicit two-step
form the subscriber is registered after priming and simply starts from the
refreshed cache:

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

### Detecting a revoked API key

A revoked or invalid API key can't be re-authenticated from inside the client
— the key is static — so the public WebSocket would otherwise redial forever on
repeated `401` handshakes without the consumer ever learning the key died.
After two consecutive `401`s the client emits `WebsocketState.AUTH_FAILED` over
the existing state channels (`subscribe_events_websocket_state` /
`subscribe_devices_websocket_state`) and switches to a longer backoff to stop
hammering the NVR. Subscribe to that channel to be notified, then install a
fresh key with `set_api_key()` — it re-arms both public WebSockets immediately
so recovery doesn't wait out the backoff:

```python
def on_state(state: WebsocketState) -> None:
    if state is WebsocketState.AUTH_FAILED:
        protect.set_api_key(fetch_new_api_key())

unsub = protect.subscribe_events_websocket_state(on_state)
```

Events arrive **only** on the events WebSocket, so if it drops and reconnects
while the devices WebSocket stays up, an `end` frame missed during the gap
would otherwise leave the event active — a camera's derived
`is_*_currently_detected` stuck ON until the periodic TTL sweep (~45 min worst
case) closes it. On events-WS reconnect the client therefore **force-ends
active detection events regardless of age** (a still-active detection
re-asserts on its next frame) and flushes other channels past the 1 h
staleness window. Both the typed `subscribe_events` stream (an `ENDED` change)
and `subscribe_devices` (a camera update naming the flipped `is_*_detected`
fields) see the drop immediately, and the derived camera flags read correct on
the next synchronous access.

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
- **Observable.** A background prime/refresh that actually changes a camera's
  streams is announced: the client emits a synthetic devices-WS `update` for
  that camera (`new_obj` is the refreshed camera) through the existing devices
  subscription, so both `subscribe_devices_websocket` and typed
  `subscribe_devices` consumers observe stream availability without polling.
  A refresh that yields no change — an identity-guard backoff, a fetch failure,
  or a re-fetch equal to the cached value — emits nothing.

## Public vs. private API

`uiprotect` can talk to UniFi Protect two ways, and is actively migrating
from the second to the first:

- **Public Integration API** — Ubiquiti's officially documented REST API
  under `/integration/v1/…`. It authenticates with an **API key** (create one
  with `uiprotect create-api-key NAME`), is stable across firmware releases,
  and is the forward-looking path. The typed `subscribe_events` stream and the
  public-API CLI groups (`viewers-public`, `users-public`, `liveviews`, …) are
  driven by this API. Requests on this path are **auto-paced** to stay under
  the server's per-API-key rate budget — the client seeds its rate from the
  `RateLimit-Policy` header on the first response (with safety margin for the
  shared-budget public WebSocket) and falls back to a conservative default
  until that header is seen, so a bootstrap fan-out no longer trips a `429`
  storm. Rotating the key via `set_api_key()` resets the pacing.
- **Private API** — the reverse-engineered, undocumented endpoints under
  `/api/…` plus the binary WebSocket update stream. It authenticates with
  username/password and powers most of the historical `bootstrap`-based
  surface. It is **not** documented by Ubiquiti, can shift between firmware
  versions, and is being deprecated capability-by-capability as the public
  API gains coverage.

Prefer the public API for new code. Reach for the private API only for
capabilities the public API does not yet expose; treat that as a temporary
escape hatch rather than the default path.

## Device convenience setters (public API)

Camera, light, sensor and chime devices from `public_bootstrap` expose `set_*`
convenience methods that patch a single setting and write the server's response
straight back into the cached device — so a **public-only client** (API key, no
username/password) can mutate a device without hand-building nested
`update_*_public` bodies:

```python
await protect.update_public()
camera = next(iter(protect.public_bootstrap.cameras.values()))

# Write-through: the cached camera reflects the change on return.
await camera.set_status_light(True)
await camera.set_mic_volume(50)
assert protect.public_bootstrap.cameras[camera.id].mic_volume == 50
```

Each setter validates the device's capability flags (e.g. a camera without a
microphone rejects `set_mic_volume`), applies the same numeric bounds the server
enforces, and serialises concurrent read-modify-write setters (chime ring
volume, camera smart-detect toggles, light mode/device settings) on one device
under a per-object lock.
`PublicCamera.rtsps_streams` is owned out-of-band by the library and is never
touched by a setter.

The private-API `Device.set_*_public` methods remain and are unchanged; when a
public bootstrap is loaded they keep the cached public twin fresh through the
same `update_*_public` endpoints, so the Home Assistant integration and the CLI
continue to work as before.

## Shared identity interface

The public device models expose the same derived identity attributes as the
private tree: `display_name` (falling back `name → type`, mirroring the private
`name → market_name → type`) and a `type` alias for the raw `device_type`
field. So `PublicNVR().display_name` and `PublicCamera().type` work the same as
their private-tree counterparts.

Code that handles "the NVR" or "a camera" generically — for example the Home
Assistant integration's device-info paths, which must now accept either tree —
can type against the `ProtectDeviceIdentity` protocol instead of `cast()`-ing
between the unrelated private (`NVR`, `Camera`, …) and public (`PublicNVR`,
`PublicCamera`, …) types. Both trees satisfy it structurally:

```python
from uiprotect.data import ProtectDeviceIdentity

def label(device: ProtectDeviceIdentity) -> str:
    # Accepts an NVR or a PublicNVR (a Camera or a PublicCamera, …) unchanged.
    return f"{device.display_name} ({device.type}) [{device.mac}] {device.id}"
```

The protocol covers `id`, `mac`, `display_name`, `type`, and `model`; `mac` and
`type` are optional because the public tree omits them on older firmware.
