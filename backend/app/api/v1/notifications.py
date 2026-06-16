"""Notification API routes.

Provides operations for user notifications:
- GET /api/v1/notifications - list notifications (notifications.read)
- PUT /api/v1/notifications/{id}/read - mark as read (notifications.update)

Permission matrix:
- Admin: full access
- Data_Engineer: read only
- Operator: read + update
- Viewer: read only
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_permissions
from backend.app.schemas.notification import NotificationListResponse
from backend.app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _get_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    """Dependency to get NotificationService instance."""
    return NotificationService(db)


@router.get("/", response_model=NotificationListResponse, operation_id="notifications_list")
async def list_notifications(
    page: int = 1,
    page_size: int = 30,
    current_user: TokenClaims = Depends(require_permissions("notifications.read")),
    service: NotificationService = Depends(_get_service),
):
    """List user notifications with pagination.

    Returns a chronologically ordered list (newest first) of notifications
    for the authenticated user, with read status and recurrence count.
    """
    result = await service.get_user_notifications(
        user_id=current_user.user_id,
        page=page,
        page_size=page_size,
    )
    return result


@router.put("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, operation_id="notifications_mark_read")
async def mark_as_read(
    notification_id: UUID,
    current_user: TokenClaims = Depends(require_permissions("notifications.update")),
    service: NotificationService = Depends(_get_service),
):
    """Mark a notification as read.

    Only the notification's owner can mark it as read.
    Returns 204 No Content on success.
    """
    try:
        await service.mark_as_read(
            notification_id=notification_id,
            user_id=current_user.user_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
