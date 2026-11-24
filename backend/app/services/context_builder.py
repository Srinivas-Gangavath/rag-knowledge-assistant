"""Turn retrieved chunks into labeled, untrusted RAG context."""

from app.core.logging import get_logger
from app.services.retrieval import RetrievedChunk

logger = get_logger(__name__)


class ContextBuilder:
    def build(self, chunks: list[RetrievedChunk]) -> str:
        sections: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            page = "unknown" if chunk.page_number is None else str(chunk.page_number)
            sections.append(
                "\n".join(
                    [
                        f"[Source {index}]",
                        f"Document: {chunk.filename}",
                        f"Page: {page}",
                        f"Chunk: {chunk.chunk_index}",
                        "",
                        chunk.content.strip(),
                    ]
                )
            )
        context = "\n\n".join(sections)
        logger.info(
            "AUGMENTATION built context (sources=%s, characters=%s)",
            len(chunks),
            len(context),
        )
        return context
