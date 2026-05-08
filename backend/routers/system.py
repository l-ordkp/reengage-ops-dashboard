"""System routes — assignment engine trigger."""

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from backend.auth.dependencies import require_lead, get_current_user
from backend.assignment import run_assignment

router = APIRouter(prefix="/api/system", tags=["system"])

CRON_SECRET = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-prod")


class RunAssignmentBody(BaseModel):
    full_reassign: bool = True


@router.post("/run-assignment")
def trigger_assignment(
    body: RunAssignmentBody,
    user_agent: str = Header(None),
    authorization: str = Header(None),
):
    # Allow Cloud Scheduler (no JWT) or authenticated leads
    is_cron = user_agent and "Google-Cloud-Scheduler" in user_agent
    if not is_cron:
        # Validate JWT for non-cron callers
        from backend.auth.dependencies import get_current_user
        from fastapi import Request
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")
        # Decode JWT manually
        import jwt
        token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else None
        if not token:
            # Try cookie - but for this simple check just require the header
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            payload = jwt.decode(token, CRON_SECRET, algorithms=["HS256"])
            if payload.get("role") not in ("lead", "manager"):
                raise HTTPException(status_code=403, detail="Lead access required")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    result = run_assignment(full_reassign=body.full_reassign)
    return result


@router.post("/clear-cache")
def clear_cache(user: dict = Depends(get_current_user)):
    """Clear all server-side data caches."""
    from backend.data_loaders import (
        load_reviews, load_assignments, load_my_assignments,
        load_response_configs, load_ops_log,
        load_operator_performance, load_operator_daily_breakdown,
        load_operator_chain_breakdown,
    )
    for fn in [load_reviews, load_assignments, load_my_assignments,
               load_response_configs, load_ops_log,
               load_operator_performance, load_operator_daily_breakdown,
               load_operator_chain_breakdown]:
        fn.clear()
    return {"ok": True}
