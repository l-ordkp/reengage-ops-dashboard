"""Operator performance queries — direct BQ aggregations."""
from __future__ import annotations

import pandas as pd

from backend.clients.bq_client import bq_read
from backend.config import TABLE_ASSIGNMENTS
from backend.utils.cache import cached


# Operator-throughput reporting groups by IST date: operators are in India,
# the workday and the 8 AM IST assignment cron are IST events. Grouping by
# CST would smear each shift across two CST date buckets.
_OBSERVED_OOW_FILTER = (
    # Drop rows where the extension's /observed-responded flow flagged the
    # underlying review as past the platform deadline. These are real Loop
    # replies (Chain Value counts them) but shouldn't inflate operators'
    # "today's work" view since the actual reply was sent days/weeks ago.
    "NOT IFNULL(observed_out_of_window, FALSE)"
)


@cached(ttl=120)
def fetch_operator_performance_14d() -> pd.DataFrame:
    """Per-operator totals over the last 14 IST days (completion rate = completed / total).

    Filters out `status='auto_resolved'` rows — those are external replies
    (merchant or third-party) that PR-A stamps with `operator_email=''`.
    Counting them would surface a phantom group in the leaderboard with
    bogus `total_assigned`.

    Also filters out `observed_out_of_window=TRUE` rows — those represent
    late observations of reviews already past the platform deadline (the
    Loop reply happened days/weeks ago via the portal UI). Counting them
    would credit operators for "today's work" that was actually historical.
    """
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
          AND status != 'auto_resolved'
          AND {_OBSERVED_OOW_FILTER}
        GROUP BY operator_email
    """)


@cached(ttl=300)
def fetch_operator_daily_breakdown_14d() -> pd.DataFrame:
    """Per-operator, per-IST-day metrics. Excludes auto_resolved and
    out-of-window observations (see fetch_operator_performance_14d)."""
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
          AND status != 'auto_resolved'
          AND {_OBSERVED_OOW_FILTER}
        GROUP BY operator_email, assign_date
        ORDER BY assign_date DESC, operator_email
    """)


@cached(ttl=300)
def fetch_daily_loop_completed_14d() -> pd.DataFrame:
    """One row per IST calendar day, last 14 days, with the count of assignments
    Loop ops marked completed that day. IST so each bar aligns with one
    operator workday (CST would split a shift across two bars). Densified —
    days with zero completions still appear as 0 so the chart doesn't skip.

    Filters out `observed_out_of_window=TRUE` rows so late observations of
    long-past Loop replies don't show up as spikes on the day they were
    observed (they'd otherwise inflate "today" whenever someone scrolls
    through old portal pages).
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
              AND {_OBSERVED_OOW_FILTER}
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
def fetch_daily_ingested_14d() -> pd.DataFrame:
    """One row per IST calendar day, last 14 days, with the count of distinct
    reviews that first entered the assignment system that day. "First entered"
    means MIN(assigned_at) per review_uid — the daily 8 AM IST cron INSERTs a
    fresh row on every rebuild, so the earliest assigned_at is the first time
    the review was surfaced to operators. Densified — days with zero ingested
    still appear as 0 so the chart aligns 1:1 with daily-loop-completed.
    """
    return bq_read(f"""
        WITH days AS (
            SELECT DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL n DAY) AS d
            FROM UNNEST(GENERATE_ARRAY(0, 13)) AS n
        ),
        first_seen AS (
            SELECT review_uid, MIN(assigned_at) AS first_assigned_at
            FROM `{TABLE_ASSIGNMENTS}`
            GROUP BY review_uid
        ),
        ingested AS (
            SELECT
                DATE(first_assigned_at, 'Asia/Kolkata') AS d,
                COUNT(*) AS ingested
            FROM first_seen
            WHERE DATE(first_assigned_at, 'Asia/Kolkata')
                  >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 13 DAY)
            GROUP BY d
        )
        SELECT
            days.d AS date,
            COALESCE(ingested.ingested, 0) AS ingested
        FROM days
        LEFT JOIN ingested USING (d)
        ORDER BY date ASC
    """)


@cached(ttl=300)
def fetch_operator_chain_breakdown_14d() -> pd.DataFrame:
    """Per-operator, per-chain-platform metrics (last 14 IST days). Excludes
    auto_resolved and out-of-window observations (see
    fetch_operator_performance_14d for rationale)."""
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
          AND status != 'auto_resolved'
          AND {_OBSERVED_OOW_FILTER}
        GROUP BY operator_email, chain_name, platform
        ORDER BY operator_email, assigned DESC
    """)
