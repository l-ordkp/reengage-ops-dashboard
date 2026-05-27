"""Chain Health aggregations — totals vs in-scope, per-chain + global summary.

Math the page enforces (per chain and at the summary level):

    total           = out_of_scope + pending + responded + expired
    loop_responded  ⊆  responded            (subset, not an additional bucket)

"Responded" treats a review as replied if either the platform's
`is_replied` flag or Loop's `is_loop_replied` flag is true — avoids the
ELT lag where the platform-side confirmation takes hours-to-days to land
after our extension already marked the review.
"""
from __future__ import annotations

import pandas as pd

from backend.repositories.review_repository import (
    fetch_chain_totals_14d,
    fetch_reviews_14d,
)
from backend.utils.serializers import df_to_dicts


def get_chain_health() -> dict:
    """Return {summary, chains}. Only ReEngage-managed chains (= at least
    one non-paused review_response_config row) appear."""
    totals = fetch_chain_totals_14d()
    in_scope = fetch_reviews_14d()

    if not in_scope.empty:
        # fetch_reviews_14d's LEFT JOINs (to review_responses + assignments)
        # can multiply rows per review_uid — dedupe before aggregating.
        in_scope_unique = in_scope.drop_duplicates(subset=["review_uid"], keep="first").copy()
        # Critical / Urgent are urgency-now metrics: only PENDING reviews with
        # <=1 day / ==2 days left should count. The previous version counted
        # every review that ever passed through the critical window in 14d
        # (including responded + expired), inflating the number 5-10x.
        in_scope_unique["is_critical_pending"] = (
            (in_scope_unique["priority"] == "CRITICAL")
            & (in_scope_unique["status"] == "PENDING")
        )
        in_scope_unique["is_urgent_pending"] = (
            (in_scope_unique["priority"] == "URGENT")
            & (in_scope_unique["status"] == "PENDING")
        )
        in_scope_rollup = in_scope_unique.groupby("chain_name").agg(
            in_scope=("review_uid", "count"),
            in_scope_responded=("status", lambda x: int((x == "RESPONDED").sum())),
            pending=("status", lambda x: int((x == "PENDING").sum())),
            expired=("status", lambda x: int((x == "EXPIRED").sum())),
            in_scope_loop_responded=(
                "is_loop_replied",
                lambda x: int(x.fillna(False).astype(bool).sum()),
            ),
            critical=("is_critical_pending", "sum"),
            urgent=("is_urgent_pending", "sum"),
            has_response=("response_text", lambda x: int(x.notna().sum())),
            avg_rating=("rating_numeric", "mean"),
            locations=("slug", "nunique"),
        ).reset_index()
    else:
        in_scope_rollup = pd.DataFrame(columns=[
            "chain_name", "in_scope", "in_scope_responded", "pending", "expired",
            "in_scope_loop_responded", "critical", "urgent", "has_response",
            "avg_rating", "locations",
        ])

    if totals.empty:
        return {"summary": _empty_summary(), "chains": []}

    chains = totals.merge(in_scope_rollup, on="chain_name", how="left")

    int_cols = [
        "in_scope", "in_scope_responded", "pending", "expired",
        "in_scope_loop_responded", "critical", "urgent", "has_response", "locations",
    ]
    for col in int_cols:
        chains[col] = chains[col].fillna(0).astype(int)

    # Per-chain partition components
    chains["out_of_scope"] = (chains["total"] - chains["in_scope"]).clip(lower=0)
    # Display "Responded" + "Loop Responded" as the in-scope counts so the row
    # adds up to in_scope and (with out_of_scope) up to total.
    chains["responded"] = chains["in_scope_responded"]
    chains["loop_responded"] = chains["in_scope_loop_responded"]

    chains["response_rate"] = chains.apply(
        lambda r: round(r["responded"] / r["in_scope"] * 100, 1) if r["in_scope"] > 0 else 0.0,
        axis=1,
    )
    chains["loop_coverage"] = chains.apply(
        lambda r: round(r["loop_responded"] / r["in_scope"] * 100, 1) if r["in_scope"] > 0 else 0.0,
        axis=1,
    )
    chains["ai_coverage"] = chains.apply(
        lambda r: round(r["has_response"] / r["in_scope"] * 100, 1) if r["in_scope"] > 0 else 0.0,
        axis=1,
    )
    chains["avg_rating"] = chains["avg_rating"].round(2)

    chains = chains.sort_values(
        ["critical", "pending", "in_scope"], ascending=[False, False, False],
    )

    summary = {
        "total":          int(chains["total"].sum()),
        "out_of_scope":   int(chains["out_of_scope"].sum()),
        "in_scope":       int(chains["in_scope"].sum()),
        "pending":        int(chains["pending"].sum()),
        "responded":      int(chains["responded"].sum()),
        "loop_responded": int(chains["loop_responded"].sum()),
        "expired":        int(chains["expired"].sum()),
    }

    return {"summary": summary, "chains": df_to_dicts(chains)}


def _empty_summary() -> dict:
    return {
        "total": 0, "out_of_scope": 0, "in_scope": 0,
        "pending": 0, "responded": 0, "loop_responded": 0, "expired": 0,
    }
