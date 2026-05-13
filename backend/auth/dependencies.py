"""JWT auth dependencies for FastAPI routes."""
from __future__ import annotations

import os

import jwt
from fastapi import Depends, HTTPException, Request

from backend.enums.role import LEAD_ROLES, Role

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-prod")
ALGORITHM = "HS256"


def get_current_user(request: Request) -> dict:
    """Decode JWT from cookie or Authorization header. Raises 401 on failure."""
    token = request.cookies.get("auth_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"email": payload["email"], "name": payload["name"], "role": payload["role"]}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_lead(user: dict = Depends(get_current_user)) -> dict:
    """Allow leads and managers. Managers inherit lead access."""
    if user["role"] not in {r.value for r in LEAD_ROLES}:
        raise HTTPException(status_code=403, detail="Lead access required")
    return user
