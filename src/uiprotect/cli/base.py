from __future__ import annotations

import hashlib
import ssl
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar, cast

import aiohttp
import orjson
import typer
from pydantic import ValidationError

from ..api import ProtectApiClient
from ..data import (
    NVR,
    AiPort,
    Bootstrap,
    Camera,
    Chime,
    Light,
    ProtectAdoptableDeviceModel,
    ProtectBaseObject,
    Sensor,
    Viewer,
)
from ..data.public_devices import PublicDeviceModel
from ..exceptions import BadRequest, NvrError, StreamError
from ..utils import run_async

T = TypeVar("T")

OPTION_FORCE = typer.Option(False, "-f", "--force", help="Skip confirmation prompt")

PRIVATE_ONLY_ERROR = (
    "Not available in public-only mode: this command needs the private API. "
    "Pass --username/--password to use it."
)
MISSING_CREDENTIALS_ERROR = (
    "This command needs the private API: pass --username and --password "
    "(or set UFP_USERNAME and UFP_PASSWORD)."
)
DROP_CREDENTIAL_HINT = (
    "Or drop --username/--password (and UFP_USERNAME/UFP_PASSWORD) to run "
    "commands on the API key alone."
)
_PUBLIC_DEVICES_KEY = "uiprotect.public_devices"


class OutputFormatEnum(StrEnum):
    JSON = "json"
    PLAIN = "plain"


@dataclass
class CliContext:
    protect: ProtectApiClient
    output_format: OutputFormatEnum


def run(ctx: typer.Context, func: Awaitable[T]) -> T:
    """Helper method to call async function and clean up API client"""

    async def callback() -> T:
        try:
            return await func
        finally:
            await ctx.obj.protect.close_session()
            await ctx.obj.protect.close_public_api_session()

    try:
        return run_async(callback())
    except (BadRequest, ValidationError, StreamError, NvrError) as err:
        # A public-API request fails the same way a private login does when the
        # console serves a certificate we do not trust.
        if not _report_ssl_error(ctx.obj.protect, err):
            typer.secho(str(err), fg="red")
        raise typer.Exit(1) from err


def json_output(obj: Any) -> None:
    typer.echo(orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode("utf-8"))


def print_unifi_obj(
    obj: ProtectBaseObject | None,
    output_format: OutputFormatEnum,
) -> None:
    """Helper method to print a single protect object"""
    if obj is not None:
        json_output(obj.unifi_dict())
    elif output_format == OutputFormatEnum.JSON:
        json_output(None)


def print_unifi_list(
    objs: Sequence[ProtectBaseObject],
    output_format: OutputFormatEnum = OutputFormatEnum.JSON,
) -> None:
    """Helper method to print a list of protect objects"""
    if objs:
        json_output([o.unifi_dict() for o in objs])
    elif output_format == OutputFormatEnum.JSON:
        json_output([])


def print_unifi_dict(objs: Mapping[str, ProtectBaseObject]) -> None:
    """Helper method to print a dictionary of protect objects"""
    data = {k: v.unifi_dict() for k, v in objs.items()}
    json_output(data)


def require_private_api(ctx: typer.Context) -> None:
    """Rejects the command in public-only mode; prompts for missing credentials."""
    protect: ProtectApiClient = ctx.obj.protect
    if protect.is_public_only:
        typer.secho(PRIVATE_ONLY_ERROR, fg="red", err=True)
        raise typer.Exit(1)
    if protect._username and protect._password:
        return
    # A prompt without a terminal would hang a scripted run.
    if not _is_interactive():
        typer.secho(MISSING_CREDENTIALS_ERROR, fg="red", err=True)
        if protect._api_key:
            typer.secho(DROP_CREDENTIAL_HINT, err=True)
        raise typer.Exit(1)
    if not protect._username:
        protect._username = typer.prompt("Username")
    if not protect._password:
        protect._password = typer.prompt("Password", hide_input=True)


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _is_ssl_error(exc: BaseException) -> bool:
    """Check if an exception is an SSL certificate verification error."""
    if isinstance(exc, aiohttp.ClientConnectorCertificateError):
        return True
    if isinstance(exc, aiohttp.ClientConnectorSSLError):
        return True
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    # Check nested exceptions
    if exc.__cause__ is not None:
        return _is_ssl_error(exc.__cause__)
    return False


def _get_cert_fingerprint(host: str, port: int) -> str | None:
    """Return the SHA-256 fingerprint of the server's leaf certificate, or None."""
    try:
        pem = ssl.get_server_certificate((host, port), timeout=5)
    except (OSError, ssl.SSLError):
        return None
    if not pem:
        return None
    der = ssl.PEM_cert_to_DER_cert(pem)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


async def _connect_and_bootstrap(protect: ProtectApiClient) -> None:
    """Connect to the Protect API and fetch bootstrap data."""
    protect._bootstrap = await protect.get_bootstrap()
    await protect.close_session()
    await protect.close_public_api_session()


