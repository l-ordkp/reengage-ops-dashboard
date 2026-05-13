"""
BigQuery client and raw query helpers.
Owns the singleton BQ client and basic read/exec primitives.
Business logic and serialization live elsewhere.
"""
from __future__ import annotations

import os

import pandas as pd
from google.cloud import bigquery
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.transport.requests import Request as AuthRequest

from backend.config import PROJECT

_bq_client: bigquery.Client | None = None


def _get_bq_client() -> bigquery.Client:
    """Lazy-singleton BigQuery client. Uses ADC locally, OAuth refresh token in Cloud Run."""
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
        _bq_client = bigquery.Client(project=PROJECT)

    return _bq_client


def bq_read(sql: str) -> pd.DataFrame:
    """Run a SELECT query and return a DataFrame."""
    return _get_bq_client().query(sql).to_dataframe()


def bq_exec(sql: str) -> None:
    """Run a DML/DDL statement. Blocks until done."""
    _get_bq_client().query(sql).result()


def bq_read_dicts(sql: str) -> list[dict]:
    """Convenience: read query result as a list of dicts (used by extension API)."""
    from backend.utils.serializers import df_to_dicts
    return df_to_dicts(bq_read(sql))
