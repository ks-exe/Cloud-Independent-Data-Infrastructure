"""Unit tests for the permissions module."""

import pytest

from backend.app.core.permissions import (
    ROLE_PERMISSIONS,
    Permissions,
    RoleName,
    get_role_permissions,
    role_has_permission,
)


class TestRolePermissionDefinitions:
    """Tests verifying the role-permission mapping definitions."""

    def test_all_five_roles_defined(self):
        """All 5 roles should have permission entries."""
        expected_roles = {"Admin", "Data_Engineer", "Operator", "Auditor", "Viewer"}
        actual_roles = set(ROLE_PERMISSIONS.keys())
        assert expected_roles == actual_roles

    def test_admin_has_wildcard_for_all_resources(self):
        """Admin should have wildcard access to all resources."""
        admin_perms = ROLE_PERMISSIONS[RoleName.ADMIN]
        assert "users.*" in admin_perms
        assert "connectors.*" in admin_perms
        assert "pipelines.*" in admin_perms
        assert "schedules.*" in admin_perms
        assert "monitoring.*" in admin_perms
        assert "audit.*" in admin_perms
        assert "lineage.*" in admin_perms
        assert "settings.*" in admin_perms
        assert "notifications.*" in admin_perms

    def test_data_engineer_permissions(self):
        """Data_Engineer should have connectors (CRUD+test), pipelines.*, schedules.*, notifications.read."""
        perms = ROLE_PERMISSIONS[RoleName.DATA_ENGINEER]
        assert "pipelines.*" in perms
        assert "schedules.*" in perms
        assert Permissions.CONNECTORS_CREATE in perms
        assert Permissions.CONNECTORS_READ in perms
        assert Permissions.CONNECTORS_UPDATE in perms
        assert Permissions.CONNECTORS_DELETE in perms
        assert Permissions.CONNECTORS_TEST in perms
        assert Permissions.NOTIFICATIONS_READ in perms

    def test_operator_permissions(self):
        """Operator should have monitoring.read, pipelines.read/retry, notifications.read/update."""
        perms = ROLE_PERMISSIONS[RoleName.OPERATOR]
        assert Permissions.MONITORING_READ in perms
        assert Permissions.PIPELINES_READ in perms
        assert Permissions.PIPELINES_RETRY in perms
        assert Permissions.NOTIFICATIONS_READ in perms
        assert Permissions.NOTIFICATIONS_UPDATE in perms

    def test_auditor_permissions(self):
        """Auditor should have audit.*, lineage.*, pipelines.read."""
        perms = ROLE_PERMISSIONS[RoleName.AUDITOR]
        assert "audit.*" in perms
        assert "lineage.*" in perms
        assert Permissions.PIPELINES_READ in perms

    def test_viewer_permissions(self):
        """Viewer should have monitoring.read, pipelines.read, connectors.read, notifications.read."""
        perms = ROLE_PERMISSIONS[RoleName.VIEWER]
        assert Permissions.MONITORING_READ in perms
        assert Permissions.PIPELINES_READ in perms
        assert Permissions.CONNECTORS_READ in perms
        assert Permissions.NOTIFICATIONS_READ in perms


