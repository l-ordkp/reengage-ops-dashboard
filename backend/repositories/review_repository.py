"""
Review data access — reads `automation_reviews` (joined with chain/response data) from BigQuery.
This is the dashboard's heaviest query.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from backend.clients.bq_client import bq_read
from backend.config import (
    TABLE_AUTOMATION_REVIEWS,
    TABLE_REVIEW_RESPONSES,
    TABLE_REVIEW_RESPONSE_CFG,
    TABLE_SLUG_AM_MAPPING,
    TABLE_ASSIGNMENTS,
)
from backend.utils.cache import cached


@cached(ttl=300)
def fetch_reviews_14d() -> pd.DataFrame:
    """
    Main reviews query: last 14 days, joined with chain mapping + AI responses + assignments.
    Returns one row per review_uid with all the fields the dashboard needs.
    Cached for 5 minutes.
    """
    sql = f"""
    WITH eligible_reviews AS (
        SELECT
            COALESCE(automation_review.review_id, automation_review.order_id) AS review_uid,
            automation_review.order_id,
            automation_review.review_id,
            slug_mapping.chain AS chain_name,
            slug_mapping.b_name_id,
            slug_mapping.vb_name AS brand_name,
            automation_review.platform,
            automation_review.slug,
            automation_review.store_id,
            slug_mapping.username AS portal_username,
            slug_mapping.password AS portal_password,
            automation_review.customer_name,
            automation_review.user_id AS customer_id,
            SAFE_CAST(automation_review.orders_count AS INT64) AS orders_count,
            CASE
                WHEN SAFE_CAST(automation_review.orders_count AS INT64) > 1 THEN 'existing'
                ELSE 'new'
            END AS customer_type,
            automation_review.star_rating,
            automation_review.rating_type,
            automation_review.rating_value,
            automation_review.review_text,
            automation_review.is_replied,
            automation_review.replied_comment,
            automation_review.items,
            automation_review.order_value,
            COALESCE(automation_review.review_timestamp, automation_review.order_timestamp) AS event_timestamp,
            DATE(DATETIME(
                COALESCE(automation_review.review_timestamp, automation_review.order_timestamp),
                'America/Chicago'
            )) AS review_date
        FROM `{TABLE_AUTOMATION_REVIEWS}` AS automation_review
        INNER JOIN `{TABLE_SLUG_AM_MAPPING}` AS slug_mapping
            ON automation_review.slug = slug_mapping.slug
        WHERE COALESCE(automation_review.review_timestamp, automation_review.order_timestamp)
              >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
          -- Prune the partition. automation_reviews is DAY-partitioned on
          -- review_timestamp, but the COALESCE filter above wraps the partition
          -- column in a function, so BigQuery can't prune and scans all ~727
          -- partitions (~4.4 GiB) on every call. This bare-column predicate lets
          -- it prune to recent partitions; the IS NULL arm keeps rows with no
          -- review_timestamp that fall back to order_timestamp. 1 extra day of
          -- slack covers any timezone rounding in the COALESCE comparison.
          AND (
              automation_review.review_timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 15 DAY))
              OR automation_review.review_timestamp IS NULL
          )
          AND EXISTS (
              SELECT 1
              FROM `{TABLE_REVIEW_RESPONSE_CFG}` AS response_config
              WHERE response_config.paused = FALSE
                AND slug_mapping.chain = response_config.chain_name
                AND (
                    ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(response_config.vb_platforms), [])) = 0
                    OR automation_review.platform IN UNNEST(JSON_VALUE_ARRAY(response_config.vb_platforms))
                )
                AND (
                    ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(response_config.ratings), [])) = 0
                    OR CAST(automation_review.star_rating AS STRING) IN UNNEST(JSON_VALUE_ARRAY(response_config.ratings))
                    OR automation_review.rating_value IN UNNEST(JSON_VALUE_ARRAY(response_config.ratings))
                )
                AND (
                    ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(response_config.customer_types), [])) = 0
                    OR (CASE WHEN SAFE_CAST(automation_review.orders_count AS INT64) > 1
                             THEN 'existing' ELSE 'new' END)
                       IN UNNEST(JSON_VALUE_ARRAY(response_config.customer_types))
                )
                AND (
                    ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(response_config.feedback_presence), [])) = 0
                    OR (CASE WHEN COALESCE(TRIM(automation_review.review_text), '') = ''
                             THEN 'without_feedback' ELSE 'with_feedback' END)
                       IN UNNEST(JSON_VALUE_ARRAY(response_config.feedback_presence))
                )
          )
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY COALESCE(automation_review.review_id, automation_review.order_id)
            ORDER BY COALESCE(automation_review.review_timestamp, automation_review.order_timestamp) DESC
        ) = 1
    ),
    reviews_with_deadline AS (
        SELECT
            eligible_reviews.*,
            -- Hours from now until the platform deadline (review_timestamp + N days).
            -- Switched from day-bucket math: the date-rounded version lost 0-24h of
            -- usable window per review and its CST midnight rollover hit mid-IST-shift,
            -- silently flipping reviews from CRITICAL → EXPIRED while operators worked.
            -- TIMESTAMP_DIFF is timezone-agnostic (returns elapsed UTC hours).
            CASE
                WHEN platform = 'Doordash' THEN
                    TIMESTAMP_DIFF(TIMESTAMP_ADD(event_timestamp, INTERVAL 7 DAY), CURRENT_TIMESTAMP(), HOUR)
                WHEN platform = 'UberEats' THEN
                    TIMESTAMP_DIFF(TIMESTAMP_ADD(event_timestamp, INTERVAL 14 DAY), CURRENT_TIMESTAMP(), HOUR)
                ELSE 0
            END AS hours_left
        FROM eligible_reviews
    ),
    reviews_with_response AS (
        SELECT
            reviews_with_deadline.*,
            review_response.response_text AS ai_response,
            review_response.response_type AS ai_response_type,
            review_response.coupon_value,
            review_response.response_sent,
            review_response.config_id
        FROM reviews_with_deadline
        LEFT JOIN `{TABLE_REVIEW_RESPONSES}` AS review_response
            ON reviews_with_deadline.order_id = review_response.order_id
    ),
    reviews_with_assignment AS (
        -- LEFT JOIN against a per-review_uid deduped view of assignments.
        -- Widening the status filter (PR-B) means a review_uid that legitimately
        -- has both a `completed` and an `auto_resolved` row would otherwise
        -- duplicate into the output and break downstream per-row aggregations
        -- (e.g. chain_health_manager's drop_duplicates is non-deterministic on
        -- which row wins). Priority: completed beats auto_resolved so
        -- is_loop_replied stays TRUE when Loop actually did the work.
        SELECT
            reviews_with_response.*,
            assignment.status AS assignment_status
        FROM reviews_with_response
        LEFT JOIN (
            SELECT review_uid, status
            FROM `{TABLE_ASSIGNMENTS}`
            WHERE status IN ('completed', 'auto_resolved')
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY review_uid
                ORDER BY CASE status
                    WHEN 'completed' THEN 0
                    ELSE 1
                END
            ) = 1
        ) AS assignment USING (review_uid)
    ),
    reviews_with_status AS (
        SELECT
            reviews_with_assignment.*,
            CASE
                WHEN is_replied = TRUE THEN 'RESPONDED'
                WHEN response_sent IS NOT NULL THEN 'RESPONDED'
                -- auto_resolved = platform reports the review replied by
                -- someone outside Loop. Still RESPONDED for queue purposes
                -- (don't re-assign), but is_loop_replied below stays FALSE
                -- so it doesn't inflate Loop-completed metrics.
                WHEN assignment_status IN ('completed', 'auto_resolved') THEN 'RESPONDED'
                WHEN hours_left <= 0 THEN 'EXPIRED'
                ELSE 'PENDING'
            END AS status,
            COALESCE(replied_comment, ai_response) AS response_text,
            CASE
                WHEN hours_left <= 24 THEN 'CRITICAL'
                WHEN hours_left <= 48 THEN 'URGENT'
                ELSE 'NORMAL'
            END AS priority,
            CASE
                WHEN rating_value = 'RATING_VALUE_LOVED' THEN 'Loved'
                WHEN rating_value = 'RATING_VALUE_THUMBS_UP' THEN 'Thumbs Up'
                WHEN rating_value = 'RATING_VALUE_THUMBS_DOWN' THEN 'Thumbs Down'
                WHEN rating_value = 'RATING_VALUE_FIVE' THEN '5 Stars'
                WHEN SAFE_CAST(star_rating AS FLOAT64) > 0
                    THEN CONCAT(CAST(CAST(SAFE_CAST(star_rating AS FLOAT64) AS INT64) AS STRING), ' Stars')
                ELSE COALESCE(rating_value, CAST(star_rating AS STRING))
            END AS rating_display,
            CASE
                WHEN rating_value = 'RATING_VALUE_LOVED' THEN 5.0
                WHEN rating_value = 'RATING_VALUE_THUMBS_UP' THEN 4.0
                WHEN rating_value = 'RATING_VALUE_THUMBS_DOWN' THEN 1.0
                WHEN rating_value = 'RATING_VALUE_FIVE' THEN 5.0
                WHEN SAFE_CAST(star_rating AS FLOAT64) > 0 THEN SAFE_CAST(star_rating AS FLOAT64)
                ELSE NULL
            END AS rating_numeric,
            CASE
                WHEN platform = 'UberEats' THEN
                    CONCAT('https://merchants.ubereats.com/manager/home/', store_id, '/feedback/reviews/', order_id)
                WHEN platform = 'Doordash' THEN
                    CONCAT('https://www.doordash.com/merchant/feedback?store_id=', store_id)
                ELSE ''
            END AS portal_link
        FROM reviews_with_assignment
    )
    SELECT
        review_uid, order_id, review_id, chain_name, b_name_id, brand_name,
        platform, slug, store_id,
        customer_name, customer_id, orders_count, customer_type,
        CAST(star_rating AS STRING) AS star_rating, rating_type, rating_value,
        rating_numeric, rating_display, review_text, items, order_value,
        review_date, hours_left,
        portal_link, response_text, ai_response_type AS response_type, coupon_value,
        CAST(config_id AS STRING) AS config_id, status, priority,
        is_replied,
        -- is_loop_replied is TRUE only when Loop actually did the work —
        -- real mark_responded via extension, OR observed_responded with a
        -- responder email that matched the slug's portal username
        -- (missed_but_ours). Both of these write status='completed'.
        -- auto_resolved (external responder) deliberately does NOT count.
        (assignment_status = 'completed') AS is_loop_replied,
        portal_username, portal_password
    FROM reviews_with_status
    ORDER BY
        CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END,
        hours_left ASC, chain_name, platform, slug
    """
    return bq_read(sql)


@cached(ttl=300)
def fetch_chain_totals_14d() -> pd.DataFrame:
    """
    Per-chain totals over the last 14 days, restricted to chains ReEngage
    actually manages (= at least one non-paused row in review_response_config).
    Used by Chain Health for the top-level summary cards.

    `loop_responded` is derived from our own reengage_dashboard_v2_assignments
    table (a Loop reply ⇔ an assignment row with status='completed' for that
    review). We do NOT read `automation_reviews.is_loop_replied` anymore —
    we stopped writing to it to avoid colliding with the dbt MERGE.

    `responded` counts a review as replied if either the platform has confirmed
    it (`is_replied`) OR our assignments table has a completed row for it.
    Matching on (order_id OR review_id) also catches the historical DoorDash
    rows where the extension passed `complaintId` (= review_id) as `order_id`.
    """
    from backend.config import TABLE_ASSIGNMENTS
    return bq_read(f"""
        WITH loop_completed AS (
            SELECT DISTINCT order_id AS completed_id
            FROM `{TABLE_ASSIGNMENTS}`
            WHERE status = 'completed'
        )
        SELECT
            slug_mapping.chain AS chain_name,
            COUNT(*) AS total,
            COUNTIF(
                automation_review.is_replied = TRUE
                OR lc_oid.completed_id IS NOT NULL
                OR lc_rid.completed_id IS NOT NULL
            ) AS responded,
            COUNTIF(
                lc_oid.completed_id IS NOT NULL
                OR lc_rid.completed_id IS NOT NULL
            ) AS loop_responded
        FROM `{TABLE_AUTOMATION_REVIEWS}` AS automation_review
        INNER JOIN `{TABLE_SLUG_AM_MAPPING}` AS slug_mapping
            ON automation_review.slug = slug_mapping.slug
        LEFT JOIN loop_completed AS lc_oid
            ON lc_oid.completed_id = automation_review.order_id
        LEFT JOIN loop_completed AS lc_rid
            ON lc_rid.completed_id = automation_review.review_id
        WHERE COALESCE(automation_review.review_timestamp, automation_review.order_timestamp)
              >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
          -- Prune the partition. automation_reviews is DAY-partitioned on
          -- review_timestamp, but the COALESCE filter above wraps the partition
          -- column in a function, so BigQuery can't prune and scans all ~727
          -- partitions (~4.4 GiB) on every call. This bare-column predicate lets
          -- it prune to recent partitions; the IS NULL arm keeps rows with no
          -- review_timestamp that fall back to order_timestamp. 1 extra day of
          -- slack covers any timezone rounding in the COALESCE comparison.
          AND (
              automation_review.review_timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 15 DAY))
              OR automation_review.review_timestamp IS NULL
          )
          AND EXISTS (
              SELECT 1
              FROM `{TABLE_REVIEW_RESPONSE_CFG}` AS response_config
              WHERE response_config.paused = FALSE
                AND response_config.chain_name = slug_mapping.chain
          )
        GROUP BY 1
    """)


@cached(ttl=300)
def fetch_managed_chains() -> list[str]:
    """Distinct chain names that ReEngage actively manages (≥1 non-paused config row)."""
    df = bq_read(f"""
        SELECT DISTINCT chain_name
        FROM `{TABLE_REVIEW_RESPONSE_CFG}`
        WHERE paused = FALSE AND chain_name IS NOT NULL
        ORDER BY chain_name
    """)
    return df["chain_name"].dropna().tolist() if not df.empty else []


@cached(ttl=300)
def fetch_chain_value(
    chain: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """All-time (or date-bounded) waterfall for a chain: total reviews,
    in-scope, responded, Loop-responded — per platform plus an 'ALL' rollup.
    Uses the new assignments table as the primary Loop-reply source, with
    the legacy automation_reviews.is_loop_replied flag as a fallback for
    pre-dashboard history (correct-when-TRUE, just incomplete on the old
    pipeline). Dates filter on the review's event_timestamp; end_date is
    inclusive of the full day.
    """
    safe_chain = (chain or "").replace("'", "''")
    date_filter = ""
    if start_date:
        date_filter += (
            f" AND COALESCE(ar.review_timestamp, ar.order_timestamp) "
            f">= TIMESTAMP('{start_date}')"
        )
    if end_date:
        date_filter += (
            f" AND COALESCE(ar.review_timestamp, ar.order_timestamp) "
            f"< TIMESTAMP_ADD(TIMESTAMP('{end_date}'), INTERVAL 1 DAY)"
        )
    return bq_read(f"""
    WITH loop_completed AS (
      SELECT DISTINCT order_id AS completed_id
      FROM `{TABLE_ASSIGNMENTS}`
      WHERE status = 'completed'
    ),
    deduped_reviews AS (
      SELECT
        ar.review_id, ar.order_id, ar.slug, ar.platform,
        ar.is_replied, ar.star_rating, ar.rating_value,
        SAFE_CAST(ar.orders_count AS INT64) AS orders_count,
        ar.review_text,
        COALESCE(ar.is_loop_replied, FALSE) AS is_loop_replied_hist
      FROM `{TABLE_AUTOMATION_REVIEWS}` AS ar
      WHERE TRUE{date_filter}
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COALESCE(ar.review_id, ar.order_id)
        ORDER BY COALESCE(ar.review_timestamp, ar.order_timestamp) DESC
      ) = 1
    ),
    reviews AS (
      SELECT
        dr.platform,
        dr.is_replied,
        (lc_oid.completed_id IS NOT NULL
         OR lc_rid.completed_id IS NOT NULL
         OR dr.is_loop_replied_hist) AS is_loop_replied,
        EXISTS (
          SELECT 1
          FROM `{TABLE_REVIEW_RESPONSE_CFG}` AS rrc
          WHERE LOWER(rrc.chain_name) = LOWER(sm.chain)
            AND rrc.paused = FALSE
            AND (
              ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rrc.vb_platforms), [])) = 0
              OR dr.platform IN UNNEST(JSON_VALUE_ARRAY(rrc.vb_platforms))
            )
            AND (
              ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rrc.ratings), [])) = 0
              OR CAST(dr.star_rating AS STRING) IN UNNEST(JSON_VALUE_ARRAY(rrc.ratings))
              OR dr.rating_value IN UNNEST(JSON_VALUE_ARRAY(rrc.ratings))
            )
            AND (
              ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rrc.customer_types), [])) = 0
              OR (CASE WHEN dr.orders_count > 1 THEN 'existing' ELSE 'new' END)
                 IN UNNEST(JSON_VALUE_ARRAY(rrc.customer_types))
            )
            AND (
              ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rrc.feedback_presence), [])) = 0
              OR (CASE WHEN COALESCE(TRIM(dr.review_text), '') = '' THEN 'without_feedback' ELSE 'with_feedback' END)
                 IN UNNEST(JSON_VALUE_ARRAY(rrc.feedback_presence))
            )
        ) AS in_scope
      FROM deduped_reviews AS dr
      INNER JOIN `{TABLE_SLUG_AM_MAPPING}` AS sm ON dr.slug = sm.slug
      LEFT JOIN loop_completed AS lc_oid ON lc_oid.completed_id = dr.order_id
      LEFT JOIN loop_completed AS lc_rid ON lc_rid.completed_id = dr.review_id
      WHERE LOWER(sm.chain) = LOWER('{safe_chain}')
    )
    SELECT
      CASE WHEN is_rollup = 1 THEN 'ALL' ELSE source_platform END AS platform,
      total_reviews, in_scope, responded, loop_responded
    FROM (
      SELECT
        platform AS source_platform,
        GROUPING(platform) AS is_rollup,
        COUNT(*) AS total_reviews,
        COUNTIF(in_scope) AS in_scope,
        COUNTIF(is_replied OR is_loop_replied) AS responded,
        COUNTIF(is_loop_replied) AS loop_responded
      FROM reviews
      GROUP BY ROLLUP(platform)
    )
    ORDER BY is_rollup DESC, platform
    """)


@cached(ttl=300)
def fetch_flow_activity_7d(period_days: int = 7) -> dict:
    """Period-ACTIVITY (flow) view: events that happened in the last `period_days`,
    each counted on its own event date (America/Chicago), independent of when the
    review was posted. Companion to the stock view in get_chain_health().

      - ingested: in-scope reviews POSTED in the window.
      - solved:   Loop completions with completed_at in the window (reliable signal,
                  same as the daily throughput alert; external replies excluded).
      - missed:   in-scope reviews whose DEADLINE fell in the window and were not
                  replied by that deadline.

    Returns {period_start, period_end,
      new_reviews: {total, doordash, ubereats, replied, pending, expired}  # cohort — replied+pending+expired sum to total
      solved:      {total, doordash, ubereats}                              # Loop completions this week (independent)
      missed:      {total, doordash, ubereats}                              # deadlines missed this week (independent)
    }. new_reviews is a lifecycle funnel of THIS week's inflow (expired ~0 for a
    fresh week — they haven't matured); solved/missed are independent event counts.
    """
    today_ct = datetime.now(ZoneInfo("America/Chicago")).date()
    end_date = today_ct.isoformat()
    start_date = (today_ct - timedelta(days=period_days - 1)).isoformat()

    review_sql = f"""
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
        resolved AS (
          SELECT DISTINCT key FROM (
            SELECT review_uid AS key FROM `{TABLE_ASSIGNMENTS}` WHERE status IN ('completed','auto_resolved')
            UNION ALL SELECT order_id AS key FROM `{TABLE_ASSIGNMENTS}` WHERE status IN ('completed','auto_resolved') AND order_id IS NOT NULL
          )
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
          -- Cover both legs: ingested (posted in window) and missed (deadline in
          -- window => posted up to 14 days earlier). ~22-day COALESCE bound +
          -- bare-column partition prune (see review_repository.py:65-77).
          WHERE COALESCE(ar.review_timestamp, ar.order_timestamp) >= TIMESTAMP(DATE_SUB(DATE '{start_date}', INTERVAL 15 DAY))
            AND (ar.review_timestamp >= TIMESTAMP(DATE_SUB(DATE '{start_date}', INTERVAL 16 DAY)) OR ar.review_timestamp IS NULL)
            AND ar.platform IN ('Doordash','UberEats')
            AND EXISTS (
              SELECT 1 FROM `{TABLE_REVIEW_RESPONSE_CFG}` rc
              WHERE rc.paused=FALSE AND sm.chain=rc.chain_name
                AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.vb_platforms),[]))=0      OR ar.platform IN UNNEST(JSON_VALUE_ARRAY(rc.vb_platforms)))
                AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.ratings),[]))=0           OR CAST(ar.star_rating AS STRING) IN UNNEST(JSON_VALUE_ARRAY(rc.ratings)) OR ar.rating_value IN UNNEST(JSON_VALUE_ARRAY(rc.ratings)))
                AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.customer_types),[]))=0    OR (CASE WHEN SAFE_CAST(ar.orders_count AS INT64)>1 THEN 'existing' ELSE 'new' END) IN UNNEST(JSON_VALUE_ARRAY(rc.customer_types)))
                AND (ARRAY_LENGTH(IFNULL(JSON_VALUE_ARRAY(rc.feedback_presence),[]))=0 OR (CASE WHEN COALESCE(TRIM(ar.review_text),'')='' THEN 'without_feedback' ELSE 'with_feedback' END) IN UNNEST(JSON_VALUE_ARRAY(rc.feedback_presence)))
            )
          QUALIFY ROW_NUMBER() OVER (PARTITION BY COALESCE(ar.review_id, ar.order_id) ORDER BY COALESCE(ar.review_timestamp, ar.order_timestamp) DESC) = 1
        ),
        enriched AS (
          SELECT b.*, DATE(DATETIME(b.deadline_ts,'America/Chicago')) AS deadline_date,
            (b.is_replied OR res_o.key IS NOT NULL OR res_r.key IS NOT NULL) AS replied_now,
            (b.is_replied OR are_o.key IS NOT NULL OR are_r.key IS NOT NULL
             OR (LEAST(IFNULL(ld_o.completed_at, TIMESTAMP '9999-12-31'),
                       IFNULL(ld_r.completed_at, TIMESTAMP '9999-12-31')) <= b.deadline_ts)) AS replied_by_deadline
          FROM base b
          LEFT JOIN resolved res_o ON res_o.key=b.order_id
          LEFT JOIN resolved res_r ON res_r.key=b.review_id
          LEFT JOIN auto_res  are_o ON are_o.key=b.order_id
          LEFT JOIN auto_res  are_r ON are_r.key=b.review_id
          LEFT JOIN loop_done ld_o  ON ld_o.key=b.order_id
          LEFT JOIN loop_done ld_r  ON ld_r.key=b.review_id
        )
        SELECT
          -- New-reviews cohort: posted in the window, split by CURRENT status (sums to nr_total)
          COUNTIF(posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}')                          AS nr_total,
          COUNTIF(posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND platform='Doordash')  AS nr_dd,
          COUNTIF(posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND platform='UberEats')   AS nr_ue,
          COUNTIF(posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND replied_now)           AS nr_replied,
          COUNTIF(posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND NOT replied_now AND deadline_ts >  CURRENT_TIMESTAMP()) AS nr_pending,
          COUNTIF(posted_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND NOT replied_now AND deadline_ts <= CURRENT_TIMESTAMP()) AS nr_expired,
          -- Deadlines missed this week (by deadline date; independent of the cohort above)
          COUNTIF(deadline_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND NOT replied_by_deadline)                          AS missed_total,
          COUNTIF(deadline_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND NOT replied_by_deadline AND platform='Doordash')  AS missed_dd,
          COUNTIF(deadline_date BETWEEN DATE '{start_date}' AND DATE '{end_date}' AND NOT replied_by_deadline AND platform='UberEats')   AS missed_ue
        FROM enriched
    """
    solved_sql = f"""
        SELECT platform, COUNT(DISTINCT COALESCE(review_uid, order_id)) AS total
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status='completed' AND completed_at IS NOT NULL
          AND DATE(DATETIME(completed_at,'America/Chicago')) BETWEEN DATE '{start_date}' AND DATE '{end_date}'
          AND NOT IFNULL(observed_out_of_window, FALSE)
        GROUP BY platform
    """
    rev = bq_read(review_sql).to_dict("records")[0]
    sol = bq_read(solved_sql)

    # New-reviews cohort — replied + pending + expired sum to total.
    new_reviews = {
        "total": int(rev["nr_total"]), "doordash": int(rev["nr_dd"]), "ubereats": int(rev["nr_ue"]),
        "replied": int(rev["nr_replied"]), "pending": int(rev["nr_pending"]), "expired": int(rev["nr_expired"]),
    }
    missed = {
        "total": int(rev["missed_total"]), "doordash": int(rev["missed_dd"]), "ubereats": int(rev["missed_ue"]),
    }
    solved = {"total": 0, "doordash": 0, "ubereats": 0}
    for r in sol.to_dict("records"):
        plat = "doordash" if r["platform"] == "Doordash" else "ubereats" if r["platform"] == "UberEats" else None
        if plat:
            solved[plat] = int(r["total"])
    solved["total"] = solved["doordash"] + solved["ubereats"]

    return {
        "period_start": start_date, "period_end": end_date,
        "new_reviews": new_reviews, "solved": solved, "missed": missed,
    }
