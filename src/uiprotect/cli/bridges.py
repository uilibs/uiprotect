from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_BRIDGE_ID = typer.Argument(..., help="Bridge ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Bridge commands (Public API)."""


@app.command("list")
def list_bridges(ctx: typer.Context) -> None:
    """List bridges."""

    async def _fetch() -> None:
        items = await ctx.obj.protect.get_bridges_public()
        base.print_unifi_list(items, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, bridge_id: str = ARG_BRIDGE_ID) -> None:
    """Show details for a specific bridge."""

    async def _fetch() -> None:
        obj = await ctx.obj.protect.get_bridge_public(bridge_id)
        base.print_unifi_obj(obj, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def set_name(
    ctx: typer.Context,
    bridge_id: str = ARG_BRIDGE_ID,
    name: str = typer.Argument(..., help="New name for the bridge"),
) -> None:
    """Rename a bridge."""
    base.run(ctx, ctx.obj.protect.update_bridge_public(bridge_id, name=name))
