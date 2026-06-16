"""Reusable input validation utilities.

Provides centralized validation functions used across schemas and services
to enforce data integrity consistently:
- Email format validation
- Username format validation (3-64 alphanumeric/underscore)
- Cron expression validation (delegates to scheduler_service)
- Maximum length enforcement (255 for text, 5000 for descriptions)
- Field presence checking
- Common Pydantic field validators for reuse in schemas

Requirements: 13.1, 13.2, 16.1, 16.6
"""

import re
from typing import Any


# --- Constants ---

MAX_TEXT_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 5000
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 64
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

# Regex patterns
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,64}$")
EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
    r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

# Cron field ranges for validation
CRON_FIELD_RANGES: dict[str, tuple[int, int]] = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 6),
}


# --- Validation Functions ---


def validate_email_format(email: str) -> tuple[bool, str | None]:
    """Validate email format.

    Args:
        email: Email address string to validate.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not email:
        return False, "Email address is required"

    if len(email) > MAX_TEXT_LENGTH:
        return False, f"Email must not exceed {MAX_TEXT_LENGTH} characters"

    if not EMAIL_PATTERN.match(email):
        return False, "Invalid email address format"

    # Must contain exactly one @ and a domain with at least one dot
    parts = email.split("@")
    if len(parts) != 2:
        return False, "Invalid email address format"

    local, domain = parts
    if not local or not domain:
        return False, "Invalid email address format"

    if "." not in domain:
        return False, "Email domain must contain at least one dot"

    return True, None


def validate_username(username: str) -> tuple[bool, str | None]:
    """Validate username format: 3-64 alphanumeric/underscore characters.

    Args:
        username: Username string to validate.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not username:
        return False, "Username is required"

    if len(username) < MIN_USERNAME_LENGTH:
        return False, f"Username must be at least {MIN_USERNAME_LENGTH} characters"

    if len(username) > MAX_USERNAME_LENGTH:
        return False, f"Username must not exceed {MAX_USERNAME_LENGTH} characters"

    if not USERNAME_PATTERN.match(username):
        return False, "Username must contain only alphanumeric characters and underscores"

    return True, None


def validate_cron_expression(expression: str) -> tuple[bool, str | None]:
    """Validate a 5-field cron expression.

    Checks:
    - Exactly 5 space-separated fields
    - Each field is within its valid range
    - Minimum interval is at least 1 minute

    Args:
        expression: Cron expression string to validate.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not expression or not expression.strip():
        return False, "Cron expression is required"

    expression = expression.strip()
    fields = expression.split()

    if len(fields) != 5:
        return False, "Cron expression must have exactly 5 fields (minute hour day month weekday)"

    field_names = list(CRON_FIELD_RANGES.keys())

    for i, (field, field_name) in enumerate(zip(fields, field_names)):
        min_val, max_val = CRON_FIELD_RANGES[field_name]
        error = _validate_cron_field(field, field_name, min_val, max_val)
        if error:
            return False, f"Invalid {field_name} field: {error}"

    return True, None


def _validate_cron_field(field: str, field_name: str, min_val: int, max_val: int) -> str | None:
    """Validate a single cron field."""
    parts = field.split(",")
    for part in parts:
        error = _validate_cron_part(part.strip(), field_name, min_val, max_val)
        if error:
            return error
    return None


def _validate_cron_part(part: str, field_name: str, min_val: int, max_val: int) -> str | None:
    """Validate a single part of a cron field (handles ranges and steps)."""
    if not part:
        return "empty value"

    # Handle step values (e.g., */5, 1-10/2)
    if "/" in part:
        base, step_str = part.split("/", 1)
        if not step_str.isdigit() or int(step_str) == 0:
            return f"invalid step value '{step_str}'"
        step = int(step_str)
        if step > max_val:
            return f"step value {step} exceeds maximum {max_val}"
        return _validate_cron_base(base, field_name, min_val, max_val)

    return _validate_cron_base(part, field_name, min_val, max_val)


def _validate_cron_base(base: str, field_name: str, min_val: int, max_val: int) -> str | None:
    """Validate the base part of a cron field."""
    # Wildcard
    if base == "*":
        return None

    # Range (e.g., 1-5)
    if "-" in base:
        range_parts = base.split("-", 1)
        if len(range_parts) != 2:
            return f"invalid range '{base}'"
        start_str, end_str = range_parts
        if not start_str.isdigit() or not end_str.isdigit():
            return f"range values must be integers in '{base}'"
        start, end = int(start_str), int(end_str)
        if start < min_val or start > max_val:
            return f"range start {start} out of bounds ({min_val}-{max_val})"
        if end < min_val or end > max_val:
            return f"range end {end} out of bounds ({min_val}-{max_val})"
        if start > end:
            return f"range start {start} must not exceed end {end}"
        return None

    # Single value
    if not base.isdigit():
        return f"invalid value '{base}'"
    val = int(base)
    if val < min_val or val > max_val:
        return f"value {val} out of bounds ({min_val}-{max_val})"
    return None


def validate_max_length(value: str, max_length: int, field_name: str) -> tuple[bool, str | None]:
    """Validate that a string does not exceed the maximum length.

    Args:
        value: The string value to check.
        max_length: Maximum allowed length.
        field_name: Name of the field for error messaging.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if value and len(value) > max_length:
        return False, f"{field_name} must not exceed {max_length} characters"
    return True, None


