"""
BigQuery client and query helpers — no Streamlit dependency.
Uses env vars for credentials, module-level singleton for client.
"""
from __future__ import annotations

import os

import pandas as pd
from google.cloud import bigquery
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.transport.requests import Request as AuthRequest

from backend.config import PROJECT

_bq_client = None


def _get_bq_client():
    global _bq_client
    if _bq_client is not None:
        return _bq_client

    refresh_token = os.environ.get("GCP_REFRESH_TOKEN")
    if refresh_token:
        creds = OAuthCredentials(
            token=None,
            refresh_token=refresh_token,
            client_id=os.environ.get("GCP_CLIENT_ID"),
            client_secret=os.environ.get("GCP_CLIENT_SECRET"),
            token_uri="https://oauth2.googleapis.com/token",
        )
        creds.refresh(AuthRequest())
        _bq_client = bigquery.Client(project=PROJECT, credentials=creds)
    else:
        # Local dev: use Application Default Credentials
        _bq_client = bigquery.Client(project=PROJECT)

    return _bq_client


def bq_read(sql: str) -> pd.DataFrame:
    return _get_bq_client().query(sql).to_dataframe()


def bq_read_dicts(sql: str) -> list[dict]:
    """Return query results as a list of dicts (JSON-serializable)."""
    df = bq_read(sql)
    return _df_to_dicts(df)


def bq_exec(sql: str):
    _get_bq_client().query(sql).result()


def _df_to_dicts(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to list of dicts, fully JSON-serializable.
    Handles NaN/NaT, numpy int64/float64, pandas Timestamp, date objects."""
    import numpy as np
    from datetime import date, datetime as dt

    records = df.where(df.notna(), None).to_dict("records")
    for row in records:
        for k, v in row.items():
            if v is None:
                continue
            elif isinstance(v, (pd.Timestamp, dt)):
                row[k] = v.isoformat()
            elif isinstance(v, date):
                row[k] = v.isoformat()
            elif isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = float(v) if not np.isnan(v) else None
            elif isinstance(v, np.bool_):
                row[k] = bool(v)
    return records
