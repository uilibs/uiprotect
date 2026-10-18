"""Tests for the devices-websocket background sensor fetch."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, Mock

import aiohttp
import orjson
import pytest

from uiprotect import ProtectApiClient
from uiprotect.data import PublicBootstrap
from uiprotect.data.public_devices import PublicSensor, SensorAlarmType
from uiprotect.data.types import ModelType
from uiprotect.data.websocket import WSAction, WSSubscriptionMessage
from uiprotect.exceptions import BadRequest, NvrError

from .test_public_devices_models import SENSOR_PAYLOAD

# Snapshot at import: other tests build models from the shared dict in place.
_BASE_PAYLOAD = deepcopy(SENSOR_PAYLOAD)
SENSOR_ID = _BASE_PAYLOAD["id"]
SMOKE_FLAGS = {"smoke": {"channelCount": 1}}


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uiprotect.api.SENSOR_FETCH_RETRY_DELAYS", (0.0, 0.0, 0.0))


def _client() -> ProtectApiClient:
    client = ProtectApiClient.public_only("127.0.0.1", 0, api_key="test_key")
    client._public_bootstrap = PublicBootstrap()
    return client


def _payload(state: str = "CONNECTED", flags: Any = None) -> dict[str, Any]:
    payload = deepcopy(_BASE_PAYLOAD)
    payload["state"] = state
    payload.pop("featureFlags", None)
    if flags is not None:
        payload["featureFlags"] = deepcopy(flags)
    return payload


def _sensor(client: ProtectApiClient, **kwargs: Any) -> PublicSensor:
    return PublicSensor.from_unifi_dict(api=client, **_payload(**kwargs))


def _frame(client: ProtectApiClient, action: str, item: dict[str, Any]) -> None:
    msg = Mock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.data = orjson.dumps({"type": action, "item": item})
    client._process_devices_ws_message(msg)


def _update(client: ProtectApiClient, **fields: Any) -> None:
    _frame(client, "update", {"id": SENSOR_ID, "modelKey": "sensor", **fields})


def _flag_frames(messages: list[WSSubscriptionMessage]) -> list[dict[str, Any]]:
    return [m.changed_data for m in messages if "featureFlags" in m.changed_data]


def _capture(client: ProtectApiClient) -> list[WSSubscriptionMessage]:
    messages: list[WSSubscriptionMessage] = []
    client._devices_ws_subscriptions.append(messages.append)
    return messages


async def _drain(client: ProtectApiClient) -> None:
    while client._sensor_fetch_tasks:
        task, _state = next(iter(client._sensor_fetch_tasks.values()))
        await asyncio.gather(task, return_exceptions=True)


def _blocking_get(
    client: ProtectApiClient, result: PublicSensor
) -> tuple[asyncio.Event, AsyncMock]:
    release = asyncio.Event()

    async def _get(sensor_id: str) -> PublicSensor:
        await release.wait()
        return result

    get = AsyncMock(side_effect=_get)
    client.get_sensor_public = get  # type: ignore[method-assign]
    return release, get


@pytest.mark.asyncio()
async def test_pairing_sensor_gets_feature_flags_on_connected() -> None:
    """A sensor paired over the WS gets its flags merged once it is CONNECTED."""
    client = _client()
    messages = _capture(client)
    fetched = _sensor(client, flags=SMOKE_FLAGS)
    fetched.name = "REST name"
    client.get_sensor_public = AsyncMock(return_value=fetched)  # type: ignore[method-assign]

    _frame(client, "add", _payload(state="DISCONNECTED"))
    _update(client, state="CONNECTING", name="Pairing")
    assert client._sensor_fetch_tasks == {}
    _update(client, state="CONNECTED")
    await _drain(client)

    sensor = client._public_bootstrap.sensors[SENSOR_ID]
    client.get_sensor_public.assert_awaited_once_with(SENSOR_ID)
    assert sensor.supported_alarm_types == {SensorAlarmType.SMOKE, SensorAlarmType.CO}
    assert sensor.name == "Pairing"
    assert _flag_frames(messages) == [
        {"modelKey": "sensor", "id": SENSOR_ID, "featureFlags": SMOKE_FLAGS}
    ]
    msg = messages[-1]
    assert msg.action is WSAction.UPDATE
    assert msg.new_update_id == SENSOR_ID
    assert msg.new_obj is sensor
    assert msg.old_obj is None


@pytest.mark.asyncio()
async def test_pairing_frame_sequence_from_console() -> None:
    """The console's pairing frames, flapping before CONNECTED, yield one flags frame."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            _sensor(client, state="CONNECTING"),
            _sensor(client, state="CONNECTED", flags=SMOKE_FLAGS),
        ]
    )

    _frame(client, "add", _payload(state="DISCONNECTED"))
    for state in ("CONNECTING", "DISCONNECTED", "CONNECTING", "DISCONNECTED"):
        _update(client, state=state)
    _update(client, state="CONNECTING", name="Pairing")
    assert client._sensor_fetch_tasks == {}
    _update(client, state="CONNECTED")
    _update(client, state="CONNECTED", isMotionDetected=True)
    await _drain(client)

    sensor = client._public_bootstrap.sensors[SENSOR_ID]
    assert client.get_sensor_public.await_count == 2
    assert sensor.supported_alarm_types == {SensorAlarmType.SMOKE, SensorAlarmType.CO}
    assert sensor.name == "Pairing"
    assert _flag_frames(messages) == [
        {"modelKey": "sensor", "id": SENSOR_ID, "featureFlags": SMOKE_FLAGS}
    ]


