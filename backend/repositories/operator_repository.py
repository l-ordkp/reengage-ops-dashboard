"""Operator performance queries — direct BQ aggregations."""
from __future__ import annotations

import pandas as pd

from backend.clients.bq_client import bq_read
from backend.config import TABLE_ASSIGNMENTS
from backend.utils.cache import cached


# Operator-throughput reporting groups by IST date: operators are in India,
# the workday and the 8 AM IST assignment cron are IST events. Grouping by
# CST would smear each shift across two CST date buckets.
@cached(ttl=120)
def fetch_operator_performance_14d() -> pd.DataFrame:
    """Per-operator totals over the last 14 IST days (completion rate = completed / total)."""
    return bq_read(f"""
        SELECT
            operator_email,
            COUNT(*) AS total_assigned,
            COUNTIF(DATE(assigned_at, 'Asia/Kolkata') = CURRENT_DATE('Asia/Kolkata')) AS assigned_today,
            COUNTIF(assigned_at >= TIMESTAMP(DATE_TRUNC(CURRENT_DATE('Asia/Kolkata'), WEEK(MONDAY)), 'Asia/Kolkata')) AS assigned_this_week,
            COUNTIF(status = 'completed') AS completed,
            COUNTIF(status = 'expired') AS expired,
            COUNTIF(status = 'pending') AS pending,
            COUNTIF(status = 'reassigned') AS reassigned,
            SAFE_DIVIDE(COUNTIF(status = 'completed'), COUNT(*)) * 100 AS completion_rate
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 14 DAY), 'Asia/Kolkata')
        GROUP BY operator_email
    """)


@cached(ttl=300)
def fetch_operator_daily_breakdown_14d() -> pd.DataFrame:
    """Per-operator, per-IST-day metrics."""
    return bq_read(f"""
        SELECT
            operator_email,
            DATE(assigned_at, 'Asia/Kolkata') AS assign_date,
            COUNT(*) AS assigned,
            COUNTIF(status = 'completed') AS completed,
            COUNTIF(status = 'expired') AS expired,
            COUNTIF(status = 'pending') AS pending,
            COUNTIF(status = 'reassigned') AS reassigned,
            SAFE_DIVIDE(COUNTIF(status = 'completed'), COUNT(*)) * 100 AS completion_pct
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 14 DAY), 'Asia/Kolkata')
        GROUP BY operator_email, assign_date
        ORDER BY assign_date DESC, operator_email
    """)


@cached(ttl=300)
def fetch_daily_loop_completed_14d() -> pd.DataFrame:
    """One row per IST calendar day, last 14 days, with the count of assignments
    Loop ops marked completed that day. IST so each bar aligns with one
    operator workday (CST would split a shift across two bars). Densified —
    days with zero completions still appear as 0 so the chart doesn't skip.
    """
    return bq_read(f"""
        WITH days AS (
            SELECT DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL n DAY) AS d
            FROM UNNEST(GENERATE_ARRAY(0, 13)) AS n
        ),
        completions AS (
            SELECT
                DATE(completed_at, 'Asia/Kolkata') AS d,
                COUNT(*) AS loop_completed
            FROM `{TABLE_ASSIGNMENTS}`
            WHERE status = 'completed'
              AND completed_at IS NOT NULL
              AND DATE(completed_at, 'Asia/Kolkata')
                  >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 13 DAY)
            GROUP BY d
        )
        SELECT
            days.d AS date,
            COALESCE(completions.loop_completed, 0) AS loop_completed
        FROM days
        LEFT JOIN completions USING (d)
        ORDER BY date ASC
    """)


@cached(ttl=300)
def fetch_operator_chain_breakdown_14d() -> pd.DataFrame:
    """Per-operator, per-chain-platform metrics (last 14 IST days)."""
    return bq_read(f"""
        SELECT
            operator_email, chain_name, platform,
            COUNT(*) AS assigned,
            COUNTIF(status = 'completed') AS completed,
            COUNTIF(status = 'expired') AS expired,
            COUNTIF(status = 'pending') AS pending,
            COUNTIF(status = 'reassigned') AS reassigned
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 14 DAY), 'Asia/Kolkata')
        GROUP BY operator_email, chain_name, platform
        ORDER BY operator_email, assigned DESC
    """)
