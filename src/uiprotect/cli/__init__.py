from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import ssl
import sys
from pathlib import Path
from typing import cast

import aiohttp
import orjson
import typer
from rich.progress import track

from uiprotect.api import MetaInfo, ProtectApiClient

from ..data import WSPacket
from ..exceptions import BadRequest
from ..test_util import SampleDataGenerator
from ..utils import get_local_timezone, run_async
from ..utils import profile_ws as profile_ws_job
from .aiports import app as aiports_app
from .arm import app as arm_app
from .base import CliContext, OutputFormatEnum
from .bridges import app as bridges_app
from .cameras import app as camera_app
from .chimes import app as chime_app
from .doorlocks import app as doorlock_app
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

# Sub-apps that only use the public API (API key) and do not need username/password
_PUBLIC_ONLY_COMMAND_NAMES: tuple[str, ...] = (
    "sirens",
    "relays",
    "fobs",
    "speakers",
    "link-stations",
    "liveviews",
    "bridges",
    "viewers-public",
    "users-public",
    "ulp-users-public",
    "files-public",
    "arm",
)
_PUBLIC_ONLY_COMMANDS: frozenset[str] = frozenset(_PUBLIC_ONLY_COMMAND_NAMES)
_PUBLIC_ONLY_COMMANDS_HELP: str = ", ".join(_PUBLIC_ONLY_COMMAND_NAMES)

OPTION_USERNAME = typer.Option(
    None,
    "--username",
    "-U",
    help=(
        "UniFi Protect username (not required for public API commands: "
        f"{_PUBLIC_ONLY_COMMANDS_HELP})"
    ),
    envvar="UFP_USERNAME",
)
OPTION_PASSWORD = typer.Option(
    None,
    "--password",
    "-P",
    help=(
        "UniFi Protect password (not required for public API commands: "
        f"{_PUBLIC_ONLY_COMMANDS_HELP})"
    ),
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
app.add_typer(doorlock_app, name="doorlocks")
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


def _is_ssl_error(exc: BaseException) -> bool:
    """Check if an exception is an SSL certificate verification error."""
    if isinstance(exc, aiohttp.ClientConnectorCertificateError):
        return True
    if isinstance(exc, aiohttp.ClientConnectorSSLError):
        return True
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    # Check nested exceptions
    if exc.__cause__ is not None:
        return _is_ssl_error(exc.__cause__)
    return False


def _get_cert_fingerprint(host: str, port: int) -> str | None:
    """Return the SHA-256 fingerprint of the server's leaf certificate, or None."""
    try:
        pem = ssl.get_server_certificate((host, port), timeout=5)
    except (OSError, ssl.SSLError):
        return None
    if not pem:
        return None
    der = ssl.PEM_cert_to_DER_cert(pem)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


async def _connect_and_bootstrap(protect: ProtectApiClient) -> None:
    """Connect to the Protect API and fetch bootstrap data."""
    protect._bootstrap = await protect.get_bootstrap()
    await protect.close_session()
    await protect.close_public_api_session()


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

    is_public_only = ctx.invoked_subcommand in _PUBLIC_ONLY_COMMANDS

    if not is_public_only:
        # Private API commands require username and password.
        # Prompt interactively if not supplied via option/env.
        if not username:
            username = typer.prompt("Username")
        if not password:
            password = typer.prompt("Password", hide_input=True)

    try:
        protect = ProtectApiClient(
            address,
            port,
            username=None if is_public_only else (username or ""),
            password=None if is_public_only else (password or ""),
            api_key=api_key,
            verify_ssl=verify_ssl,
            ignore_unadopted=not include_unadopted,
        )
    except BadRequest as err:
        typer.secho(str(err), fg="red", err=True)
        raise typer.Exit(code=1) from err

    async def close_protect() -> None:
        """Close the Protect API client sessions."""
        await protect.close_session()
        await protect.close_public_api_session()

    if not is_public_only:
        try:
            run_async(_connect_and_bootstrap(protect))
        except Exception as exc:
            # Always close the session on error to avoid "Unclosed client session" warning
            run_async(close_protect())

            if verify_ssl and _is_ssl_error(exc):
                typer.secho(
                    f"SSL certificate verification failed for {address}:{port}.",
                    fg="red",
                    err=True,
                )
                fingerprint = _get_cert_fingerprint(address, port)
                if fingerprint:
                    typer.secho(
                        f"  Server certificate SHA-256: {fingerprint}",
                        err=True,
                    )
                typer.secho(
                    "Refusing to retry with verification disabled — sending "
                    "credentials over an unauthenticated TLS channel would "
                    "expose them to any on-path attacker.",
                    fg="red",
                    err=True,
                )
                typer.secho(
                    "If you have verified the fingerprint above out-of-band "
                    "(e.g. via the UniFi Protect console), rerun the command "
                    "with --no-verify-ssl to skip verification for this "
                    "invocation.",
                    err=True,
                )
                raise typer.Exit(code=1) from exc
            typer.secho(f"Connection failed: {exc}", fg="red")
            raise typer.Exit(code=1) from exc

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
