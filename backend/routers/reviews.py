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
    user: dict = Depends(require_lead),
):
    return search_reviews(field=field, query=query,
                          customer_name=customer_name, chain_name=chain_name)


@router.post("/generate-batch")
def generate_batch(body: GenerateBatchBody, user: dict = Depends(get_current_user)):
    from backend.managers.response_manager import find_matching_config, generate_and_save
    from fastapi import HTTPException

    df = fetch_reviews_14d()
    configs = fetch_configs_for_matching()
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
                results["success"] += 1
                results["details"].append({"uid": uid, "status": "success", "note": "generated but DB save failed"})
            else:
                results["failed"] += 1
                results["details"].append({"uid": uid, "status": "failed", "reason": result.get("errors", "generation failed")})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"uid": uid, "status": "failed", "reason": f"{type(e).__name__}: {e}"})

    fetch_reviews_14d.clear()
    return results
