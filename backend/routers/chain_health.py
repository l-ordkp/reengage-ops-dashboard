"""Chain health routes."""

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.data_loaders import load_reviews
from backend.db import _df_to_dicts

router = APIRouter(prefix="/api/chain-health", tags=["chain-health"])


@router.get("")
def chain_health(user: dict = Depends(get_current_user)):
    df = load_reviews()
    if df.empty:
        return []

    ch = df.groupby("chain_name").agg(
        total=("review_uid", "count"),
        responded=("status", lambda x: int((x == "RESPONDED").sum())),
        pending=("status", lambda x: int((x == "PENDING").sum())),
        expired=("status", lambda x: int((x == "EXPIRED").sum())),
        critical=("priority", lambda x: int((x == "CRITICAL").sum())),
        has_response=("response_text", lambda x: int(x.notna().sum())),
        avg_rating=("rating_numeric", "mean"),
        locations=("slug", "nunique"),
    ).reset_index()
    ch["response_rate"] = (ch["responded"] / ch["total"] * 100).round(1)
    ch["ai_coverage"] = (ch["has_response"] / ch["total"] * 100).round(1)
    ch["avg_rating"] = ch["avg_rating"].round(2)
    ch = ch.sort_values(["critical", "pending"], ascending=[False, False])

    return _df_to_dicts(ch)