class TestRoleHasPermission:
    """Tests for the role_has_permission function."""

    def test_direct_permission_match(self):
        """Direct permission match should return True."""
        assert role_has_permission("Operator", "monitoring.read") is True

    def test_wildcard_permission_match(self):
        """Wildcard 'resource.*' should grant any action on that resource."""
        assert role_has_permission("Admin", "users.create") is True
        assert role_has_permission("Admin", "users.delete") is True
        assert role_has_permission("Admin", "users.update") is True
        assert role_has_permission("Admin", "connectors.test") is True
        assert role_has_permission("Admin", "pipelines.execute") is True

    def test_wildcard_does_not_cross_resources(self):
        """Wildcard on one resource should not grant access to a different resource."""
        # Operator has monitoring.read but not users.*
        assert role_has_permission("Operator", "users.create") is False

    def test_permission_denied_for_missing_permission(self):
        """Should return False when role doesn't have the permission."""
        assert role_has_permission("Viewer", "users.create") is False
        assert role_has_permission("Viewer", "connectors.create") is False
        assert role_has_permission("Viewer", "pipelines.execute") is False

    def test_unknown_role_returns_false(self):
        """Unknown role should return False."""
        assert role_has_permission("NonExistentRole", "users.read") is False

    def test_data_engineer_wildcard_pipelines(self):
        """Data_Engineer's pipelines.* should cover any pipeline action."""
        assert role_has_permission("Data_Engineer", "pipelines.create") is True
        assert role_has_permission("Data_Engineer", "pipelines.execute") is True
        assert role_has_permission("Data_Engineer", "pipelines.delete") is True
        assert role_has_permission("Data_Engineer", "pipelines.retry") is True

    def test_operator_specific_permissions(self):
        """Operator should have specific permissions but not wildcard on pipelines."""
        assert role_has_permission("Operator", "pipelines.read") is True
        assert role_has_permission("Operator", "pipelines.retry") is True
        # Operator does NOT have pipelines.* so no pipelines.create
        assert role_has_permission("Operator", "pipelines.create") is False
        assert role_has_permission("Operator", "pipelines.execute") is False

    def test_viewer_read_only(self):
        """Viewer should only have read access."""
        assert role_has_permission("Viewer", "monitoring.read") is True
        assert role_has_permission("Viewer", "pipelines.read") is True
        assert role_has_permission("Viewer", "connectors.read") is True
        assert role_has_permission("Viewer", "notifications.read") is True
        # No write access
        assert role_has_permission("Viewer", "pipelines.create") is False
        assert role_has_permission("Viewer", "connectors.create") is False
        assert role_has_permission("Viewer", "notifications.update") is False

    def test_auditor_audit_wildcard(self):
        """Auditor's audit.* should cover read and export."""
        assert role_has_permission("Auditor", "audit.read") is True
        assert role_has_permission("Auditor", "audit.export") is True

    def test_auditor_lineage_wildcard(self):
        """Auditor's lineage.* should cover read."""
        assert role_has_permission("Auditor", "lineage.read") is True

    def test_data_engineer_no_user_access(self):
        """Data_Engineer should not have user management access."""
        assert role_has_permission("Data_Engineer", "users.create") is False
        assert role_has_permission("Data_Engineer", "users.read") is False
        assert role_has_permission("Data_Engineer", "users.delete") is False

    def test_operator_notification_access(self):
        """Operator should be able to read and update notifications."""
        assert role_has_permission("Operator", "notifications.read") is True
        assert role_has_permission("Operator", "notifications.update") is True


class TestGetRolePermissions:
    """Tests for the get_role_permissions function."""

    def test_returns_correct_set_for_known_role(self):
        """Should return the full permission set for a known role."""
        perms = get_role_permissions("Admin")
        assert isinstance(perms, set)
        assert "users.*" in perms

    def test_returns_empty_set_for_unknown_role(self):
        """Should return an empty set for an unknown role."""
        perms = get_role_permissions("Unknown")
        assert perms == set()

    def test_admin_has_most_permissions(self):
        """Admin should have the most permission entries (9 wildcards)."""
        admin_perms = get_role_permissions("Admin")
        assert len(admin_perms) == 9  # One wildcard per resource


class TestPermissionConstants:
    """Tests for the Permissions class constants."""

    def test_permission_format(self):
        """All permission constants should follow resource.action format."""
        for attr in dir(Permissions):
            if attr.isupper() and not attr.startswith("_"):
                value = getattr(Permissions, attr)
                assert "." in value, f"{attr} = {value} doesn't follow resource.action format"
                parts = value.split(".")
                assert len(parts) == 2, f"{attr} = {value} has unexpected number of parts"

    def test_all_resources_covered(self):
        """All expected resources should have at least one permission constant."""
        expected_resources = {
            "users", "connectors", "pipelines", "schedules",
            "monitoring", "audit", "lineage", "settings", "notifications",
        }
        actual_resources = set()
        for attr in dir(Permissions):
            if attr.isupper() and not attr.startswith("_"):
                value = getattr(Permissions, attr)
                resource = value.split(".")[0]
                actual_resources.add(resource)
        assert expected_resources == actual_resources
