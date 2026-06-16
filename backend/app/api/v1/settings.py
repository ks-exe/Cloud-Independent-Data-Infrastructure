"""Settings management API routes.

Provides system settings operations for Admins:
- POST /api/v1/settings/rotate-key - rotate master encryption key (Admin only)

Permission matrix:
- Admin: full access
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import TokenClaims, require_role

router = APIRouter(prefix="/settings", tags=["Settings"])


class KeyRotationRequest(BaseModel):
    """Request body for master encryption key rotation."""

    current_key_hex: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Current master encryption key as a 64-character hex string (32 bytes).",
    )
    new_key_hex: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="New master encryption key as a 64-character hex string (32 bytes).",
    )


class KeyRotationResponse(BaseModel):
    """Response for key rotation operation."""

    success: bool
    total_connectors: int
    rotated_count: int
    failed_count: int
    error_message: str | None = None
    rolled_back: bool = False


@router.post("/rotate-key", response_model=KeyRotationResponse)
async def rotate_encryption_key(
    body: KeyRotationRequest,
    request: Request,
    current_user: TokenClaims = Depends(require_role("Admin")),
    db: AsyncSession = Depends(get_db),
):
    """Rotate the master encryption key.

    Re-encrypts all existing connector credentials with the new key.
    Requires Admin role. On failure, all credentials are rolled back to
    the previous key with no data loss.

    No connector re-creation is required. Active pipeline executions
    are not interrupted during rotation.
    """
    from backend.app.services.key_rotation_service import get_key_rotation_service

    # Parse hex keys to bytes
    try:
        old_key = bytes.fromhex(body.current_key_hex)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="current_key_hex must be a valid hex string.",
        )

    try:
        new_key = bytes.fromhex(body.new_key_hex)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="new_key_hex must be a valid hex string.",
        )

    # Get client IP
    ip_address = _get_client_ip(request)

    # Perform rotation
    service = get_key_rotation_service(db)
    result = await service.rotate_encryption_key(
        old_key=old_key,
        new_key=new_key,
        actor_id=current_user.user_id,
        ip_address=ip_address,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "total_connectors": result.total_connectors,
                "rotated_count": result.rotated_count,
                "failed_count": result.failed_count,
                "error_message": result.error_message,
                "rolled_back": result.rolled_back,
            },
        )

    return KeyRotationResponse(
        success=True,
        total_connectors=result.total_connectors,
        rotated_count=result.rotated_count,
        failed_count=result.failed_count,
        rolled_back=False,
    )


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
