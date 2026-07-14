"""
Chrome extension API business logic — lookup + mark responded.
Operator auth uses X-Operator-Email (not JWT) — validated here.
"""
from __future__ import annotations

import re
import uuid

from fastapi import HTTPException

from backend.repositories.assignment_repository import (
    fetch_assignments_by_ids,
    mark_is_loop_replied,
)
from backend.repositories.extension_repository import (
    fetch_loop_usernames_for_stores,
    fetch_review_age_status,
    is_operator_approved,
    lookup_response_by_order,
    lookup_review_uid_by_order,
    resolve_canonical_order_id,
)
from backend.repositories.pg_reengage_repository import (
    log_action,
    log_actions_bulk,
    mark_completed,
    write_observed,
)
from backend.repositories.operator_repository import (
    fetch_daily_loop_completed_14d,
    fetch_operator_chain_breakdown_14d,
    fetch_operator_daily_breakdown_14d,
    fetch_operator_performance_14d,
)
from backend.repositories.review_repository import (
    fetch_chain_totals_14d,
    fetch_chain_value,
    fetch_reviews_14d,
)

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

    # Record the reply in Postgres (authoritative): one audit row, then
    # flip/insert the assignment to completed. mark_completed carries the
    # platform reply/coupon IDs and handles the pending-flip, fresh-insert, and
    # auto_resolved-promotion cases against the terminal-uniqueness guard.
    log_action(
        review_uid, platform, chain_name, "mark_responded",
        operator_email, operator_email, qc_info,
    )
    mark_completed(
        review_uid=review_uid, order_id=order_id, operator_email=operator_email,
        platform=platform, chain_name=chain_name,
        platform_reply_id=platform_reply_id, platform_coupon_id=platform_coupon_id,
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
    """Back-mark reviews the platform has confirmed as replied.

    For each item we classify by responder identity (DD's merchantUserEmail
    against the slug's Loop portal username in slug_am_mapping):

      - match  → `missed_but_ours`: a Loop operator replied via the platform
                 UI bypassing our extension. Row written as status='completed',
                 attributed to the matched Loop username. Counts toward Loop
                 throughput like any real submit.
      - no match (or no responder id, e.g. UE) → `external`: merchant or
                 third-party replied. Row written as status='auto_resolved',
                 operator_email=NULL. Hidden from queues but does NOT count
                 toward Loop throughput.

    Combined with whether a prior assignment row existed (self_resolved vs
    during_pending) this yields 4 ops_log remark values; see the spec in
    PR-A's description.

    Already-completed rows are still skipped — observations never overwrite
    a real submit's metadata.
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
            "platform_responder_id": (item.get("platform_responder_id") or "").strip(),
        })

    if not valid:
        return {
            "processed": 0, "skipped": 0, "flipped": 0, "inserted": 0,
            "missed_but_ours": 0, "external": 0, "out_of_window": 0,
        }

    # Classify each item as in-window or out-of-window against the platform
    # response deadline. Out-of-window rows still get written (so Chain Value
    # captures the late discovery), but the assignment row is stamped with
    # `observed_out_of_window=TRUE` and downstream per-operator + daily-
    # throughput reads filter it out so it doesn't inflate "today's" counts.
    age_status = fetch_review_age_status(valid)
    for v in valid:
        v["observed_out_of_window"] = age_status.get(v["review_uid"], "out_of_window") == "out_of_window"

    existing = fetch_assignments_by_ids(
        review_uids=[v["review_uid"] for v in valid],
        order_ids=[v["order_id"] for v in valid],
    )
    # Priority resolves "multiple rows for the same review_uid/order_id" cases.
    # A live 'pending' assignment must beat a stale 'reassigned'/'expired' row,
    # otherwise iteration order (undefined in BQ) decides whether we flip or
    # insert. 'completed' and 'auto_resolved' are firm caps — never overwritten
    # by a further observation.
    STATUS_PRIORITY = {
        "completed": 4, "auto_resolved": 3,
        "pending": 2, "expired": 1, "reassigned": 0,
    }

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

    # Batched per-platform lookup of each store's Loop portal usernames —
    # used to decide `missed_but_ours` (responder matches) vs `external`.
    # Skipped per platform when no item carries a `platform_responder_id`
    # (today: every UE batch, since UE's reviews payload doesn't expose the
    # email). Saves one BQ round-trip per such batch.
    loop_usernames_by_store: dict[tuple[str, str], set[str]] = {}
    for plat in ("Doordash", "UberEats"):
        store_ids = [
            v["store_id"] for v in valid
            if v["platform"] == plat and v["store_id"] and v["platform_responder_id"]
        ]
        if not store_ids:
            continue
        mapping = fetch_loop_usernames_for_stores(store_ids, plat)
        for sid, usernames in mapping.items():
            loop_usernames_by_store[(plat, sid)] = usernames

    def _matched_loop_username(item: dict) -> str | None:
        """Return the matched Loop portal username for this item, or None."""
        responder = item["platform_responder_id"].lower()
        if not responder:
            return None
        usernames = loop_usernames_by_store.get((item["platform"], item["store_id"]))
        if not usernames:
            return None
        return responder if responder in usernames else None

    to_flip_loop: list[dict] = []   # missed_but_ours | during_pending
    to_flip_ext: list[dict] = []    # external        | during_pending
    to_insert_loop: list[dict] = [] # missed_but_ours | self_resolved
    to_insert_ext: list[dict] = []  # external        | self_resolved
    skipped = 0
    for item in valid:
        candidate_statuses = [
            status_by_review_uid.get(item["review_uid"]),
            status_by_order_id.get(item["order_id"]),
        ]
        candidate_statuses = [s for s in candidate_statuses if s]
        prior_status = (
            max(candidate_statuses, key=lambda s: STATUS_PRIORITY.get(s, -1))
            if candidate_statuses else None
        )
        # Already-terminal rows (completed or auto_resolved) are never
        # overwritten — those classifications are firm.
        if prior_status in ("completed", "auto_resolved"):
            skipped += 1
            continue
        matched = _matched_loop_username(item)
        item_with_match = {**item, "_matched_loop_username": matched}
        if prior_status == "pending":
            (to_flip_loop if matched else to_flip_ext).append(item_with_match)
        else:
            (to_insert_loop if matched else to_insert_ext).append(item_with_match)

    # Persist to Postgres (authoritative): flip pending rows / insert terminal
    # rows for each observed reply. Loop-matched -> completed (attributed to the
    # matched username); external -> auto_resolved. write_observed does the
    # flip-else-insert against the terminal-uniqueness guard.
    pg_items = []
    for it in to_flip_loop + to_insert_loop:
        pg_items.append({
            "review_uid": it["review_uid"], "order_id": it["order_id"],
            "platform": it["platform"], "status": "completed",
            "operator_email": it.get("_matched_loop_username") or "",
            "observed_out_of_window": bool(it.get("observed_out_of_window")),
        })
    for it in to_flip_ext + to_insert_ext:
        pg_items.append({
            "review_uid": it["review_uid"], "order_id": it["order_id"],
            "platform": it["platform"], "status": "auto_resolved",
            "operator_email": "",
            "observed_out_of_window": bool(it.get("observed_out_of_window")),
        })
    write_observed(pg_items)

    log_entries: list[dict] = []
    for item in to_flip_loop:
        log_entries.append({
            "review_uid": item["review_uid"],
            "platform": item["platform"],
            "chain_name": "",
            "action": "observed_responded",
            "operator_email": item["_matched_loop_username"],
            "performed_by": operator_email,
            "remarks": "missed_but_ours|during_pending",
        })
    for item in to_flip_ext:
        log_entries.append({
            "review_uid": item["review_uid"],
            "platform": item["platform"],
            "chain_name": "",
            "action": "observed_responded",
            "operator_email": "",
            "performed_by": operator_email,
            "remarks": "external|during_pending",
        })
    for item in to_insert_loop:
        log_entries.append({
            "review_uid": item["review_uid"],
            "platform": item["platform"],
            "chain_name": "",
            "action": "observed_responded",
            "operator_email": item["_matched_loop_username"],
            "performed_by": operator_email,
            "remarks": "missed_but_ours|self_resolved",
        })
    for item in to_insert_ext:
        log_entries.append({
            "review_uid": item["review_uid"],
            "platform": item["platform"],
            "chain_name": "",
            "action": "observed_responded",
            "operator_email": "",
            "performed_by": operator_email,
            "remarks": "external|self_resolved",
        })
    if log_entries:
        log_actions_bulk(log_entries)


    # Bust every cached dashboard read that touches the assignments table,
    # so an observation lands across the whole UI immediately rather than
    # rolling in over the 2-5 minute TTL window. Without this, Chain Value's
    # loop_responded count and the operator-leaderboard sit stale right
    # after a busy portal browse.
    flipped_count = len(to_flip_loop) + len(to_flip_ext)
    inserted_count = len(to_insert_loop) + len(to_insert_ext)
    if flipped_count or inserted_count:
        fetch_reviews_14d.clear()
        fetch_chain_value.clear()
        fetch_chain_totals_14d.clear()
        fetch_daily_loop_completed_14d.clear()
        fetch_operator_performance_14d.clear()
        fetch_operator_daily_breakdown_14d.clear()
        fetch_operator_chain_breakdown_14d.clear()

    out_of_window_count = sum(
        1 for v in valid if v.get("observed_out_of_window")
    )
    return {
        "processed": len(valid),
        "skipped": skipped,
        "flipped": flipped_count,
        "inserted": inserted_count,
        "missed_but_ours": len(to_flip_loop) + len(to_insert_loop),
        "external": len(to_flip_ext) + len(to_insert_ext),
        "out_of_window": out_of_window_count,
    }
