"""Chain Value API — all-time or date-bounded waterfall for a chosen chain."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.dependencies import get_current_user
from backend.repositories.review_repository import (
    fetch_chain_value,
    fetch_managed_chains,
)
from backend.utils.serializers import df_to_dicts

router = APIRouter(prefix="/api/chain-value", tags=["chain-value"])


@router.get("/chains")
def list_chains(user: dict = Depends(get_current_user)):
    return {"chains": fetch_managed_chains()}


def _validate_date(value: Optional[str], field: str) -> None:
    """Reject non-ISO dates and impossible calendar dates (e.g. 2026-02-30)
    before they reach BigQuery — date.fromisoformat enforces both."""
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be a valid YYYY-MM-DD date",
        )


@router.get("")
def chain_value(
    chain: str = Query(..., min_length=1),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    user: dict = Depends(get_current_user),
):
    _validate_date(start_date, "start_date")
    _validate_date(end_date, "end_date")
    df = fetch_chain_value(chain, start_date=start_date, end_date=end_date)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No reviews for chain '{chain}'")
    rows = df_to_dicts(df)
    overall = next((r for r in rows if r["platform"] == "ALL"), None)
    platforms = [r for r in rows if r["platform"] != "ALL"]
    return {
        "chain": chain,
        "start_date": start_date,
        "end_date": end_date,
        "overall": overall,
        "platforms": platforms,
    }
