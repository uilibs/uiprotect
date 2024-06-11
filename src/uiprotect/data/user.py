"""UniFi Protect User models."""

from __future__ import annotations

from datetime import datetime
from functools import cache
from typing import Any

try:
    from pydantic.v1.fields import PrivateAttr
except ImportError:
    from pydantic.fields import PrivateAttr

from .base import ProtectBaseObject, ProtectModel, ProtectModelWithId
from .types import ModelType, PermissionNode


class Permission(ProtectBaseObject):
    raw_permission: str
    model: ModelType
    nodes: set[PermissionNode]
    obj_ids: set[str] | None

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        permission = data.get("rawPermission", "")
        parts = permission.split(":")
        if len(parts) < 2:
            raise ValueError(f"Invalid permission: {permission}")

        data["model"] = ModelType(parts[0])
        if parts[1] == "*":
            data["nodes"] = list(PermissionNode)
        else:
            data["nodes"] = [PermissionNode(n) for n in parts[1].split(",")]

        if len(parts) == 3 and parts[2] != "*":
            if parts[2] == "$":
                data["obj_ids"] = ["self"]
            else:
                data["obj_ids"] = parts[2].split(",")

        return super().unifi_dict_to_dict(data)

    def unifi_dict(  # type: ignore[override]
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> str:
        return self.raw_permission

    @property
    def objs(self) -> list[ProtectModelWithId] | None:
        if self.obj_ids == {"self"} or self.obj_ids is None:
            return None

        devices = getattr(self._api.bootstrap, f"{self.model.value}s")
        return [devices[oid] for oid in self.obj_ids]


class Group(ProtectModelWithId):
    name: str
    permissions: list[Permission]
    type: str
    is_default: bool

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "permissions" in data:
            permissions = data.pop("permissions")
            data["permissions"] = [{"rawPermission": p} for p in permissions]

        return super().unifi_dict_to_dict(data)


class UserLocation(ProtectModel):
    is_away: bool
    latitude: float | None
    longitude: float | None


class CloudAccount(ProtectModelWithId):
    first_name: str
    last_name: str
    email: str
    user_id: str
    name: str
    location: UserLocation | None
    profile_img: str | None = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "user": "userId"}

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        # id and cloud ID are always the same
        if "id" in data:
            data["cloudId"] = data["id"]
        if "location" in data and data["location"] is None:
            del data["location"]

        return data

    @property
    def user(self) -> User:
        return self._api.bootstrap.users[self.user_id]


class UserFeatureFlags(ProtectBaseObject):
    notifications_v2: bool


class User(ProtectModelWithId):
    permissions: list[Permission]
    last_login_ip: str | None
    last_login_time: datetime | None
    is_owner: bool
    enable_notifications: bool
    has_accepted_invite: bool
    all_permissions: list[Permission]
    scopes: list[str] | None = None
    location: UserLocation | None
    name: str
    first_name: str
    last_name: str
    email: str | None
    local_username: str
    group_ids: list[str]
    cloud_account: CloudAccount | None
    feature_flags: UserFeatureFlags

    # TODO:
    # settings
    # alertRules
    # notificationsV2
    # notifications
    # cloudProviders

    _groups: list[Group] | None = PrivateAttr(None)
    _perm_cache: dict[str, bool] = PrivateAttr({})

    def __init__(self, **data: Any) -> None:
        if "permissions" in data:
            permissions = data.pop("permissions")
            data["permissions"] = [
                {"raw_permission": p} if isinstance(p, str) else p for p in permissions
            ]
        if "allPermissions" in data:
            permissions = data.pop("allPermissions")
            data["allPermissions"] = [
                {"raw_permission": p} if isinstance(p, str) else p for p in permissions
            ]

        super().__init__(**data)

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "permissions" in data:
            permissions = data.pop("permissions")
            data["permissions"] = [{"rawPermission": p} for p in permissions]
        if "allPermissions" in data:
            permissions = data.pop("allPermissions")
            data["allPermissions"] = [{"rawPermission": p} for p in permissions]

        return super().unifi_dict_to_dict(data)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "groups": "groupIds"}

    def unifi_dict(
        self,
        data: dict[str, Any] | None = None,
        exclude: set[str] | None = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "location" in data and data["location"] is None:
            del data["location"]

        return data

    @property
    def groups(self) -> list[Group]:
        """
        Groups the user is in

        Will always be empty if the user only has read only access.
        """
        if self._groups is not None:
            return self._groups

        self._groups = [
            self._api.bootstrap.groups[g]
            for g in self.group_ids
            if g in self._api.bootstrap.groups
        ]
        return self._groups

    def can(
        self,
        model: ModelType,
        node: PermissionNode,
        obj: ProtectModelWithId | None = None,
    ) -> bool:
        """Checks if a user can do a specific action"""
        check_self = False
        if model == self.model and obj is not None and obj.id == self.id:
            perm_str = f"{model.value}:{node.value}:$"
            check_self = True
        else:
            perm_str = (
                f"{model.value}:{node.value}:{obj.id if obj is not None else '*'}"
            )
        if perm_str in self._perm_cache:
            return self._perm_cache[perm_str]

        for perm in self.all_permissions:
            if model != perm.model or node not in perm.nodes:
                continue
            if perm.obj_ids is None:
                self._perm_cache[perm_str] = True
                return True
            if check_self and perm.obj_ids == {"self"}:
                self._perm_cache[perm_str] = True
                return True
            if perm.obj_ids is not None and obj is not None and obj.id in perm.obj_ids:
                self._perm_cache[perm_str] = True
                return True
        self._perm_cache[perm_str] = False
        return False
