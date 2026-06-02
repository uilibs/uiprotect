from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_ULP_USER_ID = typer.Argument(..., help="ULP user ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """UniFi Identity (ULP) user commands (Public API)."""


@app.command("list")
def list_ulp_users(ctx: typer.Context) -> None:
    """List UniFi Identity users."""

    async def _fetch() -> None:
        items = await ctx.obj.protect.get_ulp_users_public()
        base.print_unifi_list(items, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, ulp_user_id: str = ARG_ULP_USER_ID) -> None:
    """Show details for a specific UniFi Identity user."""

    async def _fetch() -> None:
        obj = await ctx.obj.protect.get_ulp_user_public(ulp_user_id)
        base.print_unifi_obj(obj, ctx.obj.output_format)

    base.run(ctx, _fetch())
