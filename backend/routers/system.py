"""System routes — assignment engine trigger."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.dependencies import require_lead
from backend.assignment import run_assignment

router = APIRouter(prefix="/api/system", tags=["system"])


class RunAssignmentBody(BaseModel):
    full_reassign: bool = False


@router.post("/run-assignment")
def trigger_assignment(body: RunAssignmentBody, user: dict = Depends(require_lead)):
    result = run_assignment(full_reassign=body.full_reassign)
    return result
