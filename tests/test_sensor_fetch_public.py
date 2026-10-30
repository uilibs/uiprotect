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


def _seed(client: ProtectApiClient, **kwargs: Any) -> None:
    """Cache a sensor already announced, as an ``update_public`` snapshot does."""
    client._public_bootstrap.sensors[SENSOR_ID] = _sensor(client, **kwargs)


def _adds(messages: list[WSSubscriptionMessage]) -> list[WSSubscriptionMessage]:
    return [m for m in messages if m.action is WSAction.ADD]


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
async def test_pairing_frame_sequence_from_console() -> None:
    """The console's pairing frames, flapping before CONNECTED, merge flags once."""
    client = _client()
    messages = _capture(client)
    fetched = _sensor(client, state="CONNECTED", flags=SMOKE_FLAGS)
    fetched.name = "REST name"
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=[_sensor(client, state="CONNECTING"), fetched]
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
    assert _flag_frames(messages) == []
    assert [m.action for m in messages] == [WSAction.UPDATE] * 7 + [WSAction.ADD]
    msg = messages[-1]
    assert msg.changed_data == {"modelKey": "sensor", "id": SENSOR_ID}
    assert msg.new_update_id == SENSOR_ID
    assert msg.new_obj is sensor
    assert msg.old_obj is None
    assert client._sensor_add_pending == set()


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
    _seed(client, state="CONNECTING")

    _update(client, state="CONNECTED")
    await _drain(client)

    assert client.get_sensor_public.await_count == 4
    assert client._public_bootstrap.sensors[SENSOR_ID].supported_alarm_types
    assert len(_flag_frames(messages)) == 1
    assert messages[-1].action is WSAction.UPDATE
    assert messages[-1].new_obj is client._public_bootstrap.sensors[SENSOR_ID]
    assert messages[-1].old_obj is None
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
@pytest.mark.parametrize("flags", [{"motion": {"channelCount": 1}}, None])
async def test_fetch_skips_replaced_sensor(flags: dict[str, Any] | None) -> None:
    """A sensor replaced mid-fetch is left alone."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _seed(client, state="DISCONNECTED")
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)

    replacement = _sensor(client, flags=flags)
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
    _seed(client, state="DISCONNECTED")
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
    assert _flag_frames(messages) == []
    assert [m.new_obj for m in _adds(messages)] == [added]


@pytest.mark.asyncio()
async def test_flagless_fetch_keeps_late_instance_flags() -> None:
    """A response without flags leaves a sensor cached mid-fetch with flags alone."""
    client = _client()
    release, _get = _blocking_get(client, _sensor(client))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)
    messages = _capture(client)

    late = _sensor(client, flags=SMOKE_FLAGS)
    client._public_bootstrap.sensors[SENSOR_ID] = late
    release.set()
    await _drain(client)

    assert client._public_bootstrap.sensors[SENSOR_ID] is late
    assert late.supported_alarm_types == {SensorAlarmType.SMOKE, SensorAlarmType.CO}
    assert messages == []


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


@pytest.mark.asyncio()
async def test_add_with_flags_is_emitted_immediately() -> None:
    """A sensor already carrying flags on ``add`` is announced at once."""
    client = _client()
    messages = _capture(client)

    _frame(client, "add", _payload(state="DISCONNECTED", flags=SMOKE_FLAGS))

    assert len(_adds(messages)) == 1
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_pending_sensor_is_cached_and_updates_are_emitted() -> None:
    """A held sensor is in the cache and its ``update`` frames still go out."""
    client = _client()
    messages = _capture(client)

    _frame(client, "add", _payload(state="DISCONNECTED"))
    assert messages == []
    assert SENSOR_ID in client._public_bootstrap.sensors
    assert client._sensor_add_pending == {SENSOR_ID}

    _update(client, name="Pairing")
    assert [m.action for m in messages] == [WSAction.UPDATE]


@pytest.mark.asyncio()
@pytest.mark.parametrize("flags", [None, {"smoke": None}])
async def test_pending_sensor_with_empty_flags_is_added(flags: Any) -> None:
    """A sensor REST never reports flags for is added once retries run out."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, flags=flags)
    )
    _frame(client, "add", _payload(state="DISCONNECTED"))

    _update(client, state="CONNECTED")
    await _drain(client)

    assert client.get_sensor_public.await_count == 4
    assert [m.new_obj for m in _adds(messages)] == [
        client._public_bootstrap.sensors[SENSOR_ID]
    ]
    assert _flag_frames(messages) == []
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "error", [NvrError("boom"), BadRequest("404")], ids=["nvr-error", "not-found"]
)
async def test_failed_fetch_while_connected_emits_add(error: Exception) -> None:
    """A fetch failing for a CONNECTED pending sensor still announces it, once."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=error
    )
    _frame(client, "add", _payload(state="CONNECTED"))
    assert _adds(messages) == []

    await _drain(client)

    assert len(_adds(messages)) == 1
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_add_after_failed_fetch_in_same_state_is_not_held() -> None:
    """With no fetch left to wait for, a CONNECTED ``add`` goes out at once."""
    client = _client()
    messages = _capture(client)
    client._sensor_fetch_failed[SENSOR_ID] = "CONNECTED"

    _frame(client, "add", _payload(state="CONNECTED"))

    assert len(_adds(messages)) == 1
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_failed_fetch_before_connected_keeps_sensor_pending() -> None:
    """A late ``add`` whose fetch fails before CONNECTED stays unannounced."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=BadRequest("404")
    )
    _update(client, state="CONNECTING")
    _frame(client, "add", _payload(state="CONNECTING"))

    await _drain(client)

    assert _adds(messages) == []
    assert client._sensor_add_pending == {SENSOR_ID}


