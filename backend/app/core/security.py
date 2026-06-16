"""Security module — JWT creation/validation, password hashing, user extraction, and RBAC enforcement.

Provides:
- Password hashing: hash_password, verify_password (bcrypt with configurable cost factor)
- JWT lifecycle: create_access_token, create_refresh_token, decode_token
- FastAPI dependencies:
  - get_current_user: Validates JWT, returns user claims (HTTP 401 on failure)
  - require_role(*roles): Ensures user has one of the specified roles (HTTP 403 on failure)
  - require_permissions(*permissions): Ensures user's role grants all specified permissions (HTTP 403)

All 401/403 events are recorded in the audit_log.

Role propagation: On each request, the user's role is read from the database (not cached
from the JWT claims) so that role changes take effect on the next API request without
requiring re-authentication.
"""

import logging
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import role_has_permission
from backend.app.core.redis import get_redis_client
from backend.app.models.users import User

logger = logging.getLogger(__name__)

# --- Password Hashing (bcrypt with cost factor 12) ---


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt with the configured cost factor (12).

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt hash string.
    """
    salt = bcrypt.gensalt(rounds=settings.bcrypt_cost_factor)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Args:
        plain_password: The plaintext password to verify.
        hashed_password: The stored bcrypt hash.

    Returns:
        True if the password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


# --- JWT Token Management ---


class TokenError(Exception):
    """Exception raised when JWT token operations fail."""

    def __init__(self, message: str = "Token is invalid or expired"):
        self.message = message
        super().__init__(message)


def create_access_token(
    user_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> tuple[str, str, datetime]:
    """Create a signed JWT access token.

    Args:
        user_id: The user's UUID as a string (becomes the 'sub' claim).
        role: The user's role name.
        expires_delta: Optional custom expiry duration. Defaults to configured value.

    Returns:
        Tuple of (encoded_jwt, jti, expiry_datetime).
    """
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    expire = now + expires_delta
    jti = str(_uuid.uuid4())

    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": now,
        "jti": jti,
    }

    encoded_jwt = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt, jti, expire


def create_refresh_token(
    user_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> tuple[str, str, datetime]:
    """Create a signed JWT refresh token.

    Args:
        user_id: The user's UUID as a string (becomes the 'sub' claim).
        role: The user's role name.
        expires_delta: Optional custom expiry duration. Defaults to configured value (7 days).

    Returns:
        Tuple of (encoded_jwt, jti, expiry_datetime).
    """
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)

    expire = now + expires_delta
    jti = str(_uuid.uuid4())

    payload = {
        "sub": user_id,
        "role": role,
        "type": "refresh",
        "exp": expire,
        "iat": now,
        "jti": jti,
    }

    encoded_jwt = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt, jti, expire


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Validates the token signature, expiration, and required claims.

    Args:
        token: The encoded JWT string.

    Returns:
        The decoded token payload dictionary.

    Raises:
        TokenError: If the token is invalid, expired, or malformed.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise TokenError(f"Token validation failed: {e}")

    # Verify required claims
    required_claims = ["sub", "role", "type", "exp", "jti"]
    for claim in required_claims:
        if claim not in payload:
            raise TokenError(f"Token missing required claim: {claim}")

    return payload


# HTTPBearer scheme extracts the token from the Authorization header
_bearer_scheme = HTTPBearer(auto_error=False)


class TokenClaims:
    """Validated JWT token claims with fresh role from DB."""

    def __init__(
        self,
        user_id: UUID,
        username: str,
        role_name: str,
        email: str | None = None,
    ):
        self.user_id = user_id
        self.username = username
        self.role_name = role_name
        self.email = email


async def _record_auth_event(
    request: Request,
    event_type: str,
    actor_id: UUID | None,
    target_resource: str | None,
    result: str,
    db: AsyncSession,
) -> None:
    """Record an authentication/authorization event in the audit log.

    Uses a direct insert to avoid circular dependency with AuditService.
    """
    from backend.app.models.audit import AuditLog

    ip_address = _get_client_ip(request)

    audit_log = AuditLog(
        event_type=event_type,
        actor_id=actor_id or UUID("00000000-0000-0000-0000-000000000000"),  # System actor for unauthenticated
        target_resource_id=target_resource,
        target_resource_type="endpoint",
        result=result,
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(audit_log)
    try:
        await db.flush()
    except Exception as exc:
        # Don't let audit logging failure prevent the auth response
        logger.warning("Failed to record auth audit event: %s", exc)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def _validate_jwt_token(token: str) -> dict[str, Any]:
    """Validate JWT token signature, expiration, and blacklist status.

    Args:
        token: The raw JWT token string.

    Returns:
        Decoded token payload.

    Raises:
        HTTPException: 401 if token is invalid, expired, or blacklisted.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        logger.debug("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check token expiration (jose handles this, but belt-and-suspenders)
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check token blacklist in Redis
    try:
        redis_client = get_redis_client()
        jti = payload.get("jti", token[:32])  # Use jti claim or first 32 chars as key
        is_blacklisted = await redis_client.get(f"token_blacklist:{jti}")
        if is_blacklisted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Redis unavailable — fail-open for token blacklist check
        # In production with strict security, this could fail-closed instead
        logger.warning("Redis blacklist check failed (fail-open): %s", exc)

    return payload


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> TokenClaims:
    """FastAPI dependency: validate JWT and return current user claims.

    Performs:
    1. Extract JWT from Authorization header
    2. Validate token signature and expiration
    3. Check token not blacklisted
    4. Read user role fresh from DB (for role change propagation)
    5. Verify user is active and not deleted

    Returns:
        TokenClaims with user_id, username, role_name, email.

    Raises:
        HTTPException: 401 if authentication fails.
    """
    if credentials is None:
        # No token provided — record 401 event
        await _record_auth_event(
            request=request,
            event_type="UNAUTHENTICATED_ACCESS",
            actor_id=None,
            target_resource=str(request.url.path),
            result="failure",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        payload = await _validate_jwt_token(token)
    except HTTPException:
        # Record the 401 event before re-raising
        await _record_auth_event(
            request=request,
            event_type="UNAUTHENTICATED_ACCESS",
            actor_id=None,
            target_resource=str(request.url.path),
            result="failure",
            db=db,
        )
        raise

    # Extract user_id from token
    sub = payload.get("sub")
    if not sub:
        await _record_auth_event(
            request=request,
            event_type="UNAUTHENTICATED_ACCESS",
            actor_id=None,
            target_resource=str(request.url.path),
            result="failure",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        await _record_auth_event(
            request=request,
            event_type="UNAUTHENTICATED_ACCESS",
            actor_id=None,
            target_resource=str(request.url.path),
            result="failure",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fresh DB lookup for role propagation (Requirement 3.9)
    stmt = select(User).options(selectinload(User.role)).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or user.is_deleted or not user.is_active:
        await _record_auth_event(
            request=request,
            event_type="UNAUTHENTICATED_ACCESS",
            actor_id=user_id,
            target_resource=str(request.url.path),
            result="failure",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenClaims(
        user_id=user.id,
        username=user.username,
        role_name=user.role.name,
        email=user.email,
    )


def require_role(*allowed_roles: str):
    """FastAPI dependency factory: ensure user has one of the specified roles.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("Admin"))])

    Or as a parameter dependency:
        async def endpoint(user: TokenClaims = Depends(require_role("Admin", "Operator"))):

    Args:
        *allowed_roles: One or more role names that are permitted.

    Returns:
        A FastAPI dependency that validates the user's role.
    """

    async def _check_role(
        request: Request,
        current_user: TokenClaims = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> TokenClaims:
        if current_user.role_name not in allowed_roles:
            # Record 403 event
            await _record_auth_event(
                request=request,
                event_type="PERMISSION_DENIED",
                actor_id=current_user.user_id,
                target_resource=str(request.url.path),
                result="failure",
                db=db,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role_name}' does not have access to this resource",
            )
        return current_user

    return _check_role


def require_permissions(*permissions: str):
    """FastAPI dependency factory: ensure user's role grants all specified permissions.

    Uses the role-permission mappings from permissions.py to check if the user's
    current role (read fresh from DB) grants every required permission.

    Usage:
        @router.post("/connectors", dependencies=[Depends(require_permissions("connectors.create"))])

    Or as a parameter:
        async def endpoint(user: TokenClaims = Depends(require_permissions("pipelines.execute"))):

    Args:
        *permissions: One or more permission strings required (all must be satisfied).

    Returns:
        A FastAPI dependency that validates the user's permissions.
    """

    async def _check_permissions(
        request: Request,
        current_user: TokenClaims = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> TokenClaims:
        missing_permissions = []
        for perm in permissions:
            if not role_has_permission(current_user.role_name, perm):
                missing_permissions.append(perm)

        if missing_permissions:
            # Record 403 event
            await _record_auth_event(
                request=request,
                event_type="PERMISSION_DENIED",
                actor_id=current_user.user_id,
                target_resource=str(request.url.path),
                result="failure",
                db=db,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions. Missing: {', '.join(missing_permissions)}"
                ),
            )
        return current_user

    return _check_permissions
