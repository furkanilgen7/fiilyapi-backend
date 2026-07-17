import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import UserStatus


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)
    title: str = Field(default="", max_length=150)
    role_id: uuid.UUID
    status: UserStatus = UserStatus.active


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    title: str | None = Field(default=None, max_length=150)
    role_id: uuid.UUID | None = None
    status: UserStatus | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    title: str
    role_id: uuid.UUID
    status: UserStatus
