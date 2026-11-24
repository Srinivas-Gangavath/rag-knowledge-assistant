"""Authentication and membership endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.database import get_db
from app.core.request_context import extract_request_context
from app.db.models import (
    AuditEventType,
    AuditOutcome,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    RefreshToken,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TokenRefreshResponse,
    UserDetailResponse,
    UserOrgResponse,
    UserResponse,
    UserWorkspaceResponse,
)
from app.services.audit_service import AuditLogService

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw_token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=settings.auth_cookie_path,
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path=settings.auth_cookie_path,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """Register a new user, create an initial organization and workspace, and issue credentials."""
    existing_user = db.scalars(select(User).where(User.email == payload.email)).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists.",
        )

    req_ctx = extract_request_context(request)

    # 1. Create user
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        is_active=True,
    )
    db.add(user)
    db.flush()

    # 2. Create personal organization
    org = Organization(
        name=f"{user.full_name}'s Organization",
        slug=f"org-{user.id.hex[:8]}",
    )
    db.add(org)
    db.flush()

    # 3. Create default workspace
    workspace = Workspace(
        organization_id=org.id,
        name="Default Workspace",
        slug="default",
        settings={},
    )
    db.add(workspace)
    db.flush()

    # 4. Create memberships
    org_membership = OrganizationMembership(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.OWNER,
    )
    ws_membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.WORKSPACE_ADMIN,
    )
    db.add(org_membership)
    db.add(ws_membership)

    # 5. Record initial audit events
    AuditLogService.record_event(
        db,
        organization_id=org.id,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.MEMBER_ADDED,
        action="MEMBER_ADDED",
        outcome=AuditOutcome.SUCCESS,
        resource_type="organization_membership",
        resource_id=str(user.id),
        metadata={"role": "OWNER"},
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    AuditLogService.record_event(
        db,
        organization_id=org.id,
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

    # 6. Issue refresh token
    settings = get_settings()
    raw_refresh = generate_refresh_token()
    token_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(token_record)
    db.commit()

    _set_refresh_cookie(response, raw_refresh)
    access_token = create_access_token(user.id, user.email)

    logger.info("User registered successfully (user_id=%s, email=%s)", user.id, user.email)
    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """Authenticate user with email and password, issuing access and refresh credentials."""
    req_ctx = extract_request_context(request)
    user = db.scalars(select(User).where(User.email == payload.email)).first()

    if user is None or not user.is_active or not verify_password(payload.password, user.hashed_password):
        # Resolve org for failure audit log
        org_id = None
        if user is not None:
            org_mem = db.scalars(
                select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
            ).first()
            if org_mem:
                org_id = org_mem.organization_id
        if org_id is None:
            default_org = db.scalars(select(Organization).order_by(Organization.created_at.asc())).first()
            if default_org:
                org_id = default_org.id

        if org_id is not None:
            AuditLogService.record_event(
                db,
                organization_id=org_id,
                actor_email=payload.email,
                event_type=AuditEventType.LOGIN_FAILURE,
                action="LOGIN",
                outcome=AuditOutcome.FAILURE,
                metadata={"reason": "invalid_credentials"},
                ip_address=req_ctx.ip_address,
                user_agent=req_ctx.user_agent,
                request_id=req_ctx.request_id,
                autocommit=True,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Resolve user's primary organization
    org_mem = db.scalars(
        select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
    ).first()
    org_id = org_mem.organization_id if org_mem else None
    if org_id is None:
        default_org = db.scalars(select(Organization).order_by(Organization.created_at.asc())).first()
        org_id = default_org.id if default_org else user.id

    settings = get_settings()
    raw_refresh = generate_refresh_token()
    token_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(token_record)

    AuditLogService.record_event(
        db,
        organization_id=org_id,
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.LOGIN_SUCCESS,
        action="LOGIN",
        outcome=AuditOutcome.SUCCESS,
        metadata={"auth_method": "password"},
        ip_address=req_ctx.ip_address,
        user_agent=req_ctx.user_agent,
        request_id=req_ctx.request_id,
    )
    db.commit()

    _set_refresh_cookie(response, raw_refresh)
    access_token = create_access_token(user.id, user.email)

    logger.info("User logged in successfully (user_id=%s)", user.id)
    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenRefreshResponse:
    """Rotate the refresh token and issue a new access token."""
    req_ctx = extract_request_context(request)
    settings = get_settings()
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie missing.",
        )

    token_hash = hash_token(raw_token)
    token_record = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).first()

    now = datetime.now(timezone.utc)
    if (
        token_record is None
        or token_record.revoked_at is not None
        or token_record.expires_at <= now
    ):
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked refresh token.",
        )

    # Revoke old token
    token_record.revoked_at = now
    token_record.last_used_at = now

    user = db.get(User, token_record.user_id)
    if user is None or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found.",
        )

    # Rotate: issue new refresh token
    new_raw_refresh = generate_refresh_token()
    new_token_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_raw_refresh),
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(new_token_record)

    org_mem = db.scalars(
        select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
    ).first()
    org_id = org_mem.organization_id if org_mem else None
    if org_id is not None:
        AuditLogService.record_event(
            db,
            organization_id=org_id,
            actor_user_id=user.id,
            actor_email=user.email,
            event_type=AuditEventType.TOKEN_REFRESH,
            action="TOKEN_REFRESH",
            outcome=AuditOutcome.SUCCESS,
            ip_address=req_ctx.ip_address,
            user_agent=req_ctx.user_agent,
            request_id=req_ctx.request_id,
        )

    db.commit()

    _set_refresh_cookie(response, new_raw_refresh)
    new_access_token = create_access_token(user.id, user.email)

    return TokenRefreshResponse(
        access_token=new_access_token,
        token_type="bearer",
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Response:
    """Revoke the current refresh session and clear the cookie."""
    req_ctx = extract_request_context(request)
    settings = get_settings()
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if raw_token:
        token_hash = hash_token(raw_token)
        token_record = db.scalars(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).first()
        if token_record and token_record.revoked_at is None:
            token_record.revoked_at = datetime.now(timezone.utc)
            user = db.get(User, token_record.user_id)
            if user:
                org_mem = db.scalars(
                    select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
                ).first()
                org_id = org_mem.organization_id if org_mem else None
                if org_id:
                    AuditLogService.record_event(
                        db,
                        organization_id=org_id,
                        actor_user_id=user.id,
                        actor_email=user.email,
                        event_type=AuditEventType.LOGOUT,
                        action="LOGOUT",
                        outcome=AuditOutcome.SUCCESS,
                        ip_address=req_ctx.ip_address,
                        user_agent=req_ctx.user_agent,
                        request_id=req_ctx.request_id,
                    )
            db.commit()

    _clear_refresh_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/me", response_model=UserDetailResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserDetailResponse:
    """Return profile, organization memberships, and workspace memberships for the authenticated user."""
    org_memberships = db.scalars(
        select(OrganizationMembership)
        .options(joinedload(OrganizationMembership.organization))
        .where(OrganizationMembership.user_id == current_user.id)
        .order_by(OrganizationMembership.created_at.asc())
    ).all()

    ws_memberships = db.scalars(
        select(WorkspaceMembership)
        .options(joinedload(WorkspaceMembership.workspace))
        .where(WorkspaceMembership.user_id == current_user.id)
        .order_by(WorkspaceMembership.created_at.asc())
    ).all()

    orgs = [
        UserOrgResponse(
            id=m.organization.id,
            name=m.organization.name,
            slug=m.organization.slug,
            role=m.role.value if hasattr(m.role, "value") else str(m.role),
        )
        for m in org_memberships
        if m.organization is not None
    ]

    workspaces = [
        UserWorkspaceResponse(
            id=m.workspace.id,
            organization_id=m.workspace.organization_id,
            name=m.workspace.name,
            slug=m.workspace.slug,
            role=m.role.value if hasattr(m.role, "value") else str(m.role),
        )
        for m in ws_memberships
        if m.workspace is not None
    ]

    return UserDetailResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        organizations=orgs,
        workspaces=workspaces,
    )
