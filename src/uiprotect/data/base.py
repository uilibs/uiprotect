"""UniFi Protect Data."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import cache
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Any, NamedTuple
from uuid import UUID

from convertertools import pop_dict_set_if_none, pop_dict_tuple
from pydantic import BaseModel, ConfigDict
from pydantic.fields import PrivateAttr

from .._compat import cached_property
from ..exceptions import BadRequest, ClientError, NotAuthorized
from ..utils import (
    asyncio_timeout,
    convert_to_datetime,
    convert_unifi_data,
    dict_diff,
    is_debug,
    serialize_unifi_obj,
    to_snake_case,
)
from .types import (
    SHAPE_DICT_V1,
    SHAPE_LIST_V1,
    ModelType,
    PercentFloat,
    PermissionNode,
    ProtectWSPayloadFormat,
    StateType,
    extract_type_shape,
)
from .websocket import (
    WSJSONPacketFrame,
    WSPacket,
    WSPacketFrameHeader,
)

if TYPE_CHECKING:
    from asyncio.events import TimerHandle

    from typing_extensions import Self  # requires Python 3.11+

    from ..api import ProtectApiClient
    from ..data.devices import Bridge
    from ..data.nvr import Event
    from ..data.user import User


RECENT_EVENT_MAX = timedelta(seconds=30)
EVENT_PING_INTERVAL = timedelta(seconds=3)
EVENT_PING_INTERVAL_SECONDS = EVENT_PING_INTERVAL.total_seconds()

_EMPTY_EVENT_PING_BACK: dict[Any, Any] = {}


_LOGGER = logging.getLogger(__name__)


@cache
def _is_protect_base_object(cls: type[Any]) -> bool:
    """A cached version of `issubclass(cls, ProtectBaseObject)` to speed up the check."""
    return issubclass(cls, ProtectBaseObject)


class _ProtectModelObjects(NamedTuple):
    """
    Class to track all child of UFP objects.

    objs are UFP objects
    lists are lists of UFP objects
    dicts are dicts of UFP objects
    """

    objs: dict[str, type[ProtectBaseObject]]
    has_objs: bool
    lists: dict[str, type[ProtectBaseObject]]
    has_lists: bool
    dicts: dict[str, type[ProtectBaseObject]]
    has_dicts: bool


class ProtectBaseObject(BaseModel):
    """
    Base class for building Python objects from UniFi Protect JSON.

    * Provides `.unifi_dict_to_dict` to convert UFP JSON to a more Pythonic formatted dict (camel case to snake case)
    * Add attrs with matching Pyhonic name and they will automatically be populated from the UFP JSON if passed in to the constructer
    * Provides `.unifi_dict` to convert object back into UFP JSON
    """

    _api: ProtectApiClient = PrivateAttr(None)  # type: ignore[assignment]
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    def __init__(self, api: ProtectApiClient | None = None, **data: Any) -> None:
        """
        Base class for creating Python objects from UFP JSON data.

        Use the static method `.from_unifi_dict()` to create objects from UFP JSON data from then the main class constructor.
        """
        super().__init__(**data)
        if api is not None:
            self._api = api

    @classmethod
    def from_unifi_dict(
        cls,
        api: ProtectApiClient | None = None,
        **data: Any,
    ) -> Self:
        """
        Main constructor for `ProtectBaseObject`

        Args:
        ----
            api: Optional reference to the ProtectAPIClient that created generated the UFP JSON
            **data: decoded UFP JSON

        `api` is is expected as a `@property`. If it is `None` and accessed, a `BadRequest` will be raised.

        API can be used for saving updates for the Protect object or fetching references to other objects
        (cameras, users, etc.)

        """
        if api is not None:
            data["api"] = api
        data = cls.unifi_dict_to_dict(data)

        if is_debug():
            data.pop("api", None)
            return cls(api=api, **data)

        return cls.model_construct(**data)

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: Any
    ) -> Self:
        api: ProtectApiClient | None = values.pop("api", None)
        (
            unifi_objs,
            has_unifi_objs,
            unifi_lists,
            has_unifi_lists,
            unifi_dicts,
            has_unifi_dicts,
        ) = cls._get_protect_model()
        for key, value in values.items():
            if has_unifi_objs and key in unifi_objs and isinstance(value, dict):
                values[key] = unifi_objs[key].model_construct(**value)
            elif has_unifi_lists and key in unifi_lists and isinstance(value, list):
                values[key] = [
                    unifi_lists[key].model_construct(**v) if isinstance(v, dict) else v
                    for v in value
                ]
            elif has_unifi_dicts and key in unifi_dicts and isinstance(value, dict):
                values[key] = {
                    k: unifi_dicts[key].model_construct(**v)
                    if isinstance(v, dict)
                    else v
                    for k, v in value.items()
                }

        obj = super().model_construct(_fields_set=_fields_set, **values)
        if api is not None:
            obj._api = api

        return obj

    @classmethod
    @cache
    def _get_excluded_changed_fields(cls) -> set[str]:
        """
        Helper method for override in child classes for fields that excluded from calculating "changed" state for a
        model (`.get_changed()`)
        """
        return set()

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        """
        Helper method for overriding in child classes for remapping UFP JSON keys to Python ones that do not fit the
        simple camel case to snake case formula.

        Return format is
        {
            "ufpJsonName": "python_name"
        }
        """
        return {}

    @classmethod
    @cache
    def _get_to_unifi_remaps(cls) -> dict[str, str]:
        """
        Helper method for overriding in child classes for reversing remap UFP
        JSON keys to Python ones that do not fit the simple camel case to
        snake case formula.

        Return format is
        {
            "python_name": "ufpJsonName"
        }
        """
        return {
            to_key: from_key for from_key, to_key in cls._get_unifi_remaps().items()
        }

    @classmethod
    @cache
    def _get_protect_model(cls) -> _ProtectModelObjects:
        """Helper method to detect attrs of current class that are UFP Objects themselves"""
        objs: dict[str, type[ProtectBaseObject]] = {}
        lists: dict[str, type[ProtectBaseObject]] = {}
        dicts: dict[str, type[ProtectBaseObject]] = {}

        for name, field in cls.model_fields.items():
            try:
                type_, shape = extract_type_shape(field.annotation)  # type: ignore[arg-type]
                if _is_protect_base_object(type_):
                    if shape == SHAPE_LIST_V1:
                        lists[name] = type_
                    elif shape == SHAPE_DICT_V1:
                        dicts[name] = type_
                    else:
                        objs[name] = type_
            except TypeError:
                pass

        return _ProtectModelObjects(
            objs, bool(objs), lists, bool(lists), dicts, bool(dicts)
        )

    @classmethod
    @cache
    def _get_excluded_fields(cls) -> set[str]:
        """Helper method to get all excluded fields for the current object."""
        protect_model = cls._get_protect_model()
        return set(protect_model.objs) | set(protect_model.lists)

    @classmethod
    def _clean_protect_obj(
        cls,
        data: Any,
        klass: type[ProtectBaseObject],
        api: ProtectApiClient | None,
    ) -> Any:
        if isinstance(data, dict):
            if api is not None:
                data["api"] = api
            return klass.unifi_dict_to_dict(data=data)
        return data

    @classmethod
    def _clean_protect_obj_list(
        cls,
        items: list[Any],
        klass: type[ProtectBaseObject],
        api: ProtectApiClient | None,
    ) -> list[Any]:
        return [cls._clean_protect_obj(item, klass, api) for item in items]

    @classmethod
    def _clean_protect_obj_dict(
        cls,
        items: dict[Any, Any],
        klass: type[ProtectBaseObject],
        api: ProtectApiClient | None,
    ) -> dict[Any, Any]:
        return {k: cls._clean_protect_obj(v, klass, api) for k, v in items.items()}

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        """
        Helper method for overriding in child classes for converting UFP JSON data to Python data types.

        Return format is
        {
            "ufpJsonName": Callable[[Any], Any]
        }
        """
        return {}

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Takes a decoded UFP JSON dict and converts it into a Python dict

        * Remaps items from `._get_unifi_remaps()`
        * Converts camelCase keys to snake_case keys
        * Injects ProtectAPIClient into any child UFP object Dicts
        * Runs `.unifi_dict_to_dict` for any child UFP objects

        Args:
        ----
            data: decoded UFP JSON dict

        """
        # get the API client instance
        api: ProtectApiClient | None = data.get("api") or (
            cls._api if isinstance(cls, ProtectBaseObject) else None
        )

        conversions = cls.unifi_dict_conversions()
        for key, convert in conversions.items():
            if (val := data.get(key)) is not None:
                data[key] = convert(val)  # type: ignore[operator]

        remaps = cls._get_unifi_remaps()
        # convert to snake_case and remove extra fields
        _fields = cls.model_fields
        for key in data.copy():
            if key in remaps:
                # remap keys that will not be converted correctly by snake_case convert
                remapped_key = remaps[key]
                data[remapped_key] = data.pop(key)
                key = remapped_key

            new_key = to_snake_case(key)
            data[new_key] = data.pop(key)
            key = new_key

            if key == "api":
                continue

            if key not in _fields:
                del data[key]
                continue
            data[key] = convert_unifi_data(data[key], _fields[key])

        if not data:
            return data

        # clean child UFP objs
        (
            unifi_objs,
            has_unifi_objs,
            unifi_lists,
            has_unifi_lists,
            unifi_dicts,
            has_unifi_dicts,
        ) = cls._get_protect_model()
        for key, value in data.items():
            if has_unifi_objs and key in unifi_objs:
                data[key] = cls._clean_protect_obj(value, unifi_objs[key], api)
            elif has_unifi_lists and key in unifi_lists and isinstance(value, list):
                data[key] = cls._clean_protect_obj_list(value, unifi_lists[key], api)
            elif has_unifi_dicts and key in unifi_dicts and isinstance(value, dict):
                data[key] = cls._clean_protect_obj_dict(value, unifi_dicts[key], api)

        return data

    def _unifi_dict_protect_obj(
        self,
        data: dict[str, Any],
        key: str,
        use_obj: bool,
        klass: type[ProtectBaseObject],
    ) -> Any:
        value: Any | None = data.get(key)
        if use_obj:
            value = getattr(self, key)

        if isinstance(value, ProtectBaseObject):
            value = value.unifi_dict()
        elif isinstance(value, dict):
            value = klass.model_construct({}).unifi_dict(data=value)  # type: ignore[arg-type]

        return value

    def _unifi_dict_protect_obj_list(
        self,
        data: dict[str, Any],
        key: str,
        use_obj: bool,
        klass: type[ProtectBaseObject],
    ) -> Any:
        value: Any | None = data.get(key)
        if use_obj:
            value = getattr(self, key)

        if not isinstance(value, list):
            return value

        return [
            item.unifi_dict()
            if isinstance(item, ProtectBaseObject)
            else klass.model_construct({}).unifi_dict(data=item)  # type: ignore[arg-type]
            for item in value
        ]

    def _unifi_dict_protect_obj_dict(
        self,
        data: dict[str, Any],
        key: str,
        use_obj: bool,
    ) -> Any:
        value: Any | None = data.get(key)
        if use_obj:
            value = getattr(self, key)

        if not isinstance(value, dict):
            return value

        return {
            obj_key: obj.unifi_dict() if isinstance(obj, ProtectBaseObject) else obj
            for obj_key, obj in value.items()
        }

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        """
        Can either convert current Python object into UFP JSON dict or take the output of a `.dict()` call and convert it.

        * Remaps items from `._get_unifi_remaps()` in reverse
        * Converts snake_case to camelCase
        * Automatically removes any ProtectApiClient instances that might still be in the data
        * Automatically calls `.unifi_dict()` for any UFP Python objects that are detected

        Args:
        ----
            data: Optional output of `.dict()` for the Python object. If `None`, will call `.dict` first
            exclude: Optional set of fields to exclude from convert. Useful for subclassing and having custom
                processing for dumping to UFP JSON data.

        """
        use_obj = False
        if data is None:
            excluded_fields = self._get_excluded_fields()
            if exclude is not None:
                excluded_fields = excluded_fields.copy() | exclude
            data = self.model_dump(exclude=excluded_fields)
            use_obj = True

        (
            unifi_objs,
            has_unifi_objs,
            unifi_lists,
            has_unifi_lists,
            unifi_dicts,
            has_unifi_dicts,
        ) = self._get_protect_model()

        if has_unifi_objs:
            for key, klass in unifi_objs.items():
                if use_obj or key in data:
                    data[key] = self._unifi_dict_protect_obj(data, key, use_obj, klass)

        if has_unifi_lists:
            for key, klass in unifi_lists.items():
                if use_obj or key in data:
                    data[key] = self._unifi_dict_protect_obj_list(
                        data, key, use_obj, klass
                    )

        if has_unifi_dicts:
            for key in unifi_dicts:
                if use_obj or key in data:
                    data[key] = self._unifi_dict_protect_obj_dict(data, key, use_obj)

        # all child objects have been serialized correctly do not do it twice
        new_data: dict[str, Any] = serialize_unifi_obj(data, levels=2)
        remaps = self._get_to_unifi_remaps()
        for to_key in set(new_data).intersection(remaps):
            new_data[remaps[to_key]] = new_data.pop(to_key)

        return new_data

    def update_from_dict(self, data: dict[str, Any]) -> Self:
        """
        Updates current object from a cleaned UFP JSON dict.

        The api client is injected into each dict for any child
        UFP objects that are detected.
        """
        (
            unifi_objs,
            has_unifi_objs,
            unifi_lists,
            has_unifi_lists,
            unifi_dicts,
            has_unifi_dicts,
        ) = self._get_protect_model()
        api = self._api
        _fields = self.__class__.model_fields
        unifi_obj: ProtectBaseObject | None
        value: Any

        for key, item in data.items():
            if has_unifi_objs and key in unifi_objs and isinstance(item, dict):
                if (unifi_obj := getattr(self, key)) is not None:
                    value = unifi_obj.update_from_dict(item)
                else:
                    value = unifi_objs[key](**item, api=api)
            elif has_unifi_lists and key in unifi_lists and isinstance(item, list):
                klass = unifi_lists[key]
                value = [
                    klass(**i, api=api) if isinstance(i, dict) else i
                    for i in item
                    if i is not None and isinstance(i, (dict, ProtectBaseObject))
                ]
            else:
                value = convert_unifi_data(item, _fields[key])

            setattr(self, key, value)

        return self

    def dict_with_excludes(self) -> dict[str, Any]:
        """Returns a dict of the current object without any UFP objects converted to dicts."""
        excludes = self.__class__._get_excluded_changed_fields()
        return self.model_dump(exclude=excludes)

    def get_changed(self, data_before_changes: dict[str, Any]) -> dict[str, Any]:
        return dict_diff(data_before_changes, self.model_dump())

    @property
    def api(self) -> ProtectApiClient:
        """
        ProtectApiClient that the UFP object was created with. If no API Client was passed in time of
        creation, will raise `BadRequest`
        """
        if self._api is None:
            raise BadRequest("API Client not initialized")

        return self._api


