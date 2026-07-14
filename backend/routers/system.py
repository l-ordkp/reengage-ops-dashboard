"""System control routes — assignment trigger, cache clear."""
from __future__ import annotations

import os

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException

from backend.auth.dependencies import ALGORITHM, SECRET_KEY, get_current_user
from backend.enums.role import LEAD_ROLES
from backend.config import FOCUSED_ASSIGNMENT_MODE
from backend.managers.assignment_manager import run_assignment
from backend.managers.focused_assignment_manager import run_focused_assignment
from backend.managers.throughput_notifier import send_yesterday_throughput
from backend.managers.weekly_funnel_notifier import (
    maybe_send_weekly_funnel,
    send_last_week_funnel,
)
from backend.schemas.system import RunAssignmentBody

router = APIRouter(prefix="/api/system", tags=["system"])


def _is_scheduler_or_lead(user_agent: str | None, authorization: str | None) -> bool:
    """Cloud Scheduler bypasses JWT (User-Agent check). Manual triggers require
    a lead/manager JWT. Returns True iff the caller is the scheduler."""
    is_cron = bool(user_agent and "Google-Cloud-Scheduler" in user_agent)
    if is_cron:
        return True
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") not in {r.value for r in LEAD_ROLES}:
            raise HTTPException(status_code=403, detail="Lead access required")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return False


@router.post("/run-assignment")
def trigger_assignment(
    body: RunAssignmentBody,
    user_agent: str = Header(None),
    authorization: str = Header(None),
):
    """Cloud Scheduler bypasses JWT (User-Agent check). Manual triggers require lead/manager JWT."""
    is_cron = _is_scheduler_or_lead(user_agent, authorization)

    if FOCUSED_ASSIGNMENT_MODE:
        result = run_focused_assignment(full_reassign=body.full_reassign)
    else:
        result = run_assignment(full_reassign=body.full_reassign)

    # Synchronous (not BackgroundTasks): if the response gets cut by an
    # upstream timeout, BackgroundTasks may never fire. The Slack call
    # itself is wrapped in try/except inside the notifier, so a Slack
    # outage cannot fail the cron.
    if is_cron and "error" not in result:
        send_yesterday_throughput()
        # Weekly Fri–Thu funnel rides the same daily cron; no-op except Fridays.
        maybe_send_weekly_funnel()

    return result


@router.post("/run-weekly-funnel")
def trigger_weekly_funnel(
    user_agent: str = Header(None),
    authorization: str = Header(None),
):
    """Post last week's (Fri–Thu) in-scope review funnel to Slack.

    Cloud Scheduler bypasses JWT (User-Agent check); manual triggers require a
    lead/manager JWT (401/403 otherwise). Once authorized it always 200s — the
    notifier swallows its own errors.
    """
    _is_scheduler_or_lead(user_agent, authorization)
    send_last_week_funnel()
    return {"ok": True}


@router.post("/clear-cache")
def clear_cache(user: dict = Depends(get_current_user)):
    """Clear all server-side data caches."""
    from backend.repositories.assignment_repository import (
        fetch_all_assignments_14d, fetch_my_pending_assignments,
    )
    from backend.repositories.config_repository import fetch_all_configs
    from backend.repositories.operator_repository import (
        fetch_operator_chain_breakdown_14d,
        fetch_operator_daily_breakdown_14d,
        fetch_operator_performance_14d,
    )
    from backend.repositories.ops_log_repository import fetch_recent_ops_log
    from backend.repositories.review_repository import fetch_reviews_14d

    for fn in [
        fetch_reviews_14d, fetch_all_assignments_14d, fetch_my_pending_assignments,
        fetch_all_configs, fetch_recent_ops_log,
        fetch_operator_performance_14d, fetch_operator_daily_breakdown_14d,
        fetch_operator_chain_breakdown_14d,
    ]:
        fn.clear()
    return {"ok": True}
