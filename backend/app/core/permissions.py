"""Role-permission definitions for RBAC enforcement.

Defines the 5 roles and their associated permissions using a resource.action pattern.
Each user holds exactly one role at any time, and that role determines which API
operations the user can access.

Permission format: "resource.action" where action can be a wildcard "*" meaning all
actions on that resource.

Roles:
- Admin: Full access to all resources (users, connectors, pipelines, schedules,
         monitoring, audit, lineage, settings, notifications).
- Data_Engineer: Create/read/update/delete/test connectors, full pipeline and schedule
                 access, read notifications.
- Operator: Monitoring access, read pipelines, retry pipelines, read/update notifications.
- Auditor: Read audit logs, export audit logs, read lineage, read pipelines.
- Viewer: Read-only access to monitoring dashboards, pipelines, connectors, and notifications.
"""

from enum import Enum


class RoleName(str, Enum):
    """Enumeration of all platform roles."""

    ADMIN = "Admin"
    DATA_ENGINEER = "Data_Engineer"
    OPERATOR = "Operator"
    AUDITOR = "Auditor"
    VIEWER = "Viewer"


# ---------------------------------------------------------------------------
# Permission constants organized by resource
# ---------------------------------------------------------------------------

class Permissions:
    """Permission constants organized by resource."""

    # Users
    USERS_CREATE = "users.create"
    USERS_READ = "users.read"
    USERS_UPDATE = "users.update"
    USERS_DELETE = "users.delete"

    # Connectors
    CONNECTORS_CREATE = "connectors.create"
    CONNECTORS_READ = "connectors.read"
    CONNECTORS_UPDATE = "connectors.update"
    CONNECTORS_DELETE = "connectors.delete"
    CONNECTORS_TEST = "connectors.test"

    # Pipelines
    PIPELINES_CREATE = "pipelines.create"
    PIPELINES_READ = "pipelines.read"
    PIPELINES_UPDATE = "pipelines.update"
    PIPELINES_DELETE = "pipelines.delete"
    PIPELINES_EXECUTE = "pipelines.execute"
    PIPELINES_RETRY = "pipelines.retry"

    # Schedules
    SCHEDULES_CREATE = "schedules.create"
    SCHEDULES_READ = "schedules.read"
    SCHEDULES_UPDATE = "schedules.update"
    SCHEDULES_DELETE = "schedules.delete"
    SCHEDULES_PAUSE = "schedules.pause"
    SCHEDULES_RESUME = "schedules.resume"

    # Monitoring
    MONITORING_READ = "monitoring.read"

    # Audit
    AUDIT_READ = "audit.read"
    AUDIT_EXPORT = "audit.export"

    # Lineage
    LINEAGE_READ = "lineage.read"

    # Settings
    SETTINGS_READ = "settings.read"
    SETTINGS_UPDATE = "settings.update"

    # Notifications
    NOTIFICATIONS_READ = "notifications.read"
    NOTIFICATIONS_UPDATE = "notifications.update"


# ---------------------------------------------------------------------------
# Role → Permissions mapping
# ---------------------------------------------------------------------------

# Permission definitions per role.
# A permission of "resource.*" grants all actions on that resource.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    RoleName.ADMIN: {
        # Full access to all resources
        "users.*",
        "connectors.*",
        "pipelines.*",
        "schedules.*",
        "monitoring.*",
        "audit.*",
        "lineage.*",
        "settings.*",
        "notifications.*",
    },
    RoleName.DATA_ENGINEER: {
        # Full connector management
        Permissions.CONNECTORS_CREATE,
        Permissions.CONNECTORS_READ,
        Permissions.CONNECTORS_UPDATE,
        Permissions.CONNECTORS_DELETE,
        Permissions.CONNECTORS_TEST,
        # Full pipeline management
        "pipelines.*",
        # Full schedule management
        "schedules.*",
        # Read notifications
        Permissions.NOTIFICATIONS_READ,
    },
    RoleName.OPERATOR: {
        # Monitoring access
        Permissions.MONITORING_READ,
        # Read pipelines and retry failed executions
        Permissions.PIPELINES_READ,
        Permissions.PIPELINES_RETRY,
        # Read and update notifications
        Permissions.NOTIFICATIONS_READ,
        Permissions.NOTIFICATIONS_UPDATE,
    },
    RoleName.AUDITOR: {
        # Full audit access
        "audit.*",
        # Lineage read access
        "lineage.*",
        # Read-only pipeline access
        Permissions.PIPELINES_READ,
    },
    RoleName.VIEWER: {
        # Read-only dashboard/monitoring access
        Permissions.MONITORING_READ,
        # Read-only pipeline status
        Permissions.PIPELINES_READ,
        # Read-only connector listing
        Permissions.CONNECTORS_READ,
        # Read notifications
        Permissions.NOTIFICATIONS_READ,
    },
}


def role_has_permission(role_name: str, required_permission: str) -> bool:
    """Check if a role grants a specific permission.

    Supports wildcard matching: if the role has "resource.*", it matches
    any "resource.action" request.

    Args:
        role_name: The name of the user's role (e.g. "Admin").
        required_permission: The permission required (e.g. "users.create").

    Returns:
        True if the role grants the required permission, False otherwise.
    """
    permissions = ROLE_PERMISSIONS.get(role_name, set())

    # Direct match
    if required_permission in permissions:
        return True

    # Wildcard match: check if role has "resource.*" for the requested resource
    resource = required_permission.split(".")[0] if "." in required_permission else required_permission
    wildcard = f"{resource}.*"
    if wildcard in permissions:
        return True

    return False


def get_role_permissions(role_name: str) -> set[str]:
    """Get the full permission set for a given role.

    Args:
        role_name: The name of the role.

    Returns:
        Set of permission strings granted to the role.
    """
    return ROLE_PERMISSIONS.get(role_name, set())
