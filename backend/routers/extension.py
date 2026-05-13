"""
Chrome extension API endpoints.
Auth via X-Operator-Email header (validated against approved users table) — NOT JWT.
"""
from __future__ import annotations

from fastapi import APIRouter, Header

from backend.managers.extension_manager import (
    lookup as do_lookup,
    mark_responded as do_mark_responded,
)
from backend.schemas.extension import MarkRespondedBody

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
    )
