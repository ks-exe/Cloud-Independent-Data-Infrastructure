"""User request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.core.validators import (
    MAX_TEXT_LENGTH,
    pydantic_validate_username,
)


class UserCreate(BaseModel):
    """Schema for creating a new user."""

    username: str = Field(..., min_length=3, max_length=64, description="Username (3-64 alphanumeric/underscore)")
    email: EmailStr = Field(..., description="Valid email address")
    role_id: UUID = Field(..., description="Role UUID to assign")
    display_name: str | None = Field(None, max_length=MAX_TEXT_LENGTH, description="Optional display name")
    password: str = Field(..., min_length=8, max_length=128, description="User password")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return pydantic_validate_username(v)


class UserUpdate(BaseModel):
    """Schema for updating user details."""

    email: EmailStr | None = Field(None, description="New email address")
    display_name: str | None = Field(None, max_length=MAX_TEXT_LENGTH, description="New display name")
    role_id: UUID | None = Field(None, description="New role UUID")


class UserResponse(BaseModel):
    """Schema for user response."""

    id: UUID
    username: str
    email: str
    display_name: str | None
    role_id: UUID
    role_name: str | None = None
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Paginated list of users."""

    items: list[UserResponse]
    total: int
    page: int
    page_size: int
    pages: int
