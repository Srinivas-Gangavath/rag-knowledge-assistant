"""Organization membership management endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.permissions import ORGANIZATION_ROLE_PERMISSIONS, Permission
from app.core.request_context import extract_request_context
from app.db.models import AuditEventType, AuditOutcome, Organization, OrganizationMembership, OrganizationRole, User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.user_repository import UserRepository
from app.schemas.membership import (
    OrgMemberAddRequest,
    OrgMemberListResponse,
    OrgMemberResponse,
    OrgMemberRoleUpdateRequest,
)
from app.services.audit_service import AuditLogService

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _get_caller_org_membership(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> OrganizationMembership:
    mem_repo = MembershipRepository(db)
    membership = mem_repo.get_organization_membership(organization_id, user_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )
    return membership


@router.get("/{organization_id}/members", response_model=OrgMemberListResponse)
def list_organization_members(
    organization_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgMemberListResponse:
    """List members of an organization.
    
    Requires ORGANIZATION_READ permission (any organization member).
    """
    _get_caller_org_membership(db, organization_id, user.id)

    mem_repo = MembershipRepository(db)
    memberships = mem_repo.list_organization_members(organization_id)
    return OrgMemberListResponse(
        members=[
            OrgMemberResponse(
                id=m.id,
                user_id=m.user_id,
                organization_id=m.organization_id,
                email=m.user.email,
                full_name=m.user.full_name,
                role=m.role.value if hasattr(m.role, "value") else str(m.role),
                created_at=m.created_at,
            )
            for m in memberships
        ]
    )


@router.post("/{organization_id}/members", response_model=OrgMemberResponse, status_code=201)
def add_organization_member(
    organization_id: UUID,
    payload: OrgMemberAddRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgMemberResponse:
    """Add an existing user to the organization.
    
    Requires ORGANIZATION_MEMBER_MANAGE permission (OWNER or ADMIN).
    Only an OWNER can add someone as an OWNER.
    """
    req_ctx = extract_request_context(request)
    caller_mem = _get_caller_org_membership(db, organization_id, user.id)
    caller_perms = ORGANIZATION_ROLE_PERMISSIONS.get(caller_mem.role, set())
    if Permission.ORGANIZATION_MEMBER_MANAGE not in caller_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: ORGANIZATION_MEMBER_MANAGE capability required",
        )

    # Only OWNER can grant OWNER role
    if payload.role == OrganizationRole.OWNER and caller_mem.role != OrganizationRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners can grant the OWNER role",
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
    existing_mem = mem_repo.get_organization_membership(organization_id, target_user.id)
    if existing_mem is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this organization",
        )

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=target_user.id,
        role=payload.role,
    )
    mem_repo.add_organization_membership(membership)

    AuditLogService.record_event(
        db,
        organization_id=organization_id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.MEMBER_ADDED,
        action="MEMBER_ADDED",
        outcome=AuditOutcome.SUCCESS,
        resource_type="organization_membership",
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

    return OrgMemberResponse(
        id=membership.id,
        user_id=target_user.id,
        organization_id=organization_id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=membership.role.value if hasattr(membership.role, "value") else str(membership.role),
        created_at=membership.created_at,
    )


@router.patch("/{organization_id}/members/{target_user_id}", response_model=OrgMemberResponse)
def update_organization_member_role(
    organization_id: UUID,
    target_user_id: UUID,
    payload: OrgMemberRoleUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgMemberResponse:
    """Change member role in organization.
    
    Requires ORGANIZATION_MEMBER_MANAGE permission.
    Users cannot change their own role.
    Only OWNER can grant or revoke the OWNER role.
    Cannot demote the last OWNER.
    """
    req_ctx = extract_request_context(request)
    caller_mem = _get_caller_org_membership(db, organization_id, user.id)
    caller_perms = ORGANIZATION_ROLE_PERMISSIONS.get(caller_mem.role, set())
    if Permission.ORGANIZATION_MEMBER_MANAGE not in caller_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: ORGANIZATION_MEMBER_MANAGE capability required",
        )

    # Self role change protection
    if target_user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot modify your own organization role",
        )

    mem_repo = MembershipRepository(db)
    target_mem = mem_repo.get_organization_membership(organization_id, target_user_id)
    if target_mem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization membership not found")

    # If promoting to OWNER or modifying an existing OWNER, caller must be OWNER
    if (payload.role == OrganizationRole.OWNER or target_mem.role == OrganizationRole.OWNER) and caller_mem.role != OrganizationRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners can modify owner roles",
        )

    # Demoting last OWNER check
    if target_mem.role == OrganizationRole.OWNER and payload.role != OrganizationRole.OWNER:
        owner_count = mem_repo.count_organization_owners(organization_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last organization owner",
            )

    old_role = target_mem.role.value if hasattr(target_mem.role, "value") else str(target_mem.role)
    target_mem.role = payload.role

    AuditLogService.record_event(
        db,
        organization_id=organization_id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.MEMBER_ROLE_CHANGED,
        action="ROLE_CHANGED",
        outcome=AuditOutcome.SUCCESS,
        resource_type="organization_membership",
        resource_id=str(target_mem.id),
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

    return OrgMemberResponse(
        id=target_mem.id,
        user_id=target_mem.user_id,
        organization_id=organization_id,
        email=target_mem.user.email,
        full_name=target_mem.user.full_name,
        role=target_mem.role.value if hasattr(target_mem.role, "value") else str(target_mem.role),
        created_at=target_mem.created_at,
    )


@router.delete("/{organization_id}/members/{target_user_id}", status_code=204)
def remove_organization_member(
    organization_id: UUID,
    target_user_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Remove member from organization.
    
    Requires ORGANIZATION_MEMBER_MANAGE permission.
    Cannot remove last OWNER.
    Non-owners cannot remove an OWNER.
    """
    req_ctx = extract_request_context(request)
    caller_mem = _get_caller_org_membership(db, organization_id, user.id)
    caller_perms = ORGANIZATION_ROLE_PERMISSIONS.get(caller_mem.role, set())
    if Permission.ORGANIZATION_MEMBER_MANAGE not in caller_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: ORGANIZATION_MEMBER_MANAGE capability required",
        )

    mem_repo = MembershipRepository(db)
    target_mem = mem_repo.get_organization_membership(organization_id, target_user_id)
    if target_mem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization membership not found")

    if target_mem.role == OrganizationRole.OWNER:
        if caller_mem.role != OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization owners can remove an owner",
            )
        owner_count = mem_repo.count_organization_owners(organization_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last organization owner",
            )

    mem_repo.delete_organization_membership(organization_id, target_user_id)

    AuditLogService.record_event(
        db,
        organization_id=organization_id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.MEMBER_REMOVED,
        action="MEMBER_REMOVED",
        outcome=AuditOutcome.SUCCESS,
        resource_type="organization_membership",
        resource_id=str(target_user_id),
        metadata={"target_user_id": str(target_user_id)},
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    db.commit()
    return Response(status_code=204)

