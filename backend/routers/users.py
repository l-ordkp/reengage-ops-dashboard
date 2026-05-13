"""User management API (lead/manager only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.dependencies import require_lead
from backend.managers.user_manager import (
    add_user, change_role, list_users, remove_user, set_approval,
)
from backend.schemas.users import AddUserBody, UpdateApprovalBody, UpdateRoleBody

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_endpoint(user: dict = Depends(require_lead)):
    return list_users()


@router.post("")
def create_endpoint(body: AddUserBody, user: dict = Depends(require_lead)):
    add_user(body.email.strip(), body.name.strip(), body.role, body.reduction_pct, user["email"])
    return {"ok": True}


@router.put("/{email}/role")
def update_role_endpoint(email: str, body: UpdateRoleBody, user: dict = Depends(require_lead)):
    change_role(email, body.role, body.reduction_pct)
    return {"ok": True}


@router.put("/{email}/approval")
def update_approval_endpoint(email: str, body: UpdateApprovalBody, user: dict = Depends(require_lead)):
    set_approval(email, body.approved)
    return {"ok": True}


@router.delete("/{email}")
def delete_endpoint(email: str, user: dict = Depends(require_lead)):
    remove_user(email)
    return {"ok": True}
