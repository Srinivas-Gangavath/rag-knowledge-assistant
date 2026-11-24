from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_conversation_service
from app.core.permissions import Permission
from app.schemas.chat import ChatRequest, ChatResponse, ChatSource
from app.services.conversation_service import ConversationService
from app.services.rag import RagSource

router = APIRouter(prefix="/chat", tags=["chat"])

STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sources_to_schema(sources: list[RagSource]) -> list[ChatSource]:
    return [
        ChatSource(
            document_id=source.document_id,
            filename=source.filename,
            page_number=source.page_number,
            chunk_index=source.chunk_index,
            similarity_score=source.similarity_score,
        )
        for source in sources
    ]


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    service.require_permission(Permission.KNOWLEDGE_QUERY)
    result = service.ask(
        payload.question,
        conversation_id=payload.conversation_id,
        filters=None if payload.filters is None else payload.filters.to_domain(),
    )
    return ChatResponse(
        answer=result.answer,
        sources=sources_to_schema(result.sources),
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        user_message_id=result.user_message_id,
    )


@router.post("/stream")
def chat_stream(
    payload: ChatRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> StreamingResponse:
    service.require_permission(Permission.KNOWLEDGE_QUERY)
    prepared = service.prepare_turn(
        payload.question,
        conversation_id=payload.conversation_id,
        filters=None if payload.filters is None else payload.filters.to_domain(),
    )
    return StreamingResponse(
        service.iter_chat_events(prepared),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
