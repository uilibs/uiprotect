from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import orjson
import typer

from ..cli import base
from ..data import NVR, AnalyticsOption

app = typer.Typer(rich_markup_mode="rich")

ARG_TIMEOUT = typer.Argument(..., help="Timeout (in seconds)")
ARG_DOORBELL_MESSAGE = typer.Argument(..., help="ASCII only. Max length 30")
OPTION_ENABLE_SMART = typer.Option(
    False,
    "--enable-smart",
    help="Automatically enable smart detections",
)


@dataclass
class NVRContext(base.CliContext):
    device: NVR


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """
    NVR device CLI.

    Return NVR object without any arguments passed.
    """
    context = NVRContext(
        protect=ctx.obj.protect,
        device=ctx.obj.protect.bootstrap.nvr,
        output_format=ctx.obj.output_format,
    )
    ctx.obj = context

    if not ctx.invoked_subcommand:
        base.print_unifi_obj(context.device, ctx.obj.output_format)


app.command(name="protect-url")(base.protect_url)
app.command(name="reboot")(base.reboot)
app.command(name="set-name")(base.set_name)


@app.command()
def set_analytics(ctx: typer.Context, value: AnalyticsOption) -> None:
    """Sets analytics collection for NVR."""
    nvr: NVR = ctx.obj.device
    base.run(ctx, nvr.set_analytics(value))


@app.command()
def set_default_reset_timeout(ctx: typer.Context, timeout: int = ARG_TIMEOUT) -> None:
    """
    Sets default message reset timeout.

    This is how long until a custom message is reset back to the default message if no
    timeout is passed in when the custom message is set.
    """
    nvr: NVR = ctx.obj.device
    base.run(ctx, nvr.set_default_reset_timeout(timedelta(seconds=timeout)))
    base.print_unifi_obj(nvr.doorbell_settings, ctx.obj.output_format)


@app.command()
def set_default_doorbell_message(
    ctx: typer.Context,
    msg: str = ARG_DOORBELL_MESSAGE,
) -> None:
    """
    Sets default message for doorbell.

    This is the message that is set when a custom doorbell message times out or an empty
    one is set.
    """
    nvr: NVR = ctx.obj.device
    base.run(ctx, nvr.set_default_doorbell_message(msg))
    base.print_unifi_obj(nvr.doorbell_settings, ctx.obj.output_format)


@app.command()
def add_custom_doorbell_message(
    ctx: typer.Context,
    msg: str = ARG_DOORBELL_MESSAGE,
) -> None:
    """Adds a custom doorbell message."""
    nvr: NVR = ctx.obj.device
    base.run(ctx, nvr.add_custom_doorbell_message(msg))
    base.print_unifi_obj(nvr.doorbell_settings, ctx.obj.output_format)


@app.command()
def remove_custom_doorbell_message(
    ctx: typer.Context,
    msg: str = ARG_DOORBELL_MESSAGE,
) -> None:
    """Removes a custom doorbell message."""
    nvr: NVR = ctx.obj.device
    base.run(ctx, nvr.remove_custom_doorbell_message(msg))
    base.print_unifi_obj(nvr.doorbell_settings, ctx.obj.output_format)


@app.command()
def update(ctx: typer.Context, data: str) -> None:
    """Updates the NVR."""
    nvr: NVR = ctx.obj.device
    base.run(ctx, nvr.api.update_nvr(orjson.loads(data)))


@app.command()
def set_smart_detections(ctx: typer.Context, value: bool) -> None:
    """Set if smart detections are globally enabled or not."""
    nvr: NVR = ctx.obj.device
    base.run(ctx, nvr.set_smart_detections(value))


@app.command()
def set_face_recognition(
    ctx: typer.Context,
    value: bool,
    enable_smart: bool = OPTION_ENABLE_SMART,
) -> None:
    """Set if face detections is enabled. Requires smart detections to be enabled."""
    nvr: NVR = ctx.obj.device

    async def callback() -> None:
        if enable_smart:
            await nvr.set_smart_detections(True)
        await nvr.set_face_recognition(value)

    base.run(ctx, callback())


@app.command()
def set_license_plate_recognition(
    ctx: typer.Context,
    value: bool,
    enable_smart: bool = OPTION_ENABLE_SMART,
) -> None:
    """Set if license plate detections is enabled. Requires smart detections to be enabled."""
    nvr: NVR = ctx.obj.device

    async def callback() -> None:
        if enable_smart:
            await nvr.set_smart_detections(True)
        await nvr.set_license_plate_recognition(value)

    base.run(ctx, callback())
