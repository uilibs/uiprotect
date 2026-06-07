#!/usr/bin/env python3
"""
Fetch the UniFi Protect integration OpenAPI spec from the official deb package.

Writes openapi/integration.json (gitignored).  Requires only stdlib.
"""

from __future__ import annotations

import argparse
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

import orjson

FIRMWARE_API = "https://fw-update.ubnt.com/api/v2/firmware-latest"
SPEC_MEMBER = "./usr/share/unifi-protect/app/fixtures/integration/openapi.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "openapi" / "integration.json"


def fetch_spec(version: str | None = None, output: Path = DEFAULT_OUTPUT) -> None:
    """Download the unifi-protect deb and extract the integration OpenAPI spec."""
    url, ver = _get_download_url(version)
    print(f"unifi-protect {ver}", file=sys.stderr)
    print(f"Downloading (~74 MB): {url}", file=sys.stderr)

    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        deb_bytes = resp.read()

    print("Extracting spec …", file=sys.stderr)
    spec_bytes = _extract_from_deb(deb_bytes)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(spec_bytes)
    spec = orjson.loads(spec_bytes)
    print(
        f"Written {output}  "
        f"(version {spec['info']['version']}, "
        f"{len(spec['paths'])} paths)",
        file=sys.stderr,
    )


def _get_download_url(version: str | None) -> tuple[str, str]:
    """Return (download_url, version_string) for the requested protect version."""
    params = [
        "filter=eq~~product~~unifi-protect",
        "filter=eq~~platform~~uos-deb11-arm64",
    ]
    if version:
        parts = version.split(".")
        if len(parts) != 3:
            msg = f"version must be MAJOR.MINOR.PATCH, got {version!r}"
            raise ValueError(msg)
        major, minor, patch = parts
        params += [
            f"filter=eq~~version_major~~{major}",
            f"filter=eq~~version_minor~~{minor}",
            f"filter=eq~~version_patch~~{patch}",
        ]
    else:
        params.append("filter=eq~~channel~~release")

    url = f"{FIRMWARE_API}?{'&'.join(params)}"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        data = orjson.loads(resp.read())

    entries = data["_embedded"]["firmware"]
    if not entries:
        msg = f"No firmware found for version={version!r}"
        raise RuntimeError(msg)

    fw = entries[0]
    return fw["_links"]["data"]["href"], fw["version"]


def _extract_from_deb(deb_bytes: bytes) -> bytes:
    """Extract the integration openapi.json from a .deb (ar archive)."""
    if deb_bytes[:8] != b"!<arch>\n":
        msg = "Not an ar archive"
        raise ValueError(msg)

    offset = 8
    while offset < len(deb_bytes):
        name = deb_bytes[offset : offset + 16].decode("ascii").rstrip()
        size = int(deb_bytes[offset + 48 : offset + 58].decode("ascii").strip())
        offset += 60  # ar header is exactly 60 bytes
        member_data = deb_bytes[offset : offset + size]
        offset += size + (size % 2)  # ar pads members to even byte boundary

        if name.startswith("data.tar"):
            with tarfile.open(fileobj=io.BytesIO(member_data)) as tf:
                f = tf.extractfile(tf.getmember(SPEC_MEMBER))
                if f is None:
                    msg = f"{SPEC_MEMBER!r} is not a regular file in deb"
                    raise RuntimeError(msg)
                return f.read()

    msg = f"{SPEC_MEMBER!r} not found in deb"
    raise FileNotFoundError(msg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        help="Protect version to fetch, e.g. 7.0.104 (default: latest release)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    fetch_spec(args.version, args.output)
