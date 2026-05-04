"""Users routes — CRUD for user management."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.dependencies import require_lead
from backend.auth.user_crud import load_all_users, add_user, update_user_role, update_user_approval, remove_user
from backend.db import _df_to_dicts

router = APIRouter(prefix="/api/users", tags=["users"])


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


@router.get("")
def list_users(user: dict = Depends(require_lead)):
    df = load_all_users()
    return _df_to_dicts(df)


@router.post("")
def create_user(body: AddUserBody, user: dict = Depends(require_lead)):
    add_user(body.email.strip(), body.name.strip(), body.role, body.reduction_pct, user["email"])
    return {"ok": True}


@router.put("/{email}/role")
def update_role(email: str, body: UpdateRoleBody, user: dict = Depends(require_lead)):
    reduction = body.reduction_pct if body.role == "new_operator" else 0.0
    update_user_role(email, body.role, reduction)
    return {"ok": True}


@router.put("/{email}/approval")
def toggle_approval(email: str, body: UpdateApprovalBody, user: dict = Depends(require_lead)):
    update_user_approval(email, body.approved)
    return {"ok": True}


@router.delete("/{email}")
def delete_user(email: str, user: dict = Depends(require_lead)):
    remove_user(email)
    return {"ok": True}
