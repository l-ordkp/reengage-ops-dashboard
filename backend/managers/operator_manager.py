"""Operator performance / metrics business logic."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from backend.repositories.operator_repository import (
    fetch_operator_chain_breakdown_14d,
    fetch_operator_daily_breakdown_14d,
    fetch_operator_performance_14d,
)
from backend.repositories.ops_log_repository import fetch_qc_log, fetch_qc_mismatches
from backend.repositories.user_repository import fetch_all_users
from backend.utils.serializers import df_to_dicts


def get_performance() -> list[dict]:
    perf = fetch_operator_performance_14d()
    users = fetch_all_users()
    if not perf.empty and not users.empty:
        perf = perf.merge(
            users[["email", "name", "role"]],
            left_on="operator_email", right_on="email", how="left",
        ).drop(columns=["email"], errors="ignore")
    return df_to_dicts(perf)


def get_daily_breakdown(date_from: Optional[str] = None, date_to: Optional[str] = None) -> list[dict]:
    daily = fetch_operator_daily_breakdown_14d()
    users = fetch_all_users()
    if not daily.empty and not users.empty:
        daily = daily.merge(
            users[["email", "name"]],
            left_on="operator_email", right_on="email", how="left",
        ).drop(columns=["email"], errors="ignore")
        daily["name"] = daily["name"].fillna(daily["operator_email"])
    if date_from and not daily.empty:
        daily = daily[daily["assign_date"] >= pd.Timestamp(date_from).date()]
    if date_to and not daily.empty:
        daily = daily[daily["assign_date"] <= pd.Timestamp(date_to).date()]
    return df_to_dicts(daily)


def get_chain_breakdown(operator_email: Optional[str] = None) -> list[dict]:
    data = fetch_operator_chain_breakdown_14d()
    if operator_email and not data.empty:
        data = data[data["operator_email"] == operator_email]
    return df_to_dicts(data)


def get_qc_mismatches(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> list[dict]:
    """Per-row drilldown of QC mismatches. All data sourced from BigQuery
    (ops_log + automation_reviews + review_responses CDC mirror + users)."""
    mismatches = fetch_qc_mismatches(date_from=date_from, date_to=date_to)
    return df_to_dicts(mismatches)


def get_qc_summary(date_from: Optional[str] = None, date_to: Optional[str] = None) -> list[dict]:
    """QC accuracy from ops_log remarks. Optional date range filter."""
    qc_rows = fetch_qc_log(date_from=date_from, date_to=date_to)
    users = fetch_all_users()
    if qc_rows.empty:
        return []
    qc_rows = qc_rows.copy()
    qc_rows["resp_match"] = qc_rows["remarks"].str.contains("resp:exact", na=False)
    qc_rows["disc_match"] = qc_rows["remarks"].str.contains("disc:exact", na=False)
    summary = qc_rows.groupby("operator_email").agg(
        total_qc=("remarks", "count"),
        resp_exact=("resp_match", "sum"),
        disc_exact=("disc_match", "sum"),
    ).reset_index()
    summary["resp_accuracy"] = (summary["resp_exact"] / summary["total_qc"] * 100).round(1)
    summary["disc_accuracy"] = (summary["disc_exact"] / summary["total_qc"] * 100).round(1)
    if not users.empty:
        summary = summary.merge(
            users[["email", "name"]],
            left_on="operator_email", right_on="email", how="left",
        ).drop(columns=["email"], errors="ignore")
    return df_to_dicts(summary)
