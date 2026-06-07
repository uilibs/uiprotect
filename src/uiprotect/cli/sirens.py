from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_SIREN_ID = typer.Argument(..., help="Siren ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Siren commands (Public API)."""


@app.command("list")
def list_sirens(ctx: typer.Context) -> None:
    """List all sirens."""

    async def _fetch() -> None:
        sirens = await ctx.obj.protect.get_sirens_public()
        base.print_unifi_list(sirens)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, siren_id: str = ARG_SIREN_ID) -> None:
    """Show details for a specific siren."""

    async def _fetch() -> None:
        siren = await ctx.obj.protect.get_siren_public(siren_id)
        base.print_unifi_obj(siren, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def play(
    ctx: typer.Context,
    siren_id: str = ARG_SIREN_ID,
    duration: int | None = typer.Option(
        None,
        "--duration",
        "-d",
        help="Duration in seconds (5, 10, 20, or 30). Omit to use server default.",
        min=1,
    ),
) -> None:
    """Activate a siren."""
    base.run(ctx, ctx.obj.protect.play_siren_public(siren_id, duration=duration))


@app.command()
def stop(ctx: typer.Context, siren_id: str = ARG_SIREN_ID) -> None:
    """Stop an active siren."""
    base.run(ctx, ctx.obj.protect.stop_siren_public(siren_id))


@app.command()
def test_sound(
    ctx: typer.Context,
    siren_id: str = ARG_SIREN_ID,  # noqa: PT028  # typer CLI argument, not a pytest test
    volume: int | None = typer.Option(  # noqa: PT028  # typer CLI argument, not a pytest test
        None,
        "--volume",
        "-v",
        help="Test volume (1-100). Omit to use the current siren volume.",
        min=1,
        max=100,
    ),
) -> None:
    """Play a 5-second test sound on a siren."""
    base.run(ctx, ctx.obj.protect.test_siren_sound_public(siren_id, volume=volume))


@app.command()
def set_volume(
    ctx: typer.Context,
    siren_id: str = ARG_SIREN_ID,
    volume: int = typer.Argument(..., help="Volume (1-100)", min=1, max=100),
) -> None:
    """Set the siren volume."""
    base.run(ctx, ctx.obj.protect.update_siren_public(siren_id, volume=volume))


@app.command()
def set_name(
    ctx: typer.Context,
    siren_id: str = ARG_SIREN_ID,
    name: str = typer.Argument(..., help="New name for the siren"),
) -> None:
    """Rename a siren."""
    base.run(ctx, ctx.obj.protect.update_siren_public(siren_id, name=name))


@app.command()
def set_status_light(
    ctx: typer.Context,
    siren_id: str = ARG_SIREN_ID,
    enabled: bool = typer.Argument(..., help="Enable or disable the LED status light"),
) -> None:
    """Enable or disable the LED status light on a siren."""
    base.run(ctx, ctx.obj.protect.update_siren_public(siren_id, led_is_enabled=enabled))