def private_bootstrap(ctx: typer.Context) -> Bootstrap:
    """The private bootstrap, logging in and fetching it on first use."""
    require_private_api(ctx)
    protect: ProtectApiClient = ctx.obj.protect
    # ``_bootstrap`` is what ``_connect_and_bootstrap`` fills in; the public
    # ``bootstrap`` property raises instead of reporting that it is unset.
    if protect._bootstrap is not None:
        return protect.bootstrap

    try:
        run_async(_connect_and_bootstrap(protect))
    except Exception as exc:
        # Always close the session on error to avoid "Unclosed client session" warning
        run_async(_close_protect(protect))

        if not _report_ssl_error(protect, exc):
            typer.secho(f"Connection failed: {exc}", fg="red")
        raise typer.Exit(code=1) from exc

    return protect.bootstrap


def _report_ssl_error(protect: ProtectApiClient, exc: BaseException) -> bool:
    """Print the certificate guidance for a verification failure, if that is what it is."""
    if not protect._verify_ssl or not _is_ssl_error(exc):
        return False

    address, port = protect._host, protect._port
    typer.secho(
        f"SSL certificate verification failed for {address}:{port}.",
        fg="red",
        err=True,
    )
    fingerprint = _get_cert_fingerprint(address, port)
    if fingerprint:
        typer.secho(
            f"  Server certificate SHA-256: {fingerprint}",
            err=True,
        )
    typer.secho(
        "Refusing to retry with verification disabled — sending "
        "credentials over an unauthenticated TLS channel would "
        "expose them to any on-path attacker.",
        fg="red",
        err=True,
    )
    typer.secho(
        "If you have verified the fingerprint above out-of-band "
        "(e.g. via the UniFi Protect console), rerun the command "
        "with --no-verify-ssl to skip verification for this "
        "invocation.",
        err=True,
    )
    return True


async def _close_protect(protect: ProtectApiClient) -> None:
    """Close the Protect API client sessions."""
    await protect.close_session()
    await protect.close_public_api_session()


def public_call(
    obj: ProtectBaseObject,
    method: str,
    *args: Any,
    **kwargs: Any,
) -> Awaitable[Any]:
    """
    Calls a Public Integration API setter on a private or public device model.

    The public device models name these ``set_x``; their private counterparts
    carry the same call as ``set_x_public``.
    """
    if isinstance(obj, PublicDeviceModel):
        return cast("Awaitable[Any]", getattr(obj, method)(*args, **kwargs))
    return cast("Awaitable[Any]", getattr(obj, f"{method}_public")(*args, **kwargs))


def device_map(ctx: typer.Context, attr: str) -> dict[str, Any]:
    """
    Devices of one kind, keyed by id.

    In public-only mode only that kind is fetched, and a failed request exits
    with its error rather than reading as an empty list.
    """
    protect: ProtectApiClient = ctx.obj.protect
    if not protect.is_public_only:
        return cast("dict[str, Any]", getattr(private_bootstrap(ctx), attr))
    cache: dict[str, dict[str, Any]] = ctx.meta.setdefault(_PUBLIC_DEVICES_KEY, {})
    if attr not in cache:
        items = run(ctx, getattr(protect, f"get_{attr}_public")())
        cache[attr] = {item.id: item for item in items}
    return cache[attr]


def require_device_id(ctx: typer.Context, *, public_ok: bool = False) -> None:
    """Requires device ID in context; a private-API device unless ``public_ok``."""
    if ctx.obj.device is None:
        typer.secho("Requires a valid device ID to be selected")
        raise typer.Exit(1)
    if not public_ok and isinstance(ctx.obj.device, PublicDeviceModel):
        typer.secho(PRIVATE_ONLY_ERROR, fg="red", err=True)
        raise typer.Exit(1)


def require_no_device_id(ctx: typer.Context) -> None:
    """Requires no device ID in context"""
    if ctx.obj.device is not None:
        typer.secho("Requires no device ID to be selected")
        raise typer.Exit(1)


def _list_name(obj: ProtectAdoptableDeviceModel | PublicDeviceModel) -> str:
    """Display name annotated with the device state, for ``list-ids``."""
    name = obj.display_name
    if isinstance(obj, PublicDeviceModel):
        # The public payload carries a single state field; adoption and
        # firmware-update state are private-API only.
        return name if obj.is_reachable else f"{name} [Disconnected]"

    if obj.is_adopted_by_other:
        name = f"{name} [Managed by Another Console]"
    elif obj.is_adopting:
        name = f"{name} [Adopting]"
    elif obj.can_adopt:
        name = f"{name} [Unadopted]"
    elif obj.is_rebooting:
        name = f"{name} [Restarting]"
    elif obj.is_updating:
        name = f"{name} [Updating]"
    elif not obj.is_connected:
        name = f"{name} [Disconnected]"
    return name


