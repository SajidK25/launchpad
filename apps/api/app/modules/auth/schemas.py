"""Pydantic request and response contracts for authentication actions."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RoleName = Literal["member", "reviewer", "admin"]


class EmailPasswordRequest(BaseModel):
    email: str
    password: str


class EmailRequest(BaseModel):
    email: str


class TokenRequest(BaseModel):
    token: str = Field(min_length=1)


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str


class AcceptedResponse(BaseModel):
    accepted: bool = True


class LoginResponse(BaseModel):
    account_id: UUID
    verified: bool
    role: RoleName
    suspended: bool
    csrf_token: str


class SessionResponse(BaseModel):
    account_id: UUID
    verified: bool
    role: RoleName
    suspended: bool
    csrf_token: str
