from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import typer

from ..api import ProtectApiClient
from ..cli import base
from ..data import Camera, Chime
from ..data.public_devices import PublicChime

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of chime to select for subcommands")
ARG_REPEAT = typer.Argument(..., help="Repeat times count", min=1, max=6)
ARG_VOLUME = typer.Argument(..., help="Volume", min=1, max=100)


@dataclass
class ChimeContext(base.CliContext):
    devices: dict[str, Chime | PublicChime]
    device: Chime | PublicChime | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: str | None = ARG_DEVICE_ID) -> None:
    """
    Chime device CLI.

    Returns full list of Chimes without any arguments passed.
    """
    devices = base.device_map(ctx, "chimes")
    context = ChimeContext(
        protect=ctx.obj.protect,
        device=None,
        devices=devices,
        output_format=ctx.obj.output_format,
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := devices.get(device_id)) is None:
            typer.secho("Invalid chime ID", fg="red")
            raise typer.Exit(1)
        ctx.obj.device = device

    if not ctx.invoked_subcommand:
        if device_id in ALL_COMMANDS:
            ctx.invoke(ALL_COMMANDS[device_id], ctx)
            return

        if ctx.obj.device is not None:
            base.print_unifi_obj(ctx.obj.device, ctx.obj.output_format)
            return

        base.print_unifi_dict(ctx.obj.devices)


@app.command()
def cameras(
    ctx: typer.Context,
    camera_ids: list[str] = typer.Argument(
        None,
        help="Set to [] to empty list of cameras",
    ),
    add: bool = typer.Option(False, "-a", "--add", help="Add cameras instead of set"),
    remove: bool = typer.Option(
        False,
        "-r",
        "--remove",
        help="Remove cameras instead of set",
    ),
) -> None:
    """Returns or sets paired doorbells for the chime."""
    base.require_device_id(ctx, public_ok=True)
    obj: Chime | PublicChime = ctx.obj.device

    if add and remove:
        typer.secho("Add and remove are mutually exclusive", fg="red")
        raise typer.Exit(1)

    cameras_by_id = base.device_map(ctx, "cameras")
    # Typer passes ``None`` for an omitted variadic argument.
    if not camera_ids:
        base.json_output(
            [
                base.camera_dict(cameras_by_id[i])
                for i in obj.camera_ids
                if i in cameras_by_id
            ]
        )
        return

    protect: ProtectApiClient = ctx.obj.protect

    if len(camera_ids) == 1 and camera_ids[0] == "[]":
        camera_ids = []

    for camera_id in camera_ids:
        if (camera := cameras_by_id.get(camera_id)) is None:
            typer.secho(f"Invalid camera ID: {camera_id}", fg="red")
            raise typer.Exit(1)

        # The public camera model carries no doorbell flag; the console
        # validates the pairing itself.
        if isinstance(camera, Camera) and not camera.feature_flags.is_doorbell:
            typer.secho(f"Camera is not a doorbell: {camera_id}", fg="red")
            raise typer.Exit(1)

    if add:
        camera_ids = list(set(obj.camera_ids) | set(camera_ids))
    elif remove:
        camera_ids = list(set(obj.camera_ids) - set(camera_ids))

    base.run(ctx, protect.update_chime_public(obj.id, camera_ids=camera_ids))


@app.command()
def set_volume(
    ctx: typer.Context,
    value: int = ARG_VOLUME,
    camera_id: str | None = typer.Option(
        None,
        "-c",
        "--camera",
        help="Camera ID to apply volume to",
    ),
) -> None:
    """Set volume level for chime rings."""
    # Without a camera the whole ring-settings list is rewritten, which only
    # the private model can build a request body for.
    base.require_device_id(ctx, public_ok=camera_id is not None)
    obj: Chime | PublicChime = ctx.obj.device
    protect: ProtectApiClient = ctx.obj.protect
    if camera_id is None:
        base.run(ctx, _update_ring_settings(protect, cast("Chime", obj), volume=value))
    else:
        camera = base.device_map(ctx, "cameras").get(camera_id)
        if camera is None:
            typer.secho(f"Invalid camera ID: {camera_id}", fg="red")
            raise typer.Exit(1)
        if isinstance(obj, PublicChime):
            base.run(ctx, obj.set_volume_for_camera(camera.id, value))
        else:
            base.run(ctx, obj.set_volume_for_camera_public(camera, value))


@app.command()
def play(
    ctx: typer.Context,
    volume: int | None = typer.Option(None, "-v", "--volume", min=1, max=100),
    repeat_times: int | None = typer.Option(None, "-r", "--repeat", min=1, max=6),
) -> None:
    """Plays chime tone."""
    base.require_device_id(ctx)
    obj: Chime = ctx.obj.device
    base.run(ctx, obj.play(volume=volume, repeat_times=repeat_times))


@app.command()
def play_buzzer(ctx: typer.Context) -> None:
    """Plays chime buzzer."""
    base.require_device_id(ctx)
    obj: Chime = ctx.obj.device
    base.run(ctx, obj.play_buzzer())


@app.command()
def set_repeat_times(
    ctx: typer.Context,
    value: int = ARG_REPEAT,
    camera_id: str | None = typer.Option(
        None,
        "-c",
        "--camera",
        help="Camera ID to apply repeat times to",
    ),
) -> None:
    """Set number of times for a chime to repeat when doorbell is rang."""
    # Without a camera the whole ring-settings list is rewritten, which only
    # the private model can build a request body for.
    base.require_device_id(ctx, public_ok=camera_id is not None)
    obj: Chime | PublicChime = ctx.obj.device
    protect: ProtectApiClient = ctx.obj.protect
    if camera_id is None:
        base.run(
            ctx, _update_ring_settings(protect, cast("Chime", obj), repeat_times=value)
        )
    else:
        camera = base.device_map(ctx, "cameras").get(camera_id)
        if camera is None:
            typer.secho(f"Invalid camera ID: {camera_id}", fg="red")
            raise typer.Exit(1)
        if isinstance(obj, PublicChime):
            base.run(ctx, obj.set_repeat_times_for_camera(camera.id, value))
        else:
            base.run(ctx, obj.set_repeat_times_for_camera_public(camera, value))


async def _update_ring_settings(
    protect: ProtectApiClient, chime: Chime, **changes: int
) -> None:
    # Built inside the coroutine so ChimeRingtoneNotSetError reaches base.run.
    await protect.update_chime_public(
        chime.id,
        ring_settings=[s.to_api_dict(**changes) for s in chime.ring_settings],
    )
