from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_PROFILE_ID = typer.Argument(..., help="External arm profile ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """External alarm manager arm profile commands (Public API, Protect 7.4+)."""


@app.command("list")
def list_profiles(ctx: typer.Context) -> None:
    """List all external arm profiles."""

    async def _fetch() -> None:
        profiles = await ctx.obj.protect.get_external_arm_profiles_public()
        base.print_unifi_list(profiles)

    base.run(ctx, _fetch())


@app.command()
def arm(
    ctx: typer.Context,
    profile_id: str = ARG_PROFILE_ID,
) -> None:
    """Arm an external arm profile."""

    async def _arm() -> None:
        profile = await ctx.obj.protect.arm_external_arm_profile_public(profile_id)
        base.print_unifi_obj(profile, ctx.obj.output_format)

    base.run(ctx, _arm())


@app.command()
def disarm(
    ctx: typer.Context,
    profile_id: str = ARG_PROFILE_ID,
) -> None:
    """Disarm an external arm profile."""

    async def _disarm() -> None:
        profile = await ctx.obj.protect.disarm_external_arm_profile_public(profile_id)
        base.print_unifi_obj(profile, ctx.obj.output_format)

    base.run(ctx, _disarm())
