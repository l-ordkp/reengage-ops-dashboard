-- ============================================================================
-- Backfill: observed-responded historical classification
--
-- Pre-PR-A (#6), the /observed-responded flow inserted/flipped rows attributed
-- to the *observer's* email and stamped them remarks 'auto_self_resolved' or
-- 'auto_during_pending'. PR-A replaces this with a slug-username match:
--
--   - responder email matches the slug's Loop portal username → status stays
--     'completed', operator_email becomes the matched Loop username, remarks
--     become 'missed_but_ours|self_resolved' or 'missed_but_ours|during_pending'
--   - no match → status becomes 'auto_resolved', operator_email becomes NULL,
--     remarks become 'external|self_resolved' or 'external|during_pending'
--
-- This script reclassifies the 88 historical observed-responded rows that
-- predate PR-A:
--
--   - DD auto rows (83 rows / 82 review_uids): assume-match against the slug's
--     Loop portal username. Justification: every affected DD chain (gvcs,
--     Starbird) has exactly one Loop username per platform in slug_am_mapping,
--     and direct evidence from one screenshot + the platform's
--     `merchantUserEmail` field confirmed the gvcs case (accounting-gvcs@
--     restauranttechpros.com). Same shape for Starbird is presumed.
--   - UE auto rows (5 rows / 5 review_uids): UE's reviews payload never
--     exposed a responder email historically, so no positive Loop signal
--     exists. Reclassified as `external` (auto_resolved + remarks
--     `external|during_pending`).
--
-- Run AFTER PR-A is deployed. PR-B's read changes assume this has run.
-- Eyeball each step's row count against the pre-flight expected values.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Pre-flight: confirm scope. Expected (as of 2026-06-12):
--   Doordash | auto_during_pending |  6
--   Doordash | auto_self_resolved  | 77
--   UberEats | auto_during_pending |  5
-- ----------------------------------------------------------------------------
SELECT a.platform, au.remarks, COUNT(*) AS rows_to_touch
FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments` a
JOIN (
  SELECT DISTINCT review_uid, remarks
  FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log`
  WHERE action = 'observed_responded'
) au USING (review_uid)
WHERE a.status = 'completed'
GROUP BY a.platform, au.remarks
ORDER BY a.platform, au.remarks;


-- ----------------------------------------------------------------------------
-- 1. DD assignments: stamp operator_email with the slug's Loop portal
--    username. status stays 'completed' (these are `missed_but_ours`).
--    JOIN automation_reviews on order_id OR review_id to cover the historical
--    DoorDash complaintId-as-order_id rows.
-- ----------------------------------------------------------------------------
UPDATE `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments` AS a
SET operator_email = subq.username
FROM (
  -- QUALIFY = 1 guarantees at-most-one row per (review_id, order_id), so the
  -- UPDATE..FROM cannot trigger BigQuery's "must match at most one source row
  -- for each target row" error if a slug ever has multiple Loop usernames in
  -- slug_am_mapping (audited safe for gvcs / Starbird today, but future-
  -- proofing). Ordering by sm.id is arbitrary but deterministic.
  SELECT review_id, order_id, username FROM (
    SELECT
      ar.review_id,
      ar.order_id,
      LOWER(TRIM(sm.username)) AS username,
      sm.id AS sm_id
    FROM `arboreal-vision-339901.elt_data.automation_reviews` AS ar
    JOIN `arboreal-vision-339901.restaurant_aggregate_metrics.slug_am_mapping` AS sm
      ON ar.slug = sm.slug
     AND LOWER(sm.vb_platform) = 'doordash'
    WHERE sm.username IS NOT NULL
      AND TRIM(sm.username) != ''
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY ar.review_id, ar.order_id
      ORDER BY sm.id
    ) = 1
  )
) AS subq
WHERE a.platform = 'Doordash'
  AND a.status = 'completed'
  AND (a.order_id = subq.order_id OR a.review_uid = subq.review_id)
  AND a.review_uid IN (
    SELECT DISTINCT review_uid
    FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log`
    WHERE action = 'observed_responded'
  );


-- ----------------------------------------------------------------------------
-- 2. UE assignments: status='auto_resolved', operator_email=NULL.
--    Historic UE auto rows had no responder-id signal — treat as external.
-- ----------------------------------------------------------------------------
UPDATE `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments`
SET status = 'auto_resolved',
    operator_email = NULL
WHERE platform = 'UberEats'
  AND status = 'completed'
  AND review_uid IN (
    SELECT DISTINCT review_uid
    FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log`
    WHERE action = 'observed_responded'
  );


-- ----------------------------------------------------------------------------
-- 3. DD ops_log: 'auto_self_resolved' → 'missed_but_ours|self_resolved'
-- ----------------------------------------------------------------------------
UPDATE `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log` AS l
SET remarks = 'missed_but_ours|self_resolved'
WHERE l.action = 'observed_responded'
  AND l.remarks = 'auto_self_resolved'
  AND l.review_uid IN (
    SELECT DISTINCT review_uid
    FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments`
    WHERE platform = 'Doordash'
  );


-- ----------------------------------------------------------------------------
-- 4. DD ops_log: 'auto_during_pending' → 'missed_but_ours|during_pending'
-- ----------------------------------------------------------------------------
UPDATE `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log` AS l
SET remarks = 'missed_but_ours|during_pending'
WHERE l.action = 'observed_responded'
  AND l.remarks = 'auto_during_pending'
  AND l.review_uid IN (
    SELECT DISTINCT review_uid
    FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments`
    WHERE platform = 'Doordash'
  );


-- ----------------------------------------------------------------------------
-- 5. UE ops_log: 'auto_during_pending' → 'external|during_pending'
--    (UE never produced auto_self_resolved historically — no row needed.)
-- ----------------------------------------------------------------------------
UPDATE `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log` AS l
SET remarks = 'external|during_pending'
WHERE l.action = 'observed_responded'
  AND l.remarks = 'auto_during_pending'
  AND l.review_uid IN (
    SELECT DISTINCT review_uid
    FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_assignments`
    WHERE platform = 'UberEats'
  );


-- ----------------------------------------------------------------------------
-- Post-verify. Expected after backfill:
--   external|during_pending          |  5
--   missed_but_ours|during_pending   |  6
--   missed_but_ours|self_resolved    | 77
-- And no rows should remain with remarks 'auto_self_resolved' or
-- 'auto_during_pending'.
-- ----------------------------------------------------------------------------
SELECT remarks, COUNT(*) AS rows
FROM `arboreal-vision-339901.ops_metrics_data.reengage_dashboard_v2_ops_log`
WHERE action = 'observed_responded'
GROUP BY remarks
ORDER BY remarks;
