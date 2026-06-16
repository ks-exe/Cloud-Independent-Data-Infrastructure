"""Unit tests for the master encryption key rotation service.

Tests cover:
- Successful full rotation of all credentials
- Rollback on partial failure
- No-op when no credentials exist
- Key validation (length, same key)
- Dual-key decryption during rotation transition
- Audit log recording on success and failure
"""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.core.encryption import (
    decrypt_credentials,
    encrypt_credentials,
)
from backend.app.services.key_rotation_service import (
    KeyRotationService,
    RotationResult,
    clear_previous_key,
    get_previous_key,
)


def _mock_db_with_configs(configs: list) -> AsyncMock:
    """Create a mock async DB session that returns the given configs from a query."""
    db = AsyncMock()

    # db.execute() is awaited, returns a result object
    # result.scalars() returns an object with .all() method (synchronous)
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = configs

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock

    db.execute.return_value = execute_result
    db.flush = AsyncMock()
    return db


def _generate_key() -> bytes:
    """Generate a random 32-byte key for testing."""
    return os.urandom(32)


class TestKeyRotationServiceSuccess:
    """Tests for successful key rotation scenarios."""

    @pytest.mark.anyio
    async def test_rotate_no_credentials_is_success(self):
        """Rotation with no connector configs is a no-op success."""
        old_key = _generate_key()
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        db = _mock_db_with_configs([])

        service = KeyRotationService(db)
        # Mock audit service to avoid real DB interaction
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        result = await service.rotate_encryption_key(old_key, new_key, actor_id)

        assert result.success is True
        assert result.total_connectors == 0
        assert result.rotated_count == 0
        assert result.rolled_back is False

    @pytest.mark.anyio
    async def test_rotate_single_credential_success(self):
        """Successfully re-encrypts a single connector's credentials."""
        old_key = _generate_key()
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        # Create a mock connector config with real encrypted data
        original_creds = {"username": "admin", "password": "secret123"}
        encrypted_with_old = encrypt_credentials(original_creds, old_key)

        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.connector_id = uuid.uuid4()
        mock_config.encrypted_credentials = encrypted_with_old

        db = _mock_db_with_configs([mock_config])

        service = KeyRotationService(db)
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        result = await service.rotate_encryption_key(old_key, new_key, actor_id)

        assert result.success is True
        assert result.total_connectors == 1
        assert result.rotated_count == 1
        assert result.failed_count == 0

        # Verify the config was re-encrypted with the new key
        new_encrypted = mock_config.encrypted_credentials
        decrypted = decrypt_credentials(new_encrypted, new_key)
        assert decrypted == original_creds

    @pytest.mark.anyio
    async def test_rotate_multiple_credentials_success(self):
        """Successfully re-encrypts multiple connectors' credentials."""
        old_key = _generate_key()
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        # Create multiple mock connector configs
        creds_list = [
            {"username": "user1", "password": "pass1"},
            {"api_key": "sk-12345"},
            {"username": "user3", "password": "p@ss!", "host": "db.local"},
        ]

        mock_configs = []
        for creds in creds_list:
            config = MagicMock()
            config.id = uuid.uuid4()
            config.connector_id = uuid.uuid4()
            config.encrypted_credentials = encrypt_credentials(creds, old_key)
            mock_configs.append(config)

        db = _mock_db_with_configs(mock_configs)

        service = KeyRotationService(db)
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        result = await service.rotate_encryption_key(old_key, new_key, actor_id)

        assert result.success is True
        assert result.total_connectors == 3
        assert result.rotated_count == 3
        assert result.failed_count == 0

        # Verify all configs re-encrypted correctly
        for i, config in enumerate(mock_configs):
            decrypted = decrypt_credentials(config.encrypted_credentials, new_key)
            assert decrypted == creds_list[i]


class TestKeyRotationServiceRollback:
    """Tests for key rotation rollback scenarios."""

    @pytest.mark.anyio
    async def test_rollback_on_decryption_failure(self):
        """Rolls back when decryption fails (wrong old key provided)."""
        old_key = _generate_key()
        wrong_old_key = _generate_key()  # Not the actual key used to encrypt
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        # Encrypt with the actual old key, but provide wrong key
        actual_key = _generate_key()
        original_creds = {"username": "admin", "password": "secret"}
        encrypted = encrypt_credentials(original_creds, actual_key)

        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.connector_id = uuid.uuid4()
        mock_config.encrypted_credentials = encrypted

        db = _mock_db_with_configs([mock_config])

        service = KeyRotationService(db)
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        result = await service.rotate_encryption_key(wrong_old_key, new_key, actor_id)

        assert result.success is False
        assert result.rolled_back is True
        assert result.failed_count == 1
        assert result.error_message is not None

        # Verify original credentials are restored
        assert mock_config.encrypted_credentials == encrypted

    @pytest.mark.anyio
    async def test_rollback_on_partial_failure(self):
        """Rolls back all changes when rotation fails midway."""
        old_key = _generate_key()
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        # Create configs: first is valid, second will cause failure
        creds1 = {"username": "user1", "password": "pass1"}
        encrypted1 = encrypt_credentials(creds1, old_key)

        # Second config has corrupted encrypted data that can't be decrypted
        corrupted_data = os.urandom(50)  # Random bytes that won't decrypt

        config1 = MagicMock()
        config1.id = uuid.uuid4()
        config1.connector_id = uuid.uuid4()
        config1.encrypted_credentials = encrypted1

        config2 = MagicMock()
        config2.id = uuid.uuid4()
        config2.connector_id = uuid.uuid4()
        config2.encrypted_credentials = corrupted_data

        db = _mock_db_with_configs([config1, config2])

        service = KeyRotationService(db)
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        result = await service.rotate_encryption_key(old_key, new_key, actor_id)

        assert result.success is False
        assert result.rolled_back is True
        # Config1 should have been rolled back to original
        assert config1.encrypted_credentials == encrypted1
        # Config2 should still have its original corrupted data
        assert config2.encrypted_credentials == corrupted_data

    @pytest.mark.anyio
    async def test_rollback_on_db_flush_failure(self):
        """Rolls back when DB flush fails after re-encryption."""
        old_key = _generate_key()
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        creds = {"username": "admin", "password": "secret"}
        encrypted = encrypt_credentials(creds, old_key)

        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.connector_id = uuid.uuid4()
        mock_config.encrypted_credentials = encrypted

        db = _mock_db_with_configs([mock_config])
        # First flush raises (the main flush), second succeeds (the rollback flush)
        db.flush = AsyncMock(side_effect=[Exception("DB connection lost"), None])

        service = KeyRotationService(db)
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        result = await service.rotate_encryption_key(old_key, new_key, actor_id)

        assert result.success is False
        assert result.rolled_back is True
        assert "Database update failed" in result.error_message


