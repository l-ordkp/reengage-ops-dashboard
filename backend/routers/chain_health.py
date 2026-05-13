"""Chain Health API."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.managers.chain_health_manager import get_chain_health

router = APIRouter(prefix="/api/chain-health", tags=["chain-health"])


@router.get("")
def chain_health(user: dict = Depends(get_current_user)):
    return get_chain_health()
