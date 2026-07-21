"""Operator performance queries — direct BQ aggregations."""
from __future__ import annotations

import pandas as pd

from backend.clients.bq_client import bq_read
from backend.config import TABLE_ASSIGNMENTS_READ, TABLE_OPS_LOG_READ, TABLE_USERS
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

# Keep only rows whose operator_email is an actual team member. The extension's
# `missed_but_ours` flow stamps `operator_email` with the matched Loop *portal
# username* (e.g. haven_hot_chicken@fmtfoods.net) — that's the account the reply
# was posted from, NOT a Loop operator. Those rows are status='completed', so
# the auto_resolved filter doesn't catch them; without this join they surface as
# phantom operators in the leaderboard. Matched case-insensitively because auth
# normalises emails with LOWER().
_OPERATOR_IN_USERS_FILTER = (
    f"LOWER(operator_email) IN (SELECT LOWER(email) FROM `{TABLE_USERS}`)"
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

    Finally, joins to the users table (`_OPERATOR_IN_USERS_FILTER`) so only
    real team members appear — the `missed_but_ours` flow stamps the matched
    Loop portal username into `operator_email`, which would otherwise surface
    portal accounts (e.g. haven_hot_chicken@fmtfoods.net) as phantom operators.
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
        FROM `{TABLE_ASSIGNMENTS_READ}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 14 DAY), 'Asia/Kolkata')
          AND status != 'auto_resolved'
          AND {_OBSERVED_OOW_FILTER}
          AND {_OPERATOR_IN_USERS_FILTER}
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
        FROM `{TABLE_ASSIGNMENTS_READ}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 14 DAY), 'Asia/Kolkata')
          AND status != 'auto_resolved'
          AND {_OBSERVED_OOW_FILTER}
          AND {_OPERATOR_IN_USERS_FILTER}
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
            FROM `{TABLE_ASSIGNMENTS_READ}`
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
    """One row per IST calendar day, last 14 days, with the count of new scoped
    reviews that entered the system that day. Source of truth is the
    first_seen ledger (action='first_seen' rows in ops_log, written by the
    daily cron's gate) — NOT assignment rows, which since the focused
    algorithm reflect prioritization, not arrival. MIN(processing_timestamp)
    per review_uid guards against the rare double-write race. Densified —
    days with zero ingested still appear as 0 so the chart aligns 1:1 with
    daily-loop-completed.
    """
    return bq_read(f"""
        WITH days AS (
            SELECT DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL n DAY) AS d
            FROM UNNEST(GENERATE_ARRAY(0, 13)) AS n
        ),
        first_seen AS (
            SELECT review_uid, MIN(processing_timestamp) AS first_seen_at
            FROM `{TABLE_OPS_LOG_READ}`
            WHERE action = 'first_seen'
            GROUP BY review_uid
        ),
        ingested AS (
            SELECT
                DATE(first_seen_at, 'Asia/Kolkata') AS d,
                COUNT(*) AS ingested
            FROM first_seen
            WHERE DATE(first_seen_at, 'Asia/Kolkata')
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
        FROM `{TABLE_ASSIGNMENTS_READ}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 14 DAY), 'Asia/Kolkata')
          AND status != 'auto_resolved'
          AND {_OBSERVED_OOW_FILTER}
          AND {_OPERATOR_IN_USERS_FILTER}
        GROUP BY operator_email, chain_name, platform
        ORDER BY operator_email, assigned DESC
    """)
