from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_FOB_ID = typer.Argument(..., help="Fob ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Fob commands (Public API)."""


@app.command("list")
def list_fobs(ctx: typer.Context) -> None:
    """List all key fobs."""

    async def _fetch() -> None:
        fobs = await ctx.obj.protect.get_fobs_public()
        base.print_unifi_list(fobs)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, fob_id: str = ARG_FOB_ID) -> None:
    """Show details for a specific key fob."""

    async def _fetch() -> None:
        fob = await ctx.obj.protect.get_fob_public(fob_id)
        base.print_unifi_obj(fob, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def set_name(
    ctx: typer.Context,
    fob_id: str = ARG_FOB_ID,
    name: str = typer.Argument(..., help="New name for the fob"),
) -> None:
    """Rename a key fob."""
    base.run(ctx, ctx.obj.protect.update_fob_public(fob_id, name=name))
