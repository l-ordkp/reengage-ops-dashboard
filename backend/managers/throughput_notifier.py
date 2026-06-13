"""Post yesterday's ingested vs. loop-completed throughput to Slack.

Runs immediately after the daily 8 AM IST assignment cron. Reads the
assignments table, splits by platform (Doordash/UberEats) plus a total,
and posts one message to #reengage-bot-notifications.

Slack failures are logged and swallowed — the assignment cron is the
critical path and must not exit non-zero just because Slack is flaky.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.clients.bq_client import bq_read
from backend.clients.slack_client import post_message
from backend.config import TABLE_ASSIGNMENTS


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
        completed AS (
            -- Excludes observed_out_of_window rows so late observations of
            -- already-replied old reviews don't inflate yesterday's count.
            -- The actual reply happened days/weeks earlier via the portal UI
            -- — counting it as "yesterday's throughput" misleads readers.
            SELECT platform, COUNT(*) AS loop_completed
            FROM `{TABLE_ASSIGNMENTS}`
            WHERE status = 'completed'
              AND completed_at IS NOT NULL
              AND DATE(completed_at, 'Asia/Kolkata') = DATE('{target_date}')
              AND NOT IFNULL(observed_out_of_window, FALSE)
            GROUP BY platform
        )
        SELECT
            platforms.platform,
            COALESCE(ingested.ingested, 0) AS ingested,
            COALESCE(completed.loop_completed, 0) AS loop_completed
        FROM platforms
        LEFT JOIN ingested  USING (platform)
        LEFT JOIN completed USING (platform)
        ORDER BY platform
    """
    return bq_read(sql).to_dict("records")


def _format_date(target_date: str) -> str:
    return datetime.strptime(target_date, "%Y-%m-%d").strftime("%a %d %b")


def _build_blocks(target_date: str, rows: list[dict]) -> tuple[str, list[dict]]:
    total_ing = sum(int(r["ingested"]) for r in rows)
    total_cmp = sum(int(r["loop_completed"]) for r in rows)
    pretty_date = _format_date(target_date)

    if total_ing == 0 and total_cmp == 0:
        text = (
            f":warning: No throughput logged for {pretty_date} (IST) — "
            "verify pipeline if unexpected."
        )
        return text, [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    header = f":bar_chart: *Daily throughput — {pretty_date} (IST)*"

    def _line(label: str, ing: int, cmp_: int) -> str:
        return f"*{label}*  ·  ingested: `{ing}`  ·  completed: `{cmp_}`"

    body_lines = [_line("Total", total_ing, total_cmp)]
    for r in rows:
        body_lines.append(_line(r["platform"], int(r["ingested"]), int(r["loop_completed"])))

    text_fallback = (
        f"Daily throughput {pretty_date}: ingested {total_ing}, "
        f"completed {total_cmp}"
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
