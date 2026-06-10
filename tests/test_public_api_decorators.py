"""Framework, registry, and signature/docstring invariants for the public-API decorators."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock

import pytest

from uiprotect._public_api import (
    _to_camel,
    public_get,
    public_patch,
    public_post,
    registry,
)
from uiprotect.api import ProtectApiClient
from uiprotect.exceptions import BadRequest


class _Model:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    @classmethod
    def from_unifi_dict(cls, **kwargs: Any) -> _Model:
        return cls(**kwargs)


class _Client:
    @public_get("/v1/things", item=_Model)
    async def list_things(self) -> list[_Model]:
        """List things."""
        raise NotImplementedError

    @public_get("/v1/things/{thing_id}", returns=_Model)
    async def get_thing(self, thing_id: str) -> _Model:
        """Get a thing."""
        raise NotImplementedError

    @public_patch("/v1/things/{thing_id}", returns=_Model)
    async def update_thing(
        self,
        thing_id: str,
        *,
        name: str | None = None,
        mic_volume: int | None = None,
    ) -> _Model:
        """Update a thing."""
        raise NotImplementedError

    @public_post("/v1/things/{thing_id}/go/{slot}")
    async def go(self, thing_id: str, *, slot: int) -> None:
        """Fire and forget."""
        raise NotImplementedError


def _client() -> _Client:
    client = _Client()
    client.api_request_list = AsyncMock()  # type: ignore[method-assign]
    client.api_request_obj = AsyncMock()  # type: ignore[method-assign]
    client.api_request_raw = AsyncMock()  # type: ignore[method-assign]
    return client


def test_to_camel() -> None:
    assert _to_camel("name") == "name"
    assert _to_camel("mic_volume") == "micVolume"
    assert _to_camel("is_mic_enabled") == "isMicEnabled"


@pytest.mark.asyncio()
async def test_list_dispatch_and_model_construction() -> None:
    client = _client()
    client.api_request_list.return_value = [{"id": "1"}, {"id": "2"}]

    result = await client.list_things()

    client.api_request_list.assert_called_once_with(url="/v1/things", public_api=True)
    assert [m.kwargs for m in result] == [
        {"id": "1", "api": client},
        {"id": "2", "api": client},
    ]


@pytest.mark.asyncio()
async def test_list_empty_is_empty_list() -> None:
    client = _client()
    client.api_request_list.return_value = []
    assert await client.list_things() == []


@pytest.mark.asyncio()
async def test_obj_get_binds_path_placeholder() -> None:
    client = _client()
    client.api_request_obj.return_value = {"id": "abc"}

    result = await client.get_thing("abc")

    client.api_request_obj.assert_called_once_with(
        url="/v1/things/abc", public_api=True
    )
    assert result.kwargs == {"id": "abc", "api": client}


@pytest.mark.asyncio()
async def test_patch_assembles_camel_body_and_drops_none() -> None:
    client = _client()
    client.api_request_obj.return_value = {"id": "x"}

    await client.update_thing("x", name="hi", mic_volume=5)

    client.api_request_obj.assert_called_once_with(
        url="/v1/things/x",
        method="patch",
        json={"name": "hi", "micVolume": 5},
        public_api=True,
    )


@pytest.mark.asyncio()
async def test_patch_path_param_not_emitted_into_body() -> None:
    client = _client()
    client.api_request_obj.return_value = {"id": "x"}

    await client.update_thing("x", name="only")

    _, kwargs = client.api_request_obj.call_args
    assert "thingId" not in kwargs["json"]
    assert kwargs["json"] == {"name": "only"}


@pytest.mark.asyncio()
async def test_empty_patch_body_raises_bad_request() -> None:
    client = _client()
    with pytest.raises(BadRequest, match="At least one parameter must be provided"):
        await client.update_thing("x")
    client.api_request_obj.assert_not_called()


@pytest.mark.asyncio()
async def test_post_fire_and_forget_binds_all_path_params() -> None:
    client = _client()

    result = await client.go("cam", slot=3)

    assert result is None
    client.api_request_raw.assert_called_once_with(
        url="/v1/things/cam/go/3", method="post", public_api=True
    )


def test_duplicate_endpoint_raises_at_decoration() -> None:
    with pytest.raises(RuntimeError, match="Duplicate public endpoint"):

        class _Dup:
            @public_get("/v1/dup", returns=_Model)
            async def a(self) -> _Model:
                """First."""
                raise NotImplementedError

            @public_get("/v1/dup", returns=_Model)
            async def b(self) -> _Model:
                """Second."""
                raise NotImplementedError


# ---------------------------------------------------------------------------
# Invariants against the real client
# ---------------------------------------------------------------------------

_REGISTRY = registry.for_class("ProtectApiClient")
_REGISTERED_METHODS = sorted(_REGISTRY.values())


def test_registry_is_non_empty_and_covers_converted_endpoints() -> None:
    assert len(_REGISTRY) == 34
    # paths are unique per (verb, path) key by construction
    assert len(set(_REGISTRY)) == len(_REGISTRY)


def test_registry_all_endpoints_includes_client() -> None:
    assert "ProtectApiClient" in registry.all_endpoints()


@pytest.mark.parametrize("method_name", _REGISTERED_METHODS)
def test_each_registered_method_appears_exactly_once(method_name: str) -> None:
    assert _REGISTERED_METHODS.count(method_name) == 1


@pytest.mark.parametrize(
    "excluded",
    [
        "update_camera_public",
        "update_light_public",
        "update_viewer_public",
        "get_bridge_public",
        "get_viewer_public",
        "get_liveview_public",
        "send_alarm_webhook_public",
        "get_alarm_hubs_public",
        "update_public",
    ],
)
def test_hand_written_exceptions_absent_from_registry(excluded: str) -> None:
    assert excluded not in _REGISTERED_METHODS


def test_signature_preserved() -> None:
    # ``from __future__ import annotations`` keeps annotations as strings, so
    # compare structurally rather than against a fully-resolved repr.
    sig = inspect.signature(ProtectApiClient.get_camera_public)
    assert list(sig.parameters) == ["self", "camera_id"]
    assert sig.parameters["camera_id"].annotation == "str"
    assert sig.return_annotation == "PublicCamera"


@pytest.mark.parametrize("method_name", _REGISTERED_METHODS)
def test_decorated_method_has_docstring(method_name: str) -> None:
    doc = getattr(ProtectApiClient, method_name).__doc__
    assert doc is not None and doc.strip()
