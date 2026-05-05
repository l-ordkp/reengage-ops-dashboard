"""System routes — assignment engine trigger."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.dependencies import require_lead, get_current_user
from backend.assignment import run_assignment

router = APIRouter(prefix="/api/system", tags=["system"])


class RunAssignmentBody(BaseModel):
    full_reassign: bool = False


@router.post("/run-assignment")
def trigger_assignment(body: RunAssignmentBody, user: dict = Depends(require_lead)):
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
