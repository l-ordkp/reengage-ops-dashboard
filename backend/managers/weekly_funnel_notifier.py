"""Post last week's review ACTIVITY (flow) to Slack.

Posts every Friday (piggybacking on the daily 8 AM IST assignment cron — see
`maybe_send_weekly_funnel`) for the previous Fri–Thu week. Unlike a posted-cohort
funnel, this is a FLOW report: it counts events that HAPPENED during the week,
each bucketed by its OWN event date (America/Chicago), regardless of when the
review was posted:

  • Ingested  — reviews POSTED in the week.
  • Solved    — reviews Loop-COMPLETED in the week (by assignment completed_at).
  • Expired   — reviews whose DEADLINE fell in the week and were not replied by
                that deadline (can include reviews posted up to 7/14 days earlier).

These are three independent populations — they do NOT sum. Pending is
intentionally omitted (it's a stock, i.e. "waiting right now", not a weekly
event). Because Expired is bucketed by deadline date, everything it counts has
already matured, so it shows the real number (no "fresh week reads ~0" artifact
that a posted-cohort funnel has).

Definitions / caveats:
  • Expired = deadline in-window AND NOT replied-by-deadline, where
    "replied-by-deadline" = platform is_replied OR an external auto_resolved
    assignment (both assumed timely — the platform gives no reply timestamp) OR
    a Loop completion whose completed_at <= the deadline. So a Loop reply that
    landed AFTER the deadline correctly still counts as a miss.
  • Solved counts Loop completions only (reliable completed_at). External
    replies have no trustworthy reply time, so they're not attributed to a week.
  • Expired keeps the late_ingestion_N / ingested_after_expiry breakdown
    (root cause: days from posted to first queued).

In-scope universe mirrors the dashboard: `automation_reviews` ⨝ `slug_am_mapping`,
scoped to a non-paused `review_response_config`, one row per review_uid (latest).

Slack failures are logged and swallowed — never raises.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from backend.clients.bq_client import bq_read
from backend.clients.slack_client import post_message
from backend.config import (
    TABLE_ASSIGNMENTS,
    TABLE_AUTOMATION_REVIEWS,
    TABLE_REVIEW_RESPONSE_CFG,
    TABLE_SLUG_AM_MAPPING,
)


_CHANNEL = "#reengage-bot-notifications"
# Gated on / anchored to the IST run day: the daily cron fires at 8 AM IST,
# which is still the prior evening in CT. Anchoring the week to CT would read
# one day earlier and report a week behind. (Event dates are bucketed in
# America/Chicago inside the SQL.)
_IST = timezone(timedelta(hours=5, minutes=30))
_FRIDAY = 4  # datetime.weekday(): Mon=0 … Fri=4

log = logging.getLogger(__name__)


def _last_week_window() -> tuple[str, str]:
    """Most recently completed Fri–Thu week, anchored to the IST run day, as ISO
    dates. Run on Fri Jul 3 -> ('2026-06-26', '2026-07-02'). Robust to any run
    day: always the last full Fri–Thu before the current week's Friday."""
    today = datetime.now(_IST).date()
    days_since_friday = (today.weekday() - _FRIDAY) % 7
    current_week_start = today - timedelta(days=days_since_friday)  # this week's Friday
    start = current_week_start - timedelta(days=7)                  # last week's Friday
    end = current_week_start - timedelta(days=1)                    # last Thursday
    return start.isoformat(), end.isoformat()