@pytest.mark.asyncio()
async def test_fetch_retries_while_rest_lags() -> None:
    """A 200 without flags or not yet CONNECTED is retried until both arrive."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            _sensor(client, state="DISCONNECTED"),
            _sensor(client, state="CONNECTING", flags=SMOKE_FLAGS),
            _sensor(client, state="CONNECTED"),
            _sensor(client, state="CONNECTED", flags=SMOKE_FLAGS),
        ]
    )
    _frame(client, "add", _payload(state="CONNECTING"))

    _update(client, state="CONNECTED")
    await _drain(client)

    assert client.get_sensor_public.await_count == 4
    assert client._public_bootstrap.sensors[SENSOR_ID].supported_alarm_types
    assert len(_flag_frames(messages)) == 1
    assert client._sensor_fetch_failed == {}


@pytest.mark.asyncio()
async def test_fetch_retry_is_bounded() -> None:
    """A sensor REST never reports flags for stops after the last retry."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, state="CONNECTING")
    )
    _frame(client, "add", _payload(state="DISCONNECTED"))

    _update(client, state="CONNECTED")
    await _drain(client)

    assert client.get_sensor_public.await_count == 4
    assert _flag_frames(messages) == []
    assert not client._public_bootstrap.sensors[SENSOR_ID].supported_alarm_types


@pytest.mark.asyncio()
async def test_connected_sensor_with_flags_is_not_fetched() -> None:
    """A sensor reconnecting with flags in hand is not fetched."""
    client = _client()
    client.get_sensor_public = AsyncMock()  # type: ignore[method-assign]
    _frame(client, "add", _payload(state="DISCONNECTED", flags=SMOKE_FLAGS))

    _update(client, state="CONNECTED")

    assert client._sensor_fetch_tasks == {}
    client.get_sensor_public.assert_not_called()


@pytest.mark.asyncio()
async def test_sensor_without_flags_is_fetched_once_per_reconnect() -> None:
    """A sensor reporting no flags is fetched on each CONNECTED transition only."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client)
    )
    _frame(client, "add", _payload(state="DISCONNECTED"))

    _update(client, state="CONNECTED")
    await _drain(client)
    _update(client, state="CONNECTED")
    _update(client, name="Renamed")
    assert client._sensor_fetch_tasks == {}
    assert client.get_sensor_public.await_count == 4
    assert _flag_frames(messages) == []

    _update(client, state="DISCONNECTED")
    _update(client, state="CONNECTED")
    await _drain(client)
    assert client.get_sensor_public.await_count == 8


@pytest.mark.asyncio()
async def test_update_for_unknown_sensor_adds_it() -> None:
    """An ``update`` for a sensor whose ``add`` was missed fetches and adds it."""
    client = _client()
    messages = _capture(client)
    fetched = _sensor(client, flags=SMOKE_FLAGS)
    client.get_sensor_public = AsyncMock(return_value=fetched)  # type: ignore[method-assign]

    _update(client, state="CONNECTED")
    await _drain(client)

    assert client._public_bootstrap.sensors[SENSOR_ID] is fetched
    msg = messages[-1]
    assert msg.action is WSAction.ADD
    assert msg.new_obj is fetched
    assert msg.changed_data == {"modelKey": "sensor", "id": SENSOR_ID}


@pytest.mark.asyncio()
async def test_not_found_sensor_waits_for_state_change() -> None:
    """After a 404 the sensor is not fetched again until its state changes."""
    client = _client()
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=BadRequest("404")
    )

    _update(client, state="CONNECTED")
    await _drain(client)
    assert client.get_sensor_public.await_count == 1

    _update(client, state="CONNECTED")
    _update(client, isMotionDetected=True)
    assert client._sensor_fetch_tasks == {}
    assert client.get_sensor_public.await_count == 1

    _update(client, state="DISCONNECTED")
    await _drain(client)
    assert client.get_sensor_public.await_count == 2

    fetched = _sensor(client)
    client.get_sensor_public = AsyncMock(return_value=fetched)  # type: ignore[method-assign]
    _update(client, state="CONNECTED")
    await _drain(client)
    assert client._public_bootstrap.sensors[SENSOR_ID] is fetched
    assert client._sensor_fetch_failed == {}


@pytest.mark.asyncio()
async def test_known_sensor_fetch_failure_waits_for_reconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed fetch is logged and retried on the next CONNECTED transition."""
    client = _client()
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=NvrError("boom")
    )
    _frame(client, "add", _payload(state="DISCONNECTED"))

    with caplog.at_level(logging.WARNING):
        _update(client, state="CONNECTED")
        await _drain(client)

    assert "Failed to fetch sensor sensor1: boom" in caplog.text
    assert client.get_sensor_public.await_count == 1
    assert client._sensor_fetch_failed == {SENSOR_ID: "CONNECTED"}

    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, flags=SMOKE_FLAGS)
    )
    _update(client, state="DISCONNECTED")
    assert client._sensor_fetch_failed == {}
    _update(client, state="CONNECTED")
    await _drain(client)
    assert client._public_bootstrap.sensors[SENSOR_ID].supported_alarm_types


