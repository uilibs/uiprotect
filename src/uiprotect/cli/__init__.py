from __future__ import annotations

import asyncio
import base64
import logging
import sys
from pathlib import Path
from typing import cast

import orjson
import typer
from rich.progress import track

from uiprotect.api import MetaInfo, ProtectApiClient

from ..data import WSPacket
from ..exceptions import BadRequest
from ..test_util import SampleDataGenerator
from ..utils import get_local_timezone, run_async
from ..utils import profile_ws as profile_ws_job
from . import base
from .aiports import app as aiports_app
from .arm import app as arm_app
from .base import CliContext, OutputFormatEnum
from .bridges import app as bridges_app
from .cameras import app as camera_app
from .chimes import app as chime_app
from .events import app as event_app
from .files_public import app as files_public_app
from .fobs import app as fob_app
from .lights import app as light_app
from .link_stations import app as link_station_app
from .liveviews import app as liveview_app
from .nvr import app as nvr_app
from .relays import app as relay_app
from .sensors import app as sensor_app
from .sirens import app as siren_app
from .speakers import app as speaker_app
from .ulp_users_public import app as ulp_users_public_app
from .users_public import app as users_public_app
from .viewers import app as viewer_app
from .viewers_public import app as viewer_public_app

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

_PUBLIC_ONLY_HELP = (
    "Omit both (and pass --api-key) to run against the Public Integration "
    "API only; commands with no public equivalent are then unavailable."
)

OPTION_USERNAME = typer.Option(
    None,
    "--username",
    "-U",
    help=f"UniFi Protect username. {_PUBLIC_ONLY_HELP}",
    envvar="UFP_USERNAME",
)
OPTION_PASSWORD = typer.Option(
    None,
    "--password",
    "-P",
    help=f"UniFi Protect password. {_PUBLIC_ONLY_HELP}",
    hide_input=True,
    envvar="UFP_PASSWORD",
)
OPTION_API_KEY = typer.Option(
    None,
    "--api-key",
    "-k",
    help="UniFi Protect API key (required for public API operations)",
    envvar="UFP_API_KEY",
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
OPTION_VERIFY_SSL = typer.Option(
    True,
    "--verify-ssl/--no-verify-ssl",
    help="Verify SSL certificate. Disable for self-signed certificates.",
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
app.add_typer(light_app, name="lights")
app.add_typer(sensor_app, name="sensors")
app.add_typer(viewer_app, name="viewers")
app.add_typer(viewer_public_app, name="viewers-public")
app.add_typer(aiports_app, name="aiports")
app.add_typer(siren_app, name="sirens")
app.add_typer(relay_app, name="relays")
app.add_typer(fob_app, name="fobs")
app.add_typer(speaker_app, name="speakers")
app.add_typer(link_station_app, name="link-stations")
app.add_typer(bridges_app, name="bridges")
app.add_typer(users_public_app, name="users-public")
app.add_typer(ulp_users_public_app, name="ulp-users-public")
app.add_typer(files_public_app, name="files-public")
app.add_typer(arm_app, name="arm")

if backup_app is not None:
    app.add_typer(backup_app, name="backup")


@app.callback()
def main(
    ctx: typer.Context,
    username: str | None = OPTION_USERNAME,
    password: str | None = OPTION_PASSWORD,
    api_key: str | None = OPTION_API_KEY,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify_ssl: bool = OPTION_VERIFY_SSL,
    output_format: OutputFormatEnum = OPTION_OUT_FORMAT,
    include_unadopted: bool = OPTION_UNADOPTED,
) -> None:
    """UniFi Protect CLI"""
    # preload the timezone before any async code runs
    get_local_timezone()

    # The credentials decide the mode, not the subcommand: an API key without
    # a full private login runs the whole CLI against the Public Integration
    # API, with no login and no private bootstrap. Half a private credential
    # counts as none — prompting for the other half would hang a
    # non-interactive run of a command that never needed it.
    is_public_only = bool(api_key) and not (username and password)

    if not is_public_only:
        # Private API commands require username and password.
        # Prompt interactively if not supplied via option/env.
        if not username:
            username = typer.prompt("Username")
        if not password:
            password = typer.prompt("Password", hide_input=True)

    try:
        protect = (
            ProtectApiClient.public_only(
                address,
                port,
                api_key=cast("str", api_key),
                verify_ssl=verify_ssl,
                ignore_unadopted=not include_unadopted,
            )
            if is_public_only
            else ProtectApiClient(
                address,
                port,
                username=username or "",
                password=password or "",
                api_key=api_key,
                verify_ssl=verify_ssl,
                ignore_unadopted=not include_unadopted,
            )
        )
    except BadRequest as err:
        typer.secho(str(err), fg="red", err=True)
        raise typer.Exit(code=1) from err

    # The private bootstrap is fetched on first use (see
    # ``base.private_bootstrap``), so a command that only talks to the Public
    # Integration API never logs in.
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

    # The shell hands the client to the operator expecting a loaded bootstrap.
    base.private_bootstrap(ctx)

    # locals passed to shell
    protect = cast(
        "ProtectApiClient",
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
    output_folder: Path | None = OPTION_OUTPUT,
    do_zip: bool = OPTION_ZIP,
) -> None:
    """Generates sample data for UniFi Protect instance."""
    base.require_private_api(ctx)
    protect = cast("ProtectApiClient", ctx.obj.protect)

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
    output_path: Path | None = OPTION_OUTPUT,
) -> None:
    """Profiles Websocket messages for UniFi Protect instance."""
    base.require_private_api(ctx)
    protect = cast("ProtectApiClient", ctx.obj.protect)

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
        await protect.close_public_api_session()

    _setup_logger()

    run_async(callback())


@app.command()
def decode_ws_msg(
    ws_file: typer.FileBinaryRead = OPTION_WS_FILE,
    ws_data: str | None = ARG_WS_DATA,
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
def create_api_key(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Name for the API key"),
) -> None:
    """Create a new API key for the current user."""
    # Provisioning a key is a private-API operation: it needs a logged-in
    # session, which a public-only client does not have.
    base.require_private_api(ctx)
    protect = cast("ProtectApiClient", ctx.obj.protect)

    async def callback() -> str:
        api_key = await protect.create_api_key(name)
        await protect.close_session()
        await protect.close_public_api_session()
        return api_key

    _setup_logger()
    result = run_async(callback())
    typer.echo(result)


@app.command()
def get_meta_info(ctx: typer.Context) -> None:
    """Get metadata about the current UniFi Protect instance."""
    protect = cast("ProtectApiClient", ctx.obj.protect)

    async def callback() -> MetaInfo:
        meta = await protect.get_meta_info()
        await protect.close_session()
        await protect.close_public_api_session()
        return meta

    _setup_logger()

    result = run_async(callback())
    typer.echo(result.model_dump_json())
