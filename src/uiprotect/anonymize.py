from __future__ import annotations

import secrets
import string
import uuid
import warnings
from typing import Any
from urllib.parse import urlparse

from .data.types import ModelType

object_id_mapping: dict[str, str] = {}

_OBJECT_ID_KEYS = frozenset(
    {
        "owner",
        "user",
        "camera",
        "liveview",
        "authUserId",
        "event",
        "cameraId",
        "liveviewId",
        "armProfileId",
        "nightProfileId",
        "actionOutputId",
        "breachEventId",
        "breachTriggerEventId",
        "eventId",
    }
)
_OBJECT_ID_LIST_KEYS = frozenset(
    {"smartDetectEvents", "camera", "cameras", "cameraIds", "armProfileIds"}
)


def anonymize_data(value: Any, name: str | None = None) -> Any:
    if isinstance(value, list):
        value = anonymize_list(value, name=name)
    elif isinstance(value, dict):
        value = anonymize_dict(value, name=name)
    else:
        value = anonymize_value(value, name=name)

    return value


def anonymize_user(user_dict: dict[str, Any]) -> dict[str, Any]:
    for index, group_id in enumerate(user_dict.get("groups", [])):
        user_dict["groups"][index] = anonymize_object_id(group_id)

    user_dict["id"] = anonymize_object_id(user_dict["id"])

    identity = _random_identity()
    for key, value in identity.items():
        if key in user_dict:
            user_dict[key] = value

    if (cloud_account := user_dict.get("cloudAccount")) is not None:
        _anonymize_cloud_account(cloud_account, identity)

    camera_order = (user_dict.get("settings") or {}).get("cameraOrder")
    if camera_order is not None:
        for index, camera_id in enumerate(camera_order):
            camera_order[index] = anonymize_object_id(camera_id)
        user_dict["settings"]["cameraOrder"] = camera_order

    if "allPermissions" in user_dict:
        user_dict["allPermissions"] = anonymize_list(
            user_dict["allPermissions"],
            "allPermissions",
        )
    if "permissions" in user_dict:
        user_dict["permissions"] = anonymize_list(
            user_dict["permissions"],
            "permissions",
        )

    return user_dict


def anonymize_value(value: Any, name: str | None = None) -> Any:  # noqa: PLR0912
    if isinstance(value, str):
        if name == "accessKey":
            value = f"{random_number(13)}:{random_hex(24)}:{random_hex(128)}"
        elif name == "credentials":
            value = f"{random_hex(64)}"
        elif name == "privateToken":
            value = f"{random_alphanum(192)}"
        elif name in {"host", "connectionHost", "bindAddr"}:
            value = anonymize_ip(value)
        elif name in {"anonymousDeviceId", "hardwareId"}:
            value = random_identifier()
        elif name in {"rtspAlias", "ssid"}:
            value = random_alphanum(16)
        elif name in {"mac", "server_id"}:
            value = anonymize_peristent_string(value, random_hex(12).upper())
        elif name == "bssid":
            value = anonymize_peristent_string(value, random_seperated_mac())
        elif name in {"latitude", "longitude"}:
            value = "0.0"
        elif name == "name" and value != "Default":
            value = f"{random_word()} {random_word()}".title()
        elif name in _OBJECT_ID_KEYS:
            value = anonymize_object_id(value)
        elif name == "rtsp":
            value = anonymize_rstp_url(value)
        elif value.startswith("liveview:*:"):
            liveview_id = value.split(":")[-1]
            value = f"liveview:*:{anonymize_object_id(liveview_id)}"

    return value


def anonymize_dict(obj: dict[str, Any], name: str | None = None) -> dict[str, Any]:  # noqa: PLR0912
    obj_type = None
    if "modelKey" in obj:
        if obj["modelKey"] in [m.value for m in ModelType]:
            obj_type = ModelType(obj["modelKey"])
        else:
            warnings.warn(f"Unknown modelKey: {obj['modelKey']}", stacklevel=2)

    if obj_type == ModelType.USER:
        return anonymize_user(obj)

    if name == "rtspsStreams":
        for key, value in obj.items():
            if isinstance(value, str):
                obj[key] = anonymize_rstp_url(value)
            else:
                obj[key] = anonymize_data(value, name=key)
        return obj

    for key, value in obj.items():
        handled = False
        if obj_type is not None or "payload" in obj:
            if key == "id":
                obj[key] = anonymize_object_id(value)
                handled = True
            elif obj_type == ModelType.EVENT:
                if key in {"thumbnail", "heatmap"}:
                    obj[key] = anonymize_prefixed_event_id(value)
                    handled = True
                elif key == "metadata":
                    if "sensorId" in obj[key]:
                        obj[key]["sensorId"]["text"] = anonymize_object_id(
                            obj[key]["sensorId"]["text"],
                        )
                    if "sensorName" in obj[key]:
                        obj[key]["sensorName"]["text"] = (
                            f"{random_word()} {random_word()}".title()
                        )

        if not handled:
            obj[key] = anonymize_data(value, name=key)

    return obj


