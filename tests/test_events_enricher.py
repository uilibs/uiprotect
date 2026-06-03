"""Phase 3 enricher tests for the public events contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest

from uiprotect.api import ProtectApiClient
from uiprotect.data.nvr import Event, EventMetadata, FingerprintMetadata, NfcMetadata
from uiprotect.data.public_devices import PublicUlpUser
from uiprotect.data.types import EventType, ModelType, UlpUserStatus
from uiprotect.events import UlpUserIdentity, UnknownIdentity
from uiprotect.events.enricher import EventEnricher
from uiprotect.exceptions import NotAuthorized


def _make_client() -> ProtectApiClient:
    return ProtectApiClient(
        host="127.0.0.1",
        port=443,
        username="u",
        password="p",  # noqa: S106
        verify_ssl=False,
        store_sessions=False,
    )


def _make_user(api: ProtectApiClient, ulp_id: str) -> PublicUlpUser:
    return PublicUlpUser(
        api=api,
        id=ulp_id,
        model=ModelType.ULP_USER,
        first_name="A",
        last_name="B",
        full_name="A B",
        status=UlpUserStatus.ACTIVE,
    )


def _make_nfc_event(api: ProtectApiClient, *, metadata: NfcMetadata | None) -> Event:
    return Event(
        api=api,
        id="evt-nfc",
        type=EventType.NFC_CARD_SCANNED,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
        metadata=EventMetadata(api=api, nfc=metadata) if metadata is not None else None,
    )


def _make_fp_event(
    api: ProtectApiClient, *, metadata: FingerprintMetadata | None
) -> Event:
    return Event(
        api=api,
        id="evt-fp",
        type=EventType.FINGERPRINT_IDENTIFIED,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
        metadata=(
            EventMetadata(api=api, fingerprint=metadata)
            if metadata is not None
            else None
        ),
    )


def test_enrich_returns_none_for_non_credential_event() -> None:
    api = _make_client()
    enricher = EventEnricher(api)
    motion = Event(
        api=api,
        id="m",
        type=EventType.MOTION,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        device_id="cam-1",
    )
    assert enricher.enrich(motion) is None


def test_enrich_nfc_no_metadata() -> None:
    api = _make_client()
    enricher = EventEnricher(api)
    result = enricher.enrich(_make_nfc_event(api, metadata=None))
    assert result == UnknownIdentity(reason="no_metadata")


def test_enrich_nfc_ulp_id_null() -> None:
    api = _make_client()
    enricher = EventEnricher(api)
    md = NfcMetadata(api=api, ulp_id=None)
    result = enricher.enrich(_make_nfc_event(api, metadata=md))
    assert result == UnknownIdentity(reason="ulp_id_null")


def test_enrich_nfc_cache_miss() -> None:
    api = _make_client()
    enricher = EventEnricher(api)
    md = NfcMetadata(api=api, ulp_id="ulp-abc")
    result = enricher.enrich(_make_nfc_event(api, metadata=md))
    assert result == UnknownIdentity(reason="ulp_user_not_cached")


def test_enrich_nfc_cache_hit() -> None:
    api = _make_client()
    user = _make_user(api, "ulp-abc")
    api._public_ulp_users_cache["ulp-abc"] = user
    enricher = EventEnricher(api)
    md = NfcMetadata(api=api, ulp_id="ulp-abc")
    result = enricher.enrich(_make_nfc_event(api, metadata=md))
    assert isinstance(result, UlpUserIdentity)
    assert result.user is user
    assert result.ulp_id == "ulp-abc"


def test_enrich_fingerprint_cache_hit() -> None:
    api = _make_client()
    user = _make_user(api, "ulp-fp")
    api._public_ulp_users_cache["ulp-fp"] = user
    enricher = EventEnricher(api)
    md = FingerprintMetadata(api=api, ulp_id="ulp-fp")
    result = enricher.enrich(_make_fp_event(api, metadata=md))
    assert isinstance(result, UlpUserIdentity)
    assert result.user is user


def test_enrich_fingerprint_no_metadata() -> None:
    api = _make_client()
    enricher = EventEnricher(api)
    result = enricher.enrich(_make_fp_event(api, metadata=None))
    assert result == UnknownIdentity(reason="no_metadata")


def test_enrich_fingerprint_ulp_id_null() -> None:
    api = _make_client()
    enricher = EventEnricher(api)
    md = FingerprintMetadata(api=api, ulp_id=None)
    result = enricher.enrich(_make_fp_event(api, metadata=md))
    assert result == UnknownIdentity(reason="ulp_id_null")


@pytest.mark.asyncio
async def test_refresh_cache_swallows_403_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()
    api.get_ulp_users_public = cast(  # type: ignore[method-assign]
        AsyncMock,
        AsyncMock(side_effect=NotAuthorized("disabled")),
    )

    with caplog.at_level("DEBUG", logger="uiprotect.api"):
        await api._refresh_public_ulp_users_cache()
        await api._refresh_public_ulp_users_cache()

    matching = [r for r in caplog.records if "ULP" in r.message]
    assert len(matching) == 1
    assert api._public_ulp_users_cache == {}


@pytest.mark.asyncio
async def test_refresh_cache_populates_lookup() -> None:
    api = _make_client()
    user = _make_user(api, "ulp-1")
    api.get_ulp_users_public = cast(  # type: ignore[method-assign]
        AsyncMock,
        AsyncMock(return_value=[user]),
    )
    await api._refresh_public_ulp_users_cache()
    assert api._public_ulp_users_cache == {"ulp-1": user}


@pytest.mark.asyncio
async def test_refresh_cache_logs_again_after_recovery(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _make_client()

    state = {"fail": True}

    async def call() -> list[PublicUlpUser]:
        if state["fail"]:
            raise NotAuthorized("disabled")
        return []

    api.get_ulp_users_public = call  # type: ignore[method-assign]

    with caplog.at_level("DEBUG", logger="uiprotect.api"):
        await api._refresh_public_ulp_users_cache()  # logs (first failure)
        state["fail"] = False
        await api._refresh_public_ulp_users_cache()  # success resets flag
        state["fail"] = True
        await api._refresh_public_ulp_users_cache()  # logs again

    matching = [r for r in caplog.records if "ULP user fetch unavailable" in r.message]
    assert len(matching) == 2
