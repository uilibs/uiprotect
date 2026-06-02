from __future__ import annotations

from pathlib import Path

import typer

from ..cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_FILE_TYPE = typer.Argument(..., help="Device asset file type, e.g. 'animations'")
ARG_FILE_PATH = typer.Argument(
    ...,
    help="Path to the file to upload",
    exists=True,
    dir_okay=False,
    readable=True,
)

OPTION_FILE_TYPE_LIST = typer.Option(
    "animations",
    "--file-type",
    "-t",
    help="Device asset file type to list (default: animations)",
)
OPTION_CONTENT_TYPE = typer.Option(
    "image/png",
    "--content-type",
    "-c",
    help="MIME content type of the uploaded file",
)
OPTION_ORIGINAL_NAME = typer.Option(
    None,
    "--original-name",
    "-n",
    help="Original file name reported to the server (defaults to the file's basename)",
)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Device asset file commands (Public API)."""


@app.command("list")
def list_files(
    ctx: typer.Context,
    file_type: str = OPTION_FILE_TYPE_LIST,
) -> None:
    """List uploaded device asset files of the given type."""

    async def _fetch() -> None:
        items = await ctx.obj.protect.get_files_public(file_type)
        base.print_unifi_list(items, ctx.obj.output_format)

    base.run(ctx, _fetch())


@app.command()
def upload(
    ctx: typer.Context,
    file_type: str = ARG_FILE_TYPE,
    path: Path = ARG_FILE_PATH,
    content_type: str = OPTION_CONTENT_TYPE,
    original_name: str | None = OPTION_ORIGINAL_NAME,
) -> None:
    """Upload a device asset file."""
    payload = path.read_bytes()
    name = original_name if original_name is not None else path.name

    async def _upload() -> None:
        obj = await ctx.obj.protect.upload_file_public(
            file_type,
            payload,
            original_name=name,
            content_type=content_type,
        )
        base.print_unifi_obj(obj, ctx.obj.output_format)

    base.run(ctx, _upload())
