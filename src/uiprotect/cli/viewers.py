from __future__ import annotations

from dataclasses import dataclass

import typer

from ..api import ProtectApiClient
from ..cli import base
from ..data import Viewer
from ..data.public_devices import PublicViewer

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of viewer to select for subcommands")


@dataclass
class ViewerContext(base.CliContext):
    devices: dict[str, Viewer | PublicViewer]
    device: Viewer | PublicViewer | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: str | None = ARG_DEVICE_ID) -> None:
    """
    Viewers device CLI.

    Returns full list of Viewers without any arguments passed.
    """
    devices = base.device_map(ctx, "viewers")
    context = ViewerContext(
        protect=ctx.obj.protect,
        device=None,
        devices=devices,
        output_format=ctx.obj.output_format,
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := devices.get(device_id)) is None:
            typer.secho("Invalid viewer ID", fg="red")
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
def liveview(
    ctx: typer.Context,
    liveview_id: str | None = typer.Argument(
        None, help="Liveview ID to assign, or 'null' to clear"
    ),
) -> None:
    """Returns or sets the current liveview."""
    base.require_device_id(ctx, public_ok=True)
    obj: Viewer | PublicViewer = ctx.obj.device
    liveviews = base.device_map(ctx, "liveviews")

    if liveview_id is None:
        if isinstance(obj, PublicViewer):
            current = liveviews.get(obj.liveview_id) if obj.liveview_id else None
        else:
            current = obj.liveview
        base.print_unifi_obj(current, ctx.obj.output_format)
        return

    protect: ProtectApiClient = ctx.obj.protect
    if liveview_id.lower() == "null":
        base.run(ctx, protect.update_viewer_public(obj.id, liveview=None))
        return
    if liveview_id not in liveviews:
        typer.secho("Invalid liveview ID")
        raise typer.Exit(1)
    base.run(ctx, protect.update_viewer_public(obj.id, liveview=liveview_id))
