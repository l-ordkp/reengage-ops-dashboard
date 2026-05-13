"""User CRUD against `reengage_dashboard_v2_users` (BigQuery)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from backend.clients.bq_client import bq_exec, bq_read
from backend.config import TABLE_USERS


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _safe(val: str) -> str:
    return val.replace("'", "''")


def fetch_user(email: str) -> dict | None:
    se = _safe(email.lower())
    df = bq_read(f"""
        SELECT email, name, role, approved, reduction_pct
        FROM `{TABLE_USERS}` WHERE LOWER(email) = '{se}' LIMIT 1
    """)
    if df.empty:
        return None
    r = df.iloc[0]
    return {
        "email": r["email"], "name": r["name"], "role": r["role"],
        "approved": bool(r["approved"]),
        "reduction_pct": float(r.get("reduction_pct", 0)),
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
    se, sn, sa = _safe(email.lower()), _safe(name), _safe(added_by)
    bq_exec(f"""
    MERGE `{TABLE_USERS}` T USING (SELECT '{se}' AS email) S ON LOWER(T.email) = S.email
    WHEN MATCHED THEN UPDATE SET
        name = '{sn}', role = '{role}', approved = TRUE,
        reduction_pct = {reduction_pct}, updated_at = TIMESTAMP('{now}')
    WHEN NOT MATCHED THEN INSERT
        (email, name, role, approved, reduction_pct, added_by, created_at, updated_at)
    VALUES ('{se}', '{sn}', '{role}', TRUE, {reduction_pct}, '{sa}',
            TIMESTAMP('{now}'), TIMESTAMP('{now}'))
    """)


def update_role(email: str, new_role: str, reduction_pct: float) -> None:
    now = _now_str()
    se = _safe(email.lower())
    bq_exec(f"""
    UPDATE `{TABLE_USERS}`
    SET role = '{new_role}', reduction_pct = {reduction_pct},
        updated_at = TIMESTAMP('{now}')
    WHERE LOWER(email) = '{se}'
    """)


def update_approval(email: str, approved: bool) -> None:
    now = _now_str()
    se = _safe(email.lower())
    bq_exec(f"""
    UPDATE `{TABLE_USERS}`
    SET approved = {approved}, updated_at = TIMESTAMP('{now}')
    WHERE LOWER(email) = '{se}'
    """)


def delete_user(email: str) -> None:
    se = _safe(email.lower())
    bq_exec(f"DELETE FROM `{TABLE_USERS}` WHERE LOWER(email) = '{se}'")


def update_name_if_empty(email: str, name: str) -> None:
    """Set name on a user that was added without one (used during OAuth bootstrap)."""
    se = _safe(email.lower())
    sn = _safe(name)
    now = _now_str()
    bq_exec(f"""
        UPDATE `{TABLE_USERS}`
        SET name = '{sn}', updated_at = TIMESTAMP('{now}')
        WHERE LOWER(email) = '{se}'
    """)
