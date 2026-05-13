"""Ops log API (audit trail)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.repositories.ops_log_repository import fetch_recent_ops_log
from backend.utils.serializers import df_to_dicts

router = APIRouter(prefix="/api/ops-log", tags=["ops-log"])


@router.get("")
def list_ops_log(user: dict = Depends(get_current_user)):
    return df_to_dicts(fetch_recent_ops_log())
