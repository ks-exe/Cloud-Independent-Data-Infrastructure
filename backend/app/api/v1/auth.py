"""Authentication API routes.

Provides:
- POST /auth/login — authenticate and get token pair
- POST /auth/logout — invalidate tokens
- POST /auth/refresh — refresh access token
- POST /auth/reset-password-request — request password reset token
- POST /auth/reset-password-confirm — confirm reset with token and new password
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.redis import get_redis_client
from backend.app.schemas.auth import (
    AuthMessageResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordConfirm,
    ResetPasswordRequest,
    TokenPair,
)
from backend.app.schemas.error import create_error_response
from backend.app.services.auth_service import (
    AccountLockedError,
    AuthenticationError,
    AuthenticationService,
    ResetTokenError,
    TokenValidationError,
    get_auth_service,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _get_service(db: AsyncSession = Depends(get_db)) -> AuthenticationService:
    """Dependency to provide AuthenticationService instance."""
    redis = get_redis_client()
    return get_auth_service(db, redis)


def _get_client_ip(request: Request) -> str | None:
    """Extract client IP from request, handling proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _extract_bearer_token(request: Request) -> str | None:
    """Extract Bearer token from Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


@router.post("/login", response_model=TokenPair, operation_id="auth_login")
async def login(
    data: LoginRequest,
    request: Request,
    service: AuthenticationService = Depends(_get_service),
) -> TokenPair:
    """Authenticate user and return JWT token pair.

    Returns generic "Invalid credentials" on failure — never reveals
    whether the username or password was incorrect.
    """
    ip_address = _get_client_ip(request)
    try:
        return await service.login(data.username, data.password, ip_address)
    except AccountLockedError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=create_error_response(
                code=e.code,
                message=e.message,
            ).model_dump(),
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=create_error_response(
                code=e.code,
                message=e.message,
            ).model_dump(),
        )


@router.post("/logout", response_model=AuthMessageResponse, operation_id="auth_logout")
async def logout(
    data: LogoutRequest,
    request: Request,
    service: AuthenticationService = Depends(_get_service),
) -> AuthMessageResponse:
    """Invalidate current access and refresh tokens.

    Access token is extracted from the Authorization header.
    Refresh token is provided in the request body.
    """
    access_token = _extract_bearer_token(request)
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=create_error_response(
                code="MISSING_TOKEN",
                message="Authorization header with Bearer token is required",
            ).model_dump(),
        )

    # Record logout event before invalidation
    try:
        claims = await service.validate_token(access_token)
        ip_address = _get_client_ip(request)
        import uuid as _uuid

        await service._record_logout_event(_uuid.UUID(claims.sub), ip_address)
    except TokenValidationError:
        pass  # Token might already be expired; still proceed with blacklisting

    await service.logout(access_token, data.refresh_token)
    return AuthMessageResponse(message="Successfully logged out")


@router.post("/refresh", response_model=TokenPair, operation_id="auth_refresh_token")
async def refresh_token(
    data: RefreshRequest,
    service: AuthenticationService = Depends(_get_service),
) -> TokenPair:
    """Refresh access token using a valid refresh token."""
    try:
        return await service.refresh_token(data.refresh_token)
    except TokenValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=create_error_response(
                code=e.code,
                message=e.message,
            ).model_dump(),
        )


@router.post("/reset-password-request", response_model=AuthMessageResponse, operation_id="auth_reset_password_request")
async def reset_password_request(
    data: ResetPasswordRequest,
    service: AuthenticationService = Depends(_get_service),
) -> AuthMessageResponse:
    """Request a password reset token.

    Always returns a success message regardless of whether the user exists,
    to avoid leaking account existence information.
    """
    try:
        _token = await service.reset_password_request(data.username)
        # In a real system, send this token via email.
        # For now, return a generic success message.
    except AuthenticationError:
        pass  # Silently succeed — don't reveal whether user exists

    return AuthMessageResponse(
        message="If the account exists, a password reset has been initiated."
    )


@router.post("/reset-password-confirm", response_model=AuthMessageResponse, operation_id="auth_reset_password_confirm")
async def reset_password_confirm(
    data: ResetPasswordConfirm,
    service: AuthenticationService = Depends(_get_service),
) -> AuthMessageResponse:
    """Confirm password reset with token and new password."""
    try:
        await service.reset_password_confirm(data.token, data.new_password)
    except ResetTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=create_error_response(
                code=e.code,
                message=e.message,
            ).model_dump(),
        )
    return AuthMessageResponse(message="Password has been reset successfully.")
