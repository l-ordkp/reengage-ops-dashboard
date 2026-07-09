"""
Shared constants and configuration for the ReEngage Ops Dashboard.
"""

import os

PROJECT = "arboreal-vision-339901"

# ── V2 table names (new tables, never touch existing ones) ───────────────────
TABLE_USERS       = "ops_metrics_data.reengage_dashboard_v2_users"
TABLE_ASSIGNMENTS = "ops_metrics_data.reengage_dashboard_v2_assignments"
TABLE_OPS_LOG     = "ops_metrics_data.reengage_dashboard_v2_ops_log"

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

# ── Migration flags ───────────────────────────────────────────────────────────
# Dual-write extension writes to Postgres (loop_core) alongside the authoritative
# BigQuery writes during the BQ->PG migration. Best-effort (PG failures never
# break the BQ path) and OFF by default. Enable with DUAL_WRITE_PG=true.
DUAL_WRITE_PG = os.environ.get("DUAL_WRITE_PG", "false").lower() in ("1", "true", "yes")
