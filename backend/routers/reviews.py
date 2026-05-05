"""Reviews routes — list, stats, search, generate."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.dependencies import get_current_user, require_lead
from backend.data_loaders import load_reviews, load_configs_for_matching
from backend.db import _df_to_dicts

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("")
def list_reviews(
    chain_name: Optional[str] = None,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    has_response: Optional[str] = None,
    assigned_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    df = load_reviews().copy()

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
        from backend.data_loaders import load_my_assignments
        my_asgn = load_my_assignments(assigned_to)
        if not my_asgn.empty:
            uids = set(my_asgn["review_uid"].tolist())
            df = df[df["review_uid"].isin(uids)]
        else:
            df = df.iloc[0:0]

    total = len(df)
    start = (page - 1) * page_size
    page_df = df.iloc[start:start + page_size]

    return {
        "items": _df_to_dicts(page_df),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats")
def review_stats(chain_name: Optional[str] = None, user: dict = Depends(get_current_user)):
    df = load_reviews()
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


@router.get("/filters")
def review_filters(user: dict = Depends(get_current_user)):
    df = load_reviews()
    chains = sorted(df["chain_name"].unique().tolist()) if not df.empty else []
    platforms = sorted(df["platform"].unique().tolist()) if not df.empty else []
    return {"chains": chains, "platforms": platforms}


@router.get("/search")
def search_reviews(
    field: Optional[str] = None,
    query: Optional[str] = None,
    customer_name: Optional[str] = None,
    chain_name: Optional[str] = None,
    user: dict = Depends(require_lead),
):
    from backend.db import bq_read as _bq_read
    from backend.config import TABLE_AUTOMATION_REVIEWS, TABLE_SLUG_AM_MAPPING, TABLE_REVIEW_RESPONSES

    # First try the 14-day cached data
    df = load_reviews()

    if field and query:
        if field not in df.columns:
            raise HTTPException(status_code=400, detail=f"Unknown field: {field}")
        results = df[df[field].astype(str) == query.strip()]
        if results.empty:
            results = df[df[field].astype(str).str.contains(query.strip(), na=False, case=False)]

        # If not found in 14-day window, search historical data (90 days)
        if results.empty and field in ("order_id", "review_uid", "review_id", "customer_id"):
            safe_q = query.strip().replace("'", "''")
            id_col = "COALESCE(ar.review_id, ar.order_id)" if field == "review_uid" else f"ar.{field}"
            results = _bq_read(f"""
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
                    DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp), 'America/Chicago')) AS review_date,
                    CASE
                        WHEN ar.platform = 'Doordash' THEN
                            DATE_DIFF(DATE_ADD(DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp), 'America/Chicago')), INTERVAL 7 DAY), CURRENT_DATE('America/Chicago'), DAY)
                        WHEN ar.platform = 'UberEats' THEN
                            DATE_DIFF(DATE_ADD(DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp), 'America/Chicago')), INTERVAL 14 DAY), CURRENT_DATE('America/Chicago'), DAY)
                        ELSE 0
                    END AS days_left,
                    CASE WHEN ar.is_replied = TRUE THEN 'RESPONDED' ELSE 'EXPIRED' END AS status,
                    'NORMAL' AS priority,
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
            """)
    elif customer_name:
        subset = df if not chain_name or chain_name == "All" else df[df["chain_name"] == chain_name]
        mask = subset["customer_name"].astype(str).str.lower().str.contains(
            customer_name.strip().lower(), na=False)
        results = subset[mask]
    else:
        return []

    # Enrich with assignment info
    from backend.data_loaders import load_assignments
    assignments = load_assignments()
    review_results = _df_to_dicts(results.head(100))

    if not assignments.empty:
        # Get latest assignment per review_uid
        latest = assignments.sort_values("assigned_at", ascending=False).drop_duplicates("review_uid", keep="first")
        asgn_map = {}
        for _, a in latest.iterrows():
            asgn_map[a["review_uid"]] = {
                "assigned_to": a["operator_email"],
                "assignment_status": a["status"],
                "assigned_at": str(a["assigned_at"]) if a["assigned_at"] else None,
            }
        for r in review_results:
            asgn = asgn_map.get(r.get("review_uid"))
            if asgn:
                r["assigned_to"] = asgn["assigned_to"]
                r["assignment_status"] = asgn["assignment_status"]
                r["assigned_at"] = asgn["assigned_at"]

    return review_results


class GenerateBatchBody(BaseModel):
    review_uids: list[str]


@router.post("/generate-batch")
def generate_batch(body: GenerateBatchBody, user: dict = Depends(get_current_user)):
    from backend.response_generator import generate_and_save, find_matching_config

    df = load_reviews()
    configs = load_configs_for_matching()
    if not configs:
        raise HTTPException(status_code=400, detail="No response configs found")

    results = {"success": 0, "skipped": 0, "failed": 0, "details": []}

    for uid in body.review_uids:
        row = df[df["review_uid"] == uid]
        if row.empty:
            results["skipped"] += 1
            results["details"].append({"uid": uid, "status": "skipped", "reason": "review not found"})
            continue

        review_dict = row.iloc[0].to_dict()
        config = find_matching_config(review_dict, configs)
        if not config:
            results["skipped"] += 1
            results["details"].append({"uid": uid, "status": "skipped", "reason": "no matching config"})
            continue

        try:
            result = generate_and_save(review_dict, config)
            if result.get("saved"):
                results["success"] += 1
                results["details"].append({"uid": uid, "status": "success"})
            elif result.get("response_text"):
                # Generated but couldn't save to DB — still count as success
                results["success"] += 1
                results["details"].append({"uid": uid, "status": "success", "note": "generated but DB save failed"})
            else:
                results["failed"] += 1
                results["details"].append({"uid": uid, "status": "failed", "reason": result.get("errors", "generation failed")})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"uid": uid, "status": "failed", "reason": f"{type(e).__name__}: {e}"})

    load_reviews.clear()
    return results
