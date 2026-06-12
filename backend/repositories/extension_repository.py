"""
Extension API-specific reads (operator verification, response lookup).
Distinct from the dashboard's repositories because the extension API has its own auth
and may need to query without the usual JWT context.
"""
from __future__ import annotations

from backend.clients.bq_client import bq_read_dicts
from backend.config import (
    PROJECT,
    TABLE_AUTOMATION_REVIEWS,
    TABLE_REVIEW_RESPONSES,
    TABLE_SLUG_AM_MAPPING,
    TABLE_USERS,
)


def _escape(value: str) -> str:
    return (value or "").replace("'", "''")


def is_operator_approved(email: str) -> bool:
    safe = email.lower().replace("'", "''")
    rows = bq_read_dicts(f"""
        SELECT email FROM `{PROJECT}.{TABLE_USERS}`
        WHERE LOWER(email) = '{safe}' AND approved = TRUE
        LIMIT 1
    """)
    return bool(rows)


def lookup_response_by_order(order_id: str) -> dict | None:
    safe_id = order_id.replace("'", "")
    rows = bq_read_dicts(f"""
        SELECT
            rr.response_text, rr.coupon_value, rr.response_type, rr.response_sent,
            ar.customer_name, ar.review_text, ar.star_rating, ar.slug, ar.is_replied
        FROM `{PROJECT}.{TABLE_REVIEW_RESPONSES}` rr
        LEFT JOIN `{PROJECT}.{TABLE_AUTOMATION_REVIEWS}` ar
            ON rr.order_id = ar.order_id
        WHERE rr.order_id = '{safe_id}'
        LIMIT 1
    """)
    return rows[0] if rows else None


def lookup_review_uid_by_order(order_id: str) -> str:
    """Get the canonical review_uid for an order. Falls back to order_id if not found."""
    safe_id = order_id.replace("'", "")
    rows = bq_read_dicts(f"""
        SELECT COALESCE(review_id, order_id) AS review_uid
        FROM `{PROJECT}.{TABLE_AUTOMATION_REVIEWS}`
        WHERE order_id = '{safe_id}' OR review_id = '{safe_id}'
        LIMIT 1
    """)
    return rows[0]["review_uid"] if rows else order_id


def fetch_loop_usernames_for_stores(
    store_ids: list[str], platform: str,
) -> dict[str, set[str]]:
    """Return {store_id → set of lowercased Loop portal usernames} for the
    given stores on this platform. Used by the observed-responded flow to
    decide whether a platform-reported reply was sent from one of the slug's
    Loop portal accounts (`missed_but_ours`) or from a different account
    (`external`).

    Returns a SET per store, not a single string, because the audit shows
    some store_ids legitimately carry multiple usernames in slug_am_mapping
    (different vb_name rows for the same store sometimes use distinct portal
    logins). Match if the responder email is in the set.

    Lowercased so the caller can do a case-insensitive comparison against the
    platform's `merchantUserEmail`. Stores without any mapping are absent from
    the returned dict — caller should treat them as no-match.
    """
    cleaned = [s for s in {s.strip() for s in store_ids} if s]
    if not cleaned:
        return {}
    in_list = ", ".join(f"'{_escape(s)}'" for s in cleaned)
    safe_platform = _escape(platform)
    rows = bq_read_dicts(f"""
        SELECT store_id, LOWER(TRIM(username)) AS username
        FROM `{PROJECT}.{TABLE_SLUG_AM_MAPPING}`
        WHERE store_id IN ({in_list})
          AND LOWER(vb_platform) = LOWER('{safe_platform}')
          AND username IS NOT NULL
          AND TRIM(username) != ''
    """)
    out: dict[str, set[str]] = {}
    for row in rows:
        sid = row.get("store_id")
        username = row.get("username")
        if not sid or not username:
            continue
        out.setdefault(sid, set()).add(username)
    return out


def resolve_canonical_order_id(maybe_id: str) -> str | None:
    """
    The DoorDash extension passes `complaintId` (= review_id) as the
    operator's `order_id` in mark_responded. Resolve to the real
    `automation_reviews.order_id` by matching on either column.
    Returns None when no automation_review matches (e.g., review aged out
    or wrong ID entirely).
    """
    safe_id = maybe_id.replace("'", "")
    rows = bq_read_dicts(f"""
        SELECT order_id
        FROM `{PROJECT}.{TABLE_AUTOMATION_REVIEWS}`
        WHERE order_id = '{safe_id}' OR review_id = '{safe_id}'
        LIMIT 1
    """)
    return rows[0]["order_id"] if rows else None
