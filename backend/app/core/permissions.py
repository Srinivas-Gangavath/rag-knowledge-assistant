"""Authorization capability definitions and role permission matrices.

Defines fine-grained permissions (capabilities) and maps OrganizationRole and
WorkspaceRole to those capabilities according to least privilege.
"""

from __future__ import annotations

import enum
from typing import FrozenSet

from app.db.models import OrganizationRole, WorkspaceRole


class Permission(enum.StrEnum):
    # Document capabilities
    DOCUMENT_READ = "document:read"
    DOCUMENT_CREATE = "document:create"
    DOCUMENT_UPDATE = "document:update"
    DOCUMENT_DELETE = "document:delete"

    # Conversation & Search capabilities
    CONVERSATION_CREATE = "conversation:create"
    CONVERSATION_READ = "conversation:read"
    CONVERSATION_DELETE = "conversation:delete"
    CONVERSATION_MANAGE = "conversation:manage"  # Manage (view/delete) any conversation in workspace
    KNOWLEDGE_QUERY = "knowledge:query"          # Chat and hybrid search

    # Workspace capabilities
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_MANAGE = "workspace:manage"        # Update workspace name / settings / archive
    WORKSPACE_DELETE = "workspace:delete"        # Delete / archive workspace
    WORKSPACE_MEMBER_MANAGE = "workspace:member:manage"  # Add / update / remove workspace members
    WORKSPACE_CREATE = "workspace:create"        # Create a new workspace in the organization

    # Audit & Governance capabilities
    AUDIT_LOG_READ = "audit_log:read"            # View organization/workspace audit trail
    ALERT_READ = "alert:read"                    # View operational alerts
    ALERT_MANAGE = "alert:manage"                # Acknowledge, resolve alerts, manage rules

    # Organization capabilities
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_MANAGE = "organization:manage"
    ORGANIZATION_MEMBER_MANAGE = "organization:member:manage"


# Workspace Role -> Permissions mapping
WORKSPACE_ROLE_PERMISSIONS: dict[WorkspaceRole, set[Permission]] = {
    WorkspaceRole.WORKSPACE_ADMIN: {
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_CREATE,
        Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_DELETE,
        Permission.CONVERSATION_CREATE,
        Permission.CONVERSATION_READ,
        Permission.CONVERSATION_DELETE,
        Permission.CONVERSATION_MANAGE,
        Permission.KNOWLEDGE_QUERY,
        Permission.WORKSPACE_READ,
        Permission.WORKSPACE_MANAGE,
        Permission.WORKSPACE_DELETE,
        Permission.WORKSPACE_MEMBER_MANAGE,
        Permission.AUDIT_LOG_READ,
        Permission.ALERT_READ,
        Permission.ALERT_MANAGE,
    },
    WorkspaceRole.CONTRIBUTOR: {
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_CREATE,
        Permission.DOCUMENT_UPDATE,
        Permission.CONVERSATION_CREATE,
        Permission.CONVERSATION_READ,
        Permission.CONVERSATION_DELETE,
        Permission.KNOWLEDGE_QUERY,
        Permission.WORKSPACE_READ,
    },
    WorkspaceRole.VIEWER: {
        Permission.DOCUMENT_READ,
        Permission.CONVERSATION_CREATE,
        Permission.CONVERSATION_READ,
        Permission.CONVERSATION_DELETE,
        Permission.KNOWLEDGE_QUERY,
        Permission.WORKSPACE_READ,
    },
}


# Organization Role -> Permissions mapping
ORGANIZATION_ROLE_PERMISSIONS: dict[OrganizationRole, set[Permission]] = {
    OrganizationRole.OWNER: {
        Permission.ORGANIZATION_READ,
        Permission.ORGANIZATION_MANAGE,
        Permission.ORGANIZATION_MEMBER_MANAGE,
        Permission.WORKSPACE_CREATE,
        Permission.AUDIT_LOG_READ,
        Permission.ALERT_READ,
        Permission.ALERT_MANAGE,
        # OWNER inherits full workspace admin rights across all org workspaces
        Permission.WORKSPACE_READ,
        Permission.WORKSPACE_MANAGE,
        Permission.WORKSPACE_DELETE,
        Permission.WORKSPACE_MEMBER_MANAGE,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_CREATE,
        Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_DELETE,
        Permission.CONVERSATION_CREATE,
        Permission.CONVERSATION_READ,
        Permission.CONVERSATION_DELETE,
        Permission.CONVERSATION_MANAGE,
        Permission.KNOWLEDGE_QUERY,
    },
    OrganizationRole.ADMIN: {
        Permission.ORGANIZATION_READ,
        Permission.ORGANIZATION_MEMBER_MANAGE,
        Permission.WORKSPACE_CREATE,
        Permission.AUDIT_LOG_READ,
        Permission.ALERT_READ,
        Permission.ALERT_MANAGE,
        # ADMIN can manage workspace configuration & members across org workspaces
        Permission.WORKSPACE_READ,
        Permission.WORKSPACE_MANAGE,
        Permission.WORKSPACE_MEMBER_MANAGE,
    },
    OrganizationRole.MEMBER: {
        Permission.ORGANIZATION_READ,
    },
    OrganizationRole.BILLING: {
        Permission.ORGANIZATION_READ,
    },
}


def resolve_effective_permissions(
    org_role: OrganizationRole | None,
    ws_role: WorkspaceRole | None,
) -> frozenset[Permission]:
    """Resolve the combined effective permissions for an organization and workspace role."""
    perms: set[Permission] = set()

    if org_role is not None:
        perms.update(ORGANIZATION_ROLE_PERMISSIONS.get(org_role, set()))

    if ws_role is not None:
        perms.update(WORKSPACE_ROLE_PERMISSIONS.get(ws_role, set()))

    return frozenset(perms)
