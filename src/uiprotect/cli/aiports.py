from __future__ import annotations

from dataclasses import dataclass

import typer

from ..api import ProtectApiClient
from ..cli import base
from ..data import AiPort

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(
    None, help="ID of AiPort device to select for subcommands"
)


@dataclass
class AiPortContext(base.CliContext):
    devices: dict[str, AiPort]
    device: AiPort | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: str | None = ARG_DEVICE_ID) -> None:
    """
    AiPort device CLI.

    Returns full list of AiPorts without any arguments passed.
    """
    protect: ProtectApiClient = ctx.obj.protect
    context = AiPortContext(
        protect=ctx.obj.protect,
        device=None,
        devices=protect.bootstrap.aiports,
        output_format=ctx.obj.output_format,
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.aiports.get(device_id)) is None:
            typer.secho("Invalid aiport ID", fg="red")
            raise typer.Exit(1)
        ctx.obj.device = device

    if not ctx.invoked_subcommand:
        if device_id in ALL_COMMANDS:
            ctx.invoke(ALL_COMMANDS[device_id], ctx)
            return

        if ctx.obj.device is not None:
            base.print_unifi_obj(ctx.obj.device, ctx.obj.output_format)
            return

        base.print_unifi_dict(ctx.obj.devices)
