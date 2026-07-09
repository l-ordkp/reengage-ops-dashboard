"""Post last week's review ACTIVITY to Slack.

Posts every Friday (piggybacking on the daily 8 AM IST assignment cron — see
`maybe_send_weekly_funnel`) for the previous Fri–Thu week. A FLOW report: it
counts events that HAPPENED during the week, each on its OWN event date in IST
(Asia/Kolkata) — the same conventions as the daily throughput alert and the
operators tab:

  • Ingested — reviews that first ENTERED THE QUEUE in the week: MIN(assigned_at)
               per review (the 8 AM IST cron pickup). Same "ingested" as the daily
               alert / operators tab / "Daily Loop" chart. NOT the posted date.
  • Solved   — reviews Loop-COMPLETED in the week (assignment completed_at).
  • Expired  — reviews whose DEADLINE fell in the week and were not replied by
               that deadline (can include reviews posted 7/14 days earlier).

Three independent counts — they do NOT sum. Pending is omitted (it's a stock,
not a weekly event).

Definitions / caveats:
  • Expired = deadline in-window AND NOT replied-by-deadline, where
    "replied-by-deadline" = platform is_replied / external auto_resolved (assumed
    timely — no reply timestamp) OR a Loop completion with completed_at <= deadline.
    A Loop reply landing AFTER the deadline still counts as a miss.
  • Solved counts Loop completions only (reliable completed_at).
  • Expired keeps the late_ingestion_N / ingested_after_expiry breakdown
    (root cause: days from posted to first queued).

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
# Everything is IST: the cron fires 8 AM IST, and ingested/solved/expired are
# bucketed in Asia/Kolkata to match the daily alert + operators tab exactly.
_IST = timezone(timedelta(hours=5, minutes=30))
_FRIDAY = 4  # datetime.weekday(): Mon=0 … Fri=4

log = logging.getLogger(__name__)


def _last_week_window() -> tuple[str, str]:
    """Most recently completed Fri–Thu week, anchored to the IST run day, as ISO
    dates. Run on Fri Jul 3 -> ('2026-06-26', '2026-07-02')."""
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


def _fetch_ingested(start_date: str, end_date: str) -> list[dict]:
    """Reviews that first entered the assignments queue in the window
    (MIN(assigned_at), IST) — the canonical "ingested", matching the daily alert /
    operators tab. Assignments are already scoped (the cron only queues in-scope
    reviews). Returns [{platform, total}]."""
    sql = f"""
        WITH first_seen AS (
          SELECT review_uid, platform, MIN(assigned_at) AS first_assigned
          FROM `{TABLE_ASSIGNMENTS}`
          GROUP BY review_uid, platform
        )
        SELECT platform, COUNT(*) AS total
        FROM first_seen
        WHERE DATE(first_assigned, 'Asia/Kolkata') BETWEEN DATE '{start_date}' AND DATE '{end_date}'
        GROUP BY platform
    """
    return bq_read(sql).to_dict("records")


def _fetch_solved(start_date: str, end_date: str) -> list[dict]:
    """Loop completions whose completed_at fell in the window (IST). Mirrors the
    daily throughput notifier (excludes observed_out_of_window). Returns
    [{platform, total}]."""
    sql = f"""
        SELECT platform, COUNT(DISTINCT COALESCE(review_uid, order_id)) AS total
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status='completed' AND completed_at IS NOT NULL
          AND DATE(completed_at, 'Asia/Kolkata') BETWEEN DATE '{start_date}' AND DATE '{end_date}'
          AND NOT IFNULL(observed_out_of_window, FALSE)
        GROUP BY platform
    """
    return bq_read(sql).to_dict("records")


def _fetch_expired(start_date: str, end_date: str) -> list[dict]:
    """In-scope reviews whose DEADLINE fell in the window (IST) and were not replied
    by that deadline, bucketed by root cause. Returns rows with columns: bucket
    ('late_ingestion_N' | 'ingested_after_expiry'), reviews, doordash, ubereats."""
    sql = f"""
        WITH
        auto_res AS (
          SELECT DISTINCT key FROM (
            SELECT review_uid AS key FROM `{TABLE_ASSIGNMENTS}` WHERE status='auto_resolved'
            UNION ALL SELECT order_id AS key FROM `{TABLE_ASSIGNMENTS}` WHERE status='auto_resolved' AND order_id IS NOT NULL
          )
        ),
        loop_done AS (
          SELECT key, MIN(completed_at) AS completed_at FROM (
            SELECT review_uid AS key, completed_at FROM `{TABLE_ASSIGNMENTS}` WHERE status='completed' AND completed_at IS NOT NULL
            UNION ALL SELECT order_id AS key, completed_at FROM `{TABLE_ASSIGNMENTS}` WHERE status='completed' AND completed_at IS NOT NULL AND order_id IS NOT NULL
          ) GROUP BY key
        ),
        asg_first AS (
          SELECT key, MIN(assigned_at) AS first_assigned FROM (
            SELECT review_uid AS key, assigned_at FROM `{TABLE_ASSIGNMENTS}`
            UNION ALL SELECT order_id AS key, assigned_at FROM `{TABLE_ASSIGNMENTS}` WHERE order_id IS NOT NULL
          ) GROUP BY key
        ),
        base AS (
          SELECT
            COALESCE(ar.review_id, ar.order_id) AS review_uid, ar.order_id, ar.review_id, ar.platform, ar.is_replied,
            DATE(COALESCE(ar.review_timestamp, ar.order_timestamp), 'Asia/Kolkata') AS posted_date,
            CASE WHEN ar.platform='Doordash' THEN TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7  DAY)
                 WHEN ar.platform='UberEats' THEN TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 14 DAY)
                 ELSE TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7 DAY) END AS deadline_ts
          FROM `{TABLE_AUTOMATION_REVIEWS}` AS ar
          INNER JOIN `{TABLE_SLUG_AM_MAPPING}` AS sm ON ar.slug = sm.slug
          -- deadline in window => posted up to ~14 days before start. COALESCE bound
          -- + bare-column partition prune (see review_repository.py:65-77).
          WHERE COALESCE(ar.review_timestamp, ar.order_timestamp) >= TIMESTAMP(DATE_SUB(DATE '{start_date}', INTERVAL 15 DAY))
            AND (ar.review_timestamp >= TIMESTAMP(DATE_SUB(DATE '{start_date}', INTERVAL 16 DAY)) OR ar.review_timestamp IS NULL)
            AND ar.platform IN ('Doordash','UberEats')
            AND {_in_scope_exists()}
          QUALIFY ROW_NUMBER() OVER (PARTITION BY COALESCE(ar.review_id, ar.order_id) ORDER BY COALESCE(ar.review_timestamp, ar.order_timestamp) DESC) = 1
        ),
        enriched AS (
          SELECT b.*,
            DATE(b.deadline_ts, 'Asia/Kolkata') AS deadline_date,
            -- replied_by_deadline: only a Loop completion is time-checked. Platform
            -- is_replied / external auto_resolved have no reply timestamp, so assumed
            -- timely (slight undercount of late external replies).
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
        SELECT
          CASE WHEN first_assigned IS NULL THEN 'ingested_after_expiry'
               ELSE CONCAT('late_ingestion_',
                           CAST(GREATEST(DATE_DIFF(DATE(first_assigned,'Asia/Kolkata'), posted_date, DAY),0) AS STRING)) END AS bucket,
          COUNT(*) AS reviews,
          COUNTIF(platform='Doordash') AS doordash,
          COUNTIF(platform='UberEats') AS ubereats
        FROM enriched
        WHERE deadline_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
          AND NOT replied_by_deadline
        GROUP BY bucket
    """
    return bq_read(sql).to_dict("records")


def _format_window(start_date: str, end_date: str) -> str:
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    start_fmt = "%d %b" if s.year == e.year else "%d %b %Y"
    return f"{s.strftime(start_fmt)} – {e.strftime('%d %b %Y')}"


def _expired_sort_key(bucket: str) -> int:
    m = re.search(r"late_ingestion_(\d+)", bucket)
    return int(m.group(1)) if m else 9999  # ingested_after_expiry last


def _platform_totals(rows: list[dict], key: str = "total") -> tuple[int, int, int]:
    by = {r["platform"]: int(r[key]) for r in rows}
    dd, ue = by.get("Doordash", 0), by.get("UberEats", 0)
    return dd + ue, dd, ue


def _build_blocks(
    start_date: str, end_date: str,
    ingested_rows: list[dict], solved_rows: list[dict], expired_rows: list[dict],
) -> tuple[str, list[dict]]:
    ing, ing_dd, ing_ue = _platform_totals(ingested_rows)
    sol, sol_dd, sol_ue = _platform_totals(solved_rows)
    exp = sum(int(r["reviews"]) for r in expired_rows)
    exp_dd = sum(int(r["doordash"]) for r in expired_rows)
    exp_ue = sum(int(r["ubereats"]) for r in expired_rows)
    expired_sorted = sorted(expired_rows, key=lambda r: _expired_sort_key(r["bucket"]))

    window = _format_window(start_date, end_date)

    if ing == 0 and sol == 0 and exp == 0:
        text = f":warning: No ReEngage activity for {window} (IST) — verify pipeline if unexpected."
        return text, [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    header = f":bar_chart: *ReEngage weekly activity — {window} (IST)*"

    def _line(label: str, tot: int, dd: int, ue: int) -> str:
        return f"*{label}*  ·  `{tot}`   (DD `{dd}` · UE `{ue}`)"

    body_lines = [
        _line("Ingested (entered queue this week)", ing, ing_dd, ing_ue),
        _line("Solved (Loop-completed this week)", sol, sol_dd, sol_ue),
        _line("Expired (deadline missed this week)", exp, exp_dd, exp_ue),
    ]
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(body_lines)}},
    ]

    if exp > 0:
        breakdown = [":mag: *Expired — root cause* _(days from posted to first queued)_"]
        for r in expired_sorted:
            breakdown.append(f"• `{r['bucket']}`  ·  `{int(r['reviews'])}`   (DD `{int(r['doordash'])}` · UE `{int(r['ubereats'])}`)")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(breakdown)}})

    note = (
        "_Independent weekly counts (they don't sum), all IST. *Ingested* = first entered the "
        "queue this week (same as the daily alert / operators tab); *Solved* = Loop-completed "
        "this week; *Expired* = deadline fell this week and was missed. `late_ingestion_N` = "
        "days from posted to first actionable; `ingested_after_expiry` = never queued before the deadline._"
    )
    text_fallback = f"ReEngage weekly activity {window}: ingested {ing}, solved {sol}, expired {exp}"
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
    return text_fallback, blocks


def send_last_week_funnel() -> None:
    """Post last week's (Fri–Thu) review activity to Slack. Never raises."""
    try:
        start_date, end_date = _last_week_window()
        text, blocks = _build_blocks(
            start_date, end_date,
            _fetch_ingested(start_date, end_date),
            _fetch_solved(start_date, end_date),
            _fetch_expired(start_date, end_date),
        )
        post_message(_CHANNEL, text=text, blocks=blocks)
        log.info("weekly_funnel_notifier: posted %s..%s", start_date, end_date)
    except Exception as e:
        log.exception("weekly_funnel_notifier: failed to post — %s", e)


def maybe_send_weekly_funnel() -> None:
    """Daily-cron hook: post the weekly activity only on Fridays (IST); a no-op on
    other days. Never raises (delegates to send_last_week_funnel)."""
    if datetime.now(_IST).weekday() == _FRIDAY:
        send_last_week_funnel()