class ProtectModel(ProtectBaseObject):
    """
    Base class for UFP objects with a `modelKey` attr. Provides `.from_unifi_dict()` static helper method for
    automatically decoding a `modelKey` object into the correct UFP object and type
    """

    model: ModelType | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "modelKey": "model"}

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(data, {"modelKey"})
        return data


class UpdateSynchronization:
    """Helper class for managing updates to Protect devices."""

    @cached_property
    def lock(self) -> asyncio.Lock:
        """Lock to prevent multiple updates at once."""
        return asyncio.Lock()

    @cached_property
    def queue(self) -> asyncio.Queue[Callable[[], None]]:
        """Queue to store device updates."""
        return asyncio.Queue()

    @cached_property
    def event(self) -> asyncio.Event:
        """Event to signal when a device update has been queued."""
        return asyncio.Event()


class ProtectModelWithId(ProtectModel):
    id: str

    _update_sync: UpdateSynchronization = PrivateAttr(None)  # type: ignore[assignment]

    def __init__(self, **data: Any) -> None:
        update_sync = data.pop("update_sync", None)
        super().__init__(**data)
        self._update_sync = update_sync or UpdateSynchronization()

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: Any
    ) -> Self:
        update_sync = values.pop("update_sync", None)
        obj = super().model_construct(_fields_set=_fields_set, **values)
        obj._update_sync = update_sync or UpdateSynchronization()
        return obj

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return set()

    async def _api_update(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def revert_changes(self, data_before_changes: dict[str, Any]) -> None:
        """Reverts current changes to device and resets it back to initial state"""
        changed = self.get_changed(data_before_changes)
        for key in changed:
            setattr(self, key, data_before_changes[key])

    def can_create(self, user: User) -> bool:
        if (model := self.model) is not None:
            return user.can(model, PermissionNode.CREATE, self)
        return True

    def can_read(self, user: User) -> bool:
        if (model := self.model) is not None:
            return user.can(model, PermissionNode.READ, self)
        return True

    def can_write(self, user: User) -> bool:
        if (model := self.model) is not None:
            return user.can(model, PermissionNode.WRITE, self)
        return True

    def can_delete(self, user: User) -> bool:
        if (model := self.model) is not None:
            return user.can(model, PermissionNode.DELETE, self)
        return True

    async def queue_update(self, callback: Callable[[], None]) -> None:
        """
        Queues a device update.

        This allows aggregating devices updates so if multiple ones come in all at once,
        they can be combined in a single PATCH.
        """
        self._update_sync.queue.put_nowait(callback)

        self._update_sync.event.set()
        # release execution so other `queue_update` calls can abort
        await asyncio.sleep(0.001)
        self._update_sync.event.clear()

        try:
            async with asyncio_timeout(0.05):
                await self._update_sync.event.wait()
            self._update_sync.event.clear()
            return
        except (TimeoutError, asyncio.TimeoutError):
            async with self._update_sync.lock:
                # Important! Now that we have the lock, we yield to the event loop so any
                # updates from the websocket are processed before we generate the diff
                await asyncio.sleep(0)
                # Save the initial data before we generate the diff
                data_before_changes = self.dict_with_excludes()
                while not self._update_sync.queue.empty():
                    callback = self._update_sync.queue.get_nowait()
                    callback()
                # Important, do not yield to the event loop before generating the diff
                # otherwise we may miss updates from the websocket
                await self._save_device_changes(
                    data_before_changes,
                    self.unifi_dict(data=self.get_changed(data_before_changes)),
                )

    async def save_device(
        self,
        data_before_changes: dict[str, Any],
        force_emit: bool = False,
        revert_on_fail: bool = True,
    ) -> None:
        """
        Generates a diff for unsaved changed on the device and sends them back to UFP

        USE WITH CAUTION, updates _all_ fields for the current object that have been changed.
        May have unexpected side effects.

        Tested updates have been added a methods on applicable devices.

        Args:
        ----
            force_emit: Emit a fake UFP WS message. Should only be use for when UFP does not properly emit a WS message

        """
        # do not allow multiple save_device calls at once
        release_lock = False
        if not self._update_sync.lock.locked():
            await self._update_sync.lock.acquire()
            release_lock = True

        try:
            await self._save_device_changes(
                data_before_changes,
                self.unifi_dict(data=self.get_changed(data_before_changes)),
                force_emit=force_emit,
                revert_on_fail=revert_on_fail,
            )
        finally:
            if release_lock:
                self._update_sync.lock.release()

    async def _save_device_changes(
        self,
        data_before_changes: dict[str, Any],
        updated: dict[str, Any],
        force_emit: bool = False,
        revert_on_fail: bool = True,
    ) -> None:
        """Saves the current device changes to UFP."""
        _LOGGER.debug(
            "Saving device changes for %s (%s) data_before_changes=%s updated=%s",
            self.id,
            self.model,
            data_before_changes,
            updated,
        )

        assert self._update_sync.lock.locked(), (
            "save_device_changes should only be called when the update lock is held"
        )
        read_only_fields = self.__class__._get_read_only_fields()

        if self.model is None:
            raise BadRequest("Unknown model type")

        if not self._api.bootstrap.auth_user.can(
            self.model, PermissionNode.WRITE, self
        ):
            if revert_on_fail:
                self.revert_changes(data_before_changes)
            raise NotAuthorized(f"Do not have write permission for obj: {self.id}")

        # do not patch when there are no updates
        if updated == {}:
            return

        read_only_keys = read_only_fields.intersection(updated)
        if len(read_only_keys) > 0:
            self.revert_changes(data_before_changes)
            raise BadRequest(
                f"{type(self)} The following key(s) are read only: {read_only_keys}, updated: {updated}",
            )

        try:
            await self._api_update(updated)
        except ClientError:
            if revert_on_fail:
                self.revert_changes(data_before_changes)
            raise

        if force_emit:
            self._emit_message(updated)

    async def emit_message(self, updated: dict[str, Any]) -> None:
        """Emits fake WS message for ProtectApiClient to process."""
        self._emit_message(updated)

    def _emit_message(self, updated: dict[str, Any]) -> None:
        """Emits fake WS message for ProtectApiClient to process."""
        if _is_ping_back := updated is _EMPTY_EVENT_PING_BACK:
            _LOGGER.debug("Event ping callback started for %s", self.id)

        if self.model is None:
            raise BadRequest("Unknown model type")

        header = WSPacketFrameHeader(
            packet_type=1,
            payload_format=ProtectWSPayloadFormat.JSON.value,
            deflated=0,
            unknown=1,
            payload_size=1,
        )

        action_frame = WSJSONPacketFrame()
        action_frame.header = header
        action_frame.data = {
            "action": "update",
            "newUpdateId": None,
            "modelKey": self.model.value,
            "id": self.id,
        }

        data_frame = WSJSONPacketFrame()
        data_frame.header = header
        data_frame.data = updated

        message = self._api.bootstrap.process_ws_packet(
            WSPacket(action_frame.packed + data_frame.packed),
            is_ping_back=_is_ping_back,
        )

        if message is not None:
            self._api.emit_message(message)


class ProtectDeviceModel(ProtectModelWithId):
    name: str | None = None
    type: str
    mac: str
    host: IPv4Address | str | None = None
    up_since: datetime | None = None
    uptime: timedelta | None = None
    last_seen: datetime | None = None
    hardware_revision: str | None = None
    firmware_version: str | None = None
    is_updating: bool
    is_ssh_enabled: bool

    _callback_ping: TimerHandle | None = PrivateAttr(None)

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "mac",
            "host",
            "type",
            "upSince",
            "uptime",
            "lastSeen",
            "hardwareRevision",
            "isUpdating",
        }

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "upSince": convert_to_datetime,
            "uptime": lambda x: timedelta(milliseconds=int(x)),
            "lastSeen": convert_to_datetime,
            # hardware revisions for all devices are not simple numbers
            # so cast them all to str to be consistent
            "hardwareRevision": str,
        } | super().unifi_dict_conversions()

    def _event_callback_ping(self) -> None:
        _LOGGER.debug("Event ping timer started for %s", self.id)
        loop = asyncio.get_event_loop()
        self._callback_ping = loop.call_later(
            EVENT_PING_INTERVAL_SECONDS,
            self._emit_message,
            _EMPTY_EVENT_PING_BACK,
        )

    async def set_name(self, name: str | None) -> None:
        """Sets name for the device"""

        def callback() -> None:
            self.name = name

        await self.queue_update(callback)


