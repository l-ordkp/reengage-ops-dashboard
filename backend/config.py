"""
Shared constants and configuration for the ReEngage Ops Dashboard.
"""

import os

PROJECT = "arboreal-vision-339901"

# ── V2 table names (new tables, never touch existing ones) ───────────────────
TABLE_USERS       = "ops_metrics_data.reengage_dashboard_v2_users"
TABLE_ASSIGNMENTS = "ops_metrics_data.reengage_dashboard_v2_assignments"
TABLE_OPS_LOG     = "ops_metrics_data.reengage_dashboard_v2_ops_log"

# ── Read cutover (BQ→PG migration) ────────────────────────────────────────────
# Writes are Postgres-only (PR #32); these are the Datastream CDC mirrors of the
# PG tables in BigQuery, used by every BQ *read* so dashboards/notifiers see the
# live PG state without rewriting their automation_reviews joins. Both mirrors
# are MERGE-mode (verified: one row per id, row count and max(updated_at)
# exactly matching live PG) — no datastream_metadata dedup needed. Do NOT write
# to these (Datastream owns them); the legacy TABLE_ASSIGNMENTS/TABLE_OPS_LOG
# above stay only for the not-yet-ported redistribute write path and are
# otherwise frozen as of the 2026-07-15 PG-only-writes deploy.
TABLE_ASSIGNMENTS_READ = "pg_cdc_public.reengage_assignments"
TABLE_OPS_LOG_READ     = "pg_cdc_public.reengage_ops_log"

# ── Read-only existing tables ────────────────────────────────────────────────
TABLE_AUTOMATION_REVIEWS   = "elt_data.automation_reviews"
TABLE_SLUG_AM_MAPPING      = "restaurant_aggregate_metrics.slug_am_mapping"
TABLE_REVIEW_RESPONSE_CFG  = "pg_cdc_public.review_response_config"
TABLE_REVIEW_RESPONSES     = "pg_cdc_public.review_responses"

# ── User roles ───────────────────────────────────────────────────────────────
ROLE_MANAGER = "manager"
ROLE_LEAD    = "lead"
ROLE_TENURED = "tenured_operator"
ROLE_NEW     = "new_operator"
ALL_ROLES    = [ROLE_MANAGER, ROLE_LEAD, ROLE_TENURED, ROLE_NEW]

# TEMPORARY: route the assignment cron to the focused algorithm (critical +
# urgent + small near-urgent buffer only; far normals left unassigned). See
# backend/managers/focused_assignment_manager.py. ON by default; set
# FOCUSED_ASSIGNMENT_MODE=false to fall back to the full two-cap partition.
FOCUSED_ASSIGNMENT_MODE = os.environ.get("FOCUSED_ASSIGNMENT_MODE", "true").lower() in ("1", "true", "yes")
