import uuid

from pydantic import BaseModel, EmailStr

from app.modules.users.models import UserStatus


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    title: str
    role_key: str
    status: UserStatus
