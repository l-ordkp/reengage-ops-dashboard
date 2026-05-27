"""
Review business logic: filtering, pagination, stats, search.
Operates on the cached DataFrame from review_repository.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from backend.clients.bq_client import bq_read
from backend.config import (
    TABLE_ASSIGNMENTS,
    TABLE_AUTOMATION_REVIEWS,
    TABLE_REVIEW_RESPONSES,
    TABLE_SLUG_AM_MAPPING,
)
from backend.repositories.assignment_repository import (
    fetch_all_assignments_14d,
    fetch_my_pending_assignments,
)
from backend.repositories.ops_log_repository import fetch_recent_ops_log
from backend.repositories.review_repository import fetch_reviews_14d
from backend.utils.serializers import df_to_dicts


# ── List + Stats ────────────────────────────────────────────────────────────

def list_reviews(
    chain_name: Optional[str] = None,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    has_response: Optional[str] = None,
    assigned_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Filter + paginate reviews. Returns {items, total, page, page_size}."""
    df = fetch_reviews_14d().drop_duplicates(subset=["review_uid"], keep="first").copy()

    if chain_name and chain_name != "All":
        df = df[df["chain_name"] == chain_name]
    if platform and platform != "All":
        df = df[df["platform"] == platform]
    if status and status != "All":
        df = df[df["status"] == status]
    if priority and priority != "All":
        df = df[df["priority"] == priority]
    if has_response == "true":
        df = df[df["response_text"].notna()]
    elif has_response == "false":
        df = df[df["response_text"].isna()]
    if assigned_to:
        my_asgn = fetch_my_pending_assignments(assigned_to)
        if not my_asgn.empty:
            uids = set(my_asgn["review_uid"].tolist())
            df = df[df["review_uid"].isin(uids)]
        else:
            df = df.iloc[0:0]

    total = len(df)
    start = (page - 1) * page_size
    page_df = df.iloc[start:start + page_size]
    return {
        "items": df_to_dicts(page_df),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_review_stats(chain_name: Optional[str] = None) -> dict:
    df = fetch_reviews_14d()
    if chain_name and chain_name != "All":
        df = df[df["chain_name"] == chain_name]
    if df.empty:
        return {"total": 0, "pending": 0, "responded": 0, "expired": 0,
                "critical": 0, "auto_posted": 0, "has_response": 0}
    return {
        "total": len(df),
        "pending": int((df["status"] == "PENDING").sum()),
        "responded": int((df["status"] == "RESPONDED").sum()),
        "expired": int((df["status"] == "EXPIRED").sum()),
        "critical": int(((df["priority"] == "CRITICAL") & (df["status"] == "PENDING")).sum()),
        "auto_posted": int(df["is_replied"].sum()) if "is_replied" in df.columns else 0,
        "has_response": int(df["response_text"].notna().sum()),
    }


def get_filter_options() -> dict:
    df = fetch_reviews_14d()
    return {
        "chains": sorted(df["chain_name"].unique().tolist()) if not df.empty else [],
        "platforms": sorted(df["platform"].unique().tolist()) if not df.empty else [],
    }


# ── Search ──────────────────────────────────────────────────────────────────

def search_reviews(
    field: Optional[str] = None,
    query: Optional[str] = None,
    customer_name: Optional[str] = None,
    chain_name: Optional[str] = None,
) -> list[dict]:
    """
    Search by ID field or by customer name + chain.
    Falls back to a 90-day BQ query for historical IDs not found in the 14-day cache.
    Enriches results with assignment info + QC match from ops_log.
    """
    df = fetch_reviews_14d()
    results = pd.DataFrame()

    if field and query:
        if field not in df.columns:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Unknown field: {field}")

        results = df[df[field].astype(str) == query.strip()]
        if results.empty:
            results = df[df[field].astype(str).str.contains(query.strip(), na=False, case=False)]

        # Fallback: search historical 90-day window for IDs
        if results.empty and field in ("order_id", "review_uid", "review_id", "customer_id"):
            results = _search_historical_by_id(field, query.strip())

    elif customer_name:
        subset = df if not chain_name or chain_name == "All" else df[df["chain_name"] == chain_name]
        mask = subset["customer_name"].astype(str).str.lower().str.contains(
            customer_name.strip().lower(), na=False)
        results = subset[mask]
    else:
        return []

    results = results.drop_duplicates(subset=["review_uid", "order_id"], keep="first")
    review_results = df_to_dicts(results.head(100))

    _enrich_with_assignments(review_results)
    _enrich_with_qc(review_results)
    return review_results


def _search_historical_by_id(field: str, query: str) -> pd.DataFrame:
    """Direct BQ query for historical (up to 90 days) lookup by ID.

    Status and priority are computed from the same rules as fetch_reviews_14d
    so out-of-scope reviews shown in Search don't get an incorrect blanket
    "EXPIRED" label.
    """
    safe_q = query.replace("'", "''")
    id_col = "COALESCE(ar.review_id, ar.order_id)" if field == "review_uid" else f"ar.{field}"
    return bq_read(f"""
        WITH base AS (
          SELECT
            COALESCE(ar.review_id, ar.order_id) AS review_uid,
            ar.order_id, ar.review_id,
            sm.chain AS chain_name, sm.b_name_id, sm.vb_name AS brand_name,
            ar.platform, ar.slug, ar.store_id,
            sm.username AS portal_username, sm.password AS portal_password,
            ar.customer_name, ar.user_id AS customer_id,
            CAST(ar.star_rating AS STRING) AS star_rating,
            ar.rating_type, ar.rating_value, ar.review_text,
            ar.items, ar.order_value, ar.is_replied,
            -- Derived from our own assignments table (we no longer write to
            -- automation_reviews.is_loop_replied — see assignment_repository).
            -- OR-match handles the historical DD complaintId-as-order_id case.
            EXISTS (
                SELECT 1
                FROM `{TABLE_ASSIGNMENTS}` AS asgn
                WHERE asgn.status = 'completed'
                  AND (asgn.review_uid = COALESCE(ar.review_id, ar.order_id)
                       OR asgn.order_id = ar.order_id
                       OR asgn.order_id = ar.review_id)
            ) AS is_loop_replied,
            DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp), 'America/Chicago')) AS review_date,
            CASE
                WHEN ar.platform = 'Doordash' THEN
                    TIMESTAMP_DIFF(TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7 DAY), CURRENT_TIMESTAMP(), HOUR)
                WHEN ar.platform = 'UberEats' THEN
                    TIMESTAMP_DIFF(TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 14 DAY), CURRENT_TIMESTAMP(), HOUR)
                ELSE 0
            END AS hours_left,
            rr.response_text, rr.response_type, rr.coupon_value,
            CASE
                WHEN ar.platform = 'UberEats' THEN
                    CONCAT('https://merchants.ubereats.com/manager/home/', ar.store_id, '/feedback/reviews/', ar.order_id)
                WHEN ar.platform = 'Doordash' THEN
                    CONCAT('https://www.doordash.com/merchant/feedback?store_id=', ar.store_id)
                ELSE ''
            END AS portal_link
          FROM `{TABLE_AUTOMATION_REVIEWS}` ar
          INNER JOIN `{TABLE_SLUG_AM_MAPPING}` sm ON ar.slug = sm.slug
          LEFT JOIN `{TABLE_REVIEW_RESPONSES}` rr ON ar.order_id = rr.order_id
          WHERE {id_col} = '{safe_q}'
            AND COALESCE(ar.review_timestamp, ar.order_timestamp)
                >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY))
          LIMIT 10
        )
        SELECT
            base.*,
            CASE
                WHEN is_replied = TRUE THEN 'RESPONDED'
                WHEN is_loop_replied = TRUE THEN 'RESPONDED'
                WHEN hours_left <= 0 THEN 'EXPIRED'
                ELSE 'PENDING'
            END AS status,
            CASE
                WHEN hours_left <= 24 THEN 'CRITICAL'
                WHEN hours_left <= 48 THEN 'URGENT'
                ELSE 'NORMAL'
            END AS priority
        FROM base
    """)


def _enrich_with_assignments(reviews: list[dict]) -> None:
    """Attach assigned_to / assignment_status / assigned_at to each result."""
    assignments = fetch_all_assignments_14d()
    if assignments.empty:
        return
    latest = assignments.sort_values("assigned_at", ascending=False).drop_duplicates(
        "review_uid", keep="first")
    asgn_map = {
        a["review_uid"]: {
            "assigned_to": a["operator_email"],
            "assignment_status": a["status"],
            "assigned_at": str(a["assigned_at"]) if a["assigned_at"] else None,
        }
        for _, a in latest.iterrows()
    }
    for r in reviews:
        asgn = asgn_map.get(r.get("review_uid"))
        if asgn:
            r["assigned_to"] = asgn["assigned_to"]
            r["assignment_status"] = asgn["assignment_status"]
            r["assigned_at"] = asgn["assigned_at"]


def _enrich_with_qc(reviews: list[dict]) -> None:
    """Attach QC match flags from ops_log remarks."""
    ops = fetch_recent_ops_log()
    if ops.empty:
        return
    qc_ops = ops[
        (ops["action"] == "mark_responded") &
        (ops["remarks"].str.contains("resp:", na=False))
    ]
    if qc_ops.empty:
        return
    qc_latest = qc_ops.sort_values("processing_timestamp", ascending=False).drop_duplicates(
        "review_uid", keep="first")
    qc_map = {
        o["review_uid"]: {
            "qc_response_match": "resp:exact" in str(o["remarks"]),
            "qc_discount_match": "disc:exact" in str(o["remarks"]),
        }
        for _, o in qc_latest.iterrows()
    }
    for r in reviews:
        qc = qc_map.get(r.get("review_uid"))
        if qc:
            r["qc_response_match"] = qc["qc_response_match"]
            r["qc_discount_match"] = qc["qc_discount_match"]
