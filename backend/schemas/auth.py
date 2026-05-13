"""Auth request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class GoogleLoginBody(BaseModel):
    code: str
    redirect_uri: str


class AuthUser(BaseModel):
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: AuthUser
