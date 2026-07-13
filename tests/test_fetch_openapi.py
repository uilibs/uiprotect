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

    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body


@contextmanager
def _urlopen_returning(response: _FakeResponse) -> Any:
    yield response


def test_list_versions_parses_portal_payload() -> None:
    """`list_versions` extracts vX.Y.Z entries from the Next.js payload."""
    html = (
        'foo<script>{\\"versions\\":[{\\"version\\":\\"v7.1.87\\"},'
        '{\\"version\\":\\"v7.1.83\\"},{\\"version\\":\\"v5.3.48\\"}]}</script>bar'
    )
    with patch(
        "fetch_openapi.urllib.request.urlopen",
        return_value=_urlopen_returning(_FakeResponse(html.encode())),
    ):
        assert fetch_openapi.list_versions() == ["7.1.87", "7.1.83", "5.3.48"]


def test_list_versions_raises_when_payload_missing() -> None:
    """`list_versions` raises when the version array is absent from the page."""
    with (
        patch(
            "fetch_openapi.urllib.request.urlopen",
            return_value=_urlopen_returning(_FakeResponse(b"no versions here")),
        ),
        pytest.raises(RuntimeError, match="version list"),
    ):
        fetch_openapi.list_versions()


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
    """A 404 from the portal surfaces a hint to use --list or --from-deb."""
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
        patch(
            "fetch_openapi._query_firmware",
            return_value=("deb-url", "v7.1.87"),
        ),
        patch(
            "fetch_openapi._fetch_from_portal",
            return_value=json.dumps(spec).encode(),
        ),
    ):
        fetch_openapi.fetch_spec(output=out)

    written = json.loads(out.read_bytes())
    assert written["info"]["version"] == "7.1.87"


def test_fetch_spec_from_deb_preserves_real_version(tmp_path: Path) -> None:
    """The deb path keeps a real `info.version` and does not fetch the portal."""
    out = tmp_path / "integration.json"
    spec = {"info": {"version": "7.1.87"}, "paths": {}}
    with (
        patch(
            "fetch_openapi._query_firmware",
            return_value=("deb-url", "v7.1.87"),
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