def _in_scope_exists(review_alias: str = "ar", chain_expr: str = "sm.chain") -> str:
    """In-scope filter, shared verbatim with the dashboard (review_repository.py)."""
    return f"""
        EXISTS (
          SELECT 1 FROM `{TABLE_REVIEW_RESPONSE_CFG}` rc
          WHERE rc.paused=FALSE AND {chain_expr}=rc.chain_name
            AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.vb_platforms),[]))=0      OR {review_alias}.platform IN UNNEST(JSON_VALUE_ARRAY(rc.vb_platforms)))
            AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.ratings),[]))=0           OR CAST({review_alias}.star_rating AS STRING) IN UNNEST(JSON_VALUE_ARRAY(rc.ratings)) OR {review_alias}.rating_value IN UNNEST(JSON_VALUE_ARRAY(rc.ratings)))
            AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.customer_types),[]))=0    OR (CASE WHEN SAFE_CAST({review_alias}.orders_count AS INT64)>1 THEN 'existing' ELSE 'new' END) IN UNNEST(JSON_VALUE_ARRAY(rc.customer_types)))
            AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.feedback_presence),[]))=0 OR (CASE WHEN COALESCE(TRIM({review_alias}.review_text),'')='' THEN 'without_feedback' ELSE 'with_feedback' END) IN UNNEST(JSON_VALUE_ARRAY(rc.feedback_presence)))
        )
    """


def _fetch_review_flow(start_date: str, end_date: str) -> list[dict]:
    """From `automation_reviews`: the INGESTED count (posted in window) and the
    EXPIRED breakdown (deadline in window, not replied by deadline). Returns rows
    with columns: metric ('INGESTED'|'EXPIRED'), bucket, reviews, doordash,
    ubereats. Solved is fetched separately (assignments table)."""
    sql = f"""
        WITH
        -- external reply signal (assumed timely; no platform reply timestamp)
        auto_res AS (
          SELECT DISTINCT key FROM (
            SELECT review_uid AS key FROM `{TABLE_ASSIGNMENTS}` WHERE status='auto_resolved'
            UNION ALL
            SELECT order_id  AS key FROM `{TABLE_ASSIGNMENTS}` WHERE status='auto_resolved' AND order_id IS NOT NULL
          )
        ),
        -- earliest Loop completion time per key (for replied-by-deadline test)
        loop_done AS (
          SELECT key, MIN(completed_at) AS completed_at FROM (
            SELECT review_uid AS key, completed_at FROM `{TABLE_ASSIGNMENTS}` WHERE status='completed' AND completed_at IS NOT NULL
            UNION ALL
            SELECT order_id  AS key, completed_at FROM `{TABLE_ASSIGNMENTS}` WHERE status='completed' AND completed_at IS NOT NULL AND order_id IS NOT NULL
          ) GROUP BY key
        ),
        -- first time a review ever entered our queue (late_ingestion_N)
        asg_first AS (
          SELECT key, MIN(assigned_at) AS first_assigned FROM (
            SELECT review_uid AS key, assigned_at FROM `{TABLE_ASSIGNMENTS}`
            UNION ALL
            SELECT order_id  AS key, assigned_at FROM `{TABLE_ASSIGNMENTS}` WHERE order_id IS NOT NULL
          ) GROUP BY key
        ),
        base AS (
          SELECT
            COALESCE(ar.review_id, ar.order_id) AS review_uid, ar.order_id, ar.review_id, ar.platform, ar.is_replied,
            DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp),'America/Chicago')) AS posted_date,
            CASE WHEN ar.platform='Doordash' THEN TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7  DAY)
                 WHEN ar.platform='UberEats' THEN TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 14 DAY)
                 ELSE TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7 DAY) END AS deadline_ts
          FROM `{TABLE_AUTOMATION_REVIEWS}` AS ar
          INNER JOIN `{TABLE_SLUG_AM_MAPPING}` AS sm ON ar.slug = sm.slug
          -- Scan wide enough for BOTH legs: ingested (posted in window) AND expired
          -- (deadline in window => posted up to 14 days earlier). ±2 days tz slack.
          WHERE (ar.review_timestamp >= TIMESTAMP(DATE_SUB(DATE '{start_date}', INTERVAL 16 DAY))
                 AND ar.review_timestamp < TIMESTAMP(DATE_ADD(DATE '{end_date}', INTERVAL 2 DAY))
                 OR ar.review_timestamp IS NULL)
            AND ar.platform IN ('Doordash','UberEats')
            AND {_in_scope_exists()}
          QUALIFY ROW_NUMBER() OVER (PARTITION BY COALESCE(ar.review_id, ar.order_id) ORDER BY COALESCE(ar.review_timestamp, ar.order_timestamp) DESC) = 1
        ),
        enriched AS (
          SELECT b.*,
            DATE(DATETIME(b.deadline_ts,'America/Chicago')) AS deadline_date,
            (b.is_replied
             OR are_o.key IS NOT NULL OR are_r.key IS NOT NULL
             OR (LEAST(IFNULL(ld_o.completed_at, TIMESTAMP '9999-12-31'),
                       IFNULL(ld_r.completed_at, TIMESTAMP '9999-12-31')) <= b.deadline_ts)
            ) AS replied_by_deadline,
            (SELECT MIN(x) FROM UNNEST([f1.first_assigned, f2.first_assigned, f3.first_assigned]) x) AS first_assigned
          FROM base b
          LEFT JOIN auto_res  are_o ON are_o.key=b.order_id
          LEFT JOIN auto_res  are_r ON are_r.key=b.review_id
          LEFT JOIN loop_done ld_o  ON ld_o.key=b.order_id
          LEFT JOIN loop_done ld_r  ON ld_r.key=b.review_id
          LEFT JOIN asg_first f1    ON f1.key=b.review_uid
          LEFT JOIN asg_first f2    ON f2.key=b.order_id
          LEFT JOIN asg_first f3    ON f3.key=b.review_id
        )
        -- INGESTED: posted in the window (all statuses; it's inflow)
        SELECT 'INGESTED' AS metric, 'INGESTED' AS bucket,
               COUNT(*) AS reviews,
               COUNTIF(platform='Doordash') AS doordash,
               COUNTIF(platform='UberEats') AS ubereats
        FROM enriched
        WHERE posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
        UNION ALL
        -- EXPIRED: deadline fell in the window and not replied by that deadline
        SELECT 'EXPIRED' AS metric,
               CASE WHEN first_assigned IS NULL THEN 'EXPIRED: ingested_after_expiry'
                    ELSE CONCAT('EXPIRED: late_ingestion_',
                                CAST(GREATEST(DATE_DIFF(DATE(DATETIME(first_assigned,'America/Chicago')), posted_date, DAY),0) AS STRING)) END AS bucket,
               COUNT(*) AS reviews,
               COUNTIF(platform='Doordash') AS doordash,
               COUNTIF(platform='UberEats') AS ubereats
        FROM enriched
        WHERE deadline_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
          AND NOT replied_by_deadline
        GROUP BY bucket
    """
    return bq_read(sql).to_dict("records")


