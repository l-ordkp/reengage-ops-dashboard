"""Operator-side assignment API: queue + mark completed."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.dependencies import get_current_user
from backend.managers.queue_manager import get_my_queue
from backend.repositories.assignment_repository import fetch_my_pending_assignments
from backend.repositories.pg_reengage_repository import (
    log_action,
    mark_completed_by_assignment_id,
)

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.get("/mine")
def my_queue(user: dict = Depends(get_current_user)):
    return get_my_queue(user["email"])


@router.post("/{assignment_id}/complete")
def complete_assignment(
    assignment_id: str,
    remarks: str = "",
    user: dict = Depends(get_current_user),
):
    mark_completed_by_assignment_id(assignment_id)
    log_action(
        review_uid=assignment_id, platform="manual", chain_name="",
        action="mark_responded", operator_email=user["email"],
        performed_by=user["email"], remarks=remarks or "manual_dashboard",
    )
    fetch_my_pending_assignments.clear()
    return {"ok": True}
