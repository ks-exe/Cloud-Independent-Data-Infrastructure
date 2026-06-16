"""Pydantic schemas for authentication operations."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from backend.app.core.validators import MAX_PASSWORD_LENGTH, MAX_TEXT_LENGTH, MAX_USERNAME_LENGTH


class LoginRequest(BaseModel):
    """Request schema for user login."""

    username: str = Field(..., min_length=1, max_length=MAX_USERNAME_LENGTH, description="Username or identifier")
    password: str = Field(..., min_length=1, max_length=MAX_PASSWORD_LENGTH, description="User password")


class TokenPair(BaseModel):
    """Response schema containing access and refresh tokens."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiry in seconds")


class RefreshRequest(BaseModel):
    """Request schema for token refresh."""

    refresh_token: str = Field(..., min_length=1, description="Valid refresh token")


class LogoutRequest(BaseModel):
    """Request schema for logout — tokens extracted from header and body."""

    refresh_token: str = Field(..., min_length=1, description="Refresh token to invalidate")


class ResetPasswordRequest(BaseModel):
    """Request schema to initiate a password reset."""

    username: str = Field(..., min_length=1, max_length=64, description="Username of the account")


class ResetPasswordConfirm(BaseModel):
    """Request schema to confirm password reset with token."""

    token: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH, description="Password reset token")
    new_password: str = Field(..., min_length=8, max_length=MAX_PASSWORD_LENGTH, description="New password")


class TokenClaims(BaseModel):
    """Decoded token claims."""

    sub: str = Field(..., description="Subject (user ID)")
    role: str = Field(..., description="User role name")
    exp: datetime = Field(..., description="Expiry timestamp")
    type: str = Field(..., description="Token type: access or refresh")
    jti: str = Field(..., description="Unique token identifier")


class AuthMessageResponse(BaseModel):
    """Generic success message response for auth operations."""

    message: str = Field(..., description="Status message")
