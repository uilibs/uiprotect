from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_VIEWER_ID = typer.Argument(..., help="Viewer ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Viewer commands (Public API)."""


@app.command("list")
def list_viewers(ctx: typer.Context) -> None:
    """List viewers."""

    async def _fetch() -> None:
        items = await ctx.obj.protect.get_viewers_public()
        base.print_unifi_list(items)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, viewer_id: str = ARG_VIEWER_ID) -> None:
    """Show details for a specific viewer."""

    async def _fetch() -> None:
        obj = await ctx.obj.protect.get_viewer_public(viewer_id)
        base.print_unifi_obj(obj, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def set_name(
    ctx: typer.Context,
    viewer_id: str = ARG_VIEWER_ID,
    name: str = typer.Argument(..., help="New name for the viewer"),
) -> None:
    """Rename a viewer."""
    base.run(ctx, ctx.obj.protect.update_viewer_public(viewer_id, name=name))


@app.command()
def set_liveview(
    ctx: typer.Context,
    viewer_id: str = ARG_VIEWER_ID,
    liveview_id: str = typer.Argument(
        ..., help="Liveview ID to assign, or 'null' to clear"
    ),
) -> None:
    """Assign a liveview to a viewer."""
    target: str | None = None if liveview_id.lower() == "null" else liveview_id
    base.run(ctx, ctx.obj.protect.update_viewer_public(viewer_id, liveview=target))
