"""
Shared constants and configuration for the ReEngage Ops Dashboard.
"""

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
ROLE_LEAD    = "lead"
ROLE_TENURED = "tenured_operator"
ROLE_NEW     = "new_operator"
ALL_ROLES    = [ROLE_LEAD, ROLE_TENURED, ROLE_NEW]