class TestKeyRotationValidation:
    """Tests for input validation."""

    @pytest.mark.anyio
    async def test_rejects_short_old_key(self):
        """Rejects old key that isn't 32 bytes."""
        db = AsyncMock()
        service = KeyRotationService(db)
        result = await service.rotate_encryption_key(
            old_key=b"short", new_key=_generate_key(), actor_id=uuid.uuid4()
        )
        assert result.success is False
        assert "32 bytes" in result.error_message

    @pytest.mark.anyio
    async def test_rejects_short_new_key(self):
        """Rejects new key that isn't 32 bytes."""
        db = AsyncMock()
        service = KeyRotationService(db)
        result = await service.rotate_encryption_key(
            old_key=_generate_key(), new_key=b"short", actor_id=uuid.uuid4()
        )
        assert result.success is False
        assert "32 bytes" in result.error_message

    @pytest.mark.anyio
    async def test_rejects_same_old_and_new_key(self):
        """Rejects rotation when old and new keys are identical."""
        key = _generate_key()
        db = AsyncMock()
        service = KeyRotationService(db)
        result = await service.rotate_encryption_key(
            old_key=key, new_key=key, actor_id=uuid.uuid4()
        )
        assert result.success is False
        assert "different" in result.error_message


class TestKeyRotationAudit:
    """Tests for audit log recording during rotation."""

    @pytest.mark.anyio
    async def test_records_success_in_audit_log(self):
        """Records a success audit event on completed rotation."""
        old_key = _generate_key()
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        db = _mock_db_with_configs([])

        service = KeyRotationService(db)
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        await service.rotate_encryption_key(old_key, new_key, actor_id)

        service.audit_service.record_event.assert_called_once()
        call_args = service.audit_service.record_event.call_args[0][0]
        assert call_args.result.value == "success"
        assert call_args.target_resource_id == "master_encryption_key"

    @pytest.mark.anyio
    async def test_records_failure_in_audit_log(self):
        """Records a failure audit event when rotation fails."""
        old_key = _generate_key()
        new_key = _generate_key()
        actor_id = uuid.uuid4()

        # Corrupted data that can't be decrypted
        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.connector_id = uuid.uuid4()
        mock_config.encrypted_credentials = os.urandom(50)

        db = _mock_db_with_configs([mock_config])

        service = KeyRotationService(db)
        service.audit_service = AsyncMock()
        service.audit_service.record_event = AsyncMock()

        await service.rotate_encryption_key(old_key, new_key, actor_id)

        service.audit_service.record_event.assert_called_once()
        call_args = service.audit_service.record_event.call_args[0][0]
        assert call_args.result.value == "failure"
        assert call_args.target_resource_type == "encryption_key_rotation"


class TestDualKeyDecryption:
    """Tests for dual-key decryption during rotation transition."""

    def test_decrypt_with_previous_key_when_primary_fails(self):
        """During rotation, credentials encrypted with old key can still be decrypted."""
        old_key = _generate_key()
        new_key = _generate_key()

        # Encrypt with old key
        creds = {"username": "test", "password": "secret"}
        encrypted = encrypt_credentials(creds, old_key)

        # Simulate rotation in progress: set previous key
        import backend.app.services.key_rotation_service as krs
        krs._previous_key = old_key
        try:
            # Trying to decrypt with new key should fall back to old key
            result = decrypt_credentials(encrypted, new_key)
            assert result == creds
        finally:
            krs._previous_key = None

    def test_decrypt_without_previous_key_fails(self):
        """Without previous key set, wrong key raises an error."""
        old_key = _generate_key()
        new_key = _generate_key()

        creds = {"username": "test", "password": "secret"}
        encrypted = encrypt_credentials(creds, old_key)

        # No previous key available — should raise
        import backend.app.services.key_rotation_service as krs
        krs._previous_key = None
        with pytest.raises(Exception):
            decrypt_credentials(encrypted, new_key)

    def test_previous_key_cleared_after_rotation(self):
        """After rotation completes, previous key is cleared."""
        import backend.app.services.key_rotation_service as krs

        old_key = _generate_key()
        krs._previous_key = old_key
        assert get_previous_key() == old_key

        clear_previous_key()
        assert get_previous_key() is None

    def test_decrypt_with_correct_primary_key_ignores_previous(self):
        """When primary key works, previous key is not needed."""
        key = _generate_key()
        creds = {"username": "test", "password": "pass"}
        encrypted = encrypt_credentials(creds, key)

        # Even with a previous key set, primary key decrypts fine
        import backend.app.services.key_rotation_service as krs
        krs._previous_key = _generate_key()
        try:
            result = decrypt_credentials(encrypted, key)
            assert result == creds
        finally:
            krs._previous_key = None
