"""Ops log data access — audit trail of all operator actions."""
from __future__ import annotations

import uuid

import pandas as pd

from backend.clients.bq_client import bq_exec, bq_read
from backend.config import TABLE_OPS_LOG, TABLE_OPS_LOG_READ
from backend.utils.cache import cached


def _escape_sql(value: str) -> str:
    """Escape single quotes so the value is safe to embed inside a SQL literal."""
    return (value or "").replace("'", "''")


def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _validate_date(value: str) -> str:
    """Validate a user-supplied YYYY-MM-DD string before interpolating it into
    SQL. date_from/date_to arrive as query params, so interpolating them raw
    would allow SQL injection. A date has a fixed shape — parse it and re-emit a
    canonical YYYY-MM-DD string, rejecting anything else."""
    from datetime import datetime
    return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")


@cached(ttl=60)
def fetch_recent_ops_log(limit: int = 500) -> pd.DataFrame:
    return bq_read(f"""
        SELECT entry_id AS id, review_uid, platform, chain_name, action,
               operator_email, performed_by, remarks, processing_timestamp
        FROM `{TABLE_OPS_LOG_READ}`
        ORDER BY processing_timestamp DESC
        LIMIT {limit}
    """)


@cached(ttl=120)
def fetch_qc_log(date_from: str | None = None, date_to: str | None = None) -> pd.DataFrame:
    """
    Fetch all `mark_responded` entries that contain QC data (no limit).
    Optionally filter by date range (inclusive, on processing_timestamp).
    """
    where_parts = [
        "action = 'mark_responded'",
        "remarks LIKE '%resp:%'",
    ]
    if date_from:
        where_parts.append(f"DATE(processing_timestamp, 'Asia/Kolkata') >= DATE('{_validate_date(date_from)}')")
    if date_to:
        where_parts.append(f"DATE(processing_timestamp, 'Asia/Kolkata') <= DATE('{_validate_date(date_to)}')")
    where_clause = " AND ".join(where_parts)
    return bq_read(f"""
        SELECT review_uid, operator_email, remarks, processing_timestamp
        FROM `{TABLE_OPS_LOG_READ}`
        WHERE {where_clause}
        ORDER BY processing_timestamp DESC
    """)


@cached(ttl=120)
def fetch_qc_mismatches(
    date_from: str | None = None, date_to: str | None = None,
) -> pd.DataFrame:
    """
    Reviews where the operator's response and/or discount did NOT match the AI
    suggestion. Just identifies which reviews need investigation — the Search
    tab handles the deep-dive into AI response / posted text / portal link.
    """
    from backend.config import TABLE_AUTOMATION_REVIEWS, TABLE_USERS

    where_parts = [
        "ops_log.action = 'mark_responded'",
        "(ops_log.remarks LIKE '%resp:MISMATCH%' OR ops_log.remarks LIKE '%disc:MISMATCH%')",
    ]
    if date_from:
        where_parts.append(
            f"DATE(ops_log.processing_timestamp, 'Asia/Kolkata') >= DATE('{_validate_date(date_from)}')"
        )
    if date_to:
        where_parts.append(
            f"DATE(ops_log.processing_timestamp, 'Asia/Kolkata') <= DATE('{_validate_date(date_to)}')"
        )
    where_clause = " AND ".join(where_parts)

    return bq_read(f"""
        SELECT
            ops_log.processing_timestamp AS responded_at,
            ops_log.operator_email,
            users.name AS operator_name,
            ops_log.platform,
            ops_log.chain_name,
            ops_log.review_uid,
            automation_review.customer_name,
            REGEXP_CONTAINS(ops_log.remarks, r'resp:MISMATCH') AS resp_mismatch,
            REGEXP_CONTAINS(ops_log.remarks, r'disc:MISMATCH') AS disc_mismatch
        FROM `{TABLE_OPS_LOG_READ}` AS ops_log
        LEFT JOIN `{TABLE_AUTOMATION_REVIEWS}` AS automation_review
            ON ops_log.review_uid = COALESCE(automation_review.review_id, automation_review.order_id)
        LEFT JOIN `{TABLE_USERS}` AS users
            ON LOWER(users.email) = LOWER(ops_log.operator_email)
        WHERE {where_clause}
        ORDER BY ops_log.processing_timestamp DESC
    """)


def log_action(
    review_uid: str, platform: str, chain_name: str, action: str,
    operator_email: str, performed_by: str, remarks: str = "",
) -> None:
    """Insert a single audit log row."""
    now = _now_str()
    safe_review_uid = _escape_sql(review_uid)
    safe_platform = _escape_sql(platform)
    safe_chain_name = _escape_sql(chain_name)
    safe_action = _escape_sql(action)
    safe_operator_email = _escape_sql(operator_email)
    safe_performed_by = _escape_sql(performed_by)
    safe_remarks = _escape_sql(remarks)
    bq_exec(f"""
    INSERT INTO `{TABLE_OPS_LOG}`
        (id, review_uid, platform, chain_name, action,
         operator_email, performed_by, remarks, processing_timestamp)
    VALUES
        ('{uuid.uuid4()}', '{safe_review_uid}', '{safe_platform}', '{safe_chain_name}',
         '{safe_action}', '{safe_operator_email}', '{safe_performed_by}',
         '{safe_remarks}', TIMESTAMP('{now}'))
    """)


def log_actions_bulk(entries: list[dict]) -> None:
    """Bulk variant of log_action. Each entry: review_uid, platform, chain_name,
    action, operator_email, performed_by, remarks. Used by the observed-responded
    flow so a single dashboard refresh of N back-marked reviews produces one
    INSERT, not N."""
    if not entries:
        return
    now = _now_str()
    value_rows = []
    for entry in entries:
        value_rows.append(
            f"('{uuid.uuid4()}', '{_escape_sql(entry['review_uid'])}', "
            f"'{_escape_sql(entry['platform'])}', '{_escape_sql(entry.get('chain_name', ''))}', "
            f"'{_escape_sql(entry['action'])}', '{_escape_sql(entry['operator_email'])}', "
            f"'{_escape_sql(entry['performed_by'])}', '{_escape_sql(entry.get('remarks', ''))}', "
            f"TIMESTAMP('{now}'))"
        )
    batch_size = 500
    for start in range(0, len(value_rows), batch_size):
        batch = value_rows[start:start + batch_size]
        bq_exec(f"""
        INSERT INTO `{TABLE_OPS_LOG}`
            (id, review_uid, platform, chain_name, action,
             operator_email, performed_by, remarks, processing_timestamp)
        VALUES {', '.join(batch)}
        """)
