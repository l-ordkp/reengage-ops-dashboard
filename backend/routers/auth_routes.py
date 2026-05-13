"""Auth routes — Google OAuth login, JWT session, current user lookup."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from backend.auth.dependencies import get_current_user
from backend.managers.auth_manager import is_local_env, login_with_google
from backend.schemas.auth import GoogleLoginBody

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/google")
def google_login(body: GoogleLoginBody, response: Response):
    result = login_with_google(body.code, body.redirect_uri)
    response.set_cookie(
        key="auth_token",
        value=result["token"],
        httponly=True,
        secure=not is_local_env(),
        samesite="lax",
        max_age=86400,
    )
    return result


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("auth_token")
    return {"ok": True}
