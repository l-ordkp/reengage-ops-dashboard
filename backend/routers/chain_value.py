"""Chain Value API — all-time or date-bounded waterfall for a chosen chain."""
from __future__ import annotations

import re
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


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("")
def chain_value(
    chain: str = Query(..., min_length=1),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    user: dict = Depends(get_current_user),
):
    if start_date and not _DATE_RE.match(start_date):
        raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD")
    if end_date and not _DATE_RE.match(end_date):
        raise HTTPException(status_code=400, detail="end_date must be YYYY-MM-DD")
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
