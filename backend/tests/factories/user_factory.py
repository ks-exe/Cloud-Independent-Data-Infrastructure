"""Factory-boy factories for User and Role models."""

import uuid

import factory

from backend.app.core.security import hash_password
from backend.app.models.users import Permission, Role, User


class RoleFactory(factory.Factory):
    """Factory for creating Role instances."""

    class Meta:
        model = Role

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"role_{n}")
    description = factory.LazyAttribute(lambda o: f"Description for {o.name}")
    permissions = factory.LazyFunction(lambda: {"resources": ["*"], "actions": ["read"]})


class AdminRoleFactory(RoleFactory):
    """Factory for Admin role."""

    name = "Admin"
    description = "Full system administrator"
    permissions = factory.LazyFunction(lambda: {"resources": ["*"], "actions": ["*"]})


class OperatorRoleFactory(RoleFactory):
    """Factory for Operator role."""

    name = "Operator"
    description = "Operations team member"
    permissions = factory.LazyFunction(
        lambda: {
            "resources": ["pipelines", "connectors", "schedules", "monitoring"],
            "actions": ["read", "create", "update", "execute"],
        }
    )


class DataEngineerRoleFactory(RoleFactory):
    """Factory for Data Engineer role."""

    name = "Data_Engineer"
    description = "Data engineering team member"
    permissions = factory.LazyFunction(
        lambda: {
            "resources": ["pipelines", "connectors"],
            "actions": ["read", "create", "update"],
        }
    )


class ViewerRoleFactory(RoleFactory):
    """Factory for Viewer role."""

    name = "Viewer"
    description = "Read-only viewer"
    permissions = factory.LazyFunction(
        lambda: {"resources": ["*"], "actions": ["read"]}
    )


class UserFactory(factory.Factory):
    """Factory for creating User instances."""

    class Meta:
        model = User

    id = factory.LazyFunction(uuid.uuid4)
    username = factory.Sequence(lambda n: f"user_{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password_hash = factory.LazyFunction(lambda: hash_password("TestPassword123!"))
    display_name = factory.LazyAttribute(lambda o: o.username.replace("_", " ").title())
    role_id = factory.LazyFunction(uuid.uuid4)
    is_active = True
    is_deleted = False


class AdminUserFactory(UserFactory):
    """Factory for Admin users."""

    username = factory.Sequence(lambda n: f"admin_{n}")


class InactiveUserFactory(UserFactory):
    """Factory for inactive users."""

    is_active = False


class DeletedUserFactory(UserFactory):
    """Factory for soft-deleted users."""

    is_deleted = True


class PermissionFactory(factory.Factory):
    """Factory for creating Permission instances."""

    class Meta:
        model = Permission

    id = factory.LazyFunction(uuid.uuid4)
    resource = factory.Iterator(
        ["pipelines", "connectors", "users", "schedules", "audit", "settings"]
    )
    action = factory.Iterator(["read", "create", "update", "delete", "execute"])
    role_id = factory.LazyFunction(uuid.uuid4)
