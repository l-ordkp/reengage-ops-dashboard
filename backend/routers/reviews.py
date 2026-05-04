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
    df = load_reviews()

    if field and query:
        if field not in df.columns:
            raise HTTPException(status_code=400, detail=f"Unknown field: {field}")
        results = df[df[field].astype(str) == query.strip()]
        if results.empty:
            results = df[df[field].astype(str).str.contains(query.strip(), na=False, case=False)]
    elif customer_name:
        subset = df if not chain_name or chain_name == "All" else df[df["chain_name"] == chain_name]
        mask = subset["customer_name"].astype(str).str.lower().str.contains(
            customer_name.strip().lower(), na=False)
        results = subset[mask]
    else:
        return []

    return _df_to_dicts(results.head(100))


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
