"""Chain Health aggregations."""
from __future__ import annotations

from backend.repositories.review_repository import fetch_reviews_14d
from backend.utils.serializers import df_to_dicts


def get_chain_health() -> list[dict]:
    df = fetch_reviews_14d()
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
    return df_to_dicts(ch)
