from __future__ import annotations

from dataclasses import dataclass

import typer

from ..api import ProtectApiClient
from ..cli import base
from ..data import Viewer

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of viewer to select for subcommands")


@dataclass
class ViewerContext(base.CliContext):
    devices: dict[str, Viewer]
    device: Viewer | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: str | None = ARG_DEVICE_ID) -> None:
    """
    Viewers device CLI.

    Returns full list of Viewers without any arguments passed.
    """
    protect: ProtectApiClient = ctx.obj.protect
    context = ViewerContext(
        protect=ctx.obj.protect,
        device=None,
        devices=protect.bootstrap.viewers,
        output_format=ctx.obj.output_format,
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.viewers.get(device_id)) is None:
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
    liveview_id: str | None = typer.Argument(None),
) -> None:
    """Returns or sets the current liveview."""
    base.require_device_id(ctx)
    obj: Viewer = ctx.obj.device

    if liveview_id is None:
        base.print_unifi_obj(obj.liveview, ctx.obj.output_format)
    else:
        protect: ProtectApiClient = ctx.obj.protect
        if (liveview_obj := protect.bootstrap.liveviews.get(liveview_id)) is None:
            typer.secho("Invalid liveview ID")
            raise typer.Exit(1)
        base.run(ctx, obj.set_liveview(liveview_obj))


# ---------------------------------------------------------------------------
# Public Integration API subcommands (suffixed ``-public`` to coexist with the
# private-API commands above). They still pay the private-bootstrap callback
# cost — accepted as transitional pending maintainer feedback on whether a
# dedicated ``viewers-public`` sub-app would be preferable.
# ---------------------------------------------------------------------------

ARG_VIEWER_ID = typer.Argument(..., help="Viewer ID")


@app.command("list-public")
def list_public(ctx: typer.Context) -> None:
    """List viewers via the Public Integration API."""

    async def _fetch() -> None:
        items = await ctx.obj.protect.get_viewers_public()
        base.print_unifi_list(items)

    base.run(ctx, _fetch())


@app.command("show-public")
def show_public(ctx: typer.Context, viewer_id: str = ARG_VIEWER_ID) -> None:
    """Show details for a specific viewer via the Public Integration API."""

    async def _fetch() -> None:
        obj = await ctx.obj.protect.get_viewer_public(viewer_id)
        base.print_unifi_obj(obj, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command("set-name-public")
def set_name_public(
    ctx: typer.Context,
    viewer_id: str = ARG_VIEWER_ID,
    name: str = typer.Argument(..., help="New name for the viewer"),
) -> None:
    """Rename a viewer via the Public Integration API."""
    base.run(ctx, ctx.obj.protect.update_viewer_public(viewer_id, name=name))


@app.command("set-liveview-public")
def set_liveview_public(
    ctx: typer.Context,
    viewer_id: str = ARG_VIEWER_ID,
    liveview_id: str = typer.Argument(
        ..., help="Liveview ID to assign, or 'null' to clear"
    ),
) -> None:
    """Assign a liveview to a viewer via the Public Integration API."""
    target: str | None = None if liveview_id.lower() == "null" else liveview_id
    base.run(ctx, ctx.obj.protect.update_viewer_public(viewer_id, liveview=target))
