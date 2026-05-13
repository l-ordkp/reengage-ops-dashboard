"""Operator performance queries — direct BQ aggregations."""
from __future__ import annotations

import pandas as pd

from backend.clients.bq_client import bq_read
from backend.config import TABLE_ASSIGNMENTS
from backend.utils.cache import cached


@cached(ttl=120)
def fetch_operator_performance_14d() -> pd.DataFrame:
    """Per-operator totals over the last 14 days (completion rate = completed / total)."""
    return bq_read(f"""
        SELECT
            operator_email,
            COUNT(*) AS total_assigned,
            COUNTIF(DATE(assigned_at, 'America/Chicago') = CURRENT_DATE('America/Chicago')) AS assigned_today,
            COUNTIF(assigned_at >= TIMESTAMP(DATE_TRUNC(CURRENT_DATE('America/Chicago'), WEEK(MONDAY)))) AS assigned_this_week,
            COUNTIF(status = 'completed') AS completed,
            COUNTIF(status = 'expired') AS expired,
            COUNTIF(status = 'pending') AS pending,
            COUNTIF(status = 'reassigned') AS reassigned,
            SAFE_DIVIDE(COUNTIF(status = 'completed'), COUNT(*)) * 100 AS completion_rate
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
        GROUP BY operator_email
    """)


@cached(ttl=300)
def fetch_operator_daily_breakdown_14d() -> pd.DataFrame:
    """Per-operator, per-day metrics."""
    return bq_read(f"""
        SELECT
            operator_email,
            DATE(assigned_at, 'America/Chicago') AS assign_date,
            COUNT(*) AS assigned,
            COUNTIF(status = 'completed') AS completed,
            COUNTIF(status = 'expired') AS expired,
            COUNTIF(status = 'pending') AS pending,
            COUNTIF(status = 'reassigned') AS reassigned,
            SAFE_DIVIDE(COUNTIF(status = 'completed'), COUNT(*)) * 100 AS completion_pct
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
        GROUP BY operator_email, assign_date
        ORDER BY assign_date DESC, operator_email
    """)


@cached(ttl=300)
def fetch_operator_chain_breakdown_14d() -> pd.DataFrame:
    """Per-operator, per-chain-platform metrics."""
    return bq_read(f"""
        SELECT
            operator_email, chain_name, platform,
            COUNT(*) AS assigned,
            COUNTIF(status = 'completed') AS completed,
            COUNTIF(status = 'expired') AS expired,
            COUNTIF(status = 'pending') AS pending,
            COUNTIF(status = 'reassigned') AS reassigned
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
        GROUP BY operator_email, chain_name, platform
        ORDER BY operator_email, assigned DESC
    """)
