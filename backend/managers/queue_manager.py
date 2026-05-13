"""My Queue business logic — operator's assigned reviews enriched with review details."""
from __future__ import annotations

from backend.repositories.assignment_repository import fetch_my_pending_assignments
from backend.repositories.review_repository import fetch_reviews_14d
from backend.utils.serializers import df_to_dicts


def get_my_queue(email: str) -> dict:
    """
    Returns {assignments, reviews} where reviews are joined with the operator's pending assignments.
    Matches by both review_uid and order_id because DoorDash review_uid != order_id.
    """
    my_asgn = fetch_my_pending_assignments(email)
    if my_asgn.empty:
        return {"assignments": [], "reviews": []}

    assigned_uids = set(my_asgn["review_uid"].tolist())
    assigned_oids = set(my_asgn["order_id"].tolist())
    df_all = fetch_reviews_14d()
    df_q = df_all[df_all["review_uid"].isin(assigned_uids) | df_all["order_id"].isin(assigned_oids)].copy()

    asgn_map_uid = my_asgn.set_index("review_uid")["assignment_id"].to_dict()
    asgn_map_oid = my_asgn.set_index("order_id")["assignment_id"].to_dict()
    df_q["assignment_id"] = df_q["review_uid"].map(asgn_map_uid).fillna(df_q["order_id"].map(asgn_map_oid))

    platform_order = {"Doordash": 0, "UberEats": 1}
    df_q["_plat_order"] = df_q["platform"].map(platform_order).fillna(2)
    df_q = df_q.sort_values(
        ["chain_name", "_plat_order", "days_left"],
        ascending=[True, True, True]
    ).drop(columns=["_plat_order"])

    return {
        "assignments": df_to_dicts(my_asgn),
        "reviews": df_to_dicts(df_q),
    }
