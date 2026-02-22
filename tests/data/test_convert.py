"""Tests for uiprotect.data.convert - 100% coverage."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

from tests.conftest import TEST_CAMERA_EXISTS
from uiprotect.data.convert import (
    create_from_unifi_dict,
    get_klass_from_dict,
    list_from_unifi_list,
)
from uiprotect.data.devices import Camera
from uiprotect.data.types import ModelType
from uiprotect.exceptions import DataDecodeError

if TYPE_CHECKING:
    from uiprotect import ProtectApiClient

_skip_no_camera = pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")


class TestGetKlassFromDict:
    """Tests for get_klass_from_dict."""

    def test_no_model_key_raises(self) -> None:
        with pytest.raises(DataDecodeError, match="No modelKey"):
            get_klass_from_dict({})

    def test_unknown_model_key_raises(self) -> None:
        with pytest.raises(DataDecodeError, match="Unknown modelKey"):
            get_klass_from_dict({"modelKey": "totallyFakeModel"})

    def test_known_model_key_returns_class(self) -> None:
        assert get_klass_from_dict({"modelKey": "camera"}) is Camera


class TestCreateFromUnifiDict:
    """Tests for create_from_unifi_dict - covers the Protect 7 modelKey injection."""

    def test_no_model_key_no_model_type_raises(self) -> None:
        """No modelKey in data and no model_type provided -> DataDecodeError."""
        with pytest.raises(DataDecodeError, match="No modelKey"):
            create_from_unifi_dict({"id": "test123"})

    @_skip_no_camera
    def test_model_type_with_missing_model_key(self, camera: dict[str, Any]) -> None:
        """Protect 7+: modelKey missing from data, model_type provided -> succeed without mutating input."""
        data = deepcopy(camera)
        data.pop("modelKey", None)

        obj = create_from_unifi_dict(data, model_type=ModelType.CAMERA)

        assert isinstance(obj, Camera)
        assert "modelKey" not in data

    @_skip_no_camera
    def test_model_type_preserves_existing_model_key(
        self, camera: dict[str, Any]
    ) -> None:
        """Protect 6: modelKey already present -> don't overwrite, resolve klass from model_type."""
        data = deepcopy(camera)

        obj = create_from_unifi_dict(data, model_type=ModelType.CAMERA)

        assert isinstance(obj, Camera)
        assert data["modelKey"] == "camera"

    @_skip_no_camera
    def test_explicit_klass_skips_resolution(self, camera: dict[str, Any]) -> None:
        """When klass is explicitly provided, model_type klass resolution is skipped."""
        data = deepcopy(camera)

        obj = create_from_unifi_dict(data, klass=Camera)

        assert isinstance(obj, Camera)

    @_skip_no_camera
    def test_model_type_with_explicit_klass(self, camera: dict[str, Any]) -> None:
        """model_type + klass both provided -> succeeds without mutating input."""
        data = deepcopy(camera)
        data.pop("modelKey", None)

        obj = create_from_unifi_dict(data, klass=Camera, model_type=ModelType.CAMERA)

        assert isinstance(obj, Camera)
        assert "modelKey" not in data

    @_skip_no_camera
    def test_fallback_to_get_klass_from_dict(self, camera: dict[str, Any]) -> None:
        """No model_type, no klass -> fall back to get_klass_from_dict."""
        obj = create_from_unifi_dict(deepcopy(camera))

        assert isinstance(obj, Camera)


class TestListFromUnifiList:
    """Tests for list_from_unifi_list."""

    @_skip_no_camera
    def test_converts_list(
        self, protect_client: ProtectApiClient, camera: dict[str, Any]
    ) -> None:
        result = list_from_unifi_list(
            protect_client, [deepcopy(camera), deepcopy(camera)]
        )

        assert len(result) == 2
        assert all(isinstance(obj, Camera) for obj in result)
