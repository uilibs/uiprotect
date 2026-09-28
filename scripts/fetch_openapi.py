#!/usr/bin/env python3
"""
Fetch the UniFi Protect integration OpenAPI spec.

Primary source is Ubiquiti's developer portal
(https://developer.ui.com/protect/), which serves the spec as a small JSON
document per version. The official deb package remains available as a
fallback via ``--from-deb``.

Writes openapi/integration.json (gitignored).  Requires only stdlib.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

FIRMWARE_API = "https://fw-update.ubnt.com/api/v2/firmware-latest"
PORTAL_INDEX = "https://developer.ui.com/protect/"
PORTAL_SPEC = "https://developer.ui.com/protect/v{version}/openapi.json"
SPEC_MEMBER = "./usr/share/unifi-protect/app/fixtures/integration/openapi.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "openapi" / "integration.json"


def fetch_spec(
    version: str | None = None,
    output: Path = DEFAULT_OUTPUT,
    *,
    from_deb: bool = False,
) -> None:
    """Fetch the integration OpenAPI spec and write it to ``output``."""
    if from_deb:
        deb_url, ver = _query_firmware(version)
        print(f"unifi-protect {ver}", file=sys.stderr)
        spec_bytes = _fetch_from_deb(deb_url)
    else:
        ver = resolve_version(version)
        print(f"unifi-protect {ver}", file=sys.stderr)
        spec_bytes = _fetch_from_portal(ver)

    spec = json.loads(spec_bytes)
    # The portal spec carries a placeholder ``info.version`` ("0.0.0"); the
    # real version only lives in the URL. Stamp it so consumers can trust it.
    if spec.get("info", {}).get("version") in (None, "0.0.0"):
        spec.setdefault("info", {})["version"] = ver
        spec_bytes = json.dumps(spec, indent=2).encode() + b"\n"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(spec_bytes)
    print(
        f"Written {output}  "
        f"(version {spec['info']['version']}, "
        f"{len(spec['paths'])} paths)",
        file=sys.stderr,
    )


def _fetch_from_portal(version: str) -> bytes:
    """Download the spec from the developer portal (~400 KB)."""
    url = PORTAL_SPEC.format(version=version.removeprefix("v"))
    print(f"Downloading: {url}", file=sys.stderr)
    request = urllib.request.Request(url)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310
            if "json" not in resp.headers.get("Content-Type", ""):
                raise RuntimeError(f"Unexpected content type from {url}")
            return resp.read()
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise RuntimeError(
                f"No spec for version {version} on the developer portal; "
                "retry with --from-deb"
            ) from err
        raise


def _fetch_from_deb(url: str) -> bytes:
    """Download the unifi-protect deb (~74 MB) and extract the spec."""
    print(f"Downloading (~74 MB): {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        deb_bytes = resp.read()
    print("Extracting spec …", file=sys.stderr)
    return _extract_from_deb(deb_bytes)


def resolve_version(version: str | None = None) -> str:
    """Return ``version`` normalised, or the latest version on the developer portal."""
    return _normalize_version(version) if version else latest_portal_version()


def latest_portal_version() -> str:
    """Return the newest spec version published on the developer portal."""
    # The portal index redirects to the newest version's docs, e.g.
    # /protect/v7.3.68/gettingstarted; the page itself no longer lists versions.
    with urllib.request.urlopen(PORTAL_INDEX, timeout=60) as resp:  # noqa: S310
        url = resp.geturl()
    match = re.search(r"/protect/v(\d+\.\d+\.\d+)(?:/|$)", url)
    if match is None:
        raise RuntimeError(f"Could not find the latest version in {url}")
    return match.group(1)


def _normalize_version(version: str) -> str:
    """Return ``version`` as a bare ``MAJOR.MINOR.PATCH``, rejecting other shapes."""
    bare = version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", bare):
        raise ValueError(f"version must be MAJOR.MINOR.PATCH, got {version!r}")
    return bare


def _query_firmware(version: str | None) -> tuple[str, str]:
    """
    Return (deb_download_url, version) for the requested protect version.

    The version is normalised to a bare ``MAJOR.MINOR.PATCH``; the firmware API
    reports it ``v``-prefixed.
    """
    params = [
        "filter=eq~~product~~unifi-protect",
        "filter=eq~~platform~~uos-deb11-arm64",
    ]
    if version:
        major, minor, patch = _normalize_version(version).split(".")
        params += [
            f"filter=eq~~version_major~~{major}",
            f"filter=eq~~version_minor~~{minor}",
            f"filter=eq~~version_patch~~{patch}",
        ]
    else:
        params.append("filter=eq~~channel~~release")

    url = f"{FIRMWARE_API}?{'&'.join(params)}"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        data = json.loads(resp.read())

    entries = data["_embedded"]["firmware"]
    if not entries:
        raise RuntimeError(f"No firmware found for version={version!r}")

    fw = entries[0]
    return fw["_links"]["data"]["href"], fw["version"].removeprefix("v")


def _extract_from_deb(deb_bytes: bytes) -> bytes:
    """Extract the integration openapi.json from a .deb (ar archive)."""
    if deb_bytes[:8] != b"!<arch>\n":
        raise ValueError("Not an ar archive")

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
                    raise RuntimeError(f"{SPEC_MEMBER!r} is not a regular file in deb")
                return f.read()

    raise FileNotFoundError(f"{SPEC_MEMBER!r} not found in deb")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        help=(
            "Protect version to fetch, e.g. 7.0.104 "
            "(default: latest on the developer portal; latest release with "
            "--from-deb)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="Print the resolved version to stdout and exit (no download)",
    )
    parser.add_argument(
        "--from-deb",
        action="store_true",
        help="Extract the spec from the official deb (~74 MB) instead of the portal",
    )
    args = parser.parse_args()
    if args.print_version:
        if args.from_deb:
            print(_query_firmware(args.version)[1])
        else:
            print(resolve_version(args.version))
    else:
        fetch_spec(args.version, args.output, from_deb=args.from_deb)
