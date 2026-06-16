"""Unit tests for the Authentication Service.

Tests cover:
- Password hashing and verification (bcrypt, cost factor 12)
- JWT access token creation and validation
- JWT refresh token creation and validation
- Token blacklisting
- Failed login attempt counting and account lockout
- Generic error messages (no field-specific hints)
- Password reset token generation and confirmation
"""

import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt

from backend.app.core.config import settings
from backend.app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


# --- Password Hashing Tests ---


class TestPasswordHashing:
    """Tests for bcrypt password hashing with cost factor 12."""

    def test_hash_password_returns_bcrypt_hash(self):
        """Hashed password should start with bcrypt identifier."""
        hashed = hash_password("my_secure_password")
        assert hashed.startswith("$2b$")

    def test_hash_password_uses_cost_factor_12(self):
        """The bcrypt hash should use cost factor 12."""
        hashed = hash_password("test_password")
        # bcrypt format: $2b$<cost>$<salt+hash>
        parts = hashed.split("$")
        cost = int(parts[2])
        assert cost == 12

    def test_verify_password_correct(self):
        """verify_password returns True for matching password."""
        password = "correct_horse_battery_staple"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password returns False for wrong password."""
        hashed = hash_password("original_password")
        assert verify_password("wrong_password", hashed) is False

    def test_hash_password_produces_different_hashes(self):
        """Same password should produce different hashes (due to salt)."""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        # But both should verify
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


# --- JWT Token Tests ---


class TestJWTTokenCreation:
    """Tests for JWT access and refresh token creation."""

    def test_create_access_token_structure(self):
        """Access token should have correct claims."""
        user_id = str(uuid.uuid4())
        role = "Admin"

        token, jti, exp = create_access_token(user_id, role)

        # Decode without verification to inspect claims
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )

        assert payload["sub"] == user_id
        assert payload["role"] == role
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload
        assert payload["jti"] == jti

    def test_create_access_token_default_expiry(self):
        """Access token should expire in configured minutes (default 30)."""
        user_id = str(uuid.uuid4())
        token, jti, exp = create_access_token(user_id, "Data_Engineer")

        now = datetime.now(timezone.utc)
        expected_exp = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

        # Allow 5 seconds tolerance
        assert abs((exp - expected_exp).total_seconds()) < 5

    def test_create_access_token_custom_expiry(self):
        """Access token should respect custom expiry delta."""
        user_id = str(uuid.uuid4())
        custom_delta = timedelta(hours=2)
        token, jti, exp = create_access_token(user_id, "Viewer", expires_delta=custom_delta)

        now = datetime.now(timezone.utc)
        expected_exp = now + custom_delta
        assert abs((exp - expected_exp).total_seconds()) < 5

    def test_create_refresh_token_structure(self):
        """Refresh token should have correct claims with type=refresh."""
        user_id = str(uuid.uuid4())
        role = "Operator"

        token, jti, exp = create_refresh_token(user_id, role)

        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )

        assert payload["sub"] == user_id
        assert payload["role"] == role
        assert payload["type"] == "refresh"
        assert payload["jti"] == jti

    def test_create_refresh_token_default_expiry(self):
        """Refresh token should expire in configured days (default 7)."""
        user_id = str(uuid.uuid4())
        token, jti, exp = create_refresh_token(user_id, "Admin")

        now = datetime.now(timezone.utc)
        expected_exp = now + timedelta(days=settings.jwt_refresh_token_expire_days)
        assert abs((exp - expected_exp).total_seconds()) < 5

    def test_access_and_refresh_have_different_jti(self):
        """Each token must have a unique jti."""
        user_id = str(uuid.uuid4())
        _, jti1, _ = create_access_token(user_id, "Admin")
        _, jti2, _ = create_refresh_token(user_id, "Admin")
        assert jti1 != jti2


class TestJWTTokenDecoding:
    """Tests for JWT token decoding and validation."""

    def test_decode_valid_access_token(self):
        """Decoding a valid access token should return correct payload."""
        user_id = str(uuid.uuid4())
        role = "Data_Engineer"
        token, jti, _ = create_access_token(user_id, role)

        payload = decode_token(token)

        assert payload["sub"] == user_id
        assert payload["role"] == role
        assert payload["type"] == "access"
        assert payload["jti"] == jti

    def test_decode_expired_token_raises_error(self):
        """Decoding an expired token should raise TokenError."""
        user_id = str(uuid.uuid4())
        # Create token that expired 1 hour ago
        token, _, _ = create_access_token(
            user_id, "Admin", expires_delta=timedelta(seconds=-1)
        )

        with pytest.raises(TokenError):
            decode_token(token)

    def test_decode_invalid_signature_raises_error(self):
        """Decoding a token with wrong secret should raise TokenError."""
        user_id = str(uuid.uuid4())
        # Create token with a different secret
        payload = {
            "sub": user_id,
            "role": "Admin",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")

        with pytest.raises(TokenError):
            decode_token(token)

    def test_decode_token_missing_claims_raises_error(self):
        """Token missing required claims should raise TokenError."""
        # Create a token without 'role' claim
        payload = {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

        with pytest.raises(TokenError, match="missing required claim"):
            decode_token(token)

    def test_decode_malformed_token_raises_error(self):
        """Completely invalid token string should raise TokenError."""
        with pytest.raises(TokenError):
            decode_token("not.a.valid.jwt.token")


# --- Auth Service Integration Tests (with mocked DB and Redis) ---


class TestAuthServiceLogin:
    """Tests for AuthenticationService.login method."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock async database session."""
        db = AsyncMock()
        return db

    @pytest.fixture
    def mock_redis(self):
        """Create a mock async Redis client."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock()
        redis.setex = AsyncMock()
        redis.delete = AsyncMock()
        return redis

    @pytest.fixture
    def auth_service(self, mock_db, mock_redis):
        """Create an AuthenticationService with mocked dependencies."""
        from backend.app.services.auth_service import AuthenticationService
        return AuthenticationService(mock_db, mock_redis)

    @pytest.mark.asyncio
    async def test_login_user_not_found_generic_error(self, auth_service, mock_db):
        """Login with non-existent username should return generic error."""
        from backend.app.services.auth_service import AuthenticationError

        # Mock: user not found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.login("nonexistent_user", "any_password", "127.0.0.1")

        # Error message should be generic — not "user not found"
        assert exc_info.value.message == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_login_wrong_password_generic_error(self, auth_service, mock_db, mock_redis):
        """Login with wrong password should return generic error."""
        from backend.app.services.auth_service import AuthenticationError

        user = MagicMock()
        user.id = uuid.uuid4()
        user.username = "testuser"
        user.is_active = True
        user.is_deleted = False
        user.password_hash = hash_password("correct_password")
        user.role_id = uuid.uuid4()
        user.role = MagicMock()
        user.role.name = "Viewer"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.login("testuser", "wrong_password", "127.0.0.1")

        # Error message should be generic — not "wrong password"
        assert exc_info.value.message == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_login_success_returns_token_pair(self, auth_service, mock_db, mock_redis):
        """Successful login should return a TokenPair."""
        user = MagicMock()
        user.id = uuid.uuid4()
        user.username = "testuser"
        user.is_active = True
        user.is_deleted = False
        user.password_hash = hash_password("correct_password")
        user.role_id = uuid.uuid4()
        user.role = MagicMock()
        user.role.name = "Data_Engineer"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Patch audit service to avoid DB writes
        with patch.object(auth_service, "_record_login_event", new_callable=AsyncMock):
            token_pair = await auth_service.login("testuser", "correct_password", "127.0.0.1")

        assert token_pair.access_token is not None
        assert token_pair.refresh_token is not None
        assert token_pair.token_type == "bearer"
        assert token_pair.expires_in > 0

    @pytest.mark.asyncio
    async def test_login_locked_account_raises_error(self, auth_service, mock_db, mock_redis):
        """Login to a locked account should raise AccountLockedError."""
        from backend.app.services.auth_service import AccountLockedError

        user = MagicMock()
        user.id = uuid.uuid4()
        user.username = "locked_user"
        user.is_active = True
        user.is_deleted = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock: account is locked
        mock_redis.get = AsyncMock(return_value="1")

        # Patch audit service
        with patch.object(auth_service, "_record_login_event", new_callable=AsyncMock):
            with pytest.raises(AccountLockedError):
                await auth_service.login("locked_user", "password", "127.0.0.1")

    @pytest.mark.asyncio
    async def test_login_increments_failed_counter(self, auth_service, mock_db, mock_redis):
        """Failed login should increment the failure counter in Redis."""
        from backend.app.services.auth_service import AuthenticationError

        user = MagicMock()
        user.id = uuid.uuid4()
        user.username = "testuser"
        user.is_active = True
        user.is_deleted = False
        user.password_hash = hash_password("correct_password")
        user.role_id = uuid.uuid4()
        user.role = MagicMock()
        user.role.name = "Viewer"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Patch audit service
        with patch.object(auth_service, "_record_login_event", new_callable=AsyncMock):
            with pytest.raises(AuthenticationError):
                await auth_service.login("testuser", "wrong_password", "127.0.0.1")

        # Redis incr should have been called
        mock_redis.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_lockout_after_5_failed_attempts(self, auth_service, mock_db, mock_redis):
        """After 5 failed attempts, account should be locked."""
        from backend.app.services.auth_service import AuthenticationError, LOCKOUT_DURATION_SECONDS

        user = MagicMock()
        user.id = uuid.uuid4()
        user.username = "testuser"
        user.is_active = True
        user.is_deleted = False
        user.password_hash = hash_password("correct_password")
        user.role_id = uuid.uuid4()
        user.role = MagicMock()
        user.role.name = "Viewer"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Simulate 5th failed attempt
        mock_redis.incr = AsyncMock(return_value=5)

        with patch.object(auth_service, "_record_login_event", new_callable=AsyncMock):
            with pytest.raises(AuthenticationError):
                await auth_service.login("testuser", "wrong_password", "127.0.0.1")

        # Lockout key should be set
        mock_redis.setex.assert_called()


class TestAuthServiceTokenManagement:
    """Tests for token validation, refresh, and blacklisting."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        redis.delete = AsyncMock()
        return redis

    @pytest.fixture
    def auth_service(self, mock_db, mock_redis):
        from backend.app.services.auth_service import AuthenticationService
        return AuthenticationService(mock_db, mock_redis)

    @pytest.mark.asyncio
    async def test_validate_token_success(self, auth_service, mock_redis):
        """Valid non-blacklisted token should validate successfully."""
        user_id = str(uuid.uuid4())
        token, jti, _ = create_access_token(user_id, "Admin")

        claims = await auth_service.validate_token(token)

        assert claims.sub == user_id
        assert claims.role == "Admin"
        assert claims.type == "access"
        assert claims.jti == jti

    @pytest.mark.asyncio
    async def test_validate_blacklisted_token_fails(self, auth_service, mock_redis):
        """Blacklisted token should fail validation."""
        from backend.app.services.auth_service import TokenValidationError

        user_id = str(uuid.uuid4())
        token, jti, _ = create_access_token(user_id, "Admin")

        # Mock: token is blacklisted
        mock_redis.get = AsyncMock(return_value="1")

        with pytest.raises(TokenValidationError, match="revoked"):
            await auth_service.validate_token(token)

    @pytest.mark.asyncio
    async def test_refresh_token_issues_new_pair(self, auth_service, mock_redis):
        """Valid refresh token should produce a new token pair."""
        user_id = str(uuid.uuid4())
        refresh_tok, _, _ = create_refresh_token(user_id, "Data_Engineer")

        new_pair = await auth_service.refresh_token(refresh_tok)

        assert new_pair.access_token is not None
        assert new_pair.refresh_token is not None
        assert new_pair.token_type == "bearer"

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_fails(self, auth_service, mock_redis):
        """Using an access token for refresh should fail."""
        from backend.app.services.auth_service import TokenValidationError

        user_id = str(uuid.uuid4())
        access_tok, _, _ = create_access_token(user_id, "Admin")

        with pytest.raises(TokenValidationError, match="not a refresh token"):
            await auth_service.refresh_token(access_tok)

    @pytest.mark.asyncio
    async def test_logout_blacklists_both_tokens(self, auth_service, mock_redis):
        """Logout should blacklist both access and refresh tokens."""
        user_id = str(uuid.uuid4())
        access_tok, _, _ = create_access_token(user_id, "Admin")
        refresh_tok, _, _ = create_refresh_token(user_id, "Admin")

        await auth_service.logout(access_tok, refresh_tok)

        # setex should have been called for both tokens
        assert mock_redis.setex.call_count == 2


