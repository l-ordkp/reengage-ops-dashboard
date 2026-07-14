"""Reviews API — list, stats, filter options, search, generate."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user, require_lead
from backend.managers.review_manager import (
    get_filter_options, get_review_stats, list_reviews, search_reviews,
)
from backend.repositories.config_repository import fetch_configs_for_matching
from backend.repositories.review_repository import fetch_reviews_14d
from backend.schemas.reviews import GenerateBatchBody

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("")
def list_endpoint(
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
    return list_reviews(
        chain_name=chain_name, platform=platform, status=status, priority=priority,
        has_response=has_response, assigned_to=assigned_to,
        page=page, page_size=page_size,
    )


@router.get("/stats")
def stats_endpoint(chain_name: Optional[str] = None, user: dict = Depends(get_current_user)):
    return get_review_stats(chain_name)


@router.get("/filters")
def filters_endpoint(user: dict = Depends(get_current_user)):
    return get_filter_options()


@router.get("/search")
def search_endpoint(
    field: Optional[str] = None,
    query: Optional[str] = None,
    customer_name: Optional[str] = None,
    chain_name: Optional[str] = None,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    has_response: Optional[str] = None,
    user: dict = Depends(require_lead),
):
    return search_reviews(
        field=field, query=query,
        customer_name=customer_name, chain_name=chain_name,
        platform=platform, status=status, priority=priority,
        has_response=has_response,
    )


@router.post("/generate-batch")
def generate_batch(body: GenerateBatchBody, user: dict = Depends(get_current_user)):
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    from backend.managers.response_manager import find_matching_config, generate_and_save
    from backend.repositories.response_repository import fetch_responded_order_ids
    from fastapi import HTTPException

    # Review text/metadata doesn't change within a run, so reuse the cached
    # 14-day reviews instead of busting the cache and re-scanning BigQuery.
    # Cross-chunk dedup (skipping reviews an earlier chunk just generated) is
    # handled below by reading already-responded order_ids straight from
    # PostgreSQL — authoritative and lag-free, for a fraction of the cost.
    df = fetch_reviews_14d()
    configs = fetch_configs_for_matching()
    if not configs:
        raise HTTPException(status_code=400, detail="No response configs found")

    # Order_ids in this chunk that already have a response (skip unless forced).
    if body.force:
        already_responded: set = set()
    else:
        chunk_df = df[df["review_uid"].isin(set(body.review_uids))]
        already_responded = fetch_responded_order_ids(
            chunk_df["order_id"].dropna().unique().tolist()
        )

    results = {"success": 0, "skipped": 0, "failed": 0, "details": []}
    results_lock = Lock()

    def record(entry: dict, bucket: str) -> None:
        with results_lock:
            results[bucket] += 1
            results["details"].append(entry)

    def process_uid(uid: str) -> None:
        row = df[df["review_uid"] == uid]
        if row.empty:
            record({"uid": uid, "status": "skipped", "reason": "review not found"}, "skipped")
            return

        review_dict = row.iloc[0].to_dict()

        # Skip if already generated — either per the cached reviews snapshot
        # (prior runs) or the fresh PostgreSQL lookup (earlier chunk this run).
        existing_response = review_dict.get("response_text")
        if not body.force and (
            review_dict.get("order_id") in already_responded
            or (existing_response and pd.notna(existing_response))
        ):
            record({"uid": uid, "status": "skipped", "reason": "already generated"}, "skipped")
            return

        config = find_matching_config(review_dict, configs)
        if not config:
            record({"uid": uid, "status": "skipped", "reason": "no matching config"}, "skipped")
            return

        try:
            result = generate_and_save(review_dict, config)
            if result.get("saved"):
                record({"uid": uid, "status": "success"}, "success")
            elif result.get("response_text"):
                record({"uid": uid, "status": "success", "note": "generated but DB save failed"}, "success")
            else:
                record({"uid": uid, "status": "failed", "reason": result.get("errors", "generation failed")}, "failed")
        except Exception as e:
            record({"uid": uid, "status": "failed", "reason": f"{type(e).__name__}: {e}"}, "failed")

    # 5-worker cap respects PG pool (3 + 5 overflow shared across endpoints)
    # and OpenAI rate limits for gpt-4.1-nano default tier.
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(process_uid, body.review_uids))

    # Audit trail: one ops_log row per chunk, summarising who did what.
    # Surface chain/platform when the chunk is uniform (common after chain-scoped
    # generate); otherwise mark "all" so downstream filters still work.
    from backend.repositories.pg_reengage_repository import log_action

    chunk_uids = set(body.review_uids)
    chunk_rows = df[df["review_uid"].isin(chunk_uids)]
    unique_chains = chunk_rows["chain_name"].dropna().unique().tolist() if not chunk_rows.empty else []
    unique_platforms = chunk_rows["platform"].dropna().unique().tolist() if not chunk_rows.empty else []
    chain_label = unique_chains[0] if len(unique_chains) == 1 else "all"
    platform_label = unique_platforms[0] if len(unique_platforms) == 1 else "all"

    force_flag = " force" if body.force else ""
    log_action(
        review_uid="batch",
        platform=platform_label,
        chain_name=chain_label,
        action="generate_batch",
        operator_email=user["email"],
        performed_by=user["email"],
        remarks=(
            f"requested={len(body.review_uids)} success={results['success']} "
            f"skipped={results['skipped']} failed={results['failed']}{force_flag}"
        ),
    )

    return results
