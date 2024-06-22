from __future__ import annotations

import asyncio
import base64
import logging
import sys
from pathlib import Path
from typing import Optional, cast

import orjson
import typer
from rich.progress import track

from uiprotect.api import ProtectApiClient

from ..data import Version, WSPacket
from ..test_util import SampleDataGenerator
from ..utils import RELEASE_CACHE, get_local_timezone, run_async
from ..utils import profile_ws as profile_ws_job
from .base import CliContext, OutputFormatEnum
from .cameras import app as camera_app
from .chimes import app as chime_app
from .doorlocks import app as doorlock_app
from .events import app as event_app
from .lights import app as light_app
from .liveviews import app as liveview_app
from .nvr import app as nvr_app
from .sensors import app as sensor_app
from .viewers import app as viewer_app

try:
    from .backup import app as backup_app
except ImportError:
    backup_app = None  # type: ignore[assignment]

_LOGGER = logging.getLogger("uiprotect")

try:
    from IPython import embed
    from termcolor import colored
    from traitlets.config import get_config
except ImportError:
    embed = termcolor = get_config = None  # type: ignore[assignment]

OPTION_USERNAME = typer.Option(
    ...,
    "--username",
    "-U",
    help="UniFi Protect username",
    prompt=True,
    envvar="UFP_USERNAME",
)
OPTION_PASSWORD = typer.Option(
    ...,
    "--password",
    "-P",
    help="UniFi Protect password",
    prompt=True,
    hide_input=True,
    envvar="UFP_PASSWORD",
)
OPTION_ADDRESS = typer.Option(
    ...,
    "--address",
    "-a",
    prompt=True,
    help="UniFi Protect IP address or hostname",
    envvar="UFP_ADDRESS",
)
OPTION_PORT = typer.Option(
    443,
    "--port",
    "-p",
    help="UniFi Protect Port",
    envvar="UFP_PORT",
)
OPTION_SECONDS = typer.Option(15, "--seconds", "-s", help="Seconds to pull events")
OPTION_VERIFY = typer.Option(
    True,
    "--no-verify",
    help="Verify SSL",
    envvar="UFP_SSL_VERIFY",
)
OPTION_ANON = typer.Option(True, "--actual", help="Do not anonymize test data")
OPTION_ZIP = typer.Option(False, "--zip", help="Zip up data after generate")
OPTION_WAIT = typer.Option(
    30,
    "--wait",
    "-w",
    help="Time to wait for Websocket messages",
)
OPTION_OUTPUT = typer.Option(
    None,
    "--output",
    "-o",
    help="Output folder, defaults to `tests` folder one level above this file",
    envvar="UFP_SAMPLE_DIR",
)
OPTION_OUT_FORMAT = typer.Option(
    OutputFormatEnum.PLAIN,
    "--output-format",
    help="Preferred output format. Not all commands support both JSON and plain and may still output in one or the other.",
)
OPTION_WS_FILE = typer.Option(
    None,
    "--file",
    "-f",
    help="Path or raw binary Websocket message",
)
OPTION_UNADOPTED = typer.Option(
    False,
    "-u",
    "--include-unadopted",
    help="Include devices not adopted by this NVR.",
)
ARG_WS_DATA = typer.Argument(None, help="base64 encoded Websocket message")

SLEEP_INTERVAL = 2


app = typer.Typer(rich_markup_mode="rich")
app.add_typer(nvr_app, name="nvr")
app.add_typer(event_app, name="events")
app.add_typer(liveview_app, name="liveviews")
app.add_typer(camera_app, name="cameras")
app.add_typer(chime_app, name="chimes")
app.add_typer(doorlock_app, name="doorlocks")
app.add_typer(light_app, name="lights")
app.add_typer(sensor_app, name="sensors")
app.add_typer(viewer_app, name="viewers")

if backup_app is not None:
    app.add_typer(backup_app, name="backup")


@app.callback()
def main(
    ctx: typer.Context,
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
    output_format: OutputFormatEnum = OPTION_OUT_FORMAT,
    include_unadopted: bool = OPTION_UNADOPTED,
) -> None:
    """UniFi Protect CLI"""
    # preload the timezone before any async code runs
    get_local_timezone()

    protect = ProtectApiClient(
        address,
        port,
        username,
        password,
        verify_ssl=verify,
        ignore_unadopted=not include_unadopted,
    )

    async def update() -> None:
        protect._bootstrap = await protect.get_bootstrap()
        await protect.close_session()

    run_async(update())
    ctx.obj = CliContext(protect=protect, output_format=output_format)


