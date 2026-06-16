"""Unit tests for AES-256-GCM credential encryption module."""

import os

import pytest

from backend.app.core.encryption import (
    IV_LENGTH,
    decrypt_credentials,
    encrypt_credentials,
)


class TestEncryptCredentials:
    """Tests for encrypt_credentials function."""

    def _generate_key(self) -> bytes:
        """Generate a random 32-byte key for testing."""
        return os.urandom(32)

    def test_encrypt_returns_bytes(self):
        key = self._generate_key()
        data = {"username": "admin", "password": "secret123"}
        result = encrypt_credentials(data, key)
        assert isinstance(result, bytes)

    def test_encrypted_output_has_correct_minimum_length(self):
        """IV (12) + at least 1 byte ciphertext + tag (16) = 29 minimum."""
        key = self._generate_key()
        data = {"a": "b"}
        result = encrypt_credentials(data, key)
        assert len(result) >= IV_LENGTH + 16

    def test_encrypted_output_does_not_contain_plaintext(self):
        """Ciphertext must not contain the plaintext password."""
        key = self._generate_key()
        password = "super_secret_password_12345"
        data = {"password": password}
        result = encrypt_credentials(data, key)
        assert password.encode() not in result

    def test_encrypt_same_data_produces_different_ciphertext(self):
        """Each encryption uses a random IV, so same plaintext → different ciphertext."""
        key = self._generate_key()
        data = {"username": "test", "password": "pass123"}
        result1 = encrypt_credentials(data, key)
        result2 = encrypt_credentials(data, key)
        assert result1 != result2

    def test_encrypt_empty_credentials(self):
        """Empty dict should still encrypt successfully."""
        key = self._generate_key()
        data = {}
        result = encrypt_credentials(data, key)
        assert isinstance(result, bytes)
        assert len(result) >= IV_LENGTH + 16


class TestDecryptCredentials:
    """Tests for decrypt_credentials function."""

    def _generate_key(self) -> bytes:
        return os.urandom(32)

    def test_decrypt_returns_original_data(self):
        """Encrypt → decrypt round-trip preserves data."""
        key = self._generate_key()
        original = {"username": "admin", "password": "secret123", "port": "5432"}
        encrypted = encrypt_credentials(original, key)
        decrypted = decrypt_credentials(encrypted, key)
        assert decrypted == original

    def test_decrypt_complex_credentials(self):
        """Handles nested/complex credential structures."""
        key = self._generate_key()
        original = {
            "username": "user",
            "password": "p@$$w0rd!#%",
            "ssl_cert": "-----BEGIN CERTIFICATE-----\nMIIBxTCCA...",
            "options": "sslmode=require",
        }
        encrypted = encrypt_credentials(original, key)
        decrypted = decrypt_credentials(encrypted, key)
        assert decrypted == original

    def test_decrypt_with_wrong_key_raises_error(self):
        """Decrypting with a different key should fail."""
        key1 = self._generate_key()
        key2 = self._generate_key()
        data = {"password": "secret"}
        encrypted = encrypt_credentials(data, key1)
        with pytest.raises(Exception):  # InvalidTag from cryptography
            decrypt_credentials(encrypted, key2)

    def test_decrypt_tampered_data_raises_error(self):
        """Tampered ciphertext should fail authentication."""
        key = self._generate_key()
        data = {"password": "secret"}
        encrypted = encrypt_credentials(data, key)
        # Tamper with a byte in the ciphertext area
        tampered = bytearray(encrypted)
        tampered[IV_LENGTH + 5] ^= 0xFF
        with pytest.raises(Exception):
            decrypt_credentials(bytes(tampered), key)

    def test_decrypt_too_short_data_raises_value_error(self):
        """Data shorter than IV + tag should raise ValueError."""
        key = self._generate_key()
        with pytest.raises(ValueError, match="too short"):
            decrypt_credentials(b"short", key)

    def test_encrypt_decrypt_unicode_credentials(self):
        """Unicode characters in credentials should round-trip correctly."""
        key = self._generate_key()
        original = {"username": "用户", "password": "密码🔑"}
        encrypted = encrypt_credentials(original, key)
        decrypted = decrypt_credentials(encrypted, key)
        assert decrypted == original


class TestEncryptionRoundTrip:
    """Integration-style round-trip tests for encryption."""

    def _generate_key(self) -> bytes:
        return os.urandom(32)

    def test_multiple_credentials_round_trip(self):
        """Multiple distinct credentials all round-trip correctly."""
        key = self._generate_key()
        credentials_list = [
            {"username": "pg_user", "password": "pg_pass"},
            {"api_key": "sk-1234567890abcdef"},
            {"username": "mysql_root", "password": ""},
            {"token": "eyJhbGciOiJIUzI1NiJ9..."},
        ]
        for creds in credentials_list:
            encrypted = encrypt_credentials(creds, key)
            decrypted = decrypt_credentials(encrypted, key)
            assert decrypted == creds
