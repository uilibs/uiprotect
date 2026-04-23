from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_RELAY_ID = typer.Argument(..., help="Relay ID")
ARG_OUTPUT_ID = typer.Argument(..., help="Output channel ID (integer)")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Relay commands (Public API)."""


@app.command("list")
def list_relays(ctx: typer.Context) -> None:
    """List all relays."""

    async def _fetch() -> None:
        relays = await ctx.obj.protect.get_relays_public()
        base.print_unifi_list(relays)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, relay_id: str = ARG_RELAY_ID) -> None:
    """Show details for a specific relay."""

    async def _fetch() -> None:
        relay = await ctx.obj.protect.get_relay_public(relay_id)
        base.print_unifi_obj(relay, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def activate(
    ctx: typer.Context,
    relay_id: str = ARG_RELAY_ID,
    output_id: int = ARG_OUTPUT_ID,
    state: str | None = typer.Option(
        None,
        "--state",
        "-s",
        help="Target state: 'on' or 'off'. Omit to toggle the current state.",
    ),
    pulse_duration_ms: int | None = typer.Option(
        None,
        "--pulse-duration-ms",
        "-p",
        help="Auto-off duration in milliseconds. Only valid together with --state on.",
        min=1,
    ),
) -> None:
    """
    Activate, toggle, or pulse a relay output channel.

    Omit --state to toggle. Use --pulse-duration-ms with --state on to pulse.
    """
    if state is not None and state not in ("on", "off"):
        typer.secho("--state must be 'on' or 'off'", fg="red")
        raise typer.Exit(1)
    if pulse_duration_ms is not None and state != "on":
        typer.secho("--pulse-duration-ms requires --state on", fg="red")
        raise typer.Exit(1)
    base.run(
        ctx,
        ctx.obj.protect.activate_relay_output_public(
            relay_id,
            output_id,
            state=state,  # type: ignore[arg-type]
            pulse_duration_ms=pulse_duration_ms,
        ),
    )


@app.command()
def set_name(
    ctx: typer.Context,
    relay_id: str = ARG_RELAY_ID,
    name: str = typer.Argument(..., help="New name for the relay"),
) -> None:
    """Rename a relay."""
    base.run(ctx, ctx.obj.protect.update_relay_public(relay_id, name=name))


@app.command()
def set_status_light(
    ctx: typer.Context,
    relay_id: str = ARG_RELAY_ID,
    enabled: bool = typer.Argument(..., help="Enable or disable the LED status light"),
) -> None:
    """Enable or disable the LED status light on a relay."""
    base.run(ctx, ctx.obj.protect.update_relay_public(relay_id, led_is_enabled=enabled))
