"""Unofficial UniFi Protect Python API and Command Line Interface."""

from __future__ import annotations

from .api import ProtectApiClient
from .exceptions import Invalid, NotAuthorized, NvrError
from .utils import (
    get_nested_attr,
    get_nested_attr_as_bool,
    get_top_level_attr,
    get_top_level_attr_as_bool,
    make_enabled_getter,
    make_required_getter,
    make_value_getter,
)

__all__ = [
    "Invalid",
    "NotAuthorized",
    "NvrError",
    "ProtectApiClient",
    "get_nested_attr",
    "get_nested_attr_as_bool",
    "get_top_level_attr",
    "get_top_level_attr_as_bool",
    "make_value_getter",
    "make_enabled_getter",
    "make_required_getter",
]
