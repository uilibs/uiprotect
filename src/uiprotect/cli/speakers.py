from __future__ import annotations

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_SPEAKER_ID = typer.Argument(..., help="Speaker ID")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Speaker commands (Public API)."""


@app.command("list")
def list_speakers(ctx: typer.Context) -> None:
    """List all speakers."""

    async def _fetch() -> None:
        speakers = await ctx.obj.protect.get_speakers_public()
        base.print_unifi_list(speakers)

    base.run(ctx, _fetch())


@app.command()
def show(ctx: typer.Context, speaker_id: str = ARG_SPEAKER_ID) -> None:
    """Show details for a specific speaker."""

    async def _fetch() -> None:
        speaker = await ctx.obj.protect.get_speaker_public(speaker_id)
        base.print_unifi_obj(speaker, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def set_name(
    ctx: typer.Context,
    speaker_id: str = ARG_SPEAKER_ID,
    name: str = typer.Argument(..., help="New name for the speaker"),
) -> None:
    """Rename a speaker."""
    base.run(ctx, ctx.obj.protect.update_speaker_public(speaker_id, name=name))


@app.command()
def set_volume(
    ctx: typer.Context,
    speaker_id: str = ARG_SPEAKER_ID,
    volume: int = typer.Argument(..., help="Volume (0-100)", min=0, max=100),
) -> None:
    """Set the speaker volume."""
    base.run(ctx, ctx.obj.protect.update_speaker_public(speaker_id, volume=volume))


@app.command()
def set_mic_volume(
    ctx: typer.Context,
    speaker_id: str = ARG_SPEAKER_ID,
    mic_volume: int = typer.Argument(..., help="Mic volume (0-100)", min=0, max=100),
) -> None:
    """Set the speaker microphone volume."""
    base.run(
        ctx,
        ctx.obj.protect.update_speaker_public(speaker_id, mic_volume=mic_volume),
    )


@app.command()
def set_mic_enabled(
    ctx: typer.Context,
    speaker_id: str = ARG_SPEAKER_ID,
    enabled: bool = typer.Argument(..., help="Enable or disable the microphone"),
) -> None:
    """Enable or disable the speaker microphone."""
    base.run(
        ctx,
        ctx.obj.protect.update_speaker_public(speaker_id, is_mic_enabled=enabled),
    )


@app.command()
def test_sound(
    ctx: typer.Context,
    speaker_id: str = ARG_SPEAKER_ID,  # noqa: PT028  # typer CLI argument, not a pytest test
    volume: int | None = typer.Option(  # noqa: PT028  # typer CLI argument, not a pytest test
        None,
        "--volume",
        "-v",
        help="Test volume (0-100). Omit to use the current speaker volume.",
        min=0,
        max=100,
    ),
) -> None:
    """Play a test sound on a speaker."""
    base.run(
        ctx,
        ctx.obj.protect.test_speaker_sound_public(speaker_id, volume=volume),
    )