def validate_text_field(value: str | None, field_name: str, required: bool = False) -> tuple[bool, str | None]:
    """Validate a text field (max 255 characters).

    Args:
        value: The text value to validate.
        field_name: Name of the field for error messaging.
        required: Whether the field is required.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if required and (value is None or not value.strip()):
        return False, f"{field_name} is required"

    if value is not None and len(value) > MAX_TEXT_LENGTH:
        return False, f"{field_name} must not exceed {MAX_TEXT_LENGTH} characters"

    return True, None


def validate_description_field(value: str | None, field_name: str = "description") -> tuple[bool, str | None]:
    """Validate a description field (max 5000 characters).

    Args:
        value: The description value to validate.
        field_name: Name of the field for error messaging.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if value is not None and len(value) > MAX_DESCRIPTION_LENGTH:
        return False, f"{field_name} must not exceed {MAX_DESCRIPTION_LENGTH} characters"

    return True, None


def validate_required_fields(data: dict[str, Any], required_fields: list[str]) -> list[str]:
    """Check that all required fields are present and non-empty.

    Args:
        data: Dictionary of field name -> value.
        required_fields: List of field names that must be present.

    Returns:
        List of missing field names. Empty list if all present.
    """
    missing = []
    for field in required_fields:
        value = data.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing


def validate_password(password: str) -> tuple[bool, str | None]:
    """Validate password meets minimum requirements.

    Args:
        password: Password string to validate.

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not password:
        return False, "Password is required"

    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"

    if len(password) > MAX_PASSWORD_LENGTH:
        return False, f"Password must not exceed {MAX_PASSWORD_LENGTH} characters"

    return True, None


# --- Pydantic Field Validator Helpers ---
# These can be used with @field_validator decorators in Pydantic models


def pydantic_validate_username(v: str) -> str:
    """Pydantic field validator for username format.

    Usage:
        @field_validator("username")
        @classmethod
        def check_username(cls, v):
            return pydantic_validate_username(v)
    """
    is_valid, error = validate_username(v)
    if not is_valid:
        raise ValueError(error)
    return v


def pydantic_validate_email(v: str) -> str:
    """Pydantic field validator for email format.

    Usage:
        @field_validator("email")
        @classmethod
        def check_email(cls, v):
            return pydantic_validate_email(v)
    """
    is_valid, error = validate_email_format(v)
    if not is_valid:
        raise ValueError(error)
    return v


def pydantic_validate_cron(v: str) -> str:
    """Pydantic field validator for cron expression.

    Usage:
        @field_validator("cron_expression")
        @classmethod
        def check_cron(cls, v):
            return pydantic_validate_cron(v)
    """
    is_valid, error = validate_cron_expression(v)
    if not is_valid:
        raise ValueError(error)
    return v


def pydantic_validate_text_length(v: str | None, max_length: int = MAX_TEXT_LENGTH) -> str | None:
    """Pydantic field validator for text max length.

    Usage:
        @field_validator("name")
        @classmethod
        def check_name(cls, v):
            return pydantic_validate_text_length(v)
    """
    if v is not None and len(v) > max_length:
        raise ValueError(f"Field must not exceed {max_length} characters")
    return v


def pydantic_validate_description_length(v: str | None) -> str | None:
    """Pydantic field validator for description max length (5000 chars).

    Usage:
        @field_validator("description")
        @classmethod
        def check_description(cls, v):
            return pydantic_validate_description_length(v)
    """
    if v is not None and len(v) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f"Description must not exceed {MAX_DESCRIPTION_LENGTH} characters")
    return v
