"""JWT auth dependencies for FastAPI."""

import os

import jwt
from fastapi import Depends, HTTPException, Request

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-prod")
ALGORITHM = "HS256"


def get_current_user(request: Request) -> dict:
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
    if user["role"] not in ("lead", "manager"):
        raise HTTPException(status_code=403, detail="Lead access required")
    return user
