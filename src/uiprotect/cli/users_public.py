from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_USER_ID = typer.Argument(..., help="User ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Protect user commands (Public API)."""


@app.command("list")
def list_users(ctx: typer.Context) -> None:
    """List Protect users."""

    async def _fetch() -> None:
        items = await ctx.obj.protect.get_users_public()
        base.print_unifi_list(items, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, user_id: str = ARG_USER_ID) -> None:
    """Show details for a specific Protect user."""

    async def _fetch() -> None:
        obj = await ctx.obj.protect.get_user_public(user_id)
        base.print_unifi_obj(obj, ctx.obj.output_format)

    base.run(ctx, _fetch())
