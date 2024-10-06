"""Compat for external lib versions."""

try:
    from propcache.api import cached_property
except ImportError:
    from propcache import cached_property

__all__ = ("cached_property",)
