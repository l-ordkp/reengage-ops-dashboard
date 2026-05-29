"""
Chrome extension API endpoints.
Auth via X-Operator-Email header (validated against approved users table) — NOT JWT.
"""
from __future__ import annotations

from fastapi import APIRouter, Header

from backend.managers.extension_manager import (
    lookup as do_lookup,
    mark_responded as do_mark_responded,
    observed_responded as do_observed_responded,
)
from backend.schemas.extension import MarkRespondedBody, ObservedRespondedBody

router = APIRouter(prefix="/api/extension", tags=["extension"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/lookup")
def lookup_endpoint(order_id: str, x_operator_email: str = Header(None)):
    return do_lookup(order_id, x_operator_email or "")


@router.post("/mark-responded")
def mark_responded_endpoint(body: MarkRespondedBody, x_operator_email: str = Header(None)):
    return do_mark_responded(
        order_id=body.order_id,
        platform=body.platform,
        chain_name=body.chain_name,
        operator_email=x_operator_email or "",
        replied_response=body.replied_response,
        replied_discount=body.replied_discount,
        exact_match_response=body.exact_match_response,
        exact_match_discount=body.exact_match_discount,
        platform_reply_id=body.platform_reply_id,
        platform_coupon_id=body.platform_coupon_id,
    )


@router.post("/observed-responded")
def observed_responded_endpoint(
    body: ObservedRespondedBody, x_operator_email: str = Header(None),
):
    """Back-mark reviews the platform itself reports as already replied.
    Distinct from /mark-responded (which is the operator's own submission)
    so a stale auto-observation never overwrites real submit metadata."""
    return do_observed_responded(
        items=[item.model_dump() for item in body.items],
        operator_email=x_operator_email or "",
    )
