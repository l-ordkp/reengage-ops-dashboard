"""User CRUD against `reengage_dashboard_v2_users` (BigQuery)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from backend.clients.bq_client import bq_exec, bq_read
from backend.config import TABLE_USERS


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _escape_sql(value: str) -> str:
    """Escape single quotes so the value is safe to embed inside a SQL literal."""
    return value.replace("'", "''")


def fetch_user(email: str) -> dict | None:
    safe_email = _escape_sql(email.lower())
    df = bq_read(f"""
        SELECT email, name, role, approved, reduction_pct
        FROM `{TABLE_USERS}` WHERE LOWER(email) = '{safe_email}' LIMIT 1
    """)
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "email": row["email"], "name": row["name"], "role": row["role"],
        "approved": bool(row["approved"]),
        "reduction_pct": float(row.get("reduction_pct", 0)),
    }


def fetch_all_users() -> pd.DataFrame:
    return bq_read(f"""
        SELECT email, name, role, approved, reduction_pct,
               added_by, created_at, updated_at
        FROM `{TABLE_USERS}` ORDER BY role, email
    """)


def fetch_user_count() -> int:
    df = bq_read(f"SELECT COUNT(*) as cnt FROM `{TABLE_USERS}`")
    return int(df.iloc[0]["cnt"])


def fetch_approved_operators() -> pd.DataFrame:
    """Users eligible for review assignments (excludes managers and leads)."""
    from backend.config import ROLE_LEAD
    return bq_read(f"""
        SELECT email, name, role, reduction_pct
        FROM `{TABLE_USERS}`
        WHERE approved = TRUE AND role NOT IN ('{ROLE_LEAD}', 'manager')
        ORDER BY email
    """)


def insert_or_update_user(
    email: str, name: str, role: str, reduction_pct: float, added_by: str,
) -> None:
    now = _now_str()
    safe_email = _escape_sql(email.lower())
    safe_name = _escape_sql(name)
    safe_added_by = _escape_sql(added_by)
    bq_exec(f"""
    MERGE `{TABLE_USERS}` AS target
    USING (SELECT '{safe_email}' AS email) AS source
    ON LOWER(target.email) = source.email
    WHEN MATCHED THEN UPDATE SET
        name = '{safe_name}', role = '{role}', approved = TRUE,
        reduction_pct = {reduction_pct}, updated_at = TIMESTAMP('{now}')
    WHEN NOT MATCHED THEN INSERT
        (email, name, role, approved, reduction_pct, added_by, created_at, updated_at)
    VALUES ('{safe_email}', '{safe_name}', '{role}', TRUE, {reduction_pct}, '{safe_added_by}',
            TIMESTAMP('{now}'), TIMESTAMP('{now}'))
    """)


def update_role(email: str, new_role: str, reduction_pct: float) -> None:
    now = _now_str()
    safe_email = _escape_sql(email.lower())
    bq_exec(f"""
    UPDATE `{TABLE_USERS}`
    SET role = '{new_role}', reduction_pct = {reduction_pct},
        updated_at = TIMESTAMP('{now}')
    WHERE LOWER(email) = '{safe_email}'
    """)


def update_approval(email: str, approved: bool) -> None:
    now = _now_str()
    safe_email = _escape_sql(email.lower())
    bq_exec(f"""
    UPDATE `{TABLE_USERS}`
    SET approved = {approved}, updated_at = TIMESTAMP('{now}')
    WHERE LOWER(email) = '{safe_email}'
    """)


def delete_user(email: str) -> None:
    safe_email = _escape_sql(email.lower())
    bq_exec(f"DELETE FROM `{TABLE_USERS}` WHERE LOWER(email) = '{safe_email}'")


def update_name_if_empty(email: str, name: str) -> None:
    """Set name on a user that was added without one (used during OAuth bootstrap)."""
    safe_email = _escape_sql(email.lower())
    safe_name = _escape_sql(name)
    now = _now_str()
    bq_exec(f"""
        UPDATE `{TABLE_USERS}`
        SET name = '{safe_name}', updated_at = TIMESTAMP('{now}')
        WHERE LOWER(email) = '{safe_email}'
    """)
