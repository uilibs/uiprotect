"""
Network-free unit tests for the OpenAPI-spec fetcher.

Every network call (`urllib.request.urlopen`) is mocked; the tests pin the
portal-parsing, content-type guarding, 404 handling and version-stamping
behaviour of ``scripts/fetch_openapi.py``.
"""

from __future__ import annotations

import json
import urllib.error
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import fetch_openapi  # local import via conftest sys.path insert
import pytest

if TYPE_CHECKING:
    from pathlib import Path


class _FakeResponse:
    """Minimal stand-in for the object returned by ``urlopen`` as a context manager."""

    def __init__(
        self,
        body: bytes = b"",
        content_type: str = "application/json",
        url: str = "",
    ) -> None:
        self._body = body
        self._url = url
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


@contextmanager
def _urlopen_returning(response: _FakeResponse) -> Any:
    yield response


@pytest.mark.parametrize(
    "url",
    [
        "https://developer.ui.com/protect/v7.3.68/gettingstarted",
        "https://developer.ui.com/protect/v7.3.68",
    ],
)
def test_latest_portal_version_follows_redirect(url: str) -> None:
    """The latest version is read from the portal index's redirect target."""
    with patch(
        "fetch_openapi.urllib.request.urlopen",
        return_value=_urlopen_returning(_FakeResponse(url=url)),
    ):
        assert fetch_openapi.latest_portal_version() == "7.3.68"


def test_latest_portal_version_raises_without_versioned_redirect() -> None:
    """An unversioned redirect target surfaces as a RuntimeError naming the URL."""
    url = "https://developer.ui.com/protect/gettingstarted"
    with (
        patch(
            "fetch_openapi.urllib.request.urlopen",
            return_value=_urlopen_returning(_FakeResponse(url=url)),
        ),
        pytest.raises(RuntimeError, match="gettingstarted"),
    ):
        fetch_openapi.latest_portal_version()


@pytest.mark.parametrize(
    ("requested", "expected", "portal_calls"),
    [(None, "7.3.68", 1), ("7.3.56", "7.3.56", 0), ("v7.3.56", "7.3.56", 0)],
)
def test_resolve_version(
    requested: str | None, expected: str, portal_calls: int
) -> None:
    """An explicit version is normalised offline; none resolves the portal latest."""
    with patch("fetch_openapi.latest_portal_version", return_value="7.3.68") as latest:
        assert fetch_openapi.resolve_version(requested) == expected
    assert latest.call_count == portal_calls


def test_fetch_from_portal_returns_json_bytes() -> None:
    """`_fetch_from_portal` returns the raw JSON body on a JSON response."""
    body = b'{"openapi": "3.0.0"}'
    with patch(
        "fetch_openapi.urllib.request.urlopen",
        return_value=_urlopen_returning(_FakeResponse(body)),
    ):
        assert fetch_openapi._fetch_from_portal("v7.1.87") == body


def test_fetch_from_portal_rejects_non_json() -> None:
    """`_fetch_from_portal` raises when the portal returns non-JSON content."""
    with (
        patch(
            "fetch_openapi.urllib.request.urlopen",
            return_value=_urlopen_returning(
                _FakeResponse(b"<html>", content_type="text/html")
            ),
        ),
        pytest.raises(RuntimeError, match="Unexpected content type"),
    ):
        fetch_openapi._fetch_from_portal("7.1.87")


def test_fetch_from_portal_404_hints_at_fallback() -> None:
    """A 404 from the portal surfaces a hint to retry with --from-deb."""
    err = urllib.error.HTTPError(url="x", code=404, msg="Not Found", hdrs=None, fp=None)
    with (
        patch("fetch_openapi.urllib.request.urlopen", side_effect=err),
        pytest.raises(RuntimeError, match="--from-deb"),
    ):
        fetch_openapi._fetch_from_portal("9.9.9")


def test_fetch_from_portal_reraises_other_http_errors() -> None:
    """Non-404 HTTP errors propagate unchanged."""
    err = urllib.error.HTTPError(
        url="x", code=500, msg="Server Error", hdrs=None, fp=None
    )
    with (
        patch("fetch_openapi.urllib.request.urlopen", side_effect=err),
        pytest.raises(urllib.error.HTTPError),
    ):
        fetch_openapi._fetch_from_portal("7.1.87")


