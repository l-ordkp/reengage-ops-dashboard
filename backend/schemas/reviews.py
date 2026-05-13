"""Review-related schemas."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class GenerateBatchBody(BaseModel):
    review_uids: list[str]


class GenerateBatchResult(BaseModel):
    success: int
    skipped: int
    failed: int
    details: list[dict]


class ReviewListResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int


class ReviewStats(BaseModel):
    total: int
    pending: int
    responded: int
    expired: int
    critical: int
    auto_posted: int
    has_response: int


class FilterOptions(BaseModel):
    chains: list[str]
    platforms: list[str]


class ReviewFilters(BaseModel):
    """Internal filter object passed from router to manager."""
    chain_name: Optional[str] = None
    platform: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    has_response: Optional[str] = None
    assigned_to: Optional[str] = None
    page: int = 1
    page_size: int = 50
