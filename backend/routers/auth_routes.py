"""Auth routes — Google OAuth login, JWT session."""

import os
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel

from backend.auth.google_oauth import exchange_google_code
from backend.auth.user_crud import get_user, add_user, user_count
from backend.auth.dependencies import get_current_user, SECRET_KEY, ALGORITHM
from backend.config import ROLE_LEAD

router = APIRouter(prefix="/api/auth", tags=["auth"])


class GoogleLoginBody(BaseModel):
    code: str
    redirect_uri: str


@router.post("/google")
def google_login(body: GoogleLoginBody, response: Response):
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

    user_info = exchange_google_code(body.code, client_id, client_secret, body.redirect_uri)
    if not user_info or not user_info.get("email"):
        raise HTTPException(status_code=401, detail="Google auth failed")

    email = user_info["email"]
    name = user_info.get("name", email)

    user = get_user(email)

    # Bootstrap: first user becomes lead
    if user is None and user_count() == 0:
        add_user(email, name, ROLE_LEAD, 0.0, "bootstrap")
        user = get_user(email)

    # Auto-approve loopai.com domain
    if user is None and email.lower().endswith("@loopai.com"):
        add_user(email, name, ROLE_LEAD, 0.0, "auto_loopai_domain")
        user = get_user(email)

    if user is None:
        raise HTTPException(status_code=403, detail=f"User '{email}' not found. Ask a lead to add you.")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail=f"Account '{email}' access revoked. Contact your lead.")

    # Create JWT
    token = jwt.encode(
        {
            "email": email,
            "name": user.get("name", name),
            "role": user["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    is_local = os.environ.get("ENV") != "production"
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=not is_local,
        samesite="lax",
        max_age=86400,
    )

    return {"token": token, "user": {"email": email, "name": user.get("name", name), "role": user["role"]}}


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("auth_token")
    return {"ok": True}
