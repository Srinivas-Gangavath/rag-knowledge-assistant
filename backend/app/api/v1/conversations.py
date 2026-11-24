from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_conversation_service
from app.core.permissions import Permission
from app.db.database import get_db
from app.schemas.conversation import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummary,
    MessageResponse,
)
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationDetailResponse, status_code=201)
def create_conversation(
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailResponse:
    service.require_permission(Permission.CONVERSATION_CREATE)
    conversation = service.create_conversation()
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[],
    )


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationListResponse:
    service.require_permission(Permission.CONVERSATION_READ)
    conversations = service.list_conversations()
    return ConversationListResponse(
        conversations=[ConversationSummary.model_validate(item) for item in conversations]
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailResponse:
    service.require_permission(Permission.CONVERSATION_READ)
    conversation = service.get_conversation(conversation_id)
    messages = service.list_messages(conversation_id)
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(item) for item in messages],
    )


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    service: ConversationService = Depends(get_conversation_service),
) -> Response:
    service.require_permission(Permission.CONVERSATION_DELETE)
    service.delete_conversation(conversation_id)
    return Response(status_code=204)
