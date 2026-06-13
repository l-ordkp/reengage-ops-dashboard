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


def fetch_review_age_status(items: list[dict]) -> dict[str, str]:
    """Return {review_uid → 'in_window' | 'out_of_window'} for the given
    observed-responded items. A review is `in_window` iff it has a matching
    row in automation_reviews AND its review_timestamp is within the
    platform's response deadline (DD 7d, UE 14d). Anything else is
    `out_of_window` — either pre-pipeline (no automation_reviews row), too
    old, or just missing data.

    Used by `observed_responded` to stamp the `observed_out_of_window`
    column on the assignment row. Out-of-window observations still get
    INSERT/UPDATEd (so Chain Value's loop_responded captures the late
    discovery) but are filtered out of per-operator throughput and daily
    Slack counts so they don't inflate "today's" numbers.

    Caller passes items with at least `review_uid` and `platform` set.
    review_uids absent from the returned dict should be treated as
    out_of_window (defensive default).
    """
    if not items:
        return {}
    tuples_sql = ", ".join(
        f"('{_escape(it['review_uid'])}', '{_escape(it['platform'])}')"
        for it in items
        if it.get("review_uid") and it.get("platform")
    )
    if not tuples_sql:
        return {}
    rows = bq_read_dicts(f"""
        WITH input AS (
          SELECT review_uid, platform
          FROM UNNEST([
            STRUCT<review_uid STRING, platform STRING>
            {tuples_sql}
          ])
        )
        SELECT DISTINCT input.review_uid
        FROM input
        JOIN `{PROJECT}.{TABLE_AUTOMATION_REVIEWS}` ar
          ON input.review_uid = COALESCE(ar.review_id, ar.order_id)
        WHERE COALESCE(ar.review_timestamp, ar.order_timestamp) >= CASE input.platform
            WHEN 'Doordash' THEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
            WHEN 'UberEats' THEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
            ELSE TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
          END
          -- Upper bound: reject future-dated review_timestamps (clock skew /
          -- malformed source data) so they don't silently classify as in_window.
          AND COALESCE(ar.review_timestamp, ar.order_timestamp) <= CURRENT_TIMESTAMP()
    """)
    in_window_uids = {row["review_uid"] for row in rows if row.get("review_uid")}
    return {
        it["review_uid"]: ("in_window" if it["review_uid"] in in_window_uids else "out_of_window")
        for it in items
        if it.get("review_uid")
    }


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