def _fetch_solved(start_date: str, end_date: str) -> list[dict]:
    """Loop completions whose completed_at fell in the window (America/Chicago),
    per platform. Mirrors the daily throughput notifier's 'completed' signal
    (excludes observed_out_of_window so late observations of old replies don't
    count)."""
    sql = f"""
        SELECT platform, COUNT(DISTINCT review_uid) AS solved
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status='completed'
          AND completed_at IS NOT NULL
          AND DATE(DATETIME(completed_at,'America/Chicago')) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
          AND NOT IFNULL(observed_out_of_window, FALSE)
        GROUP BY platform
    """
    return bq_read(sql).to_dict("records")


def _format_window(start_date: str, end_date: str) -> str:
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    # Show the start year too when the week straddles a year boundary (e.g. late Dec).
    start_fmt = "%d %b" if s.year == e.year else "%d %b %Y"
    return f"{s.strftime(start_fmt)} – {e.strftime('%d %b %Y')}"


def _expired_sort_key(bucket: str) -> int:
    """Order expired buckets: late_ingestion_N ascending by N, then
    ingested_after_expiry last."""
    m = re.search(r"late_ingestion_(\d+)", bucket)
    if m:
        return int(m.group(1))
    return 9999  # ingested_after_expiry


def _build_blocks(
    start_date: str, end_date: str, review_rows: list[dict], solved_rows: list[dict]
) -> tuple[str, list[dict]]:
    def _trip(r: dict | None) -> tuple[int, int, int]:
        if not r:
            return 0, 0, 0
        return int(r["reviews"]), int(r["doordash"]), int(r["ubereats"])

    ing_row = next((r for r in review_rows if r["metric"] == "INGESTED"), None)
    expired_rows = sorted(
        (r for r in review_rows if r["metric"] == "EXPIRED"),
        key=lambda r: _expired_sort_key(r["bucket"]),
    )

    ing, ing_dd, ing_ue = _trip(ing_row)
    exp = sum(int(r["reviews"]) for r in expired_rows)
    exp_dd = sum(int(r["doordash"]) for r in expired_rows)
    exp_ue = sum(int(r["ubereats"]) for r in expired_rows)

    solved_by = {r["platform"]: int(r["solved"]) for r in solved_rows}
    sol_dd, sol_ue = solved_by.get("Doordash", 0), solved_by.get("UberEats", 0)
    sol = sol_dd + sol_ue

    window = _format_window(start_date, end_date)

    if ing == 0 and sol == 0 and exp == 0:
        text = (
            f":warning: No ReEngage activity for {window} (CT) — "
            "verify pipeline if unexpected."
        )
        return text, [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    header = f":bar_chart: *ReEngage weekly activity — {window} (CT)*"

    def _line(label: str, tot: int, dd: int, ue: int) -> str:
        return f"*{label}*  ·  `{tot}`   (DD `{dd}` · UE `{ue}`)"

    body_lines = [
        _line("Ingested (posted this week)", ing, ing_dd, ing_ue),
        _line("Solved (Loop-completed this week)", sol, sol_dd, sol_ue),
        _line("Expired (deadline missed this week)", exp, exp_dd, exp_ue),
    ]
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(body_lines)}},
    ]

    if exp > 0:
        breakdown_lines = [":mag: *Expired — root cause* _(days from posted to first queued)_"]
        for r in expired_rows:
            tot, dd, ue = _trip(r)
            label = r["bucket"].split("EXPIRED: ", 1)[-1]
            breakdown_lines.append(f"• `{label}`  ·  `{tot}`   (DD `{dd}` · UE `{ue}`)")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(breakdown_lines)}})

    note = (
        "_Activity view — each number counts events that happened this week by their own "
        "date, so they're independent and don't sum. *Ingested* = posted this week; "
        "*Solved* = Loop-completed this week; *Expired* = deadline fell this week and was "
        "missed. `late_ingestion_N` = days from posted to first actionable; "
        "`ingested_after_expiry` = never queued before the deadline._"
    )

    text_fallback = (
        f"ReEngage weekly activity {window}: ingested {ing}, solved {sol}, expired {exp}"
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
    return text_fallback, blocks


def send_last_week_funnel() -> None:
    """Post last week's (Fri–Thu) review activity to Slack. Never raises.
    Use this for unconditional/manual triggers; the daily cron uses
    `maybe_send_weekly_funnel` so it only fires on Fridays."""
    try:
        start_date, end_date = _last_week_window()
        review_rows = _fetch_review_flow(start_date, end_date)
        solved_rows = _fetch_solved(start_date, end_date)
        text, blocks = _build_blocks(start_date, end_date, review_rows, solved_rows)
        post_message(_CHANNEL, text=text, blocks=blocks)
        log.info("weekly_funnel_notifier: posted %s..%s", start_date, end_date)
    except Exception as e:
        log.exception("weekly_funnel_notifier: failed to post — %s", e)


def maybe_send_weekly_funnel() -> None:
    """Daily-cron hook: post the weekly activity only on Fridays (IST); a no-op on
    other days so the daily throughput post stands alone. The schedule is the
    existing 8 AM IST assignment cron — no separate scheduler. Never raises
    (delegates to send_last_week_funnel, which swallows its own errors)."""
    if datetime.now(_IST).weekday() == _FRIDAY:
        send_last_week_funnel()
