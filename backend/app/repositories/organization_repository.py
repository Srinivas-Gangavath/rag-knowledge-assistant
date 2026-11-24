"""Database access for Organization records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Organization


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, organization: Organization) -> Organization:
        self._session.add(organization)
        self._session.flush()
        return organization

    def get_by_id(self, organization_id: UUID) -> Organization | None:
        return self._session.get(Organization, organization_id)

    def get_by_slug(self, slug: str) -> Organization | None:
        statement = select(Organization).where(Organization.slug == slug)
        return self._session.scalars(statement).first()

    def list_all(self) -> list[Organization]:
        statement = select(Organization).order_by(Organization.created_at.asc())
        return list(self._session.scalars(statement))

    def delete(self, organization_id: UUID) -> bool:
        organization = self.get_by_id(organization_id)
        if organization is None:
            return False
        self._session.delete(organization)
        self._session.flush()
        return True
