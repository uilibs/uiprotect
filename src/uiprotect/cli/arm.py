from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_PROFILE_ID = typer.Argument(..., help="Arm profile ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Arm profile and alarm commands (Public API)."""


@app.command("list")
def list_profiles(ctx: typer.Context) -> None:
    """List all arm profiles."""

    async def _fetch() -> None:
        profiles = await ctx.obj.protect.get_arm_profiles_public()
        base.print_unifi_list(profiles)

    base.run(ctx, _fetch())


@app.command()
def status(ctx: typer.Context) -> None:
    """Show current arm manager settings (active profile + alarm state)."""

    async def _fetch() -> None:
        arm_mode = await ctx.obj.protect.get_arm_manager_settings_public()
        base.print_unifi_obj(arm_mode, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def set_profile(
    ctx: typer.Context,
    profile_id: str = ARG_PROFILE_ID,
) -> None:
    """Set the currently active arm profile."""
    base.run(ctx, ctx.obj.protect.set_current_arm_profile_public(profile_id))


@app.command()
def enable_alarm(ctx: typer.Context) -> None:
    """Enable the arm alarm using the currently selected profile."""
    base.run(ctx, ctx.obj.protect.enable_arm_alarm_public())


@app.command()
def disable_alarm(ctx: typer.Context) -> None:
    """Disable the arm alarm."""
    base.run(ctx, ctx.obj.protect.disable_arm_alarm_public())


@app.command()
def trigger(
    ctx: typer.Context,
    trigger_id: str = typer.Argument(..., help="Webhook trigger ID"),
) -> None:
    """Fire the alarm-manager webhook for the given trigger ID."""
    base.run(ctx, ctx.obj.protect.send_alarm_webhook_public(trigger_id))
