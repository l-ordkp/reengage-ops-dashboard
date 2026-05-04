"""Assignments routes."""

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.data_loaders import load_my_assignments, load_reviews
from backend.write_helpers import mark_assignment_completed, log_action
from backend.db import _df_to_dicts

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.get("/mine")
def my_assignments(user: dict = Depends(get_current_user)):
    my_asgn = load_my_assignments(user["email"])
    if my_asgn.empty:
        return {"assignments": [], "reviews": []}

    assigned_uids = set(my_asgn["review_uid"].tolist())
    df_all = load_reviews()
    df_q = df_all[df_all["review_uid"].isin(assigned_uids)].copy()

    asgn_map = my_asgn.set_index("review_uid")["assignment_id"].to_dict()
    df_q["assignment_id"] = df_q["review_uid"].map(asgn_map)

    platform_order = {"Doordash": 0, "UberEats": 1}
    df_q["_plat_order"] = df_q["platform"].map(platform_order).fillna(2)
    df_q = df_q.sort_values(
        ["chain_name", "_plat_order", "days_left"],
        ascending=[True, True, True]
    ).drop(columns=["_plat_order"])

    return {
        "assignments": _df_to_dicts(my_asgn),
        "reviews": _df_to_dicts(df_q),
    }


@router.post("/{assignment_id}/complete")
def complete_assignment(
    assignment_id: str,
    remarks: str = "",
    user: dict = Depends(get_current_user),
):
    mark_assignment_completed(assignment_id, user["email"])
    log_action(
        review_uid=assignment_id, platform="manual", chain_name="",
        action="mark_responded", operator_email=user["email"],
        performed_by=user["email"], remarks=remarks or "manual_dashboard",
    )
    load_my_assignments.clear()
    return {"ok": True}
