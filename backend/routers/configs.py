"""Response configs API."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.repositories.config_repository import fetch_all_configs
from backend.utils.serializers import df_to_dicts

router = APIRouter(prefix="/api/configs", tags=["configs"])


@router.get("")
def list_configs(user: dict = Depends(get_current_user)):
    return df_to_dicts(fetch_all_configs())
