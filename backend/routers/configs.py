"""Response configs routes."""

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.data_loaders import load_response_configs
from backend.db import _df_to_dicts

router = APIRouter(prefix="/api/configs", tags=["configs"])


@router.get("")
def list_configs(user: dict = Depends(get_current_user)):
    return _df_to_dicts(load_response_configs())
