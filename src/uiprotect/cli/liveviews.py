from __future__ import annotations

from typing import Any

import orjson
import typer

from ..cli import base
from ..data import PublicLiveviewSlotDict
from ..exceptions import BadRequest

app = typer.Typer(rich_markup_mode="rich")

ARG_LIVEVIEW_ID = typer.Argument(..., help="Liveview ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Liveview commands (Public API)."""


def _parse_slots(raw: str) -> list[PublicLiveviewSlotDict]:
    try:
        data = orjson.loads(raw)
    except orjson.JSONDecodeError as err:
        typer.secho(f"--slots must be valid JSON: {err}", fg="red")
        raise typer.Exit(1) from err
    if not isinstance(data, list):
        typer.secho("--slots must be a JSON array of slot objects", fg="red")
        raise typer.Exit(1)
    if any(not isinstance(slot, dict) for slot in data):
        typer.secho("--slots entries must be JSON objects", fg="red")
        raise typer.Exit(1)
    return data


@app.command("list")
def list_liveviews(ctx: typer.Context) -> None:
    """List all liveviews."""

    async def _fetch() -> None:
        liveviews = await ctx.obj.protect.get_liveviews_public()
        base.print_unifi_list(liveviews)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, liveview_id: str = ARG_LIVEVIEW_ID) -> None:
    """Show details for a specific liveview."""

    async def _fetch() -> None:
        liveview = await ctx.obj.protect.get_liveview_public(liveview_id)
        base.print_unifi_obj(liveview, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Liveview name"),
    owner: str = typer.Option(..., "--owner", help="Owner user ID"),
    layout: int = typer.Option(
        ..., "--layout", help="Slot count (1-26)", min=1, max=26
    ),
    slots: str = typer.Option(
        ...,
        "--slots",
        help=(
            "JSON array of slot objects, e.g. "
            '\'[{"cameras":["id1"],"cycleMode":"motion","cycleInterval":10}]\''
        ),
    ),
    is_default: bool = typer.Option(False, "--default/--no-default"),
    is_global: bool = typer.Option(False, "--global/--no-global"),
) -> None:
    """Create a new liveview."""
    parsed = _parse_slots(slots)

    async def _create() -> None:
        liveview = await ctx.obj.protect.create_liveview_public(
            name=name,
            is_default=is_default,
            is_global=is_global,
            owner=owner,
            layout=layout,
            slots=parsed,
        )
        base.print_unifi_obj(liveview, ctx.obj.output_format)

    base.run(ctx, _create())


@app.command()
def update(
    ctx: typer.Context,
    liveview_id: str = ARG_LIVEVIEW_ID,
    name: str | None = typer.Option(None, "--name"),
    owner: str | None = typer.Option(None, "--owner"),
    layout: int | None = typer.Option(None, "--layout", min=1, max=26),
    slots: str | None = typer.Option(
        None, "--slots", help="JSON array of slot objects"
    ),
    is_default: bool | None = typer.Option(
        None, "--default/--no-default", show_default=False
    ),
    is_global: bool | None = typer.Option(
        None, "--global/--no-global", show_default=False
    ),
) -> None:
    """Patch an existing liveview (partial update)."""
    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if owner is not None:
        kwargs["owner"] = owner
    if layout is not None:
        kwargs["layout"] = layout
    if slots is not None:
        kwargs["slots"] = _parse_slots(slots)
    if is_default is not None:
        kwargs["is_default"] = is_default
    if is_global is not None:
        kwargs["is_global"] = is_global
    if not kwargs:
        typer.secho("At least one field must be provided", fg="red")
        raise typer.Exit(1)

    async def _update() -> None:
        try:
            liveview = await ctx.obj.protect.update_liveview_public(
                liveview_id, **kwargs
            )
        except BadRequest as err:
            typer.secho(str(err), fg="red")
            raise typer.Exit(1) from err
        base.print_unifi_obj(liveview, ctx.obj.output_format)

    base.run(ctx, _update())
