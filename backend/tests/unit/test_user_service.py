"""Unit tests for UserService and user schemas."""

import re
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate
from backend.app.services.user_service import (
    DuplicateFieldError,
    RoleNotFoundError,
    SelfDeactivationError,
    UserNotFoundError,
    UserService,
)


# --- Schema Validation Tests ---


class TestUserCreateSchema:
    """Tests for UserCreate Pydantic schema."""

    def test_valid_username_alphanumeric(self):
        """Username with alphanumeric and underscores is accepted."""
        data = UserCreate(
            username="valid_user123",
            email="test@example.com",
            role_id=uuid.uuid4(),
            password="securepass123",
        )
        assert data.username == "valid_user123"

    def test_username_too_short(self):
        """Username shorter than 3 chars is rejected."""
        with pytest.raises(Exception):
            UserCreate(
                username="ab",
                email="test@example.com",
                role_id=uuid.uuid4(),
                password="securepass123",
            )

    def test_username_too_long(self):
        """Username longer than 64 chars is rejected."""
        with pytest.raises(Exception):
            UserCreate(
                username="a" * 65,
                email="test@example.com",
                role_id=uuid.uuid4(),
                password="securepass123",
            )

    def test_username_invalid_characters(self):
        """Username with special characters is rejected."""
        with pytest.raises(Exception):
            UserCreate(
                username="user@name",
                email="test@example.com",
                role_id=uuid.uuid4(),
                password="securepass123",
            )

    def test_username_with_spaces_rejected(self):
        """Username with spaces is rejected."""
        with pytest.raises(Exception):
            UserCreate(
                username="user name",
                email="test@example.com",
                role_id=uuid.uuid4(),
                password="securepass123",
            )

    def test_username_exactly_3_chars(self):
        """Username exactly 3 chars is accepted."""
        data = UserCreate(
            username="abc",
            email="test@example.com",
            role_id=uuid.uuid4(),
            password="securepass123",
        )
        assert data.username == "abc"

    def test_username_exactly_64_chars(self):
        """Username exactly 64 chars is accepted."""
        username = "a" * 64
        data = UserCreate(
            username=username,
            email="test@example.com",
            role_id=uuid.uuid4(),
            password="securepass123",
        )
        assert data.username == username

    def test_invalid_email_rejected(self):
        """Invalid email format is rejected."""
        with pytest.raises(Exception):
            UserCreate(
                username="valid_user",
                email="not-an-email",
                role_id=uuid.uuid4(),
                password="securepass123",
            )

    def test_valid_email_accepted(self):
        """Valid email format is accepted."""
        data = UserCreate(
            username="valid_user",
            email="user@domain.com",
            role_id=uuid.uuid4(),
            password="securepass123",
        )
        assert data.email == "user@domain.com"


class TestUserUpdateSchema:
    """Tests for UserUpdate schema."""

    def test_all_fields_optional(self):
        """All fields can be None."""
        data = UserUpdate()
        assert data.email is None
        assert data.display_name is None
        assert data.role_id is None

    def test_partial_update_email_only(self):
        """Only email can be set."""
        data = UserUpdate(email="new@example.com")
        assert data.email == "new@example.com"
        assert data.display_name is None
        assert data.role_id is None


# --- UserService Tests ---


