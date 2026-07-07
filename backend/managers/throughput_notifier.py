"""Post yesterday's ingested / loop-completed / expired throughput to Slack.

Runs immediately after the daily 8 AM IST assignment cron. Reads the
assignments table, splits by platform (Doordash/UberEats) plus a total,
and posts one message to #reengage-bot-notifications. Completed counts
carry a critical/urgent/normal breakdown of how much deadline time was
left when each reply landed.

Slack failures are logged and swallowed — the assignment cron is the
critical path and must not exit non-zero just because Slack is flaky.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.clients.bq_client import bq_read
from backend.clients.slack_client import post_message
from backend.config import TABLE_ASSIGNMENTS, TABLE_AUTOMATION_REVIEWS


_CHANNEL = "#reengage-bot-notifications"
_IST = timezone(timedelta(hours=5, minutes=30))

log = logging.getLogger(__name__)


def _yesterday_ist() -> str:
    return (datetime.now(_IST).date() - timedelta(days=1)).isoformat()


def _fetch_yesterday_rows(target_date: str) -> list[dict]:
    """One row per platform for `target_date` (IST). Densified so both
    Doordash and UberEats always appear even if zero."""
    sql = f"""
        WITH platforms AS (
            SELECT 'Doordash' AS platform UNION ALL SELECT 'UberEats'
        ),
        first_seen AS (
            SELECT review_uid, platform, MIN(assigned_at) AS first_assigned_at
            FROM `{TABLE_ASSIGNMENTS}`
            GROUP BY review_uid, platform
        ),
        ingested AS (
            SELECT platform, COUNT(*) AS ingested
            FROM first_seen
            WHERE DATE(first_assigned_at, 'Asia/Kolkata') = DATE('{target_date}')
            GROUP BY platform
        ),
        recent_reviews AS (
            -- Dedup to one row per review (dbt MERGE leaves multiple
            -- rows per key); without this the same review could join
            -- more than once. DESC matches the convention elsewhere;
            -- duplicates share identical review_timestamps (verified
            -- over 30d: 35k dup keys, 0 disagreements), so the order
            -- direction doesn't affect which deadline day is computed
            -- and expire_stale_assignments' EXISTS-any-row flip lands
            -- on the same day.
            SELECT order_id, review_timestamp, order_timestamp
            FROM `{TABLE_AUTOMATION_REVIEWS}`
            -- Prune partitions (DAY-partitioned on review_timestamp).
            -- A deadline landing on target_date means the review was
            -- posted at most 14 days earlier (UberEats window); 16 days
            -- adds slack for the IST conversion. The IS NULL arm keeps
            -- rows that fall back to order_timestamp. The same bound
            -- covers the completed CTE: an in-window reply happens at
            -- most 14 days after the review was posted.
            WHERE (
                review_timestamp >= TIMESTAMP(DATE_SUB(DATE('{target_date}'), INTERVAL 16 DAY))
                OR review_timestamp IS NULL
            )
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY COALESCE(review_id, order_id)
                ORDER BY COALESCE(review_timestamp, order_timestamp) DESC
            ) = 1
        ),
        completed AS (
            -- Excludes observed_out_of_window rows so late observations of
            -- already-replied old reviews don't inflate yesterday's count.
            -- The actual reply happened days/weeks earlier via the portal UI
            -- — counting it as "yesterday's throughput" misleads readers.
            --
            -- Priority buckets reconstruct how much deadline time was left
            -- AT THE MOMENT of reply (priority is never stored — the
            -- dashboard derives it live from CURRENT_TIMESTAMP, which would
            -- be meaningless for yesterday's replies). Thresholds match
            -- review_repository / enums.priority: <=24h CRITICAL,
            -- <=48h URGENT, else NORMAL. Replies past the deadline
            -- (negative hours) land in CRITICAL. LEFT JOIN so a reply whose
            -- review row is missing or pruned out (posted >16 days ago)
            -- still counts in loop_completed and falls into the unknown
            -- bucket — the three buckets + unknown always sum to
            -- loop_completed.
            SELECT
                platform,
                COUNT(*) AS loop_completed,
                COUNTIF(hours_left_at_reply <= 24) AS completed_critical,
                COUNTIF(hours_left_at_reply > 24
                        AND hours_left_at_reply <= 48) AS completed_urgent,
                COUNTIF(hours_left_at_reply > 48) AS completed_normal,
                COUNTIF(hours_left_at_reply IS NULL) AS completed_unknown
            FROM (
                SELECT
                    a.platform,
                    TIMESTAMP_DIFF(
                        TIMESTAMP_ADD(
                            COALESCE(ar.review_timestamp, ar.order_timestamp),
                            INTERVAL CASE WHEN a.platform = 'UberEats' THEN 14 ELSE 7 END DAY
                        ),
                        a.completed_at, HOUR
                    ) AS hours_left_at_reply
                FROM `{TABLE_ASSIGNMENTS}` a
                LEFT JOIN recent_reviews ar ON ar.order_id = a.order_id
                WHERE a.status = 'completed'
                  AND a.completed_at IS NOT NULL
                  AND DATE(a.completed_at, 'Asia/Kolkata') = DATE('{target_date}')
                  AND NOT IFNULL(a.observed_out_of_window, FALSE)
            )
            GROUP BY platform
        ),
        expired AS (
            -- Assignments have no expired_at stamp (expire_stale_assignments
            -- only flips status), so an expiry is attributed to the day its
            -- platform deadline fell — the same review_timestamp + N days
            -- rule the status engine uses. The daily cron marks expiries
            -- before this notifier runs, so yesterday's deadlines are
            -- already flagged by post time.
            SELECT a.platform, COUNT(DISTINCT a.review_uid) AS expired
            FROM `{TABLE_ASSIGNMENTS}` a
            JOIN recent_reviews ar ON ar.order_id = a.order_id
            WHERE a.status = 'expired'
              AND DATE(
                TIMESTAMP_ADD(
                  COALESCE(ar.review_timestamp, ar.order_timestamp),
                  INTERVAL CASE WHEN a.platform = 'UberEats' THEN 14 ELSE 7 END DAY
                ), 'Asia/Kolkata') = DATE('{target_date}')
            GROUP BY a.platform
        )
        SELECT
            platforms.platform,
            COALESCE(ingested.ingested, 0) AS ingested,
            COALESCE(completed.loop_completed, 0) AS loop_completed,
            COALESCE(completed.completed_critical, 0) AS completed_critical,
            COALESCE(completed.completed_urgent, 0) AS completed_urgent,
            COALESCE(completed.completed_normal, 0) AS completed_normal,
            COALESCE(completed.completed_unknown, 0) AS completed_unknown,
            COALESCE(expired.expired, 0) AS expired
        FROM platforms
        LEFT JOIN ingested  USING (platform)
        LEFT JOIN completed USING (platform)
        LEFT JOIN expired   USING (platform)
        ORDER BY platform
    """
    return bq_read(sql).to_dict("records")


def _format_date(target_date: str) -> str:
    return datetime.strptime(target_date, "%Y-%m-%d").strftime("%a %d %b")


_SUM_KEYS = (
    "ingested", "loop_completed", "completed_critical", "completed_urgent",
    "completed_normal", "completed_unknown", "expired",
)


def _build_blocks(target_date: str, rows: list[dict]) -> tuple[str, list[dict]]:
    totals = {k: sum(int(r[k]) for r in rows) for k in _SUM_KEYS}
    total_ing = totals["ingested"]
    total_cmp = totals["loop_completed"]
    total_exp = totals["expired"]
    pretty_date = _format_date(target_date)

    # Deliberately ignores total_exp: expiries derive from reviews posted
    # 7-14 days ago and need no fresh ingestion, so they're nonzero even
    # when the pipeline is dead — gating on them would mask the outage
    # this warning exists to catch.
    if total_ing == 0 and total_cmp == 0:
        text = (
            f":warning: No throughput logged for {pretty_date} (IST) — "
            "verify pipeline if unexpected."
        )
        return text, [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    header = f":bar_chart: *Daily throughput — {pretty_date} (IST)*"

    def _priority_breakdown(r: dict) -> str:
        # Priority AT REPLY TIME (see the completed CTE). "unknown" =
        # replies whose review row didn't join (missing or pruned out);
        # shown only when nonzero so the common case stays compact.
        parts = (
            f":red_circle: {int(r['completed_critical'])}"
            f" · :large_orange_circle: {int(r['completed_urgent'])}"
            f" · :large_green_circle: {int(r['completed_normal'])}"
        )
        if int(r["completed_unknown"]):
            parts += f" · unknown {int(r['completed_unknown'])}"
        return parts

    def _line(label: str, r: dict) -> str:
        return (
            f"*{label}*  ·  ingested: `{int(r['ingested'])}`"
            f"  ·  completed: `{int(r['loop_completed'])}`"
            f" ({_priority_breakdown(r)})"
            f"  ·  expired: `{int(r['expired'])}`"
        )

    body_lines = [_line("Total", totals)]
    for r in rows:
        body_lines.append(_line(r["platform"], r))

    text_fallback = (
        f"Daily throughput {pretty_date}: ingested {total_ing}, "
        f"completed {total_cmp} (critical {totals['completed_critical']}, "
        f"urgent {totals['completed_urgent']}, "
        f"normal {totals['completed_normal']}), expired {total_exp}"
    )
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(body_lines)}},
    ]
    return text_fallback, blocks


def send_yesterday_throughput() -> None:
    """Post yesterday IST throughput to Slack. Never raises."""
    try:
        target_date = _yesterday_ist()
        rows = _fetch_yesterday_rows(target_date)
        text, blocks = _build_blocks(target_date, rows)
        post_message(_CHANNEL, text=text, blocks=blocks)
        log.info("throughput_notifier: posted %s", target_date)
    except Exception as e:
        log.exception("throughput_notifier: failed to post — %s", e)
