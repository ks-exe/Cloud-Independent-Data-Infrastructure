"""User management service — CRUD operations with business rule enforcement."""

import uuid
from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.users import Role, User
from backend.app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


class UserServiceError(Exception):
    """Base exception for user service errors."""

    def __init__(self, code: str, message: str, field: str | None = None):
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)


class DuplicateFieldError(UserServiceError):
    """Raised when a unique constraint is violated."""

    def __init__(self, field: str):
        super().__init__(
            code="DUPLICATE_FIELD",
            message=f"A user with this {field} already exists",
            field=field,
        )


class SelfDeactivationError(UserServiceError):
    """Raised when an admin tries to disable/delete their own account."""

    def __init__(self):
        super().__init__(
            code="SELF_DEACTIVATION",
            message="Self-deactivation is not permitted for Admin accounts",
        )


class UserNotFoundError(UserServiceError):
    """Raised when a user is not found."""

    def __init__(self, user_id: uuid.UUID):
        super().__init__(
            code="USER_NOT_FOUND",
            message=f"User with id '{user_id}' not found",
        )


class RoleNotFoundError(UserServiceError):
    """Raised when a role is not found."""

    def __init__(self, role_id: uuid.UUID):
        super().__init__(
            code="ROLE_NOT_FOUND",
            message=f"Role with id '{role_id}' not found",
        )


class UserService:
    """Service for user CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, data: UserCreate) -> UserResponse:
        """Create a new user account.

        Validates:
        - Username uniqueness
        - Email uniqueness
        - Role exists
        """
        # Check for duplicate username
        existing_username = await self.db.execute(
            select(User).where(User.username == data.username, User.is_deleted == False)  # noqa: E712
        )
        if existing_username.scalar_one_or_none():
            raise DuplicateFieldError(field="username")

        # Check for duplicate email
        existing_email = await self.db.execute(
            select(User).where(User.email == data.email, User.is_deleted == False)  # noqa: E712
        )
        if existing_email.scalar_one_or_none():
            raise DuplicateFieldError(field="email")

        # Validate role exists
        role = await self.db.execute(select(Role).where(Role.id == data.role_id))
        role_obj = role.scalar_one_or_none()
        if not role_obj:
            raise RoleNotFoundError(role_id=data.role_id)

        # Hash the password
        password_hash = pwd_context.hash(data.password)

        # Create user
        user = User(
            id=uuid.uuid4(),
            username=data.username,
            email=data.email,
            password_hash=password_hash,
            display_name=data.display_name,
            role_id=data.role_id,
            is_active=True,
            is_deleted=False,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)

        return self._to_response(user, role_name=role_obj.name)

    async def get_user(self, user_id: uuid.UUID) -> UserResponse:
        """Get a user by ID."""
        user = await self._get_user_or_raise(user_id)
        role_name = await self._get_role_name(user.role_id)
        return self._to_response(user, role_name=role_name)

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        include_deleted: bool = False,
    ) -> UserListResponse:
        """List users with pagination."""
        query = select(User).options(selectinload(User.role))

        if not include_deleted:
            query = query.where(User.is_deleted == False)  # noqa: E712

        # Count total
        count_query = select(func.count()).select_from(User)
        if not include_deleted:
            count_query = count_query.where(User.is_deleted == False)  # noqa: E712
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(User.created_at.desc())

        result = await self.db.execute(query)
        users = result.scalars().all()

        items = [
            self._to_response(u, role_name=u.role.name if u.role else None) for u in users
        ]

        pages = (total + page_size - 1) // page_size if total > 0 else 0

        return UserListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def update_user(self, user_id: uuid.UUID, data: UserUpdate) -> UserResponse:
        """Update user details.

        Validates:
        - Email uniqueness (if changed)
        - Role exists (if changed)
        """
        user = await self._get_user_or_raise(user_id)

        # Check email uniqueness if updating email
        if data.email is not None and data.email != user.email:
            existing_email = await self.db.execute(
                select(User).where(
                    User.email == data.email,
                    User.id != user_id,
                    User.is_deleted == False,  # noqa: E712
                )
            )
            if existing_email.scalar_one_or_none():
                raise DuplicateFieldError(field="email")
            user.email = data.email

        # Validate role exists if updating role
        if data.role_id is not None:
            role = await self.db.execute(select(Role).where(Role.id == data.role_id))
            if not role.scalar_one_or_none():
                raise RoleNotFoundError(role_id=data.role_id)
            user.role_id = data.role_id

        # Update display name if provided
        if data.display_name is not None:
            user.display_name = data.display_name

        user.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(user)

        role_name = await self._get_role_name(user.role_id)
        return self._to_response(user, role_name=role_name)

    async def disable_user(
        self, user_id: uuid.UUID, current_user_id: uuid.UUID
    ) -> UserResponse:
        """Disable a user account.

        Business rules:
        - Admin cannot disable their own account
        - Sets is_active=False
        - Session revocation will integrate with auth service later
        """
        if user_id == current_user_id:
            raise SelfDeactivationError()

        user = await self._get_user_or_raise(user_id)
        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(user)

        role_name = await self._get_role_name(user.role_id)
        return self._to_response(user, role_name=role_name)

    async def delete_user(
        self, user_id: uuid.UUID, current_user_id: uuid.UUID
    ) -> UserResponse:
        """Soft-delete a user account.

        Business rules:
        - Admin cannot delete their own account
        - Sets is_deleted=True, is_active=False
        - Audit log entries are preserved (no cascade delete)
        """
        if user_id == current_user_id:
            raise SelfDeactivationError()

        user = await self._get_user_or_raise(user_id)
        user.is_deleted = True
        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(user)

        role_name = await self._get_role_name(user.role_id)
        return self._to_response(user, role_name=role_name)

    # --- Private helpers ---

    async def _get_user_or_raise(self, user_id: uuid.UUID) -> User:
        """Get a user by ID or raise UserNotFoundError."""
        result = await self.db.execute(
            select(User).where(User.id == user_id, User.is_deleted == False)  # noqa: E712
        )
        user = result.scalar_one_or_none()
        if not user:
            raise UserNotFoundError(user_id=user_id)
        return user

    async def _get_role_name(self, role_id: uuid.UUID) -> str | None:
        """Get a role name by ID."""
        result = await self.db.execute(select(Role.name).where(Role.id == role_id))
        return result.scalar_one_or_none()

    @staticmethod
    def _to_response(user: User, role_name: str | None = None) -> UserResponse:
        """Convert a User model to UserResponse schema."""
        return UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            role_id=user.role_id,
            role_name=role_name,
            is_active=user.is_active,
            is_deleted=user.is_deleted,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
