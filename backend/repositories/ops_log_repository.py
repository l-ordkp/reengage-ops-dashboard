"""Ops log data access — audit trail of all operator actions."""
from __future__ import annotations

import uuid

import pandas as pd

from backend.clients.bq_client import bq_exec, bq_read
from backend.config import TABLE_OPS_LOG
from backend.utils.cache import cached


def _safe(val: str) -> str:
    return (val or "").replace("'", "''")


def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@cached(ttl=60)
def fetch_recent_ops_log(limit: int = 500) -> pd.DataFrame:
    return bq_read(f"""
        SELECT id, review_uid, platform, chain_name, action,
               operator_email, performed_by, remarks, processing_timestamp
        FROM `{TABLE_OPS_LOG}`
        ORDER BY processing_timestamp DESC
        LIMIT {limit}
    """)


def log_action(
    review_uid: str, platform: str, chain_name: str, action: str,
    operator_email: str, performed_by: str, remarks: str = "",
) -> None:
    """Insert a single audit log row."""
    now = _now_str()
    bq_exec(f"""
    INSERT INTO `{TABLE_OPS_LOG}`
        (id, review_uid, platform, chain_name, action,
         operator_email, performed_by, remarks, processing_timestamp)
    VALUES
        ('{uuid.uuid4()}', '{_safe(review_uid)}', '{_safe(platform)}', '{_safe(chain_name)}',
         '{_safe(action)}', '{_safe(operator_email)}', '{_safe(performed_by)}',
         '{_safe(remarks)}', TIMESTAMP('{now}'))
    """)
