-- ============================================================================
-- Backfill: observed_out_of_window flag on historical observed-responded rows
--
-- Computes the OOW flag retroactively for every assignment row that has a
-- corresponding ops_log entry with action='observed_responded' (the
-- 88 initial-backfill rows from 2026-06-12 + the 89 from the gvcs browse
-- the same day + anything that's landed since).
--
-- Definition: at the time of observation, was the review's review_timestamp
-- past the platform's response window (DD 7d, UE 14d)? If yes — or if the
-- review isn't in automation_reviews at all — OOW=TRUE. Otherwise FALSE.
--
-- Observation time is MAX(ops_log.processing_timestamp) per review_uid
-- (defensive against duplicate ops_log entries — there shouldn't be any
-- but MAX collapses safely if there are). Review time uses
-- COALESCE(review_timestamp, order_timestamp) to handle UE rows where
-- review_timestamp is sometimes NULL.
--
-- Idempotent: WHERE observed_out_of_window IS NULL skips rows we've
-- already classified. Re-running the script after new observations land
-- only touches the new NULLs.
-- ============================================================================


-- Pre-flight: how many rows need the flag?
SELECT
  a.platform,
  COUNT(*) AS to_backfill
FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments` a
WHERE a.observed_out_of_window IS NULL
  AND a.review_uid IN (
    SELECT DISTINCT review_uid
    FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log`
    WHERE action = 'observed_responded'
  )
GROUP BY a.platform
ORDER BY a.platform;


-- ----------------------------------------------------------------------------
-- Backfill UPDATE.
-- ----------------------------------------------------------------------------
UPDATE `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments` a
SET observed_out_of_window = CASE
  WHEN obs.review_ts IS NULL THEN TRUE
  -- Future-dated review_timestamps (clock skew / malformed source) are
  -- treated as out_of_window so they don't leak into operator/throughput
  -- metrics. Matches the upper bound on the runtime write path
  -- (extension_repository.fetch_review_age_status).
  WHEN obs.review_ts > obs.observed_at THEN TRUE
  WHEN obs.platform = 'Doordash' THEN
    TIMESTAMP_ADD(obs.review_ts, INTERVAL 7 DAY) < obs.observed_at
  WHEN obs.platform = 'UberEats' THEN
    TIMESTAMP_ADD(obs.review_ts, INTERVAL 14 DAY) < obs.observed_at
  ELSE TRUE
END
FROM (
  SELECT
    a2.assignment_id,
    a2.platform,
    MAX(l.processing_timestamp) AS observed_at,
    MAX(COALESCE(ar.review_timestamp, ar.order_timestamp)) AS review_ts
  FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments` a2
  JOIN `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log` l
    ON a2.review_uid = l.review_uid
   AND l.action = 'observed_responded'
  LEFT JOIN `arboreal-vision-339901.elt_data.automation_reviews` ar
    ON a2.review_uid = COALESCE(ar.review_id, ar.order_id)
  WHERE a2.observed_out_of_window IS NULL
  GROUP BY a2.assignment_id, a2.platform
) obs
WHERE a.assignment_id = obs.assignment_id;


-- ----------------------------------------------------------------------------
-- Post-verify: how many ended up TRUE vs FALSE?
-- ----------------------------------------------------------------------------
SELECT
  a.platform,
  a.observed_out_of_window,
  COUNT(*) AS n
FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments` a
WHERE a.review_uid IN (
  SELECT DISTINCT review_uid
  FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log`
  WHERE action = 'observed_responded'
)
GROUP BY a.platform, a.observed_out_of_window
ORDER BY a.platform, a.observed_out_of_window;
