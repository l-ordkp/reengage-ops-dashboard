"""User management schemas."""
from __future__ import annotations

from pydantic import BaseModel


class AddUserBody(BaseModel):
    email: str
    name: str
    role: str
    reduction_pct: float = 0.0


class UpdateRoleBody(BaseModel):
    role: str
    reduction_pct: float = 0.0


class UpdateApprovalBody(BaseModel):
    approved: bool
