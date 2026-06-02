from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_LINK_STATION_ID = typer.Argument(..., help="Link station / alarm hub ID")
ARG_OUTPUT_ID = typer.Argument(..., help="Output channel ID (integer)")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Link station and alarm hub commands (Public API)."""


@app.command("list")
def list_link_stations(
    ctx: typer.Context,
    alarm_hubs_only: bool = typer.Option(
        False,
        "--alarm-hubs-only",
        help="Only return entries with isAlarmHub=True (calls /v1/alarm-hubs).",
    ),
) -> None:
    """List link stations (and alarm hubs)."""

    async def _fetch() -> None:
        if alarm_hubs_only:
            items = await ctx.obj.protect.get_alarm_hubs_public()
        else:
            items = await ctx.obj.protect.get_link_stations_public()
        base.print_unifi_list(items)

    base.run(ctx, _fetch())


@app.command()
def show(
    ctx: typer.Context,
    link_station_id: str = ARG_LINK_STATION_ID,
    alarm_hub: bool = typer.Option(
        False,
        "--alarm-hub",
        help="Use /v1/alarm-hubs/{id} instead of /v1/link-stations/{id}.",
    ),
) -> None:
    """Show details for a specific link station / alarm hub."""

    async def _fetch() -> None:
        if alarm_hub:
            obj = await ctx.obj.protect.get_alarm_hub_public(link_station_id)
        else:
            obj = await ctx.obj.protect.get_link_station_public(link_station_id)
        base.print_unifi_obj(obj, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def set_name(
    ctx: typer.Context,
    link_station_id: str = ARG_LINK_STATION_ID,
    name: str = typer.Argument(..., help="New name for the link station / alarm hub"),
    alarm_hub: bool = typer.Option(
        False,
        "--alarm-hub",
        help="Patch via /v1/alarm-hubs/{id} instead of /v1/link-stations/{id}.",
    ),
) -> None:
    """Rename a link station / alarm hub."""
    if alarm_hub:
        base.run(
            ctx,
            ctx.obj.protect.update_alarm_hub_public(link_station_id, name=name),
        )
    else:
        base.run(
            ctx,
            ctx.obj.protect.update_link_station_public(link_station_id, name=name),
        )


@app.command("trigger-output")
def trigger_output(
    ctx: typer.Context,
    link_station_id: str = ARG_LINK_STATION_ID,
    output_id: int = ARG_OUTPUT_ID,
    enable: bool | None = typer.Option(None, "--enable/--disable", show_default=False),
    delay: int | None = typer.Option(None, "--delay", min=0, help="Delay in ms"),
    duration: int | None = typer.Option(
        None, "--duration", min=0, help="Duration in ms"
    ),
) -> None:
    """Trigger an alarm-hub output channel."""
    base.run(
        ctx,
        ctx.obj.protect.trigger_alarm_hub_output_public(
            link_station_id,
            output_id,
            enable=enable,
            delay=delay,
            duration=duration,
        ),
    )
