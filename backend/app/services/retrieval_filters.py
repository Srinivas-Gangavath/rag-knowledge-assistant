"""Internal retrieval filter model.

Filters are AND-ed in PostgreSQL before cosine ranking and Top-K.
They are retrieval controls, not authorization or tenancy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class RetrievalFilters:
    document_ids: list[UUID] | None = None
    category: str | None = None
    source: str | None = None
    tags: list[str] | None = None
    uploaded_from: datetime | None = None
    uploaded_to: datetime | None = None
    page_from: int | None = None
    page_to: int | None = None

    def has_empty_document_ids(self) -> bool:
        return self.document_ids is not None and len(self.document_ids) == 0


def coalesce_filters(
    filters: RetrievalFilters | None = None,
    document_ids: list[UUID] | None = None,
) -> RetrievalFilters | None:
    """Merge an optional filter object with the legacy document_ids= argument.

    Evaluation isolation still uses document_ids=. An empty list remains an
    empty candidate set (no rows), not "search everything".
    """
    if filters is None:
        if document_ids is None:
            return None
        return RetrievalFilters(document_ids=list(document_ids))
    if document_ids is None or filters.document_ids is not None:
        return filters
    return RetrievalFilters(
        document_ids=list(document_ids),
        category=filters.category,
        source=filters.source,
        tags=None if filters.tags is None else list(filters.tags),
        uploaded_from=filters.uploaded_from,
        uploaded_to=filters.uploaded_to,
        page_from=filters.page_from,
        page_to=filters.page_to,
    )
