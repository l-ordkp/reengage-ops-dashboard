"""System control routes — assignment trigger, cache clear."""
from __future__ import annotations

import os

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from backend.auth.dependencies import ALGORITHM, SECRET_KEY, get_current_user
from backend.enums.role import LEAD_ROLES
from backend.managers.assignment_manager import run_assignment
from backend.managers.throughput_notifier import send_yesterday_throughput
from backend.schemas.system import RunAssignmentBody

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/run-assignment")
def trigger_assignment(
    body: RunAssignmentBody,
    background_tasks: BackgroundTasks,
    user_agent: str = Header(None),
    authorization: str = Header(None),
):
    """Cloud Scheduler bypasses JWT (User-Agent check). Manual triggers require lead/manager JWT."""
    is_cron = user_agent and "Google-Cloud-Scheduler" in user_agent
    if not is_cron:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Not authenticated")
        token = authorization[7:]
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("role") not in {r.value for r in LEAD_ROLES}:
                raise HTTPException(status_code=403, detail="Lead access required")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    result = run_assignment(full_reassign=body.full_reassign)

    if is_cron and "error" not in result:
        background_tasks.add_task(send_yesterday_throughput)

    return result


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
