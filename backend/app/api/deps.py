"""Authentication and workspace context dependency injection."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.permissions import (
    ORGANIZATION_ROLE_PERMISSIONS,
    Permission,
    resolve_effective_permissions,
)
from app.core.security import decode_access_token
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.db.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.services.conversation_service import ConversationService
from app.services.document_service import DocumentService


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Resolve and validate the authenticated user from the Bearer access token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    claims = decode_access_token(token)
    if not claims or "sub" not in claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(claims["sub"])
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject claim in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_workspace_context(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceContext:
    """Resolve and validate the active workspace for the authenticated user.

    Ensures the user holds a valid WorkspaceMembership or organization OWNER role.
    Rejects arbitrary or unpermitted workspace requests with 403 Forbidden.
    """
    # Enforce strict tenancy on this session for writes
    db.info["strict_tenancy"] = True

    requested_ws_id_header = request.headers.get("X-Workspace-Id")
    ws_role: WorkspaceRole | None = None
    org_role: OrganizationRole | None = None
    workspace: Workspace | None = None

    if requested_ws_id_header:
        try:
            target_ws_id = UUID(requested_ws_id_header.strip())
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Workspace-Id header format",
            )

        membership_stmt = (
            select(WorkspaceMembership)
            .options(
                joinedload(WorkspaceMembership.workspace).joinedload(Workspace.organization)
            )
            .where(
                WorkspaceMembership.workspace_id == target_ws_id,
                WorkspaceMembership.user_id == user.id,
            )
        )
        membership = db.scalars(membership_stmt).first()
        if membership is not None:
            workspace = membership.workspace
            ws_role = membership.role
            org_mem = db.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == workspace.organization_id,
                    OrganizationMembership.user_id == user.id,
                )
            ).first()
            if org_mem:
                org_role = org_mem.role
        else:
            target_workspace = db.get(Workspace, target_ws_id)
            if target_workspace is not None:
                org_mem = db.scalars(
                    select(OrganizationMembership)
                    .options(joinedload(OrganizationMembership.organization))
                    .where(
                        OrganizationMembership.organization_id == target_workspace.organization_id,
                        OrganizationMembership.user_id == user.id,
                    )
                ).first()
                if org_mem and org_mem.role == OrganizationRole.OWNER:
                    workspace = target_workspace
                    org_role = OrganizationRole.OWNER
                    ws_role = WorkspaceRole.WORKSPACE_ADMIN
                else:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have access to the requested workspace",
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to the requested workspace",
                )
    else:
        # Resolve user's primary/first workspace membership
        membership_stmt = (
            select(WorkspaceMembership)
            .options(
                joinedload(WorkspaceMembership.workspace).joinedload(Workspace.organization)
            )
            .where(WorkspaceMembership.user_id == user.id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
        membership = db.scalars(membership_stmt).first()
        if membership is not None:
            workspace = membership.workspace
            ws_role = membership.role
            org_mem = db.scalars(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == workspace.organization_id,
                    OrganizationMembership.user_id == user.id,
                )
            ).first()
            if org_mem:
                org_role = org_mem.role
        else:
            org_owner_stmt = (
                select(OrganizationMembership)
                .where(
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.role == OrganizationRole.OWNER,
                )
                .order_by(OrganizationMembership.created_at.asc())
            )
            org_owner_mem = db.scalars(org_owner_stmt).first()
            if org_owner_mem:
                ws_stmt = (
                    select(Workspace)
                    .options(joinedload(Workspace.organization))
                    .where(Workspace.organization_id == org_owner_mem.organization_id)
                    .order_by(Workspace.created_at.asc())
                )
                workspace = db.scalars(ws_stmt).first()
                if workspace:
                    org_role = OrganizationRole.OWNER
                    ws_role = WorkspaceRole.WORKSPACE_ADMIN

        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a member of any workspace",
            )

    org = workspace.organization
    effective_perms = resolve_effective_permissions(org_role, ws_role)

    return WorkspaceContext(
        workspace_id=workspace.id,
        organization_id=workspace.organization_id,
        workspace_slug=workspace.slug,
        organization_slug=org.slug if org else "default",
        user_id=user.id,
        workspace_role=ws_role,
        organization_role=org_role,
        permissions=effective_perms,
    )


def require_permission(permission: Permission):
    """Dependency factory enforcing workspace-level capability."""

    def dependency(
        ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    ) -> WorkspaceContext:
        if not ws_ctx.can(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value} capability required",
            )
        return ws_ctx

    return dependency


def require_org_permission(permission: Permission):
    """Dependency factory enforcing organization-level capability."""

    def dependency(
        organization_id: UUID,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> OrganizationMembership:
        membership = db.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user.id,
            )
        ).first()
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this organization",
            )

        org_perms = ORGANIZATION_ROLE_PERMISSIONS.get(membership.role, set())
        if permission not in org_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value} capability required for organization",
            )
        return membership

    return dependency


def get_document_service(
    db: Session = Depends(get_db),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
) -> DocumentService:
    """Provide DocumentService strictly scoped to the authenticated workspace."""
    return DocumentService(
        session=db,
        workspace_id=ws_ctx.workspace_id,
        workspace_context=ws_ctx,
    )


from app.core.request_context import extract_request_context


def get_conversation_service(
    request: Request = None,
    db: Session = Depends(get_db),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
) -> ConversationService:
    """Provide ConversationService strictly scoped to the authenticated workspace and user."""
    is_admin = ws_ctx.can(Permission.CONVERSATION_MANAGE)
    req_ctx = extract_request_context(request) if request else None
    return ConversationService(
        session=db,
        workspace_id=ws_ctx.workspace_id,
        user_id=ws_ctx.user_id,
        is_admin=is_admin,
        workspace_context=ws_ctx,
        request_context=req_ctx,
    )
