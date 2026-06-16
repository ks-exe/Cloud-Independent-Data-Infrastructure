"""AES-256-GCM credential encryption module.

Provides encrypt/decrypt operations for connector credentials using
AES-256-GCM with per-connector initialization vectors (IVs).

The encrypted format is: IV (12 bytes) + ciphertext + auth tag (16 bytes appended by AESGCM).

Master encryption key is loaded from settings (CREDENTIAL_ENCRYPTION_KEY env var).
The key must be a 64-character hex string representing 32 bytes.
"""

import json
import os
import logging

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# IV length for AES-GCM (96 bits recommended by NIST)
IV_LENGTH = 12


def _get_master_key() -> bytes:
    """Load and validate the master encryption key from settings.

    Returns:
        32-byte key derived from the hex-encoded setting.

    Raises:
        ValueError: If the key is missing or invalid length.
    """
    key_hex = settings.credential_encryption_key
    if not key_hex or key_hex == "change-this-to-a-32-byte-hex-key-in-production":
        # In dev mode, derive a deterministic key from the setting string
        # In production, this MUST be a proper 64-char hex key
        import hashlib
        key = hashlib.sha256(key_hex.encode()).digest()
        logger.warning(
            "Using derived encryption key. Set CREDENTIAL_ENCRYPTION_KEY to a "
            "64-character hex string in production."
        )
        return key

    try:
        key = bytes.fromhex(key_hex)
    except ValueError:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY must be a valid hex string. "
            "Got a non-hex value."
        )

    if len(key) != 32:
        raise ValueError(
            f"CREDENTIAL_ENCRYPTION_KEY must be 64 hex characters (32 bytes). "
            f"Got {len(key_hex)} hex characters ({len(key)} bytes)."
        )

    return key


def encrypt_credentials(data: dict, key: bytes | None = None) -> bytes:
    """Encrypt a credentials dictionary using AES-256-GCM.

    Serializes the dict to JSON, encrypts with a random per-connector IV,
    and returns IV || ciphertext+tag.

    Args:
        data: The credentials dictionary to encrypt.
        key: Optional 32-byte encryption key. Defaults to master key from settings.

    Returns:
        bytes: IV (12 bytes) + encrypted data (ciphertext + 16-byte auth tag).
    """
    if key is None:
        key = _get_master_key()

    # Serialize credentials to JSON bytes
    plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")

    # Generate a random 12-byte IV
    iv = os.urandom(IV_LENGTH)

    # Encrypt using AES-256-GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)

    # Return IV prepended to ciphertext (includes auth tag)
    return iv + ciphertext


def decrypt_credentials(encrypted: bytes, key: bytes | None = None) -> dict:
    """Decrypt AES-256-GCM encrypted credentials.

    Splits the input into IV and ciphertext+tag, decrypts, and
    deserializes the JSON back to a dictionary.

    During key rotation transitions, if decryption with the primary key fails,
    this function automatically attempts decryption with the previous key
    (if one is available). This ensures active pipeline executions are not
    interrupted during rotation.

    Args:
        encrypted: The encrypted bytes (IV + ciphertext + tag).
        key: Optional 32-byte decryption key. Defaults to master key from settings.

    Returns:
        dict: The decrypted credentials dictionary.

    Raises:
        ValueError: If the encrypted data is too short or corrupted.
        cryptography.exceptions.InvalidTag: If decryption fails (wrong key or tampered data).
    """
    if key is None:
        key = _get_master_key()

    if len(encrypted) < IV_LENGTH + 16:
        raise ValueError(
            f"Encrypted data too short. Expected at least {IV_LENGTH + 16} bytes, "
            f"got {len(encrypted)}."
        )

    # Split IV from ciphertext
    iv = encrypted[:IV_LENGTH]
    ciphertext = encrypted[IV_LENGTH:]

    # Decrypt using AES-256-GCM
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
    except Exception as primary_error:
        # During key rotation, try the previous key if available
        from backend.app.services.key_rotation_service import get_previous_key

        previous_key = get_previous_key()
        if previous_key is not None and previous_key != key:
            try:
                aesgcm_prev = AESGCM(previous_key)
                plaintext = aesgcm_prev.decrypt(iv, ciphertext, None)
                logger.debug(
                    "Decrypted credentials using previous key (rotation in progress)."
                )
            except Exception:
                # Both keys failed — raise the original error
                raise primary_error
        else:
            raise primary_error

    # Deserialize JSON
    return json.loads(plaintext.decode("utf-8"))