@pytest.mark.asyncio()
async def test_flagless_fetch_before_connected_keeps_sensor_pending() -> None:
    """A fetch without flags for a sensor not yet CONNECTED does not announce it."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, state="CONNECTING")
    )
    _update(client, state="CONNECTING")
    _frame(client, "add", _payload(state="CONNECTING"))

    await _drain(client)

    assert _adds(messages) == []
    assert client._sensor_add_pending == {SENSOR_ID}


@pytest.mark.asyncio()
async def test_never_connecting_sensor_is_never_announced() -> None:
    """An unadopted sensor flapping below CONNECTED is not fetched or announced."""
    client = _client()
    messages = _capture(client)
    client.get_sensor_public = AsyncMock()  # type: ignore[method-assign]

    _frame(client, "add", _payload(state="DISCONNECTED"))
    _update(client, state="CONNECTING")
    _update(client, state="DISCONNECTED")

    client.get_sensor_public.assert_not_called()
    assert _adds(messages) == []
    assert client._sensor_add_pending == {SENSOR_ID}


@pytest.mark.asyncio()
async def test_leaving_connected_mid_fetch_keeps_add_held() -> None:
    """A fetch cancelled by a state change defers the ``add`` to the next CONNECTED."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _frame(client, "add", _payload(state="CONNECTED"))
    await asyncio.sleep(0)

    _update(client, state="DISCONNECTED")
    assert _adds(messages) == []

    _update(client, state="CONNECTED")
    release.set()
    await _drain(client)
    assert len(_adds(messages)) == 1


@pytest.mark.asyncio()
async def test_remove_while_pending_is_not_emitted() -> None:
    """A ``remove`` for a held sensor clears it and stays silent."""
    client = _client()
    messages = _capture(client)
    _release, _get = _blocking_get(client, _sensor(client))
    _frame(client, "add", _payload(state="CONNECTED"))
    task, _state = client._sensor_fetch_tasks[SENSOR_ID]

    _frame(client, "remove", {"id": SENSOR_ID, "modelKey": "sensor"})
    await asyncio.gather(task, return_exceptions=True)

    assert messages == []
    assert client._sensor_add_pending == set()
    assert SENSOR_ID not in client._public_bootstrap.sensors


