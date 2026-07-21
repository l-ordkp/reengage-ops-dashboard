-- ============================================================================
-- Partial index for the first_seen ledger dedup lookup (PR #36)
--
-- The daily cron gate asks "which of these ~35k candidate review_uids already
-- have a first_seen row?" (pg_reengage_repository.fetch_first_seen_uids).
-- Without an index, Postgres answers with a sequential scan of ALL of
-- reengage_ops_log (~10k new rows/day across all actions) — the query's
-- 20-day time bound limits what MATCHES, not what gets READ.
--
-- Partial index: covers only action='first_seen' rows, so it stays small
-- (one entry per review ever seen, ~5k/day) and turns the lookup into pure
-- index probes regardless of how large the audit log grows.
--
-- CONCURRENTLY: no table lock; safe on live prod. Cannot run inside a
-- transaction block — execute via psql with autocommit (the default).
-- Idempotent via IF NOT EXISTS.
-- ============================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_reengage_ops_log_first_seen_uid
    ON reengage_ops_log (review_uid)
    WHERE action = 'first_seen';
