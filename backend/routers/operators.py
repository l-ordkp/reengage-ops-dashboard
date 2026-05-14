"""Operator performance API (lead/manager only)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from backend.auth.dependencies import require_lead
from backend.managers.operator_manager import (
    get_chain_breakdown, get_daily_breakdown, get_performance, get_qc_summary,
)

router = APIRouter(prefix="/api/operators", tags=["operators"])


@router.get("/performance")
def performance(user: dict = Depends(require_lead)):
    return get_performance()


@router.get("/daily-breakdown")
def daily_breakdown(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_lead),
):
    return get_daily_breakdown(date_from, date_to)


@router.get("/chain-breakdown")
def chain_breakdown(operator_email: Optional[str] = None, user: dict = Depends(require_lead)):
    return get_chain_breakdown(operator_email)


@router.get("/qc-summary")
def qc_summary(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_lead),
):
    return get_qc_summary(date_from, date_to)