class TestPasswordReset:
    """Tests for password reset token generation and confirmation."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db

    @pytest.fixture
    def mock_redis(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        redis.delete = AsyncMock()
        return redis

    @pytest.fixture
    def auth_service(self, mock_db, mock_redis):
        from backend.app.services.auth_service import AuthenticationService
        return AuthenticationService(mock_db, mock_redis)

    @pytest.mark.asyncio
    async def test_reset_request_generates_token(self, auth_service, mock_db, mock_redis):
        """Password reset request should generate a token stored in Redis."""
        user = MagicMock()
        user.id = uuid.uuid4()
        user.username = "testuser"
        user.is_active = True
        user.is_deleted = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        token = await auth_service.reset_password_request("testuser")

        assert token is not None
        assert len(token) > 20  # URL-safe token should be substantial
        # Redis setex should have been called for forward and reverse keys
        assert mock_redis.setex.call_count == 2

    @pytest.mark.asyncio
    async def test_reset_request_nonexistent_user_generic_error(self, auth_service, mock_db):
        """Reset request for non-existent user should raise generic error."""
        from backend.app.services.auth_service import AuthenticationError

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthenticationError):
            await auth_service.reset_password_request("nonexistent")

    @pytest.mark.asyncio
    async def test_reset_confirm_invalid_token(self, auth_service, mock_redis):
        """Confirming with an invalid token should raise ResetTokenError."""
        from backend.app.services.auth_service import ResetTokenError

        # Mock: no reverse lookup found
        mock_redis.get = AsyncMock(return_value=None)

        with pytest.raises(ResetTokenError):
            await auth_service.reset_password_confirm("invalid_token", "new_password123")