@pytest.mark.asyncio()
async def test_fetch_is_coalesced_per_state() -> None:
    """Frames for the same state join the fetch in flight; a new state restarts it."""
    client = _client()
    release, get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))

    _update(client, state="CONNECTING")
    first, _state = client._sensor_fetch_tasks[SENSOR_ID]
    _update(client, state="CONNECTING")
    _update(client, isMotionDetected=True)
    assert client._sensor_fetch_tasks[SENSOR_ID][0] is first
    await asyncio.sleep(0)

    _update(client, state="CONNECTED")
    second, state = client._sensor_fetch_tasks[SENSOR_ID]
    assert second is not first
    assert state == "CONNECTED"
    release.set()
    await _drain(client)

    assert first.cancelled()
    assert get.await_count == 2
    assert SENSOR_ID in client._public_bootstrap.sensors


@pytest.mark.asyncio()
async def test_remove_cancels_fetch_and_forgets_failure() -> None:
    """A ``remove`` cancels the fetch in flight and clears a recorded failure."""
    client = _client()
    _release, _get = _blocking_get(client, _sensor(client))
    client._sensor_fetch_failed["other"] = "DISCONNECTED"
    _update(client, state="CONNECTED")
    task, _state = client._sensor_fetch_tasks[SENSOR_ID]

    _frame(client, "remove", {"id": SENSOR_ID, "modelKey": "sensor"})
    _frame(client, "remove", {"id": "other", "modelKey": "sensor"})
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert client._sensor_fetch_tasks == {}
    assert client._sensor_fetch_failed == {}
    assert SENSOR_ID not in client._public_bootstrap.sensors


@pytest.mark.asyncio()
async def test_fetch_does_not_resurrect_dropped_sensor() -> None:
    """A sensor dropped from the cache mid-fetch is not written back."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)

    del client._public_bootstrap.sensors[SENSOR_ID]
    count = len(messages)
    release.set()
    await _drain(client)

    assert SENSOR_ID not in client._public_bootstrap.sensors
    assert len(messages) == count


@pytest.mark.asyncio()
async def test_fetch_skips_replaced_sensor() -> None:
    """A sensor replaced mid-fetch keeps the replacement's flags."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)

    replacement = _sensor(client, flags={"motion": {"channelCount": 1}})
    client._public_bootstrap.sensors[SENSOR_ID] = replacement
    count = len(messages)
    release.set()
    await _drain(client)

    assert client._public_bootstrap.sensors[SENSOR_ID] is replacement
    assert not replacement.supported_alarm_types
    assert len(messages) == count


