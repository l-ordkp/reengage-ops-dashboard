"""
Chrome extension API endpoints.
Auth via backend-issued operator JWT (Authorization: Bearer), obtained at
/api/extension/auth by exchanging a Google OAuth access token — NOT a
client-asserted email header.
"""
from __future__ import annotations

from fastapi import APIRouter, Header

from backend.managers.extension_manager import (
    login_extension,
    lookup as do_lookup,
    mark_responded as do_mark_responded,
    observed_responded as do_observed_responded,
)
from backend.schemas.extension import (
    ExtensionAuthBody,
    MarkRespondedBody,
    ObservedRespondedBody,
)

router = APIRouter(prefix="/api/extension", tags=["extension"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/auth")
def auth_endpoint(body: ExtensionAuthBody):
    """Exchange a Google OAuth access token for a backend operator JWT."""
    return login_extension(body.google_access_token)


@router.get("/lookup")
def lookup_endpoint(order_id: str, authorization: str = Header(None)):
    return do_lookup(order_id, authorization or "")


@router.post("/mark-responded")
def mark_responded_endpoint(body: MarkRespondedBody, authorization: str = Header(None)):
    return do_mark_responded(
        order_id=body.order_id,
        platform=body.platform,
        chain_name=body.chain_name,
        authorization=authorization or "",
        replied_response=body.replied_response,
        replied_discount=body.replied_discount,
        exact_match_response=body.exact_match_response,
        exact_match_discount=body.exact_match_discount,
        platform_reply_id=body.platform_reply_id,
        platform_coupon_id=body.platform_coupon_id,
    )


@router.post("/observed-responded")
def observed_responded_endpoint(
    body: ObservedRespondedBody, authorization: str = Header(None),
):
    """Back-mark reviews the platform itself reports as already replied.
    Distinct from /mark-responded (which is the operator's own submission)
    so a stale auto-observation never overwrites real submit metadata."""
    return do_observed_responded(
        items=[item.model_dump() for item in body.items],
        authorization=authorization or "",
    )