def list_ids(ctx: typer.Context) -> None:
    """Requires no device ID. Prints list of "id name" for each device."""
    require_no_device_id(ctx)
    objs: dict[str, ProtectAdoptableDeviceModel | PublicDeviceModel] = ctx.obj.devices
    to_print: list[tuple[str, str | None]] = [
        (obj.id, _list_name(obj)) for obj in objs.values()
    ]

    if ctx.obj.output_format == OutputFormatEnum.JSON:
        json_output(to_print)
    else:
        for item in to_print:
            typer.echo(f"{item[0]}\t{item[1]}")


def protect_url(ctx: typer.Context) -> None:
    """Gets UniFi Protect management URL."""
    require_device_id(ctx)
    obj: NVR | ProtectAdoptableDeviceModel = ctx.obj.device
    if ctx.obj.output_format == OutputFormatEnum.JSON:
        json_output(obj.protect_url)
    else:
        typer.echo(obj.protect_url)


def is_wired(ctx: typer.Context) -> None:
    """Returns if the device is wired or not."""
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    json_output(obj.is_wired)


def is_wifi(ctx: typer.Context) -> None:
    """Returns if the device has WiFi or not."""
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    json_output(obj.is_wifi)


def is_bluetooth(ctx: typer.Context) -> None:
    """Returns if the device has Bluetooth or not."""
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    json_output(obj.is_bluetooth)


def bridge(ctx: typer.Context) -> None:
    """Returns bridge device if connected via Bluetooth."""
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    print_unifi_obj(obj.bridge, ctx.obj.output_format)


def set_ssh(ctx: typer.Context, enabled: bool) -> None:
    """
    Sets the isSshEnabled value for device.

    May not have an effect on many device types. Only seems to work for
    Linux and BusyBox based devices (camera, light and viewport).
    """
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    run(ctx, obj.set_ssh(enabled))


def set_name(ctx: typer.Context, name: str | None = typer.Argument(None)) -> None:
    """Sets name for the device"""
    # The public API cannot express clearing a name, so that keeps the private
    # path and is unavailable in public-only mode.
    require_device_id(ctx, public_ok=name is not None)
    device: NVR | ProtectAdoptableDeviceModel | PublicDeviceModel = ctx.obj.device
    if isinstance(device, PublicDeviceModel):
        run(ctx, public_call(device, "set_name", cast("str", name)))
        return

    obj: NVR | ProtectAdoptableDeviceModel = device
    # AiPort subclasses Camera but has no public-API endpoint of its own.
    if (
        name is not None
        and isinstance(obj, (Camera, Chime, Light, Sensor, Viewer))
        and not isinstance(obj, AiPort)
    ):
        run(ctx, obj.set_name_public(name))
        return
    run(ctx, obj.set_name(name))


def update(ctx: typer.Context, data: str) -> None:
    """
    Updates the device.

    Makes a raw PATCH request to update a device. Advanced usage and usually recommended not to use.
    """
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device

    if obj.model is not None:
        run(ctx, obj.api.update_device(obj.model, obj.id, orjson.loads(data)))


def reboot(ctx: typer.Context, force: bool = OPTION_FORCE) -> None:
    """Reboots the device."""
    require_device_id(ctx)
    obj: NVR | ProtectAdoptableDeviceModel = ctx.obj.device

    if force or typer.confirm(f'Confirm reboot of "{obj.name}"" (id: {obj.id})'):
        run(ctx, obj.reboot())


def unadopt(ctx: typer.Context, force: bool = OPTION_FORCE) -> None:
    """Unadopt/Unmanage adopted device."""
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device

    if force or typer.confirm(f'Confirm undopt of "{obj.name}"" (id: {obj.id})'):
        run(ctx, obj.unadopt())


def adopt(ctx: typer.Context, name: str | None = typer.Argument(None)) -> None:
    """
    Adopts a device.

    By default, unadopted devices do not show up in the bootstrap. Use
    `uiprotect -u` to show unadopted devices.
    """
    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device

    run(ctx, obj.adopt(name))


def init_common_commands(
    app: typer.Typer,
) -> tuple[dict[str, Callable[..., Any]], dict[str, Callable[..., Any]]]:
    deviceless_commands: dict[str, Callable[..., Any]] = {}
    device_commands: dict[str, Callable[..., Any]] = {}

    deviceless_commands["list-ids"] = app.command()(list_ids)
    device_commands["is-wired"] = app.command()(is_wired)
    device_commands["is-wifi"] = app.command()(is_wifi)
    device_commands["is-bluetooth"] = app.command()(is_bluetooth)
    device_commands["bridge"] = app.command()(bridge)
    device_commands["set-ssh"] = app.command()(set_ssh)
    device_commands["set-name"] = app.command()(set_name)
    device_commands["update"] = app.command()(update)
    device_commands["reboot"] = app.command()(reboot)
    device_commands["unadopt"] = app.command()(unadopt)
    device_commands["adopt"] = app.command()(adopt)

    return deviceless_commands, device_commands
