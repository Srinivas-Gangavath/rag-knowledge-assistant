"""Workspace management and workspace membership endpoints."""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.permissions import (
    ORGANIZATION_ROLE_PERMISSIONS,
    WORKSPACE_ROLE_PERMISSIONS,
    Permission,
    resolve_effective_permissions,
)
from app.core.request_context import extract_request_context
from app.db.models import (
    AuditEventType,
    AuditOutcome,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.repositories.membership_repository import MembershipRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.membership import (
    WorkspaceMemberAddRequest,
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
    WorkspaceMemberRoleUpdateRequest,
)
from app.schemas.workspace import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from app.services.audit_service import AuditLogService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return cleaned.strip("-") or "workspace"


def _get_user_workspace_permissions(
    db: Session,
    user_id: UUID,
    workspace: Workspace,
) -> frozenset[Permission]:
    """Resolve effective permissions of user inside target workspace."""
    mem_repo = MembershipRepository(db)
    ws_mem = mem_repo.get_workspace_membership(workspace.id, user_id)
    org_mem = mem_repo.get_organization_membership(workspace.organization_id, user_id)

    ws_role = ws_mem.role if ws_mem else None
    org_role = org_mem.role if org_mem else None

    if org_role == OrganizationRole.OWNER and ws_role is None:
        ws_role = WorkspaceRole.WORKSPACE_ADMIN

    return resolve_effective_permissions(org_role, ws_role)


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceListResponse:
    """List all workspaces accessible to the authenticated user with their effective role."""
    ws_repo = WorkspaceRepository(db)
    accessible = ws_repo.list_accessible_workspaces(user.id)
    return WorkspaceListResponse(
        workspaces=[
            WorkspaceResponse(
                id=ws.id,
                organization_id=ws.organization_id,
                name=ws.name,
                slug=ws.slug,
                is_archived=ws.is_archived,
                settings=ws.settings or {},
                created_at=ws.created_at,
                updated_at=ws.updated_at,
                role=role,
            )
            for ws, role in accessible
        ]
    )


@router.post("", response_model=WorkspaceResponse, status_code=201)
def create_workspace(
    payload: WorkspaceCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """Create a new workspace within an organization.
    
    Requires WORKSPACE_CREATE permission (Organization OWNER or ADMIN).
    """
    req_ctx = extract_request_context(request)
    mem_repo = MembershipRepository(db)
    org_mem = mem_repo.get_organization_membership(payload.organization_id, user.id)
    if org_mem is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )

    org_perms = ORGANIZATION_ROLE_PERMISSIONS.get(org_mem.role, set())
    if Permission.WORKSPACE_CREATE not in org_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: WORKSPACE_CREATE capability required",
        )

    slug = payload.slug or _slugify(payload.name)
    ws_repo = WorkspaceRepository(db)
    existing = ws_repo.get_by_slug(payload.organization_id, slug)
    if existing is not None:
        # Append unique suffix
        suffix = 1
        while ws_repo.get_by_slug(payload.organization_id, f"{slug}-{suffix}") is not None:
            suffix += 1
        slug = f"{slug}-{suffix}"

    workspace = Workspace(
        organization_id=payload.organization_id,
        name=payload.name,
        slug=slug,
        settings=payload.settings,
        is_archived=False,
    )
    ws_repo.add(workspace)

    # Assign creator as WORKSPACE_ADMIN
    ws_membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.WORKSPACE_ADMIN,
    )
    mem_repo.add_workspace_membership(ws_membership)

    AuditLogService.record_event(
        db,
        organization_id=payload.organization_id,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.WORKSPACE_CREATED,
        action="CREATE",
        outcome=AuditOutcome.SUCCESS,
        resource_type="workspace",
        resource_id=str(workspace.id),
        metadata={"name": workspace.name, "slug": workspace.slug},
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    db.commit()

    return WorkspaceResponse(
        id=workspace.id,
        organization_id=workspace.organization_id,
        name=workspace.name,
        slug=workspace.slug,
        is_archived=workspace.is_archived,
        settings=workspace.settings,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        role=WorkspaceRole.WORKSPACE_ADMIN.value,
    )


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """Get details of a specific workspace if the user has access."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    perms = _get_user_workspace_permissions(db, user.id, ws)
    if Permission.WORKSPACE_READ not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this workspace",
        )

    mem_repo = MembershipRepository(db)
    ws_mem = mem_repo.get_workspace_membership(ws.id, user.id)
    role = ws_mem.role.value if ws_mem else ("WORKSPACE_ADMIN" if Permission.WORKSPACE_MANAGE in perms else "VIEWER")

    return WorkspaceResponse(
        id=ws.id,
        organization_id=ws.organization_id,
        name=ws.name,
        slug=ws.slug,
        is_archived=ws.is_archived,
        settings=ws.settings or {},
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        role=role,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    """Update workspace name, slug, settings, or archive status.
    
    Requires WORKSPACE_MANAGE permission.
    """
    req_ctx = extract_request_context(request)
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    perms = _get_user_workspace_permissions(db, user.id, ws)
    if Permission.WORKSPACE_MANAGE not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: WORKSPACE_MANAGE capability required",
        )

    event_type = AuditEventType.WORKSPACE_UPDATED
    if payload.is_archived is not None and payload.is_archived != ws.is_archived:
        event_type = AuditEventType.WORKSPACE_ARCHIVED if payload.is_archived else AuditEventType.WORKSPACE_RESTORED

    if payload.name is not None:
        ws.name = payload.name
    if payload.slug is not None:
        ws_repo = WorkspaceRepository(db)
        existing = ws_repo.get_by_slug(ws.organization_id, payload.slug)
        if existing is not None and existing.id != ws.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slug '{payload.slug}' already exists in this organization",
            )
        ws.slug = payload.slug
    if payload.settings is not None:
        ws.settings = payload.settings
    if payload.is_archived is not None:
        ws.is_archived = payload.is_archived

    AuditLogService.record_event(
        db,
        organization_id=ws.organization_id,
        workspace_id=ws.id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=event_type,
        action="UPDATE",
        outcome=AuditOutcome.SUCCESS,
        resource_type="workspace",
        resource_id=str(ws.id),
        metadata={"is_archived": ws.is_archived, "name": ws.name},
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )

    db.commit()
    db.refresh(ws)

    mem_repo = MembershipRepository(db)
    ws_mem = mem_repo.get_workspace_membership(ws.id, user.id)
    role = ws_mem.role.value if ws_mem else "WORKSPACE_ADMIN"

    return WorkspaceResponse(
        id=ws.id,
        organization_id=ws.organization_id,
        name=ws.name,
        slug=ws.slug,
        is_archived=ws.is_archived,
        settings=ws.settings or {},
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        role=role,
    )


@router.delete("/{workspace_id}", status_code=204)
def archive_workspace(
    workspace_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Archive a workspace (safe lifecycle deletion).
    
    Requires WORKSPACE_DELETE permission.
    """
    req_ctx = extract_request_context(request)
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    perms = _get_user_workspace_permissions(db, user.id, ws)
    if Permission.WORKSPACE_DELETE not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: WORKSPACE_DELETE capability required",
        )

    ws.is_archived = True
    AuditLogService.record_event(
        db,
        organization_id=ws.organization_id,
        workspace_id=ws.id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.WORKSPACE_ARCHIVED,
        action="ARCHIVE",
        outcome=AuditOutcome.SUCCESS,
        resource_type="workspace",
        resource_id=str(ws.id),
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Workspace Memberships
# ---------------------------------------------------------------------------

@router.get("/{workspace_id}/members", response_model=WorkspaceMemberListResponse)
def list_workspace_members(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceMemberListResponse:
    """List members of a workspace.
    
    Requires WORKSPACE_READ permission.
    """
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    perms = _get_user_workspace_permissions(db, user.id, ws)
    if Permission.WORKSPACE_READ not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this workspace",
        )

    mem_repo = MembershipRepository(db)
    memberships = mem_repo.list_workspace_members(workspace_id)
    return WorkspaceMemberListResponse(
        members=[
            WorkspaceMemberResponse(
                id=m.id,
                user_id=m.user_id,
                workspace_id=m.workspace_id,
                email=m.user.email,
                full_name=m.user.full_name,
                role=m.role.value if hasattr(m.role, "value") else str(m.role),
                created_at=m.created_at,
            )
            for m in memberships
        ]
    )


@router.post("/{workspace_id}/members", response_model=WorkspaceMemberResponse, status_code=201)
def add_workspace_member(
    workspace_id: UUID,
    payload: WorkspaceMemberAddRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceMemberResponse:
    """Add an existing organization member to a workspace.
    
    Requires WORKSPACE_MEMBER_MANAGE permission.
    Enforces that target user must belong to the parent organization.
    """
    req_ctx = extract_request_context(request)
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    perms = _get_user_workspace_permissions(db, user.id, ws)
    if Permission.WORKSPACE_MEMBER_MANAGE not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: WORKSPACE_MEMBER_MANAGE capability required",
        )

    user_repo = UserRepository(db)
    target_user: User | None = None
    if payload.user_id:
        target_user = user_repo.get_by_id(payload.user_id)
    elif payload.email:
        target_user = user_repo.get_by_email(payload.email)

    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found")

    mem_repo = MembershipRepository(db)
    # Check parent organization membership (Cross-organization invariant)
    org_mem = mem_repo.get_organization_membership(ws.organization_id, target_user.id)
    if org_mem is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not belong to the organization. Add user to the organization first.",
        )

    # Check if already a workspace member
    existing_ws_mem = mem_repo.get_workspace_membership(workspace_id, target_user.id)
    if existing_ws_mem is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this workspace",
        )

    membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=payload.role,
    )
    mem_repo.add_workspace_membership(membership)

    AuditLogService.record_event(
        db,
        organization_id=ws.organization_id,
        workspace_id=workspace_id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.WORKSPACE_MEMBER_ADDED,
        action="MEMBER_ADDED",
        outcome=AuditOutcome.SUCCESS,
        resource_type="workspace_membership",
        resource_id=str(membership.id),
        metadata={
            "target_user_id": str(target_user.id),
            "role": payload.role.value if hasattr(payload.role, "value") else str(payload.role),
        },
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    db.commit()

    return WorkspaceMemberResponse(
        id=membership.id,
        user_id=target_user.id,
        workspace_id=workspace_id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=membership.role.value if hasattr(membership.role, "value") else str(membership.role),
        created_at=membership.created_at,
    )


@router.patch("/{workspace_id}/members/{target_user_id}", response_model=WorkspaceMemberResponse)
def update_workspace_member_role(
    workspace_id: UUID,
    target_user_id: UUID,
    payload: WorkspaceMemberRoleUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceMemberResponse:
    """Change workspace member role.
    
    Requires WORKSPACE_MEMBER_MANAGE permission.
    Users cannot escalate their own role.
    """
    req_ctx = extract_request_context(request)
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    perms = _get_user_workspace_permissions(db, user.id, ws)
    if Permission.WORKSPACE_MEMBER_MANAGE not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: WORKSPACE_MEMBER_MANAGE capability required",
        )

    # Self role change protection
    if target_user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot change your own workspace role",
        )

    mem_repo = MembershipRepository(db)
    membership = mem_repo.get_workspace_membership(workspace_id, target_user_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace membership not found")

    old_role = membership.role.value if hasattr(membership.role, "value") else str(membership.role)
    membership.role = payload.role

    AuditLogService.record_event(
        db,
        organization_id=ws.organization_id,
        workspace_id=workspace_id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.WORKSPACE_MEMBER_UPDATED,
        action="ROLE_CHANGED",
        outcome=AuditOutcome.SUCCESS,
        resource_type="workspace_membership",
        resource_id=str(membership.id),
        metadata={
            "target_user_id": str(target_user_id),
            "previous_role": old_role,
            "new_role": payload.role.value if hasattr(payload.role, "value") else str(payload.role),
        },
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    db.commit()

    return WorkspaceMemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        workspace_id=workspace_id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role.value if hasattr(membership.role, "value") else str(membership.role),
        created_at=membership.created_at,
    )


@router.delete("/{workspace_id}/members/{target_user_id}", status_code=204)
def remove_workspace_member(
    workspace_id: UUID,
    target_user_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Remove member from workspace.
    
    Requires WORKSPACE_MEMBER_MANAGE permission.
    """
    req_ctx = extract_request_context(request)
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    perms = _get_user_workspace_permissions(db, user.id, ws)
    if Permission.WORKSPACE_MEMBER_MANAGE not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: WORKSPACE_MEMBER_MANAGE capability required",
        )

    mem_repo = MembershipRepository(db)
    deleted = mem_repo.delete_workspace_membership(workspace_id, target_user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace membership not found")

    AuditLogService.record_event(
        db,
        organization_id=ws.organization_id,
        workspace_id=workspace_id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.WORKSPACE_MEMBER_REMOVED,
        action="MEMBER_REMOVED",
        outcome=AuditOutcome.SUCCESS,
        resource_type="workspace_membership",
        resource_id=str(target_user_id),
        metadata={"target_user_id": str(target_user_id)},
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    db.commit()
    return Response(status_code=204)

