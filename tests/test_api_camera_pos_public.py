"""Tests for the public-API POS transaction ingestion endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from uiprotect.data import PosTransactionType
from uiprotect.exceptions import BadRequest

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient

CAMERA_ID = "6878d82800215803e45928e1"


@pytest.mark.asyncio()
async def test_create_pos_transaction_public_minimal_body(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_obj = AsyncMock(
        return_value={"created": True, "eventId": "evt-1"}
    )

    result = await protect_client.create_pos_transaction_public(
        CAMERA_ID,
        transaction_type=PosTransactionType.SALE,
        external_id="tx-1",
        amount=12.5,
    )

    assert result.created is True
    assert result.event_id == "evt-1"
    protect_client.api_request_obj.assert_called_once_with(
        url=f"/v1/pos/cameras/{CAMERA_ID}/transactions",
        method="post",
        json={"type": "sale", "externalId": "tx-1", "amount": 12.5},
        public_api=True,
    )


@pytest.mark.asyncio()
async def test_create_pos_transaction_public_full_body(
    protect_client: ProtectApiClient,
) -> None:
    protect_client.api_request_obj = AsyncMock(return_value={"created": False})

    result = await protect_client.create_pos_transaction_public(
        CAMERA_ID,
        transaction_type="refund",
        external_id="tx-2",
        amount=0,
        currency="USD",
        line_items=[{"title": "Coffee", "quantity": 2}],
        location={"id": "reg-1", "name": "Register 1"},
        payment_types=["card"],
        timestamp=1735689600000,
    )

    assert result.created is False
    assert result.event_id is None
    assert protect_client.api_request_obj.call_args.kwargs["json"] == {
        "type": "refund",
        "externalId": "tx-2",
        "amount": 0,
        "currency": "USD",
        "lineItems": [{"title": "Coffee", "quantity": 2}],
        "location": {"id": "reg-1", "name": "Register 1"},
        "paymentTypes": ["card"],
        "timestamp": 1735689600000,
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"transaction_type": "Sale"}, "transaction_type must be one of: refund, sale"),
        ({"external_id": ""}, "external_id must be between 1 and 255"),
        ({"external_id": "x" * 256}, "external_id must be between 1 and 255"),
        ({"amount": -1}, "amount must be >= 0"),
        ({"currency": "usd"}, "currency must be an uppercase ISO 4217 code"),
        ({"currency": "USDD"}, "currency must be an uppercase ISO 4217 code"),
        (
            {"line_items": [{"title": "x", "quantity": 1}] * 201},
            "line_items may hold at most 200 items",
        ),
        (
            {"payment_types": ["card"] * 21},
            "payment_types may hold at most 20 entries",
        ),
        ({"timestamp": 0}, "timestamp must be a positive epoch-millisecond value"),
    ],
)
@pytest.mark.asyncio()
async def test_create_pos_transaction_public_rejects_out_of_spec_values(
    protect_client: ProtectApiClient,
    kwargs: dict[str, object],
    message: str,
) -> None:
    protect_client.api_request_obj = AsyncMock()
    call_kwargs: dict[str, object] = {
        "transaction_type": PosTransactionType.SALE,
        "external_id": "tx-1",
        "amount": 1,
        **kwargs,
    }

    with pytest.raises(BadRequest, match=message):
        await protect_client.create_pos_transaction_public(CAMERA_ID, **call_kwargs)  # type: ignore[arg-type]

    protect_client.api_request_obj.assert_not_called()