@pytest.mark.asyncio()
async def test_fetch_skips_replaced_sensor_without_flags() -> None:
    """A sensor replaced mid-fetch by one without flags is left alone."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)

    replacement = _sensor(client)
    client._public_bootstrap.sensors[SENSOR_ID] = replacement
    count = len(messages)
    release.set()
    await _drain(client)

    assert client._public_bootstrap.sensors[SENSOR_ID] is replacement
    assert not replacement.supported_alarm_types
    assert len(messages) == count


@pytest.mark.asyncio()
async def test_state_change_cancels_pending_fetch() -> None:
    """Leaving CONNECTED cancels its fetch, so the next CONNECTED fetches again."""
    client = _client()
    release, get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _update(client, state="CONNECTED")
    first, _state = client._sensor_fetch_tasks[SENSOR_ID]
    await asyncio.sleep(0)

    _update(client, state="DISCONNECTED")
    assert client._sensor_fetch_tasks == {}
    await asyncio.gather(first, return_exceptions=True)
    assert first.cancelled()
    assert client._sensor_fetch_failed == {}

    _update(client, state="CONNECTED")
    release.set()
    await _drain(client)
    assert client._public_bootstrap.sensors[SENSOR_ID].supported_alarm_types
    assert get.await_count == 2


@pytest.mark.asyncio()
async def test_unknown_sensor_not_added_while_snapshot_applies() -> None:
    """A missed-add fetch landing mid-``update_public`` leaves membership to it."""
    client = _client()
    release, _get = _blocking_get(client, _sensor(client))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)
    messages = _capture(client)

    client._prime_ws_buffer = []
    release.set()
    await _drain(client)

    assert client._public_bootstrap.sensors == {}
    assert messages == []
    assert client._sensor_fetch_failed == {}


@pytest.mark.asyncio()
async def test_filtered_sensor_flags_merge_silently() -> None:
    """Flags are merged but not announced when sensors are filtered out."""
    client = _client()
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, flags=SMOKE_FLAGS)
    )
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _update(client, state="CONNECTED")
    messages = _capture(client)
    client._devices_ws_subscribed_models = {ModelType.CAMERA}

    await _drain(client)

    assert client._public_bootstrap.sensors[SENSOR_ID].supported_alarm_types
    assert messages == []


@pytest.mark.asyncio()
async def test_fetch_for_unknown_sensor_merges_into_late_add() -> None:
    """An ``add`` landing mid-fetch for an unknown sensor gets the fetched flags."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)

    _frame(client, "add", _payload(state="CONNECTED"))
    added = client._public_bootstrap.sensors[SENSOR_ID]
    release.set()
    await _drain(client)

    assert client._public_bootstrap.sensors[SENSOR_ID] is added
    assert added.supported_alarm_types
    assert len(_flag_frames(messages)) == 1
    assert messages[-1].action is WSAction.UPDATE
    assert messages[-1].new_obj is added


@pytest.mark.asyncio()
async def test_fetch_skips_replaced_bootstrap() -> None:
    """A fetch started against a discarded bootstrap writes nothing back."""
    client = _client()
    release, _get = _blocking_get(client, _sensor(client))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)

    client._public_bootstrap = PublicBootstrap()
    release.set()
    await _drain(client)

    assert client._public_bootstrap.sensors == {}


def test_fetch_needs_running_loop() -> None:
    """Without a running event loop no fetch is scheduled."""
    client = _client()
    client._sync_sensor_fetch(
        client._public_bootstrap, SENSOR_ID, "CONNECTED", fetch=True
    )
    assert client._sensor_fetch_tasks == {}


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "teardown", ["async_disconnect_ws", "close_session", "close_public_api_session"]
)
async def test_teardown_cancels_fetches(teardown: str) -> None:
    """Disconnecting the websockets or closing the client cancels pending fetches."""
    client = _client()
    _release, _get = _blocking_get(client, _sensor(client))
    _update(client, state="CONNECTED")
    task, _state = client._sensor_fetch_tasks[SENSOR_ID]
    client._sensor_fetch_failed["other"] = None

    await getattr(client, teardown)()

    assert task.cancelled()
    assert client._sensor_fetch_tasks == {}
    assert client._sensor_fetch_failed == {}


@pytest.mark.asyncio()
async def test_close_public_api_session_cancels_retrying_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fetch sleeping between retries is cancelled and opens no new session."""
    monkeypatch.setattr("uiprotect.api.SENSOR_FETCH_RETRY_DELAYS", (3600.0,))
    client = _client()
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, state="CONNECTING")
    )
    _update(client, state="CONNECTED")
    task, _state = client._sensor_fetch_tasks[SENSOR_ID]
    await asyncio.sleep(0)
    assert client.get_sensor_public.await_count == 1

    await client.close_public_api_session()
    await asyncio.sleep(0)

    assert task.cancelled()
    assert client.get_sensor_public.await_count == 1
    assert client._public_api_session is None
