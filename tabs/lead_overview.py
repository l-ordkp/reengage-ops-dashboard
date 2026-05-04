"""Lead Overview tab — operator performance tracking and assignment drill-down."""

import pandas as pd
import streamlit as st

from config import PRIORITY_ICON, STATUS_ICON
from data_loaders import (
    load_assignments,
    load_operator_performance,
    load_operator_daily_breakdown,
    load_operator_chain_breakdown,
)
from auth import load_all_users


def render(df_all):
    st.subheader("Operator Assignments Overview")

    assignments = load_assignments()
    users_df = load_all_users()

    if assignments.empty:
        st.info("No assignments yet. Run the assignment engine or wait for the 8 AM daily run.")
        return

    # ── Section A: Team overview metrics ─────────────────────────────────────
    pending_a = assignments[assignments["status"] == "pending"]
    completed_a = assignments[assignments["status"] == "completed"]
    expired_a = assignments[assignments["status"] == "expired"]

    total_done = len(completed_a) + len(expired_a)
    team_rate = (len(completed_a) / total_done * 100) if total_done > 0 else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Assigned", f"{len(assignments):,}")
    m2.metric("Pending", f"{len(pending_a):,}")
    m3.metric("Completed", f"{len(completed_a):,}")
    m4.metric("Expired", f"{len(expired_a):,}")
    m5.metric("Team Completion Rate", f"{team_rate:.0f}%")

    st.divider()

    # ── Section B: Operator performance table ────────────────────────────────
    st.markdown("### Operator Performance")
    st.caption("Last 14 days. Completion rate = completed / (completed + expired).")

    perf = load_operator_performance()

    if not perf.empty:
        if not users_df.empty:
            perf = perf.merge(
                users_df[["email", "name", "role"]],
                left_on="operator_email", right_on="email", how="left",
            ).drop(columns=["email"], errors="ignore")
        else:
            perf["name"] = perf["operator_email"]
            perf["role"] = ""

        perf_display = perf[[
            "name", "operator_email", "role",
            "total_assigned", "assigned_today", "assigned_this_week",
            "completed", "expired", "pending",
            "completion_rate",
        ]].copy()
        perf_display = perf_display.sort_values("total_assigned", ascending=False)

        st.dataframe(
            perf_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "name": "Name",
                "operator_email": "Email",
                "role": "Role",
                "total_assigned": st.column_config.NumberColumn("Total", help="Total assigned last 14d"),
                "assigned_today": st.column_config.NumberColumn("Today"),
                "assigned_this_week": st.column_config.NumberColumn("This Week"),
                "completed": st.column_config.NumberColumn("Completed"),
                "expired": st.column_config.NumberColumn("Missed"),
                "pending": st.column_config.NumberColumn("Pending"),
                "completion_rate": st.column_config.ProgressColumn(
                    "Completion %", min_value=0, max_value=100, format="%.0f%%"
                ),
            },
        )
    else:
        st.info("No operator performance data available.")

    st.divider()

    # ── Section C: Date-wise completion ──────────────────────────────────────
    st.markdown("### Date-wise Completion")
    st.caption("Which operator missed the most reviews on which day.")

    daily = load_operator_daily_breakdown()

    if not daily.empty:
        # Merge names
        if not users_df.empty:
            daily = daily.merge(
                users_df[["email", "name"]],
                left_on="operator_email", right_on="email", how="left",
            ).drop(columns=["email"], errors="ignore")
            daily["name"] = daily["name"].fillna(daily["operator_email"])
        else:
            daily["name"] = daily["operator_email"]

        # Date range picker
        all_dates = sorted(daily["assign_date"].unique())
        col_from, col_to = st.columns(2)
        with col_from:
            date_from = st.date_input("From", value=all_dates[0], min_value=all_dates[0],
                                      max_value=all_dates[-1], key="lo_date_from")
        with col_to:
            date_to = st.date_input("To", value=all_dates[-1], min_value=all_dates[0],
                                    max_value=all_dates[-1], key="lo_date_to")

        filtered = daily[(daily["assign_date"] >= pd.Timestamp(date_from).date())
                         & (daily["assign_date"] <= pd.Timestamp(date_to).date())]

        if filtered.empty:
            st.info("No data in the selected date range.")
        else:
            detail = filtered[[
                "assign_date", "name", "assigned", "completed", "expired", "pending", "completion_pct"
            ]].sort_values(["assign_date", "name"], ascending=[False, True])

            st.dataframe(
                detail,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "assign_date": "Date",
                    "name": "Operator",
                    "assigned": st.column_config.NumberColumn("Assigned"),
                    "completed": st.column_config.NumberColumn("Completed"),
                    "expired": st.column_config.NumberColumn("Missed"),
                    "pending": st.column_config.NumberColumn("Pending"),
                    "completion_pct": st.column_config.ProgressColumn(
                        "Completion %", min_value=0, max_value=100, format="%.0f%%"
                    ),
                },
            )
    else:
        st.info("No daily data available.")

    st.divider()

    # ── Section D: Chain x platform breakdown per operator ───────────────────
    st.markdown("### Chain x Platform Breakdown")
    st.caption("Select an operator to see their assignment breakdown by chain and platform.")

    chain_data = load_operator_chain_breakdown()

    if not chain_data.empty:
        operator_list = sorted(chain_data["operator_email"].unique().tolist())
        selected_chain_op = st.selectbox(
            "Select operator", operator_list, key="lo_chain_op",
        )

        op_chains = chain_data[chain_data["operator_email"] == selected_chain_op].copy()
        op_chains["completion_rate"] = op_chains.apply(
            lambda r: r["completed"] / (r["completed"] + r["expired"]) * 100
            if (r["completed"] + r["expired"]) > 0 else 0, axis=1
        )

        # Group by chain — each chain is a collapsed expander
        for chain_name, chain_grp in op_chains.groupby("chain_name"):
            total = int(chain_grp["assigned"].sum())
            done = int(chain_grp["completed"].sum())
            missed = int(chain_grp["expired"].sum())
            pend = int(chain_grp["pending"].sum())
            rate = done / (done + missed) * 100 if (done + missed) > 0 else 0

            label = f"{chain_name} — {total} assigned, {done} completed, {missed} missed, {pend} pending ({rate:.0f}%)"

            with st.expander(label, expanded=False):
                st.dataframe(
                    chain_grp[["platform", "assigned", "completed", "expired", "pending", "completion_rate"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "platform": "Platform",
                        "assigned": st.column_config.NumberColumn("Assigned"),
                        "completed": st.column_config.NumberColumn("Completed"),
                        "expired": st.column_config.NumberColumn("Missed"),
                        "pending": st.column_config.NumberColumn("Pending"),
                        "completion_rate": st.column_config.ProgressColumn(
                            "Completion %", min_value=0, max_value=100, format="%.0f%%"
                        ),
                    },
                )
    else:
        st.info("No chain breakdown data available.")

    st.divider()

    # ── Section D: Drill into operator queue ─────────────────────────────────
    st.markdown("### Drill into Operator Queue")
    st.caption("View an operator's pending reviews grouped by chain and platform.")

    operator_list = sorted(pending_a["operator_email"].unique().tolist()) if not pending_a.empty else []

    if not operator_list:
        st.info("No pending assignments to drill into.")
        return

    selected_op = st.selectbox("Select operator", operator_list, key="lead_op_select")

    op_assignments = pending_a[pending_a["operator_email"] == selected_op]
    op_uids = set(op_assignments["review_uid"].tolist())

    df_op = df_all[df_all["review_uid"].isin(op_uids)].copy()
    df_op = df_op.sort_values(["chain_name", "platform", "days_left"], ascending=[True, True, True])

    if df_op.empty:
        st.info(f"No matching reviews for {selected_op}.")
        return

    # Summary metrics
    total_pending = len(df_op)
    critical_count = int((df_op["priority"] == "CRITICAL").sum())
    urgent_count = int((df_op["priority"] == "URGENT").sum())
    chains_count = df_op["chain_name"].nunique()

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Pending Reviews", total_pending)
    mc2.metric("Critical", critical_count)
    mc3.metric("Urgent", urgent_count)
    mc4.metric("Chains", chains_count)

    # Grouped expanders per chain x platform (collapsed by default, expanded if critical)
    for (chain, plat), grp in df_op.groupby(["chain_name", "platform"]):
        n = len(grp)
        crits = int((grp["priority"] == "CRITICAL").sum())
        urgents = int((grp["priority"] == "URGENT").sum())
        min_days = int(grp["days_left"].min())

        label = f"{chain} / {plat} — {n} reviews, {min_days}d left"
        if crits:
            label += f" ({crits} critical)"
        elif urgents:
            label += f" ({urgents} urgent)"

        with st.expander(label, expanded=(crits > 0)):
            show_cols = [
                "priority", "status", "days_left",
                "customer_name", "rating_display", "review_text",
                "response_text", "review_date", "portal_link",
            ]
            disp = grp[[c for c in show_cols if c in grp.columns]].copy()
            disp["priority"] = disp["priority"].map(lambda x: f"{PRIORITY_ICON.get(x, '')} {x}")
            disp["status"] = disp["status"].map(lambda x: f"{STATUS_ICON.get(x, '')} {x}")

            st.dataframe(
                disp, use_container_width=True, hide_index=True,
                column_config={
                    "portal_link": st.column_config.LinkColumn("Portal"),
                    "review_text": st.column_config.TextColumn("Review", width="medium"),
                    "response_text": st.column_config.TextColumn("AI Response", width="medium"),
                },
            )
