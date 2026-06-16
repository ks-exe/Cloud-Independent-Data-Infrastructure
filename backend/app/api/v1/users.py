"""User management API routes.

Provides CRUD operations for user accounts:
- GET /api/v1/users - list users (paginated)
- GET /api/v1/users/{user_id} - get single user
- POST /api/v1/users - create user (returns 201)
- PUT /api/v1/users/{user_id} - update user
- PUT /api/v1/users/{user_id}/disable - disable user
- DELETE /api/v1/users/{user_id} - soft delete user

All endpoints require Admin role (users.* permission).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_permissions
from backend.app.schemas.error import ErrorDetail, create_error_response
from backend.app.schemas.user import (
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from backend.app.services.user_service import (
    DuplicateFieldError,
    RoleNotFoundError,
    SelfDeactivationError,
    UserNotFoundError,
    UserService,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=UserListResponse, operation_id="users_list")
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    include_deleted: bool = Query(False, description="Include soft-deleted users"),
    current_user: TokenClaims = Depends(require_permissions("users.read")),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """List all users with pagination."""
    service = UserService(db)
    return await service.list_users(page=page, page_size=page_size, include_deleted=include_deleted)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED, operation_id="users_create")
async def create_user(
    data: UserCreate,
    current_user: TokenClaims = Depends(require_permissions("users.create")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Create a new user account.

    Validates username format, email format, and role assignment.
    Returns 409 on duplicate username/email with field identification.
    """
    service = UserService(db)
    try:
        return await service.create_user(data)
    except DuplicateFieldError as e:
        error_response = create_error_response(
            code="CONFLICT",
            message="User creation failed due to a duplicate field",
            details=[
                ErrorDetail(
                    error_code="DUPLICATE_FIELD",
                    field=e.field,
                    rejected_value=None,
                    message=e.message,
                )
            ],
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_response.model_dump(),
        )
    except RoleNotFoundError as e:
        error_response = create_error_response(
            code="VALIDATION_ERROR",
            message="Invalid role specified",
            details=[
                ErrorDetail(
                    error_code="ROLE_NOT_FOUND",
                    field="role_id",
                    rejected_value=None,
                    message=e.message,
                )
            ],
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_response.model_dump(),
        )


@router.get("/{user_id}", response_model=UserResponse, operation_id="users_get")
async def get_user(
    user_id: UUID,
    current_user: TokenClaims = Depends(require_permissions("users.read")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Get user details by ID."""
    service = UserService(db)
    try:
        return await service.get_user(user_id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code="NOT_FOUND",
                message=f"User with id '{user_id}' not found",
            ).model_dump(),
        )


@router.put("/{user_id}", response_model=UserResponse, operation_id="users_update")
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    current_user: TokenClaims = Depends(require_permissions("users.update")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update user details (email, display_name, role)."""
    service = UserService(db)
    try:
        return await service.update_user(user_id, data)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code="NOT_FOUND",
                message=f"User with id '{user_id}' not found",
            ).model_dump(),
        )
    except DuplicateFieldError as e:
        error_response = create_error_response(
            code="CONFLICT",
            message="User update failed due to a duplicate field",
            details=[
                ErrorDetail(
                    error_code="DUPLICATE_FIELD",
                    field=e.field,
                    rejected_value=None,
                    message=e.message,
                )
            ],
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_response.model_dump(),
        )
    except RoleNotFoundError as e:
        error_response = create_error_response(
            code="VALIDATION_ERROR",
            message="Invalid role specified",
            details=[
                ErrorDetail(
                    error_code="ROLE_NOT_FOUND",
                    field="role_id",
                    rejected_value=None,
                    message=e.message,
                )
            ],
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_response.model_dump(),
        )


@router.put("/{user_id}/disable", response_model=UserResponse, operation_id="users_disable")
async def disable_user(
    user_id: UUID,
    current_user: TokenClaims = Depends(require_permissions("users.update")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Disable a user account.

    Sets is_active=False and revokes sessions.
    Admin cannot disable their own account.
    """
    service = UserService(db)
    try:
        return await service.disable_user(user_id, current_user.user_id)
    except SelfDeactivationError as e:
        error_response = create_error_response(
            code="FORBIDDEN",
            message=e.message,
            details=[
                ErrorDetail(
                    error_code="SELF_DEACTIVATION",
                    field=None,
                    rejected_value=None,
                    message=e.message,
                )
            ],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_response.model_dump(),
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code="NOT_FOUND",
                message=f"User with id '{user_id}' not found",
            ).model_dump(),
        )


@router.delete("/{user_id}", response_model=UserResponse, operation_id="users_delete")
async def delete_user(
    user_id: UUID,
    current_user: TokenClaims = Depends(require_permissions("users.delete")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Soft-delete a user account.

    Sets is_deleted=True and is_active=False.
    Preserves audit_log entries.
    Admin cannot delete their own account.
    """
    service = UserService(db)
    try:
        return await service.delete_user(user_id, current_user.user_id)
    except SelfDeactivationError as e:
        error_response = create_error_response(
            code="FORBIDDEN",
            message=e.message,
            details=[
                ErrorDetail(
                    error_code="SELF_DEACTIVATION",
                    field=None,
                    rejected_value=None,
                    message=e.message,
                )
            ],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_response.model_dump(),
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                code="NOT_FOUND",
                message=f"User with id '{user_id}' not found",
            ).model_dump(),
        )
