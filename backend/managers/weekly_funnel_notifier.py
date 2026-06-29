"""Post last week's in-scope review funnel to Slack.

Posts every Friday (piggybacking on the daily 8 AM IST assignment cron — see
`maybe_send_weekly_funnel`) for the previous Fri–Thu week, bucketing reviews by
the date they were POSTED (America/Chicago), and posts the top-line funnel —
Ingested / Replied / Pending / Expired, split by platform — to
#reengage-bot-notifications.

Includes the expiry root-cause breakdown (late_ingestion_N / ingested_after_
expiry), same as the `reengage-numbers` skill. Because the just-completed week
is still maturing (DoorDash reviews take 7 days to expire, UberEats 14), the
Pending leg is large and Expired — and therefore its breakdown — is partial and
keeps filling in for ~1–2 weeks. The message says so.

Logic mirrors the `reengage-numbers` funnel (posted mode): source of truth is
`automation_reviews`, joined to `slug_am_mapping` for chain, scoped to a
non-paused `review_response_config`, one row per review_uid (latest kept).

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
# The post is gated on / anchored to the IST run day, because the daily cron
# fires at 8 AM IST — which is still the prior evening in CT. Anchoring the
# week to CT would read one day earlier and report a week behind. (posted_date
# is still bucketed in America/Chicago inside the SQL.)
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


def _fetch_funnel_rows(start_date: str, end_date: str) -> list[dict]:
    """One row per bucket for reviews posted within [start_date, end_date] (CT),
    with platform split. Buckets: 'REPLIED', 'PENDING', and the expired
    breakdown — 'EXPIRED: late_ingestion_N' / 'EXPIRED: ingested_after_expiry'.
    Empty buckets simply won't appear; the formatter densifies the top line."""
    sql = f"""
        WITH lc AS (
            SELECT DISTINCT order_id AS cid
            FROM `{TABLE_ASSIGNMENTS}`
            WHERE status IN ('completed','auto_resolved')
        ),
        -- First time a review ever entered our queue (cron pickup). MIN across
        -- ALL statuses, because void_pending flips pending->reassigned but KEEPS
        -- the row + original assigned_at.
        asg_first AS (
            SELECT key, MIN(assigned_at) AS first_assigned FROM (
                SELECT review_uid AS key, assigned_at FROM `{TABLE_ASSIGNMENTS}`
                UNION ALL
                SELECT order_id  AS key, assigned_at FROM `{TABLE_ASSIGNMENTS}` WHERE order_id IS NOT NULL
            ) GROUP BY key
        ),
        base AS (
            SELECT
                COALESCE(ar.review_id, ar.order_id) AS review_uid,
                ar.order_id, ar.review_id, ar.platform, ar.is_replied,
                DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp),'America/Chicago')) AS posted_date,
                CASE
                    WHEN ar.platform='Doordash' THEN TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7  DAY)
                    WHEN ar.platform='UberEats' THEN TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 14 DAY)
                    ELSE TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7 DAY)
                END AS deadline_ts
            FROM `{TABLE_AUTOMATION_REVIEWS}` AS ar
            INNER JOIN `{TABLE_SLUG_AM_MAPPING}` AS sm ON ar.slug = sm.slug
            -- Partition prune around the posted window (±2 days covers tz rounding);
            -- review_timestamp IS NULL rows fall back to order_timestamp for posted_date.
            WHERE (ar.review_timestamp >= TIMESTAMP(DATE_SUB(DATE '{start_date}', INTERVAL 2 DAY))
                   AND ar.review_timestamp < TIMESTAMP(DATE_ADD(DATE '{end_date}', INTERVAL 2 DAY))
                   OR ar.review_timestamp IS NULL)
              AND ar.platform IN ('Doordash','UberEats')
              AND EXISTS (
                  SELECT 1 FROM `{TABLE_REVIEW_RESPONSE_CFG}` rc
                  WHERE rc.paused=FALSE AND sm.chain=rc.chain_name
                    AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.vb_platforms),[]))=0      OR ar.platform IN UNNEST(JSON_VALUE_ARRAY(rc.vb_platforms)))
                    AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.ratings),[]))=0           OR CAST(ar.star_rating AS STRING) IN UNNEST(JSON_VALUE_ARRAY(rc.ratings)) OR ar.rating_value IN UNNEST(JSON_VALUE_ARRAY(rc.ratings)))
                    AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.customer_types),[]))=0    OR (CASE WHEN SAFE_CAST(ar.orders_count AS INT64)>1 THEN 'existing' ELSE 'new' END) IN UNNEST(JSON_VALUE_ARRAY(rc.customer_types)))
                    AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.feedback_presence),[]))=0 OR (CASE WHEN COALESCE(TRIM(ar.review_text),'')='' THEN 'without_feedback' ELSE 'with_feedback' END) IN UNNEST(JSON_VALUE_ARRAY(rc.feedback_presence)))
              )
            QUALIFY ROW_NUMBER() OVER (PARTITION BY COALESCE(ar.review_id, ar.order_id) ORDER BY ar.review_timestamp DESC) = 1
        ),
        cohort AS (
            SELECT b.*, (b.is_replied OR lo.cid IS NOT NULL OR lr.cid IS NOT NULL) AS replied
            FROM base b
            LEFT JOIN lc lo ON lo.cid=b.order_id
            LEFT JOIN lc lr ON lr.cid=b.review_id
            WHERE b.posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
        ),
        classified AS (
            SELECT c.*,
                (SELECT MIN(x) FROM UNNEST([f1.first_assigned,f2.first_assigned,f3.first_assigned]) x) AS first_assigned
            FROM cohort c
            LEFT JOIN asg_first f1 ON f1.key=c.review_uid
            LEFT JOIN asg_first f2 ON f2.key=c.order_id
            LEFT JOIN asg_first f3 ON f3.key=c.review_id
        ),
        bucketed AS (
            SELECT *,
                CASE
                    WHEN replied                           THEN 'REPLIED'
                    WHEN deadline_ts > CURRENT_TIMESTAMP() THEN 'PENDING'
                    WHEN first_assigned IS NULL            THEN 'EXPIRED: ingested_after_expiry'
                    ELSE CONCAT('EXPIRED: late_ingestion_',
                                CAST(GREATEST(DATE_DIFF(DATE(DATETIME(first_assigned,'America/Chicago')), posted_date, DAY),0) AS STRING))
                END AS bucket
            FROM classified
        )
        SELECT bucket,
               COUNT(*) AS reviews,
               COUNTIF(platform='Doordash') AS doordash,
               COUNTIF(platform='UberEats') AS ubereats
        FROM bucketed
        GROUP BY bucket
    """
    return bq_read(sql).to_dict("records")


