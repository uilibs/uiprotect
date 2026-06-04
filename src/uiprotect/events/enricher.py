"""Identity enrichment for public events (ULP-only, read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..data.types import EventType
from .protect_event import EventIdentity, UlpUserIdentity, UnknownIdentity

if TYPE_CHECKING:
    from ..api import ProtectApiClient
    from ..data.nvr import Event


class EventEnricher:
    """Resolve ``EventIdentity`` for credential events."""

    def __init__(self, api: ProtectApiClient) -> None:
        self._api = api

    def enrich(self, raw: Event) -> EventIdentity | None:
        if raw.type is EventType.NFC_CARD_SCANNED:
            return self._resolve_nfc(raw)
        if raw.type is EventType.FINGERPRINT_IDENTIFIED:
            return self._resolve_fingerprint(raw)
        return None

    def _resolve_nfc(self, raw: Event) -> EventIdentity:
        metadata = raw.metadata
        if metadata is None or metadata.nfc is None:
            return UnknownIdentity(reason="no_metadata")
        ulp_id = metadata.nfc.ulp_id
        if ulp_id is None:
            return UnknownIdentity(reason="ulp_id_null")
        return self._lookup_ulp_user(ulp_id)

    def _resolve_fingerprint(self, raw: Event) -> EventIdentity:
        metadata = raw.metadata
        if metadata is None or metadata.fingerprint is None:
            return UnknownIdentity(reason="no_metadata")
        ulp_id = metadata.fingerprint.ulp_id
        if ulp_id is None:
            return UnknownIdentity(reason="ulp_id_null")
        return self._lookup_ulp_user(ulp_id)

    def _lookup_ulp_user(self, ulp_id: str) -> EventIdentity:
        # Pure read against the single identity store; a miss self-heals on
        # the next ``update_public`` / reconnect resync, no hot-path
        # scheduling.
        cached = self._api.public_bootstrap.ulp_users.get(ulp_id)
        if cached is None:
            return UnknownIdentity(reason="ulp_user_not_cached")
        return UlpUserIdentity(ulp_id=ulp_id, user=cached)
