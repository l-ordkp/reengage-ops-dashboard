"""User CRUD — extracted from auth.py, no Streamlit dependency."""

from datetime import datetime, timezone

import pandas as pd

from backend.config import ROLE_LEAD, TABLE_USERS
from backend.db import bq_read, bq_exec


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _safe(val: str) -> str:
    return val.replace("'", "''")


from typing import Optional

def get_user(email: str) -> Optional[dict]:
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
        "approved": bool(r["approved"]), "reduction_pct": float(r.get("reduction_pct", 0)),
    }


def load_all_users() -> pd.DataFrame:
    return bq_read(f"""
        SELECT email, name, role, approved, reduction_pct,
               added_by, created_at, updated_at
        FROM `{TABLE_USERS}` ORDER BY role, email
    """)


def user_count() -> int:
    df = bq_read(f"SELECT COUNT(*) as cnt FROM `{TABLE_USERS}`")
    return int(df.iloc[0]["cnt"])


def add_user(email: str, name: str, role: str, reduction_pct: float, added_by: str):
    now = _now()
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


def update_user_role(email: str, new_role: str, reduction_pct: float):
    now = _now()
    se = _safe(email.lower())
    bq_exec(f"""
    UPDATE `{TABLE_USERS}`
    SET role = '{new_role}', reduction_pct = {reduction_pct},
        updated_at = TIMESTAMP('{now}')
    WHERE LOWER(email) = '{se}'
    """)


def update_user_approval(email: str, approved: bool):
    now = _now()
    se = _safe(email.lower())
    bq_exec(f"""
    UPDATE `{TABLE_USERS}`
    SET approved = {approved}, updated_at = TIMESTAMP('{now}')
    WHERE LOWER(email) = '{se}'
    """)


def remove_user(email: str):
    from backend.write_helpers import redistribute_assignments
    redistribute_assignments(email)
    se = _safe(email.lower())
    bq_exec(f"DELETE FROM `{TABLE_USERS}` WHERE LOWER(email) = '{se}'")


def is_lead(role: str) -> bool:
    return role in (ROLE_LEAD, "manager")