@pytest.mark.asyncio()
async def test_remove_of_announced_sensor_is_emitted() -> None:
    """A ``remove`` for a sensor subscribers know about still goes out."""
    client = _client()
    _frame(client, "add", _payload(state="DISCONNECTED", flags=SMOKE_FLAGS))
    messages = _capture(client)

    _frame(client, "remove", {"id": SENSOR_ID, "modelKey": "sensor"})

    assert [m.action for m in messages] == [WSAction.REMOVE]


@pytest.mark.asyncio()
async def test_repeated_add_while_pending_stays_held() -> None:
    """A repeated ``add``, even one that cannot be parsed, keeps the sensor held."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _frame(client, "add", _payload(state="CONNECTED"))
    await asyncio.sleep(0)

    _frame(client, "add", _payload(state="CONNECTED"))
    _frame(client, "add", {"id": SENSOR_ID, "modelKey": "sensor", "mac": None})
    assert messages == []

    current = client._public_bootstrap.sensors[SENSOR_ID]
    release.set()
    await _drain(client)

    assert [m.new_obj for m in _adds(messages)] == [current]
    assert current.supported_alarm_types


@pytest.mark.asyncio()
async def test_repeated_add_with_flags_releases_pending_sensor() -> None:
    """A repeated ``add`` that carries flags is the sensor's one announcement."""
    client = _client()
    messages = _capture(client)
    _frame(client, "add", _payload(state="DISCONNECTED"))

    _frame(client, "add", _payload(state="DISCONNECTED", flags=SMOKE_FLAGS))

    assert len(_adds(messages)) == 1
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_add_for_announced_sensor_without_flags_is_emitted() -> None:
    """Only a newly appearing sensor is held."""
    client = _client()
    _seed(client, state="DISCONNECTED")
    messages = _capture(client)

    _frame(client, "add", _payload(state="DISCONNECTED"))

    assert len(_adds(messages)) == 1
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_filtered_pending_sensor_is_dropped_silently() -> None:
    """A filter set while a sensor is held suppresses its ``add``."""
    client = _client()
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, flags=SMOKE_FLAGS)
    )
    _frame(client, "add", _payload(state="CONNECTED"))
    messages = _capture(client)
    client._devices_ws_subscribed_models = {ModelType.CAMERA}

    await _drain(client)

    assert messages == []
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_snapshot_replacing_instance_mid_fetch_still_announces() -> None:
    """A pending sensor replaced mid-fetch is announced on the current instance."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _frame(client, "add", _payload(state="CONNECTED"))
    await asyncio.sleep(0)

    replacement = _sensor(client)
    client._public_bootstrap.sensors[SENSOR_ID] = replacement
    release.set()
    await _drain(client)

    assert [m.new_obj for m in _adds(messages)] == [replacement]
    assert replacement.supported_alarm_types


def _mock_resync(client: ProtectApiClient, sensors: list[PublicSensor]) -> None:
    client.get_sensors_public = AsyncMock(  # type: ignore[method-assign]
        return_value=sensors
    )
    for getter in (
        "get_nvr_public",
        "get_cameras_public",
        "get_chimes_public",
        "get_lights_public",
        "get_sirens_public",
        "get_relays_public",
        "get_fobs_public",
        "get_speakers_public",
        "get_link_stations_public",
        "_fetch_liveviews",
        "get_bridges_public",
        "get_viewers_public",
        "get_ulp_users_public",
        "_fetch_arm_profiles",
    ):
        setattr(client, getter, AsyncMock(side_effect=BadRequest("unavailable")))


@pytest.mark.asyncio()
async def test_resync_keeps_disconnected_pending_sensor_held() -> None:
    """A resync seeing a pending sensor still offline emits nothing for it."""
    client = _client()
    messages = _capture(client)
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _mock_resync(client, [_sensor(client, state="DISCONNECTED")])

    await client.update_public()

    assert messages == []
    assert client._sensor_add_pending == {SENSOR_ID}


@pytest.mark.asyncio()
async def test_resync_with_flags_announces_pending_sensor_once() -> None:
    """A snapshot completing a pending sensor yields exactly one ``add``."""
    client = _client()
    messages = _capture(client)
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _mock_resync(client, [_sensor(client, state="CONNECTED", flags=SMOKE_FLAGS)])

    await client.update_public()
    await client.update_public()

    assert [m.new_obj for m in _adds(messages)] == [
        client._public_bootstrap.sensors[SENSOR_ID]
    ]
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_resync_fetches_pending_sensor_that_connected_in_gap() -> None:
    """A CONNECTED frame lost to the gap still gets the pending sensor announced."""
    client = _client()
    messages = _capture(client)
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _mock_resync(client, [_sensor(client, state="CONNECTED")])
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, flags=SMOKE_FLAGS)
    )

    await client.update_public()
    await _drain(client)

    sensor = client._public_bootstrap.sensors[SENSOR_ID]
    assert [m.new_obj for m in _adds(messages)] == [sensor]
    assert sensor.supported_alarm_types


@pytest.mark.asyncio()
async def test_resync_dropping_pending_sensor_emits_no_remove() -> None:
    """A pending sensor gone from the snapshot is forgotten without a ``remove``."""
    client = _client()
    messages = _capture(client)
    _frame(client, "add", _payload(state="DISCONNECTED"))
    _mock_resync(client, [])

    await client.update_public()

    assert messages == []
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_add_replayed_after_resync_is_held_once() -> None:
    """An ``add`` buffered during a resync is held, not repeated by the fetch diff."""
    client = _client()
    messages = _capture(client)
    _mock_resync(client, [])
    release = asyncio.Event()

    async def _sensors() -> list[PublicSensor]:
        await release.wait()
        return []

    client.get_sensors_public = AsyncMock(  # type: ignore[method-assign]
        side_effect=_sensors
    )
    resync = asyncio.create_task(client.update_public())
    await asyncio.sleep(0)
    _frame(client, "add", _payload(state="DISCONNECTED"))
    release.set()
    await resync

    assert messages == []
    assert client._sensor_add_pending == {SENSOR_ID}


@pytest.mark.asyncio()
async def test_missed_add_fetch_clears_pending_sensor() -> None:
    """A fetch re-adding a held sensor dropped mid-fetch announces it only once."""
    client = _client()
    messages = _capture(client)
    release, _get = _blocking_get(client, _sensor(client, flags=SMOKE_FLAGS))
    _update(client, state="CONNECTED")
    await asyncio.sleep(0)
    _frame(client, "add", _payload(state="CONNECTED"))
    del client._public_bootstrap.sensors[SENSOR_ID]

    release.set()
    await _drain(client)

    assert len(_adds(messages)) == 1
    assert client._sensor_add_pending == set()


@pytest.mark.asyncio()
async def test_resync_seeing_pending_sensor_offline_cancels_fetch() -> None:
    """A snapshot moving a held sensor off CONNECTED ends the fetch and its state."""
    client = _client()
    messages = _capture(client)
    _release, _get = _blocking_get(client, _sensor(client))
    _frame(client, "add", _payload(state="CONNECTED"))
    task, _state = client._sensor_fetch_tasks[SENSOR_ID]
    await asyncio.sleep(0)
    _mock_resync(client, [_sensor(client, state="DISCONNECTED")])

    await client.update_public()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert client._sensor_fetch_tasks == {}
    assert _adds(messages) == []
    assert client._sensor_add_pending == {SENSOR_ID}


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
async def test_teardown_cancels_fetches(
    teardown: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teardown cancels a fetch sleeping between retries; it opens no session."""
    monkeypatch.setattr("uiprotect.api.SENSOR_FETCH_RETRY_DELAYS", (3600.0,))
    client = _client()
    client.get_sensor_public = AsyncMock(  # type: ignore[method-assign]
        return_value=_sensor(client, state="CONNECTING")
    )
    _update(client, state="CONNECTED")
    task, _state = client._sensor_fetch_tasks[SENSOR_ID]
    client._sensor_fetch_failed["other"] = None
    await asyncio.sleep(0)
    assert client.get_sensor_public.await_count == 1

    await getattr(client, teardown)()
    await asyncio.sleep(0)

    assert task.cancelled()
    assert client.get_sensor_public.await_count == 1
    assert client._sensor_fetch_tasks == {}
    assert client._sensor_fetch_failed == {}
    assert client._public_api_session is None
