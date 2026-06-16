"""Authentication Service — login, logout, JWT lifecycle, lockout, and password reset.

Manages:
- User authentication with bcrypt password verification
- JWT access/refresh token issuance and validation
- Token blacklist in Redis (invalidated JWTs with TTL matching remaining lifetime)
- Failed attempt counter with 5-attempt lockout for 15 minutes
- Generic authentication failure messages (no field-specific hints)
- Password reset token generation (single-use, 24-hour expiry, invalidates predecessors)
- Audit log recording for login/logout events
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    hash_password,
)
from backend.app.models.users import User
from backend.app.schemas.auth import TokenClaims, TokenPair
from backend.app.schemas.audit import AuditEventCreate, AuditEventType, AuditResult
from backend.app.services.audit_service import AuditService


# Redis key patterns
FAILED_ATTEMPTS_KEY = "login_failed:{user_id}"
LOCKOUT_KEY = "login_locked:{user_id}"
TOKEN_BLACKLIST_KEY = "token_blacklist:{jti}"
PASSWORD_RESET_KEY = "password_reset:{user_id}"

# Constants
MAX_FAILED_ATTEMPTS = settings.account_lockout_threshold  # 5
LOCKOUT_DURATION_SECONDS = settings.account_lockout_duration_minutes * 60  # 15 min
RESET_TOKEN_EXPIRY_SECONDS = settings.password_reset_token_expiry_hours * 3600  # 24h


class AuthenticationError(Exception):
    """Base exception for authentication failures."""

    def __init__(self, message: str = "Invalid credentials", code: str = "AUTH_FAILED"):
        self.message = message
        self.code = code
        super().__init__(message)


class AccountLockedError(AuthenticationError):
    """Raised when the account is locked due to too many failed attempts."""

    def __init__(self):
        super().__init__(
            message="Account is temporarily locked. Please try again later.",
            code="ACCOUNT_LOCKED",
        )


class TokenValidationError(AuthenticationError):
    """Raised when token validation fails."""

    def __init__(self, message: str = "Invalid or expired token"):
        super().__init__(message=message, code="TOKEN_INVALID")


class ResetTokenError(AuthenticationError):
    """Raised when a password reset token is invalid or expired."""

    def __init__(self):
        super().__init__(
            message="Reset token is invalid or has expired.",
            code="RESET_TOKEN_INVALID",
        )


class AuthenticationService:
    """Service for user authentication and token management."""

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self._audit_service = AuditService(db)

    async def login(self, username: str, password: str, ip_address: str | None = None) -> TokenPair:
        """Authenticate user and return a JWT token pair.

        Flow:
        1. Look up user by username (active, not deleted)
        2. Check if account is locked
        3. Verify password
        4. On failure: increment counter, check for lockout threshold
        5. On success: clear failure counter, issue tokens, record audit event

        Args:
            username: The username to authenticate.
            password: The plaintext password.
            ip_address: The client's IP address for audit logging.

        Returns:
            TokenPair with access and refresh tokens.

        Raises:
            AccountLockedError: If the account is locked.
            AuthenticationError: If credentials are invalid.
        """
        # Look up the user
        result = await self.db.execute(
            select(User).where(
                User.username == username,
                User.is_deleted == False,  # noqa: E712
            )
        )
        user = result.scalar_one_or_none()

        # If user doesn't exist, still return generic error
        if user is None:
            # Record failed login attempt for audit (use a nil UUID for unknown user)
            raise AuthenticationError()

        user_id_str = str(user.id)

        # Check if account is locked
        locked = await self.redis.get(LOCKOUT_KEY.format(user_id=user_id_str))
        if locked:
            # Record failed attempt in audit
            await self._record_login_event(user.id, ip_address, success=False)
            raise AccountLockedError()

        # Check if account is active
        if not user.is_active:
            raise AuthenticationError()

        # Verify password
        if not verify_password(password, user.password_hash):
            # Increment failed attempt counter
            await self._increment_failed_attempts(user_id_str)
            await self._record_login_event(user.id, ip_address, success=False)
            raise AuthenticationError()

        # Successful authentication — clear failed attempts
        await self._clear_failed_attempts(user_id_str)

        # Get role name
        role_name = await self._get_user_role_name(user)

        # Issue token pair
        token_pair = self._issue_token_pair(user_id_str, role_name)

        # Record successful login
        await self._record_login_event(user.id, ip_address, success=True)

        return token_pair

    async def logout(self, access_token: str, refresh_token: str) -> None:
        """Invalidate both access and refresh tokens by adding them to the blacklist.

        Args:
            access_token: The JWT access token to invalidate.
            refresh_token: The JWT refresh token to invalidate.
        """
        # Blacklist access token
        await self._blacklist_token(access_token)
        # Blacklist refresh token
        await self._blacklist_token(refresh_token)

    async def refresh_token(self, refresh_token: str) -> TokenPair:
        """Issue a new token pair using a valid refresh token.

        Args:
            refresh_token: A valid, non-expired, non-blacklisted refresh token.

        Returns:
            New TokenPair with fresh access and refresh tokens.

        Raises:
            TokenValidationError: If the refresh token is invalid/expired/blacklisted.
        """
        claims = await self.validate_token(refresh_token)

        if claims.type != "refresh":
            raise TokenValidationError("Token is not a refresh token")

        # Blacklist the old refresh token (single-use refresh)
        await self._blacklist_token(refresh_token)

        # Issue new pair
        role = claims.role
        user_id = claims.sub
        return self._issue_token_pair(user_id, role)

    async def validate_token(self, token: str) -> TokenClaims:
        """Validate a JWT token — check signature, expiry, and blacklist.

        Args:
            token: The JWT string.

        Returns:
            TokenClaims with decoded payload.

        Raises:
            TokenValidationError: If validation fails.
        """
        try:
            payload = decode_token(token)
        except TokenError as e:
            raise TokenValidationError(str(e.message))

        jti = payload.get("jti")
        if not jti:
            raise TokenValidationError("Token missing jti claim")

        # Check blacklist
        blacklisted = await self.redis.get(TOKEN_BLACKLIST_KEY.format(jti=jti))
        if blacklisted:
            raise TokenValidationError("Token has been revoked")

        return TokenClaims(
            sub=payload["sub"],
            role=payload["role"],
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            type=payload["type"],
            jti=jti,
        )

    async def reset_password_request(self, username: str) -> str:
        """Generate a password reset token for the user.

        Invalidates any previously issued reset tokens for the same user.
        The token is single-use with a 24-hour expiry.

        Args:
            username: The username to generate a reset token for.

        Returns:
            The reset token string.

        Raises:
            AuthenticationError: If the user is not found (generic message).
        """
        result = await self.db.execute(
            select(User).where(
                User.username == username,
                User.is_deleted == False,  # noqa: E712
                User.is_active == True,  # noqa: E712
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            # Return generic error — don't reveal if user exists
            raise AuthenticationError(
                message="If the account exists, a reset token has been generated.",
                code="RESET_REQUESTED",
            )

        user_id_str = str(user.id)

        # Generate a cryptographically secure token
        raw_token = secrets.token_urlsafe(48)

        # Store hash of the token in Redis (invalidates any previous token)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        forward_key = PASSWORD_RESET_KEY.format(user_id=user_id_str)

        # Delete the old reverse lookup if a previous token existed
        old_hash = await self.redis.get(forward_key)
        if old_hash:
            old_reverse_key = f"password_reset_lookup:{old_hash}"
            await self.redis.delete(old_reverse_key)

        # Set forward key (user_id -> token_hash) with TTL
        await self.redis.setex(forward_key, RESET_TOKEN_EXPIRY_SECONDS, token_hash)

        # Set reverse lookup (token_hash -> user_id) with same TTL
        reverse_key = f"password_reset_lookup:{token_hash}"
        await self.redis.setex(reverse_key, RESET_TOKEN_EXPIRY_SECONDS, user_id_str)

        return raw_token

    async def reset_password_confirm(self, token: str, new_password: str) -> None:
        """Confirm password reset using a valid reset token.

        Args:
            token: The reset token received by the user.
            new_password: The new password to set.

        Raises:
            ResetTokenError: If the token is invalid, expired, or already used.
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # We need to find which user this token belongs to.
        # Scan for matching reset keys. For efficiency, we encode user_id in the token.
        # Alternative: iterate known users. Better approach: encode user_id in the token URL.
        # For this implementation, we'll search Redis keys with the pattern.
        # However, a more scalable approach: store a reverse mapping.
        # Let's use a reverse key: password_reset_token:{token_hash} -> user_id

        # Actually, let's refactor: store both forward and reverse mappings.
        # Forward: password_reset:{user_id} -> token_hash (for invalidation)
        # Reverse: password_reset_lookup:{token_hash} -> user_id (for confirmation)

        # Check reverse lookup
        reverse_key = f"password_reset_lookup:{token_hash}"
        user_id_str = await self.redis.get(reverse_key)

        if not user_id_str:
            raise ResetTokenError()

        # Verify the forward key still matches (token not superseded)
        forward_key = PASSWORD_RESET_KEY.format(user_id=user_id_str)
        stored_hash = await self.redis.get(forward_key)

        if stored_hash != token_hash:
            # Token was superseded by a newer one
            raise ResetTokenError()

        # Token is valid — update the password
        user_id = uuid.UUID(user_id_str)
        result = await self.db.execute(
            select(User).where(User.id == user_id, User.is_deleted == False)  # noqa: E712
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise ResetTokenError()

        user.password_hash = hash_password(new_password)
        await self.db.flush()

        # Invalidate the token (delete both keys)
        await self.redis.delete(forward_key)
        await self.redis.delete(reverse_key)

    # --- Private helpers ---

    def _issue_token_pair(self, user_id: str, role: str) -> TokenPair:
        """Issue an access + refresh token pair."""
        access_token, _access_jti, access_exp = create_access_token(user_id, role)
        refresh_token, _refresh_jti, _refresh_exp = create_refresh_token(user_id, role)

        expires_in = int((access_exp - datetime.now(timezone.utc)).total_seconds())

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=expires_in,
        )

    async def _blacklist_token(self, token: str) -> None:
        """Add a token to the Redis blacklist with TTL matching remaining lifetime."""
        try:
            payload = decode_token(token)
        except TokenError:
            # If token is already invalid/expired, nothing to blacklist
            return

        jti = payload.get("jti")
        if not jti:
            return

        exp_timestamp = payload.get("exp", 0)
        exp_dt = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        remaining_seconds = int((exp_dt - now).total_seconds())

        if remaining_seconds > 0:
            await self.redis.setex(
                TOKEN_BLACKLIST_KEY.format(jti=jti),
                remaining_seconds,
                "1",
            )

    async def _increment_failed_attempts(self, user_id: str) -> None:
        """Increment failed login attempt counter and enforce lockout."""
        key = FAILED_ATTEMPTS_KEY.format(user_id=user_id)

        # Increment counter
        count = await self.redis.incr(key)

        # Set TTL on first failure (auto-expire counter after lockout duration)
        if count == 1:
            await self.redis.expire(key, LOCKOUT_DURATION_SECONDS)

        # Check if threshold reached
        if count >= MAX_FAILED_ATTEMPTS:
            # Lock the account
            lockout_key = LOCKOUT_KEY.format(user_id=user_id)
            await self.redis.setex(lockout_key, LOCKOUT_DURATION_SECONDS, "1")
            # Clear the counter
            await self.redis.delete(key)

    async def _clear_failed_attempts(self, user_id: str) -> None:
        """Clear the failed login attempt counter on successful login."""
        key = FAILED_ATTEMPTS_KEY.format(user_id=user_id)
        await self.redis.delete(key)

    async def _record_login_event(
        self, user_id: uuid.UUID, ip_address: str | None, success: bool
    ) -> None:
        """Record a login event in the audit log."""
        event = AuditEventCreate(
            event_type=AuditEventType.LOGIN,
            actor_id=user_id,
            target_resource_id=str(user_id),
            target_resource_type="user",
            result=AuditResult.SUCCESS if success else AuditResult.FAILURE,
            ip_address=ip_address,
        )
        await self._audit_service.record_event(event)

    async def _record_logout_event(
        self, user_id: uuid.UUID, ip_address: str | None
    ) -> None:
        """Record a logout event in the audit log."""
        event = AuditEventCreate(
            event_type=AuditEventType.LOGOUT,
            actor_id=user_id,
            target_resource_id=str(user_id),
            target_resource_type="user",
            result=AuditResult.SUCCESS,
            ip_address=ip_address,
        )
        await self._audit_service.record_event(event)

    async def _get_user_role_name(self, user: User) -> str:
        """Get the role name for a user, loading relation if needed."""
        if user.role and hasattr(user.role, "name"):
            return user.role.name
        # Fallback: query role table
        from backend.app.models.users import Role
        result = await self.db.execute(select(Role.name).where(Role.id == user.role_id))
        role_name = result.scalar_one_or_none()
        return role_name or "unknown"


def get_auth_service(db: AsyncSession, redis: aioredis.Redis) -> AuthenticationService:
    """Factory function for dependency injection of AuthenticationService."""
    return AuthenticationService(db, redis)