def test_fetch_spec_stamps_placeholder_version(tmp_path: Path) -> None:
    """The portal's placeholder `info.version` is replaced with the resolved one."""
    out = tmp_path / "integration.json"
    spec = {"info": {"version": "0.0.0"}, "paths": {"/x": {}}}
    with (
        patch("fetch_openapi.latest_portal_version", return_value="7.3.68"),
        patch(
            "fetch_openapi._fetch_from_portal",
            return_value=json.dumps(spec).encode(),
        ),
    ):
        fetch_openapi.fetch_spec(output=out)

    written = json.loads(out.read_bytes())
    assert written["info"]["version"] == "7.3.68"


@pytest.mark.parametrize(
    ("requested", "expected"), [(None, "7.3.68"), ("7.3.56", "7.3.56")]
)
def test_fetch_spec_from_portal_skips_firmware_api(
    tmp_path: Path, requested: str | None, expected: str
) -> None:
    """A portal fetch never queries the firmware API, even for a portal-only version."""
    spec = {"info": {"version": "0.0.0"}, "paths": {}}
    with (
        patch("fetch_openapi.latest_portal_version", return_value="7.3.68"),
        patch("fetch_openapi._query_firmware") as firmware,
        patch(
            "fetch_openapi._fetch_from_portal",
            return_value=json.dumps(spec).encode(),
        ) as portal,
    ):
        fetch_openapi.fetch_spec(requested, tmp_path / "integration.json")

    firmware.assert_not_called()
    portal.assert_called_once_with(expected)


def test_fetch_spec_from_deb_preserves_real_version(tmp_path: Path) -> None:
    """The deb path keeps a real `info.version` and does not fetch the portal."""
    out = tmp_path / "integration.json"
    spec = {"info": {"version": "7.1.87"}, "paths": {}}
    with (
        patch(
            "fetch_openapi._query_firmware",
            return_value=("deb-url", "7.1.87"),
        ),
        patch(
            "fetch_openapi._fetch_from_deb",
            return_value=json.dumps(spec).encode(),
        ) as deb,
        patch("fetch_openapi._fetch_from_portal") as portal,
    ):
        fetch_openapi.fetch_spec(output=out, from_deb=True)

    deb.assert_called_once()
    portal.assert_not_called()
    assert json.loads(out.read_bytes())["info"]["version"] == "7.1.87"


def _firmware_payload(version: str) -> bytes:
    return json.dumps(
        {
            "_embedded": {
                "firmware": [
                    {"_links": {"data": {"href": "deb-url"}}, "version": version}
                ]
            }
        }
    ).encode()


@pytest.mark.parametrize("wire", ["v7.2.105", "7.2.105"])
def test_query_firmware_returns_bare_version(wire: str) -> None:
    """`_query_firmware` normalises the firmware API's version to MAJOR.MINOR.PATCH."""
    with patch(
        "fetch_openapi.urllib.request.urlopen",
        return_value=_urlopen_returning(_FakeResponse(_firmware_payload(wire))),
    ):
        assert fetch_openapi._query_firmware(None) == ("deb-url", "7.2.105")


def test_query_firmware_rejects_malformed_version() -> None:
    """A requested version that is not MAJOR.MINOR.PATCH is rejected before any call."""
    with (
        patch("fetch_openapi.urllib.request.urlopen") as urlopen,
        pytest.raises(ValueError, match=r"MAJOR\.MINOR\.PATCH"),
    ):
        fetch_openapi._query_firmware("7.2")
    urlopen.assert_not_called()


def test_query_firmware_raises_when_no_firmware_matches() -> None:
    """An empty firmware list surfaces as a RuntimeError naming the version."""
    empty = json.dumps({"_embedded": {"firmware": []}}).encode()
    with (
        patch(
            "fetch_openapi.urllib.request.urlopen",
            return_value=_urlopen_returning(_FakeResponse(empty)),
        ),
        pytest.raises(RuntimeError, match="No firmware found"),
    ):
        fetch_openapi._query_firmware("7.2.105")
