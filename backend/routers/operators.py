"""Operators routes — performance metrics, daily breakdown, chain breakdown, queue."""

from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends

from backend.auth.dependencies import require_lead
from backend.auth.user_crud import load_all_users
from backend.data_loaders import (
    load_operator_performance,
    load_operator_daily_breakdown,
    load_operator_chain_breakdown,
    load_assignments,
    load_reviews,
)
from backend.db import _df_to_dicts

router = APIRouter(prefix="/api/operators", tags=["operators"])


@router.get("/performance")
def performance(user: dict = Depends(require_lead)):
    perf = load_operator_performance()
    users_df = load_all_users()

    if not perf.empty and not users_df.empty:
        perf = perf.merge(
            users_df[["email", "name", "role"]],
            left_on="operator_email", right_on="email", how="left",
        ).drop(columns=["email"], errors="ignore")

    return _df_to_dicts(perf)


@router.get("/daily-breakdown")
def daily_breakdown(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_lead),
):
    daily = load_operator_daily_breakdown()
    users_df = load_all_users()

    if not daily.empty and not users_df.empty:
        daily = daily.merge(
            users_df[["email", "name"]],
            left_on="operator_email", right_on="email", how="left",
        ).drop(columns=["email"], errors="ignore")
        daily["name"] = daily["name"].fillna(daily["operator_email"])

    if date_from and not daily.empty:
        daily = daily[daily["assign_date"] >= pd.Timestamp(date_from).date()]
    if date_to and not daily.empty:
        daily = daily[daily["assign_date"] <= pd.Timestamp(date_to).date()]

    return _df_to_dicts(daily)


@router.get("/chain-breakdown")
def chain_breakdown(
    operator_email: Optional[str] = None,
    user: dict = Depends(require_lead),
):
    data = load_operator_chain_breakdown()
    if operator_email and not data.empty:
        data = data[data["operator_email"] == operator_email]
    return _df_to_dicts(data)


@router.get("/{email}/queue")
def operator_queue(email: str, user: dict = Depends(require_lead)):
    assignments = load_assignments()
    pending = assignments[(assignments["status"] == "pending") & (assignments["operator_email"] == email)]

    if pending.empty:
        return {"reviews": [], "combos": []}

    uids = set(pending["review_uid"].tolist())
    df_all = load_reviews()
    df_op = df_all[df_all["review_uid"].isin(uids)].copy()
    df_op = df_op.sort_values(["chain_name", "platform", "days_left"])

    combos = df_op.groupby(["chain_name", "platform"]).agg(
        count=("review_uid", "count"),
        critical=("priority", lambda x: int((x == "CRITICAL").sum())),
        min_days=("days_left", "min"),
    ).reset_index()

    return {
        "reviews": _df_to_dicts(df_op),
        "combos": _df_to_dicts(combos),
    }


@router.get("/qc-summary")
def qc_summary(user: dict = Depends(require_lead)):
    """QC accuracy metrics per operator from ops_log remarks."""
    from backend.data_loaders import load_ops_log
    ops = load_ops_log()
    users_df = load_all_users()

    if ops.empty:
        return []

    # Filter to mark_responded actions with QC data
    qc_rows = ops[
        (ops["action"] == "mark_responded") &
        (ops["remarks"].str.contains("resp:", na=False))
    ].copy()

    if qc_rows.empty:
        return []

    qc_rows["resp_match"] = qc_rows["remarks"].str.contains("resp:exact", na=False)
    qc_rows["disc_match"] = qc_rows["remarks"].str.contains("disc:exact", na=False)

    summary = qc_rows.groupby("operator_email").agg(
        total_qc=("remarks", "count"),
        resp_exact=("resp_match", "sum"),
        disc_exact=("disc_match", "sum"),
    ).reset_index()

    summary["resp_accuracy"] = (summary["resp_exact"] / summary["total_qc"] * 100).round(1)
    summary["disc_accuracy"] = (summary["disc_exact"] / summary["total_qc"] * 100).round(1)

    if not users_df.empty:
        summary = summary.merge(
            users_df[["email", "name"]],
            left_on="operator_email", right_on="email", how="left",
        ).drop(columns=["email"], errors="ignore")

    return _df_to_dicts(summary)
