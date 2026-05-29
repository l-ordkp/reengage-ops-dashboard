"""
Chrome extension API business logic — lookup + mark responded.
Operator auth uses X-Operator-Email (not JWT) — validated here.
"""
from __future__ import annotations

import re
import uuid

from fastapi import HTTPException

from backend.repositories.assignment_repository import (
    bulk_complete_pending_by_ids,
    bulk_insert_observed_assignments,
    fetch_assignment_by_order_id,
    fetch_assignments_by_ids,
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
from backend.repositories.ops_log_repository import log_action, log_actions_bulk
from backend.repositories.review_repository import fetch_reviews_14d

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


def observed_responded(items: list[dict], operator_email: str) -> dict:
    """Back-mark reviews the platform has confirmed as replied (merchant
    self-resolved, or operator submitted via platform UI without our extension).

    Three-state logic per item:
      - already 'completed' → skip (don't overwrite a real submit's metadata)
      - 'pending'           → flip to completed (audit: auto_during_pending)
      - no row              → INSERT as completed (audit: auto_self_resolved)
    """
    operator_email = validate_operator(operator_email)

    valid: list[dict] = []
    for item in items:
        platform = (item.get("platform") or "").strip()
        review_uid = (item.get("review_uid") or "").strip()
        order_id = (item.get("order_id") or "").strip()
        if platform not in ("Doordash", "UberEats"):
            continue
        if not UUID_RE.match(review_uid) or not UUID_RE.match(order_id):
            continue
        valid.append({
            "platform": platform,
            "review_uid": review_uid,
            "order_id": order_id,
            "store_id": (item.get("store_id") or "").strip(),
        })

    if not valid:
        return {"processed": 0, "skipped": 0, "flipped": 0, "inserted": 0}

    existing = fetch_assignments_by_ids(
        review_uids=[v["review_uid"] for v in valid],
        order_ids=[v["order_id"] for v in valid],
    )
    # Priority resolves "multiple rows for the same review_uid/order_id" cases.
    # A live 'pending' assignment must beat a stale 'reassigned'/'expired' row,
    # otherwise iteration order (undefined in BQ) decides whether we flip or
    # insert. 'completed' is the firm cap — never overwritten by an observation.
    STATUS_PRIORITY = {"completed": 3, "pending": 2, "expired": 1, "reassigned": 0}

    def _merge_status(existing_status: str | None, new_status: str) -> str:
        if existing_status is None:
            return new_status
        return new_status if STATUS_PRIORITY.get(new_status, -1) > STATUS_PRIORITY.get(existing_status, -1) else existing_status

    status_by_review_uid: dict[str, str] = {}
    status_by_order_id: dict[str, str] = {}
    if not existing.empty:
        for _, row in existing.iterrows():
            if row.get("review_uid"):
                status_by_review_uid[row["review_uid"]] = _merge_status(
                    status_by_review_uid.get(row["review_uid"]), row["status"],
                )
            if row.get("order_id"):
                status_by_order_id[row["order_id"]] = _merge_status(
                    status_by_order_id.get(row["order_id"]), row["status"],
                )

    to_flip: list[dict] = []
    to_insert: list[dict] = []
    skipped = 0
    for item in valid:
        # Look at both lookup keys; pick whichever is higher priority.
        candidate_statuses = [
            status_by_review_uid.get(item["review_uid"]),
            status_by_order_id.get(item["order_id"]),
        ]
        candidate_statuses = [s for s in candidate_statuses if s]
        status = (
            max(candidate_statuses, key=lambda s: STATUS_PRIORITY.get(s, -1))
            if candidate_statuses else None
        )
        if status == "completed":
            skipped += 1
        elif status == "pending":
            to_flip.append(item)
        else:
            to_insert.append(item)

    if to_flip:
        bulk_complete_pending_by_ids(
            review_uids=[v["review_uid"] for v in to_flip],
            order_ids=[v["order_id"] for v in to_flip],
        )
    if to_insert:
        bulk_insert_observed_assignments(to_insert, operator_email)

    log_entries: list[dict] = []
    for item in to_flip:
        log_entries.append({
            "review_uid": item["review_uid"],
            "platform": item["platform"],
            "chain_name": "",
            "action": "observed_responded",
            "operator_email": operator_email,
            "performed_by": operator_email,
            "remarks": "auto_during_pending",
        })
    for item in to_insert:
        log_entries.append({
            "review_uid": item["review_uid"],
            "platform": item["platform"],
            "chain_name": "",
            "action": "observed_responded",
            "operator_email": operator_email,
            "performed_by": operator_email,
            "remarks": "auto_self_resolved",
        })
    if log_entries:
        log_actions_bulk(log_entries)

    # Bust the dashboard cache so the back-marked reviews flip to RESPONDED
    # on the next read, not after the 5-minute TTL expires.
    if to_flip or to_insert:
        fetch_reviews_14d.clear()

    return {
        "processed": len(valid),
        "skipped": skipped,
        "flipped": len(to_flip),
        "inserted": len(to_insert),
    }