def _setup_logger(level: int = logging.DEBUG, show_level: bool = False) -> None:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    if show_level:
        formatter = logging.Formatter("%(levelname)s: %(message)s")
        console_handler.setFormatter(formatter)
    _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.addHandler(console_handler)


async def _progress_bar(wait_time: int, label: str) -> None:
    for i in track(range(wait_time // SLEEP_INTERVAL), description=label):
        if i > 0:
            await asyncio.sleep(SLEEP_INTERVAL)


@app.command()
def shell(ctx: typer.Context) -> None:
    """
    Opens iPython shell with Protect client initialized.

    Requires the `shell` extra to also be installed.
    """
    if embed is None or colored is None:
        typer.echo("ipython and termcolor required for shell subcommand")
        sys.exit(1)

    # locals passed to shell
    protect = cast(
        ProtectApiClient,
        ctx.obj.protect,
    )
    _setup_logger(show_level=True)

    async def wait_forever() -> None:
        await protect.update()
        protect.subscribe_websocket(lambda _: None)
        while True:
            await asyncio.sleep(10)
            await protect.update()

    c = get_config()
    c.InteractiveShellEmbed.colors = "Linux"
    embed(  # type: ignore[no-untyped-call]
        header=colored("protect = ProtectApiClient(*args)", "green"),
        config=c,
        using="asyncio",
    )


@app.command()
def generate_sample_data(
    ctx: typer.Context,
    anonymize: bool = OPTION_ANON,
    wait_time: int = OPTION_WAIT,
    output_folder: Optional[Path] = OPTION_OUTPUT,
    do_zip: bool = OPTION_ZIP,
) -> None:
    """Generates sample data for UniFi Protect instance."""
    protect = cast(ProtectApiClient, ctx.obj.protect)

    if output_folder is None:
        tests_folder = Path(__file__).parent.parent / "tests"

        if not tests_folder.exists():
            typer.secho("Output folder required when not in dev-mode", fg="red")
            sys.exit(1)
        output_folder = (tests_folder / "sample_data").absolute()

    def log(msg: str) -> None:
        typer.echo(msg)

    def log_warning(msg: str) -> None:
        typer.secho(msg, fg="yellow")

    SampleDataGenerator(
        protect,
        output_folder,
        anonymize,
        wait_time,
        log=log,
        log_warning=log_warning,
        ws_progress=_progress_bar,
        do_zip=do_zip,
    ).generate()


@app.command()
def profile_ws(
    ctx: typer.Context,
    wait_time: int = OPTION_WAIT,
    output_path: Optional[Path] = OPTION_OUTPUT,
) -> None:
    """Profiles Websocket messages for UniFi Protect instance."""
    protect = cast(ProtectApiClient, ctx.obj.protect)

    async def callback() -> None:
        await protect.update()
        unsub = protect.subscribe_websocket(lambda _: None)
        await profile_ws_job(
            protect,
            wait_time,
            output_path=output_path,
            ws_progress=_progress_bar,
        )
        unsub()
        await protect.async_disconnect_ws()
        await protect.close_session()

    _setup_logger()

    run_async(callback())


@app.command()
def decode_ws_msg(
    ws_file: typer.FileBinaryRead = OPTION_WS_FILE,
    ws_data: Optional[str] = ARG_WS_DATA,
) -> None:
    """Decodes a base64 encoded UniFi Protect Websocket binary message."""
    if ws_file is None and ws_data is None:  # type: ignore[unreachable]
        typer.secho("Websocket data required", fg="red")  # type: ignore[unreachable]
        sys.exit(1)

    ws_data_raw = b""
    if ws_file is not None:
        ws_data_raw = ws_file.read()
    elif ws_data is not None:  # type: ignore[unreachable]
        ws_data_raw = base64.b64decode(ws_data.encode("utf8"))

    packet = WSPacket(ws_data_raw)
    response = {"action": packet.action_frame.data, "data": packet.data_frame.data}

    typer.echo(orjson.dumps(response).decode("utf-8"))


@app.command()
def release_versions(ctx: typer.Context) -> None:
    """Updates the release version cache on disk."""
    protect = cast(ProtectApiClient, ctx.obj.protect)

    async def callback() -> set[Version]:
        versions = await protect.get_release_versions()
        await protect.close_session()
        return versions

    _setup_logger()

    versions = run_async(callback())
    output = orjson.dumps(sorted([str(v) for v in versions]))

    Path(RELEASE_CACHE).write_bytes(output)
    typer.echo(output.decode("utf-8"))
