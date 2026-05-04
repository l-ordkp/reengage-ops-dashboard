"""Ops log routes."""

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.data_loaders import load_ops_log
from backend.db import _df_to_dicts

router = APIRouter(prefix="/api/ops-log", tags=["ops-log"])


@router.get("")
def list_ops_log(user: dict = Depends(get_current_user)):
    return _df_to_dicts(load_ops_log())
