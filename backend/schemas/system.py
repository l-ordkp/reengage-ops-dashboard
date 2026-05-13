"""System control schemas."""
from __future__ import annotations

from pydantic import BaseModel


class RunAssignmentBody(BaseModel):
    full_reassign: bool = True