class WiredConnectionState(ProtectBaseObject):
    phy_rate: float | None = None


class WirelessConnectionState(ProtectBaseObject):
    signal_quality: int | None = None
    signal_strength: int | None = None


class BluetoothConnectionState(WirelessConnectionState):
    experience_score: PercentFloat | None = None


class WifiConnectionState(WirelessConnectionState):
    phy_rate: float | None = None
    channel: int | None = None
    frequency: int | None = None
    ssid: str | None = None
    bssid: str | None = None
    tx_rate: float | None = None
    # requires 2.7.5+
    ap_name: str | None = None
    experience: str | None = None
    # requires 2.7.15+
    connectivity: str | None = None


class ProtectAdoptableDeviceModel(ProtectDeviceModel):
    state: StateType
    connection_host: IPv4Address | str | None = None
    connected_since: datetime | None = None
    latest_firmware_version: str | None = None
    firmware_build: str | None = None
    is_adopting: bool
    is_adopted: bool
    is_adopted_by_other: bool
    is_provisioned: bool
    is_rebooting: bool
    can_adopt: bool
    is_attempting_to_connect: bool
    is_connected: bool
    # requires 1.21+
    market_name: str | None = None
    # requires 2.7.5+
    fw_update_state: str | None = None
    # requires 2.8.14+
    nvr_mac: str | None = None
    # requires 2.8.22+
    guid: UUID | None = None
    # requires 2.9.20+
    is_restoring: bool | None = None
    last_disconnect: datetime | None = None
    anonymous_device_id: UUID | None = None

    wired_connection_state: WiredConnectionState | None = None
    wifi_connection_state: WifiConnectionState | None = None
    bluetooth_connection_state: BluetoothConnectionState | None = None
    bridge_id: str | None = None
    is_downloading_firmware: bool | None = None

    # TODO:
    # bridgeCandidates

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "connectionHost",
            "connectedSince",
            "state",
            "latestFirmwareVersion",
            "firmwareBuild",
            "isAdopting",
            "isProvisioned",
            "isRebooting",
            "canAdopt",
            "isAttemptingToConnect",
            "bluetoothConnectionState",
            "isDownloadingFirmware",
            "anonymousDeviceId",
        }

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "bridge": "bridgeId",
            "isDownloadingFW": "isDownloadingFirmware",
        }

    async def _api_update(self, data: dict[str, Any]) -> None:
        if (model := self.model) is not None:
            return await self._api.update_device(model, self.id, data)
        return None

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_set_if_none(
            data,
            {"wiredConnectionState", "wifiConnectionState", "bluetoothConnectionState"},
        )
        return data

    @classmethod
    @cache
    def unifi_dict_conversions(cls) -> dict[str, object | Callable[[Any], Any]]:
        return {
            "lastDisconnect": convert_to_datetime,
        } | super().unifi_dict_conversions()

    @property
    def display_name(self) -> str:
        return self.name or self.market_name or self.type

    @property
    def is_wired(self) -> bool:
        return self.wired_connection_state is not None

    @property
    def is_wifi(self) -> bool:
        return self.wifi_connection_state is not None

    @property
    def is_bluetooth(self) -> bool:
        return self.bluetooth_connection_state is not None

    @property
    def bridge(self) -> Bridge | None:
        if (bridge_id := self.bridge_id) is not None:
            return self._api.bootstrap.bridges[bridge_id]
        return None

    @property
    def protect_url(self) -> str:
        """UFP Web app URL for this device"""
        return f"{self._api.base_url}/protect/devices/{self.id}"

    @property
    def is_adopted_by_us(self) -> bool:
        """Verifies device is adopted and controlled by this NVR."""
        return self.is_adopted and not self.is_adopted_by_other

    def get_changed(self, data_before_changes: dict[str, Any]) -> dict[str, Any]:
        """Gets dictionary of all changed fields"""
        return dict_diff(data_before_changes, self.dict_with_excludes())

    async def set_ssh(self, enabled: bool) -> None:
        """Sets ssh status for protect device"""

        def callback() -> None:
            self.is_ssh_enabled = enabled

        await self.queue_update(callback)

    async def reboot(self) -> None:
        """Reboots an adopted device"""
        if self.model is not None:
            if not self._api.bootstrap.auth_user.can(
                self.model,
                PermissionNode.WRITE,
                self,
            ):
                raise NotAuthorized("Do not have permission to reboot device")
            await self._api.reboot_device(self.model, self.id)

    async def unadopt(self) -> None:
        """Unadopt/Unmanage adopted device"""
        if not self.is_adopted_by_us:
            raise BadRequest("Device is not adopted")

        if self.model is not None:
            if not self._api.bootstrap.auth_user.can(
                self.model,
                PermissionNode.DELETE,
                self,
            ):
                raise NotAuthorized("Do not have permission to unadopt devices")
            await self._api.unadopt_device(self.model, self.id)

    async def adopt(self, name: str | None = None) -> None:
        """Adopts a device"""
        if not self.can_adopt:
            raise BadRequest("Device cannot be adopted")

        if self.model is not None:
            if not self._api.bootstrap.auth_user.can(self.model, PermissionNode.CREATE):
                raise NotAuthorized("Do not have permission to adopt devices")

            await self._api.adopt_device(self.model, self.id)
            if name is not None:
                await self.set_name(name)


class ProtectMotionDeviceModel(ProtectAdoptableDeviceModel):
    last_motion: datetime | None = None
    is_dark: bool

    # not directly from UniFi
    last_motion_event_id: str | None = None

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {"lastMotion", "isDark"}

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)
        pop_dict_tuple(data, ("lastMotionEventId",))
        return data

    @property
    def last_motion_event(self) -> Event | None:
        if (last_motion_event_id := self.last_motion_event_id) is not None:
            return self._api.bootstrap.events.get(last_motion_event_id)
        return None
