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
    TABLE_USERS,
)


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
