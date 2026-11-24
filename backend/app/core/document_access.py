"""Document-level Access Control List (ACL) resolution and SQL query filtering.

Core Principle:
Workspace RBAC defines the maximum permission ceiling. Document ACL can only
restrict access inside that ceiling; it must never elevate privileges beyond the
user's workspace/organization role.

Default ACL Behavior:
- No ACL entries on document -> Inherits workspace-level access (all workspace members
  access according to their workspace role).
- >= 1 ACL entries on document -> Restricted. Only explicitly granted users and/or
  workspace roles may access.
- Workspace Admin / Org Owner always retains administrative control and management access
  (self-lockout protection).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select

from app.core.permissions import Permission
from app.core.workspace_context import WorkspaceContext
from app.db.models import (
    Document,
    DocumentAcl,
    DocumentPermission,
    OrganizationRole,
    PrincipalType,
    WorkspaceRole,
)


def is_workspace_admin_context(workspace_context: WorkspaceContext | None) -> bool:
    """Check if the context has administrative authority over the workspace."""
    if workspace_context is None:
        return True
    if workspace_context.organization_role == OrganizationRole.OWNER:
        return True
    if workspace_context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN:
        return True
    if workspace_context.can(Permission.WORKSPACE_MANAGE) and workspace_context.can(Permission.DOCUMENT_DELETE):
        return True
    return False


def build_document_acl_filter(
    user_id: UUID | None,
    workspace_role: WorkspaceRole | None,
    is_admin: bool,
) -> ColumnElement[bool] | None:
    """Build a SQLAlchemy WHERE clause that filters documents by ACL.

    Returns None if the user is an admin (no ACL restriction applied).
    Otherwise returns a clause matching documents that:
    1. Have no ACL records in `document_acls` (inherits workspace access), OR
    2. Have an ACL record granting access to the user_id or workspace_role.
    """
    if is_admin:
        return None

    # Subquery of all documents that have at least one ACL entry
    has_any_acls = select(DocumentAcl.document_id)

    # Condition 1: Document has no ACL entries
    no_acls_condition = ~Document.id.in_(has_any_acls)

    # Condition 2: Document has matching ACL for this user or workspace role
    matching_conditions = []
    if user_id is not None:
        matching_conditions.append(
            and_(
                DocumentAcl.principal_type == PrincipalType.USER,
                DocumentAcl.principal_id == str(user_id),
            )
        )
    if workspace_role is not None:
        matching_conditions.append(
            and_(
                DocumentAcl.principal_type == PrincipalType.WORKSPACE_ROLE,
                DocumentAcl.principal_id == str(workspace_role.value),
            )
        )

    if matching_conditions:
        matching_acls_subquery = select(DocumentAcl.document_id).where(
            or_(*matching_conditions)
        )
        has_matching_acl_condition = Document.id.in_(matching_acls_subquery)
        return or_(no_acls_condition, has_matching_acl_condition)

    return no_acls_condition


def resolve_document_permission(
    document: Document,
    user_id: UUID | None,
    workspace_role: WorkspaceRole | None,
    is_admin: bool,
) -> DocumentPermission | None:
    """Resolve the effective document-level permission granted to a user.

    Returns None if the user has no access to the document.
    """
    if is_admin:
        return DocumentPermission.ADMIN

    # If document has no ACLs, it inherits workspace access
    acls = getattr(document, "acls", None)
    if not acls:
        if workspace_role == WorkspaceRole.CONTRIBUTOR:
            return DocumentPermission.WRITE
        return DocumentPermission.READ

    # Document is restricted: evaluate matching ACL entries
    matched_permissions: list[DocumentPermission] = []
    for acl in acls:
        if acl.principal_type == PrincipalType.USER and user_id is not None:
            if acl.principal_id == str(user_id):
                matched_permissions.append(acl.permission)
        elif acl.principal_type == PrincipalType.WORKSPACE_ROLE and workspace_role is not None:
            if acl.principal_id == str(workspace_role.value):
                matched_permissions.append(acl.permission)

    if not matched_permissions:
        return None

    # Precedence: ADMIN > WRITE > READ
    if DocumentPermission.ADMIN in matched_permissions:
        return DocumentPermission.ADMIN
    if DocumentPermission.WRITE in matched_permissions:
        return DocumentPermission.WRITE
    return DocumentPermission.READ


def can_access_document(
    workspace_context: WorkspaceContext | None,
    document: Document,
    action: str = "read",
) -> bool:
    """Verify if the caller can perform the requested action on the document.

    Enforces workspace RBAC as ceiling and Document ACL as restriction.
    Actions: 'read', 'write', 'delete', 'manage_acl'.
    """
    if workspace_context is None:
        return True

    is_admin = is_workspace_admin_context(workspace_context)

    # 1. ACL Management is strictly reserved for Workspace Admins & Org Owners
    if action == "manage_acl":
        return is_admin

    # 2. Check workspace-level capability ceiling
    if action == "read":
        if not workspace_context.can(Permission.DOCUMENT_READ):
            return False
    elif action == "write":
        if not workspace_context.can(Permission.DOCUMENT_UPDATE):
            return False
    elif action == "delete":
        if not workspace_context.can(Permission.DOCUMENT_DELETE):
            return False

    # 3. Workspace Admin retains full access (self-lockout protection)
    if is_admin:
        return True

    # 4. Check document-level ACL
    doc_perm = resolve_document_permission(
        document,
        user_id=workspace_context.user_id,
        workspace_role=workspace_context.workspace_role,
        is_admin=is_admin,
    )
    if doc_perm is None:
        return False

    if action == "read":
        return True
    if action == "write":
        return doc_perm in (DocumentPermission.WRITE, DocumentPermission.ADMIN)
    if action == "delete":
        return doc_perm == DocumentPermission.ADMIN

    return False