def _format_window(start_date: str, end_date: str) -> str:
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    return f"{s.strftime('%d %b')} – {e.strftime('%d %b %Y')}"


def _expired_sort_key(bucket: str) -> int:
    """Order expired buckets: late_ingestion_N ascending by N, then
    ingested_after_expiry last."""
    m = re.search(r"late_ingestion_(\d+)", bucket)
    if m:
        return int(m.group(1))
    return 9999  # ingested_after_expiry


def _build_blocks(start_date: str, end_date: str, rows: list[dict]) -> tuple[str, list[dict]]:
    def _trip(r: dict | None) -> tuple[int, int, int]:
        if not r:
            return 0, 0, 0
        return int(r["reviews"]), int(r["doordash"]), int(r["ubereats"])

    by_bucket = {r["bucket"]: r for r in rows}
    expired_rows = sorted(
        (r for r in rows if r["bucket"].startswith("EXPIRED:")),
        key=lambda r: _expired_sort_key(r["bucket"]),
    )

    rep, rep_dd, rep_ue = _trip(by_bucket.get("REPLIED"))
    pen, pen_dd, pen_ue = _trip(by_bucket.get("PENDING"))
    exp = sum(int(r["reviews"]) for r in expired_rows)
    exp_dd = sum(int(r["doordash"]) for r in expired_rows)
    exp_ue = sum(int(r["ubereats"]) for r in expired_rows)
    ing, ing_dd, ing_ue = rep + pen + exp, rep_dd + pen_dd + exp_dd, rep_ue + pen_ue + exp_ue
    window = _format_window(start_date, end_date)

    if ing == 0:
        text = (
            f":warning: No in-scope reviews found for {window} (CT) — "
            "verify pipeline if unexpected."
        )
        return text, [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    header = f":bar_chart: *ReEngage weekly funnel — {window} (CT, by posted date)*"

    def _line(label: str, tot: int, dd: int, ue: int) -> str:
        return f"*{label}*  ·  `{tot}`   (DD `{dd}` · UE `{ue}`)"

    body_lines = [
        _line("Ingested", ing, ing_dd, ing_ue),
        _line("Replied", rep, rep_dd, rep_ue),
        _line("Pending", pen, pen_dd, pen_ue),
        _line("Expired", exp, exp_dd, exp_ue),
    ]
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(body_lines)}},
    ]

    if exp > 0:
        def _bucket_label(bucket: str) -> str:
            return bucket.split("EXPIRED: ", 1)[-1]

        breakdown_lines = [":mag: *Expired breakdown* _(partial — week still maturing)_"]
        for r in expired_rows:
            tot, dd, ue = _trip(r)
            breakdown_lines.append(f"• `{_bucket_label(r['bucket'])}`  ·  `{tot}`   (DD `{dd}` · UE `{ue}`)")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(breakdown_lines)}})

    note = (
        "_Last week is still maturing — DoorDash takes 7 days to expire and "
        "UberEats 14, so Pending is large and Expired (and its breakdown) keeps "
        "filling in for ~1–2 weeks. `late_ingestion_N` = days from posted to first "
        "actionable; `ingested_after_expiry` = never queued before the deadline._"
    )

    text_fallback = (
        f"ReEngage weekly funnel {window}: ingested {ing}, replied {rep}, "
        f"pending {pen}, expired {exp}"
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
    return text_fallback, blocks


def send_last_week_funnel() -> None:
    """Post last week's (Fri–Thu) in-scope funnel to Slack. Never raises.
    Use this for unconditional/manual triggers; the daily cron uses
    `maybe_send_weekly_funnel` so it only fires on Fridays."""
    try:
        start_date, end_date = _last_week_window()
        rows = _fetch_funnel_rows(start_date, end_date)
        text, blocks = _build_blocks(start_date, end_date, rows)
        post_message(_CHANNEL, text=text, blocks=blocks)
        log.info("weekly_funnel_notifier: posted %s..%s", start_date, end_date)
    except Exception as e:
        log.exception("weekly_funnel_notifier: failed to post — %s", e)


def maybe_send_weekly_funnel() -> None:
    """Daily-cron hook: post the weekly funnel only on Fridays (IST); a no-op on
    other days so the daily throughput post stands alone. The schedule is the
    existing 8 AM IST assignment cron — no separate scheduler. Never raises
    (delegates to send_last_week_funnel, which swallows its own errors)."""
    if datetime.now(_IST).weekday() == _FRIDAY:
        send_last_week_funnel()
