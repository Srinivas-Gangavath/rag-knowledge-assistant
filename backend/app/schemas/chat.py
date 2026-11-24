from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.metadata import RetrievalFiltersRequest


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    conversation_id: UUID | None = None
    # Optional per-turn retrieval filters. Not authorization or tenancy.
    filters: RetrievalFiltersRequest | None = None

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A question is required.")
        return cleaned


class ChatSource(BaseModel):
    document_id: UUID
    filename: str
    page_number: int | None
    chunk_index: int
    similarity_score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    conversation_id: UUID
    message_id: UUID
    user_message_id: UUID
