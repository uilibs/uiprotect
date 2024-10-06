"""Compat for external lib versions."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functools import cached_property
else:
    try:
        from propcache.api import cached_property
    except ImportError:
        from propcache import cached_property

__all__ = ("cached_property",)