def _make_mock_user(
    user_id=None,
    username="testuser",
    email="test@example.com",
    role_id=None,
    is_active=True,
    is_deleted=False,
):
    """Create a mock User object."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.username = username
    user.email = email
    user.password_hash = "$2b$12$hashed"
    user.display_name = None
    user.role_id = role_id or uuid.uuid4()
    user.is_active = is_active
    user.is_deleted = is_deleted
    user.created_at = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)
    return user


def _make_mock_role(role_id=None, name="Admin"):
    """Create a mock Role object."""
    role = MagicMock()
    role.id = role_id or uuid.uuid4()
    role.name = name
    return role


class TestUserServiceCreate:
    """Tests for UserService.create_user."""

    @pytest.mark.asyncio
    async def test_create_user_duplicate_username_raises(self):
        """Duplicate username raises DuplicateFieldError with field='username'."""
        db = AsyncMock()
        # First query (username check) returns existing user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _make_mock_user()
        db.execute.return_value = mock_result

        service = UserService(db)
        data = UserCreate(
            username="existing_user",
            email="new@example.com",
            role_id=uuid.uuid4(),
            password="securepass123",
        )

        with pytest.raises(DuplicateFieldError) as exc_info:
            await service.create_user(data)

        assert exc_info.value.field == "username"

    @pytest.mark.asyncio
    async def test_create_user_duplicate_email_raises(self):
        """Duplicate email raises DuplicateFieldError with field='email'."""
        db = AsyncMock()
        # First query (username check) returns None
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        # Second query (email check) returns existing user
        email_result = MagicMock()
        email_result.scalar_one_or_none.return_value = _make_mock_user()
        db.execute.side_effect = [no_result, email_result]

        service = UserService(db)
        data = UserCreate(
            username="new_user",
            email="existing@example.com",
            role_id=uuid.uuid4(),
            password="securepass123",
        )

        with pytest.raises(DuplicateFieldError) as exc_info:
            await service.create_user(data)

        assert exc_info.value.field == "email"

    @pytest.mark.asyncio
    async def test_create_user_invalid_role_raises(self):
        """Non-existent role raises RoleNotFoundError."""
        db = AsyncMock()
        # Username check - not found
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        # Email check - not found
        no_email = MagicMock()
        no_email.scalar_one_or_none.return_value = None
        # Role check - not found
        no_role = MagicMock()
        no_role.scalar_one_or_none.return_value = None
        db.execute.side_effect = [no_result, no_email, no_role]

        service = UserService(db)
        role_id = uuid.uuid4()
        data = UserCreate(
            username="new_user",
            email="new@example.com",
            role_id=role_id,
            password="securepass123",
        )

        with pytest.raises(RoleNotFoundError):
            await service.create_user(data)


class TestUserServiceDisable:
    """Tests for UserService.disable_user."""

    @pytest.mark.asyncio
    async def test_self_deactivation_prevented(self):
        """Admin cannot disable their own account."""
        db = AsyncMock()
        user_id = uuid.uuid4()

        service = UserService(db)

        with pytest.raises(SelfDeactivationError):
            await service.disable_user(user_id, current_user_id=user_id)

    @pytest.mark.asyncio
    async def test_disable_nonexistent_user_raises(self):
        """Disabling a user that doesn't exist raises UserNotFoundError."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        service = UserService(db)
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()

        with pytest.raises(UserNotFoundError):
            await service.disable_user(user_id, current_user_id=other_user_id)


class TestUserServiceDelete:
    """Tests for UserService.delete_user."""

    @pytest.mark.asyncio
    async def test_self_deletion_prevented(self):
        """Admin cannot delete their own account."""
        db = AsyncMock()
        user_id = uuid.uuid4()

        service = UserService(db)

        with pytest.raises(SelfDeactivationError):
            await service.delete_user(user_id, current_user_id=user_id)

    @pytest.mark.asyncio
    async def test_soft_delete_sets_flags(self):
        """Soft delete sets is_deleted=True and is_active=False."""
        db = AsyncMock()
        user_id = uuid.uuid4()
        current_user_id = uuid.uuid4()
        role_id = uuid.uuid4()

        mock_user = _make_mock_user(user_id=user_id, role_id=role_id)
        # _get_user_or_raise query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user
        # _get_role_name query
        role_name_result = MagicMock()
        role_name_result.scalar_one_or_none.return_value = "Admin"
        db.execute.side_effect = [user_result, role_name_result]

        service = UserService(db)
        result = await service.delete_user(user_id, current_user_id=current_user_id)

        # The mock user flags should be set
        assert mock_user.is_deleted is True
        assert mock_user.is_active is False