def anonymize_list(items: list[Any], name: str | None = None) -> list[Any]:
    for index, value in enumerate(items):
        handled = False

        if isinstance(value, str) and name in {
            "hosts",
            "rtspsStreams",
            "clients",
            "customMessages",
            *_OBJECT_ID_LIST_KEYS,
        }:
            handled = True
            if name == "hosts":
                items[index] = anonymize_ip(items[index])
            elif name == "rtspsStreams":
                items[index] = anonymize_rstp_url(value)
            elif name == "clients":
                items[index] = anonymize_peristent_string(value, random_hex(12).upper())
            elif name == "customMessages":
                items[index] = f"{random_word()} {random_word()}".title()
            else:
                items[index] = anonymize_object_id(value)

        if not handled:
            items[index] = anonymize_data(value)

    return items


def anonymize_prefixed_event_id(event_id: str) -> str:
    event_id = event_id[2:]

    return f"e-{anonymize_object_id(event_id)}"


def anonymize_ip(ip: Any) -> Any:
    if not isinstance(ip, str):
        return ip

    if ip in {"0.0.0.0", "127.0.0.1", "255.255.255.255"}:  # noqa: S104
        return ip

    return anonymize_peristent_string(ip, random_ip(ip))


def anonymize_uuid(uuid_str: str) -> str:
    return anonymize_peristent_string(uuid_str, random_identifier())


def anonymize_object_id(obj_id: str) -> str:
    return anonymize_peristent_string(obj_id, random_hex(24))


def anonymize_peristent_string(value: str, default: str) -> str:
    if value not in object_id_mapping:
        object_id_mapping[value] = default

    return object_id_mapping[value]


def anonymize_rstp_url(url: str) -> str:
    parts = urlparse(url)
    port = ""
    if parts.port is not None and parts.port != 554:
        port = f":{parts.port}"

    return f"{parts.scheme}://{anonymize_ip(url)}{port}/{random_alphanum(16)}"


def random_hex(length: int) -> str:
    return secrets.token_hex(length // 2)


def random_seperated_mac() -> str:
    return ":".join(random_hex(2) for _ in range(6))


def random_str(length: int, choices: str) -> str:
    return "".join(secrets.choice(choices) for _ in range(length))


def random_number(length: int) -> str:
    return random_str(length, string.digits)


def random_word() -> str:
    return random_char(secrets.randbelow(5) + 3)


def random_char(length: int) -> str:
    return random_str(length, string.ascii_letters)


def random_alphanum(length: int) -> str:
    choices = string.ascii_letters + string.ascii_letters.upper() + string.digits
    return random_str(length, choices)


def random_ip(input_ip: str) -> str:
    ip = ""

    try:
        octals = [int(i) for i in input_ip.split(".")]
    except ValueError:
        pass
    else:
        if octals[0] == 10:
            ip = f"10.{secrets.randbelow(256)}.{secrets.randbelow(256)}.{secrets.randbelow(256)}"
        elif octals[0] == 172 and 16 <= octals[1] <= 31:
            ip = f"172.{secrets.randbelow(16) + 16}.{secrets.randbelow(256)}.{secrets.randbelow(256)}"
        elif octals[0] == 192 and octals[1] == 168:
            ip = f"192.168.{secrets.randbelow(256)}.{secrets.randbelow(256)}"

    if not ip:
        ip = f"{secrets.randbelow(255) + 1}.{secrets.randbelow(256)}.{secrets.randbelow(256)}.{secrets.randbelow(256)}"
    return ip


def random_identifier() -> str:
    return str(uuid.uuid4())


def _random_identity() -> dict[str, str]:
    first_name = random_word().title()
    last_name = random_word().title()
    local_username = random_word()
    return {
        "firstName": first_name,
        "lastName": last_name,
        "name": f"{first_name} {last_name}",
        "localUsername": local_username,
        "email": f"{local_username}@example.com",
    }


def _anonymize_cloud_account(
    cloud_account: dict[str, Any], identity: dict[str, str]
) -> None:
    for key in ("firstName", "lastName", "name", "email"):
        if key in cloud_account:
            cloud_account[key] = identity[key]
    if "user" in cloud_account:
        cloud_account["user"] = anonymize_object_id(cloud_account["user"])
    for key in ("id", "cloudId"):
        if key in cloud_account:
            cloud_account[key] = anonymize_uuid(cloud_account[key])
