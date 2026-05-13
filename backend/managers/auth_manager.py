"""
Google OAuth + JWT issuance.
Handles bootstrap of first lead and auto-approval for @loopai.com domain.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt

from backend.auth.dependencies import ALGORITHM, SECRET_KEY
from backend.auth.google_oauth import exchange_google_code
from backend.enums.role import Role
from backend.managers.user_manager import (
    add_user, backfill_name, get_user, total_user_count,
)


def login_with_google(code: str, redirect_uri: str) -> dict:
    """
    Full OAuth flow:
      1. Exchange code for user info from Google
      2. Bootstrap if first user
      3. Auto-approve @loopai.com users as managers
      4. Issue JWT
    Raises HTTPException on auth failure.
    """
    from fastapi import HTTPException

    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    user_info = exchange_google_code(code, client_id, client_secret, redirect_uri)
    if not user_info or not user_info.get("email"):
        raise HTTPException(status_code=401, detail="Google auth failed")

    email = user_info["email"]
    name = user_info.get("name", email)
    user = get_user(email)

    # Bootstrap: very first user becomes lead
    if user is None and total_user_count() == 0:
        add_user(email, name, Role.LEAD, 0.0, "bootstrap")
        user = get_user(email)

    # Auto-approve @loopai.com domain
    if user is None and email.lower().endswith("@loopai.com"):
        add_user(email, name, Role.LEAD, 0.0, "auto_loopai_domain")
        user = get_user(email)

    if user is None:
        raise HTTPException(status_code=403, detail=f"User '{email}' not found. Ask a lead to add you.")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail=f"Account '{email}' access revoked. Contact your lead.")

    # Backfill name if missing
    if not user.get("name"):
        backfill_name(email, name)

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
    return {
        "token": token,
        "user": {"email": email, "name": user.get("name", name), "role": user["role"]},
    }


def is_local_env() -> bool:
    return os.environ.get("ENV") != "production"
