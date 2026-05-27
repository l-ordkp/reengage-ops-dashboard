"""
Chrome extension API business logic — lookup + mark responded.
Operator auth uses X-Operator-Email (not JWT) — validated here.
"""
from __future__ import annotations

import re
import uuid

from fastapi import HTTPException

from backend.repositories.assignment_repository import (
    fetch_assignment_by_order_id,
    insert_completed_assignment,
    mark_is_loop_replied,
    update_assignment_by_order_id,
    update_assignment_platform_ids,
)
from backend.repositories.extension_repository import (
    is_operator_approved,
    lookup_response_by_order,
    lookup_review_uid_by_order,
    resolve_canonical_order_id,
)
from backend.repositories.ops_log_repository import log_action

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_operator(email: str) -> str:
    """Raises 401/403 if invalid. Returns the email on success."""
    if not email or "@" not in email:
        raise HTTPException(status_code=401, detail="Missing operator email")
    if not is_operator_approved(email):
        raise HTTPException(status_code=403, detail="Operator not approved")
    return email


def lookup(order_id: str, operator_email: str) -> dict:
    operator_email = validate_operator(operator_email)
    if not UUID_RE.match(order_id):
        raise HTTPException(status_code=400, detail="Invalid order_id")

    row = lookup_response_by_order(order_id)
    if not row:
        return {"found": False, "order_id": order_id}

    return {
        "found": True,
        "order_id": order_id,
        "response_text": row.get("response_text"),
        "coupon_value": float(row["coupon_value"]) if row.get("coupon_value") else 0,
        "response_type": row.get("response_type"),
        "response_sent": (
            str(row["response_sent"])
            if row.get("response_sent") and str(row["response_sent"]) != "NaT"
            else None
        ),
        "customer_name": row.get("customer_name"),
        "review_text": row.get("review_text"),
        "star_rating": str(row["star_rating"]) if row.get("star_rating") else None,
        "slug": row.get("slug"),
        "is_replied": bool(row.get("is_replied")),
        "operator_email": operator_email,
    }


def mark_responded(
    order_id: str, platform: str, chain_name: str,
    operator_email: str,
    replied_response: str = "", replied_discount: str = "",
    exact_match_response: bool = True, exact_match_discount: bool = True,
    platform_reply_id: str = "", platform_coupon_id: str = "",
) -> dict:
    operator_email = validate_operator(operator_email)
    if not UUID_RE.match(order_id):
        raise HTTPException(status_code=400, detail="Invalid order_id")

    # DoorDash extension passes `complaintId` (= review_id) as `order_id`.
    # Resolve to the canonical automation_reviews.order_id so downstream
    # updates (mark_is_loop_replied / assignment lookup) actually match.
    canonical_order_id = resolve_canonical_order_id(order_id)
    if canonical_order_id:
        order_id = canonical_order_id

    review_uid = lookup_review_uid_by_order(order_id)

    platform_short = "extension_ue" if "uber" in platform.lower() else "extension_dd"
    qc_info = platform_short
    has_qc = bool(replied_response)
    if has_qc:
        match_r = "exact" if exact_match_response else "MISMATCH"
        match_d = "exact" if exact_match_discount else "MISMATCH"
        qc_info = f"{platform_short}|resp:{match_r}|disc:{match_d}"

    log_action(
        review_uid=review_uid,
        platform=platform,
        chain_name=chain_name,
        action="mark_responded",
        operator_email=operator_email,
        performed_by=operator_email,
        remarks=qc_info,
    )

    # Update or insert the assignment row. assignment_status='completed' is
    # now the canonical signal that Loop replied — Chain Health and the
    # status field on fetch_reviews_14d both derive is_loop_replied from
    # this. We no longer write back to elt_data.automation_reviews (that
    # was breaking dbt's MERGE).
    existing = fetch_assignment_by_order_id(order_id)
    if not existing.empty:
        update_assignment_by_order_id(order_id)
    else:
        insert_completed_assignment(
            review_uid=review_uid, order_id=order_id, operator_email=operator_email,
            chain_name=chain_name, platform=platform,
            platform_reply_id=platform_reply_id,
            platform_coupon_id=platform_coupon_id,
        )

    # Persist platform-issued IDs onto the assignment row. Done as a separate
    # UPDATE so the existing-row branch above also gets the IDs without
    # widening update_assignment_by_order_id's responsibilities.
    if platform_reply_id or platform_coupon_id:
        update_assignment_platform_ids(
            order_id=order_id,
            platform_reply_id=platform_reply_id,
            platform_coupon_id=platform_coupon_id,
        )

    return {
        "success": True,
        "operator_email": operator_email,
        "review_uid": review_uid,
        "qc": {
            "exact_match_response": exact_match_response,
            "exact_match_discount": exact_match_discount,
        } if has_qc else None,
    }
