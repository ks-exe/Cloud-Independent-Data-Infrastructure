"""Key Rotation Service — master encryption key rotation with rollback support.

Implements atomic re-encryption of all connector credentials with a new master key.
Ensures:
- No connector re-creation required (credentials re-encrypted in place)
- No interruption to active pipeline executions during rotation (dual-key support)
- Rollback to previous key on partial rotation failure
- Audit logging for rotation success/failure

Requirements: 11.4, 11.5, 11.6
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.encryption import decrypt_credentials, encrypt_credentials
from backend.app.models.connectors import ConnectorConfig
from backend.app.schemas.audit import AuditEventCreate, AuditEventType, AuditResult
from backend.app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


@dataclass
class RotationResult:
    """Result of a key rotation operation."""

    success: bool
    total_connectors: int = 0
    rotated_count: int = 0
    failed_count: int = 0
    error_message: str | None = None
    failed_connector_ids: list[str] = field(default_factory=list)
    rolled_back: bool = False


# Module-level store for the previous key during rotation transitions.
# Active pipeline executions can decrypt using either key.
_previous_key: bytes | None = None


def get_previous_key() -> bytes | None:
    """Get the previous encryption key (available during rotation transition).

    During and shortly after key rotation, this returns the old key so that
    active pipeline executions can still decrypt credentials that haven't been
    re-encrypted yet or were encrypted with the old key.
    """
    return _previous_key


def clear_previous_key() -> None:
    """Clear the stored previous key after rotation transition completes."""
    global _previous_key
    _previous_key = None


class KeyRotationService:
    """Service for rotating the master encryption key.

    Handles re-encryption of all connector credentials with a new key,
    with full rollback capability on failure.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit_service = AuditService(db)

    async def rotate_encryption_key(
        self,
        old_key: bytes,
        new_key: bytes,
        actor_id: uuid.UUID,
        ip_address: str | None = None,
    ) -> RotationResult:
        """Rotate the master encryption key by re-encrypting all credentials.

        Process:
        1. Store old key as previous key (for dual-key decryption during transition)
        2. Fetch all connector configs with encrypted credentials
        3. For each: decrypt with old key → re-encrypt with new key
        4. On any failure: rollback all changes, restore old encrypted values
        5. On success: update complete
        6. Record result in audit log

        Args:
            old_key: The current 32-byte encryption key.
            new_key: The new 32-byte encryption key.
            actor_id: UUID of the admin performing the rotation.
            ip_address: IP address of the requesting client.

        Returns:
            RotationResult indicating success/failure with details.
        """
        global _previous_key

        # Validate key lengths
        if len(old_key) != 32:
            return RotationResult(
                success=False,
                error_message="Old key must be 32 bytes (64 hex characters).",
            )
        if len(new_key) != 32:
            return RotationResult(
                success=False,
                error_message="New key must be 32 bytes (64 hex characters).",
            )
        if old_key == new_key:
            return RotationResult(
                success=False,
                error_message="New key must be different from the current key.",
            )

        # Store old key for dual-key decryption during rotation
        _previous_key = old_key

        # Fetch all connector configs with encrypted credentials
        result = await self.db.execute(
            select(ConnectorConfig).where(
                ConnectorConfig.encrypted_credentials.isnot(None)
            )
        )
        configs = result.scalars().all()

        total = len(configs)
        if total == 0:
            # No credentials to rotate — success
            await self._record_audit_event(
                actor_id=actor_id,
                ip_address=ip_address,
                result=AuditResult.SUCCESS,
                details="No connector credentials to rotate.",
            )
            _previous_key = None
            return RotationResult(success=True, total_connectors=0, rotated_count=0)

        # Save original encrypted values for rollback
        original_values: dict[uuid.UUID, bytes] = {}
        for config in configs:
            original_values[config.id] = config.encrypted_credentials

        # Re-encrypt each connector's credentials
        rotated_count = 0
        failed_connector_ids: list[str] = []

        for config in configs:
            try:
                # Decrypt with old key
                plaintext = decrypt_credentials(config.encrypted_credentials, key=old_key)

                # Re-encrypt with new key
                new_encrypted = encrypt_credentials(plaintext, key=new_key)

                # Update in-place
                config.encrypted_credentials = new_encrypted
                rotated_count += 1

            except Exception as e:
                logger.error(
                    "Key rotation failed for connector_config %s: %s",
                    config.id,
                    str(e),
                )
                failed_connector_ids.append(str(config.connector_id))

                # Rollback ALL changes — restore original encrypted values
                await self._rollback(configs, original_values)

                error_msg = (
                    f"Rotation failed at connector_config {config.id}: {str(e)}. "
                    f"All credentials rolled back to previous key."
                )

                # Record failure in audit log
                await self._record_audit_event(
                    actor_id=actor_id,
                    ip_address=ip_address,
                    result=AuditResult.FAILURE,
                    details=error_msg,
                )

                # Keep the previous key active since we rolled back
                # (credentials are still encrypted with old key)
                return RotationResult(
                    success=False,
                    total_connectors=total,
                    rotated_count=rotated_count,
                    failed_count=1,
                    error_message=error_msg,
                    failed_connector_ids=failed_connector_ids,
                    rolled_back=True,
                )

        # All credentials re-encrypted successfully — flush to DB
        try:
            await self.db.flush()
        except Exception as e:
            # Database write failed — rollback all in-memory changes
            logger.error("Database flush failed during key rotation: %s", str(e))
            await self._rollback(configs, original_values)

            error_msg = f"Database update failed during key rotation: {str(e)}. All credentials rolled back."

            await self._record_audit_event(
                actor_id=actor_id,
                ip_address=ip_address,
                result=AuditResult.FAILURE,
                details=error_msg,
            )

            return RotationResult(
                success=False,
                total_connectors=total,
                rotated_count=0,
                failed_count=total,
                error_message=error_msg,
                rolled_back=True,
            )

        # Record success in audit log
        await self._record_audit_event(
            actor_id=actor_id,
            ip_address=ip_address,
            result=AuditResult.SUCCESS,
            details=f"Successfully rotated encryption key for {rotated_count} connector(s).",
        )

        logger.info(
            "Encryption key rotation completed: %d/%d connectors re-encrypted.",
            rotated_count,
            total,
        )

        # Clear previous key now that all credentials use the new key
        _previous_key = None

        return RotationResult(
            success=True,
            total_connectors=total,
            rotated_count=rotated_count,
            failed_count=0,
        )

    async def _rollback(
        self,
        configs: list[ConnectorConfig],
        original_values: dict[uuid.UUID, bytes],
    ) -> None:
        """Restore all connector configs to their original encrypted values.

        Args:
            configs: The list of ConnectorConfig objects that were modified.
            original_values: Map of config ID → original encrypted_credentials bytes.
        """
        for config in configs:
            if config.id in original_values:
                config.encrypted_credentials = original_values[config.id]

        try:
            await self.db.flush()
        except Exception as e:
            # Critical: rollback flush also failed. Log but can't do more.
            logger.critical(
                "CRITICAL: Rollback flush failed during key rotation: %s. "
                "Credentials may be in inconsistent state.",
                str(e),
            )

    async def _record_audit_event(
        self,
        actor_id: uuid.UUID,
        ip_address: str | None,
        result: AuditResult,
        details: str,
    ) -> None:
        """Record a key rotation event in the audit log.

        Args:
            actor_id: The admin who initiated rotation.
            ip_address: Client IP address.
            result: SUCCESS or FAILURE.
            details: Description of the outcome.
        """
        try:
            event = AuditEventCreate(
                event_type=AuditEventType.CONNECTOR_MODIFICATION,
                actor_id=actor_id,
                target_resource_id="master_encryption_key",
                target_resource_type="encryption_key_rotation",
                result=result,
                ip_address=ip_address,
            )
            await self.audit_service.record_event(event)
        except Exception as e:
            # Don't let audit failure prevent rotation result from being returned
            logger.error("Failed to record key rotation audit event: %s", str(e))


def get_key_rotation_service(db: AsyncSession) -> KeyRotationService:
    """Factory function for dependency injection of KeyRotationService."""
    return KeyRotationService(db)
