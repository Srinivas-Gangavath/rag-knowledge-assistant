"""Chunking strategies: fixed word-window (V1 baseline) and recursive packing.

Downstream ingestion depends only on TextChunk. Strategies must not leak
implementation-specific fields into embeddings or persistence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.core.logging import get_logger
from app.services.pdf_parser import PageText

logger = get_logger(__name__)

FIXED_WORD_WINDOW = "fixed_word_window"
RECURSIVE = "recursive"
SEMANTIC = "semantic"
SUPPORTED_CHUNKING_STRATEGIES = (FIXED_WORD_WINDOW, RECURSIVE)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    page_number: int
    content: str


class ChunkingStrategy(Protocol):
    """Common contract: page text in, ordered TextChunk list out."""

    name: str

    @property
    def chunk_size(self) -> int: ...

    @property
    def chunk_overlap(self) -> int: ...

    def chunk(self, pages: list[PageText]) -> list[TextChunk]: ...


def validate_chunk_window(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be 0 or greater.")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size.")


def word_window_contents(
    words: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Exact V1 sliding-window contents. Words are never split."""
    if not words:
        return []
    step = chunk_size - chunk_overlap
    contents: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        content = " ".join(words[start:end]).strip()
        if not content:
            if end == len(words):
                break
            start += step
            continue
        contents.append(content)
        if end == len(words):
            break
        start += step
    return contents


def normalize_chunking_strategy(value: str) -> str:
    """Return a supported strategy name or raise ValueError."""
    normalized = (value or "").strip().lower()
    if normalized == SEMANTIC:
        raise ValueError(
            "CHUNKING_STRATEGY 'semantic' is not implemented. "
            "Use 'fixed_word_window' or 'recursive'."
        )
    if normalized not in SUPPORTED_CHUNKING_STRATEGIES:
        raise ValueError(
            "CHUNKING_STRATEGY must be one of "
            f"{SUPPORTED_CHUNKING_STRATEGIES}, got {value!r}."
        )
    return normalized


def create_chunker(
    settings=None,
    *,
    strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> ChunkingStrategy:
    """Build the configured chunking strategy.

    Unknown names and 'semantic' fail clearly. They never fall back.
    """
    if settings is None and (
        strategy is None or chunk_size is None or chunk_overlap is None
    ):
        from app.core.config import get_settings

        settings = get_settings()
    name = normalize_chunking_strategy(
        strategy if strategy is not None else settings.chunking_strategy
    )
    size = settings.chunk_size if chunk_size is None else chunk_size
    overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
    if name == FIXED_WORD_WINDOW:
        return Chunker(size, overlap)
    return RecursiveChunker(size, overlap)


class FixedWordWindowChunker:
    """Deterministic word-window chunking with configured overlap.

    Page boundaries are preserved so later citation can use page_number.
    Words are never split in the middle.
    """

    name = FIXED_WORD_WINDOW

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        validate_chunk_window(chunk_size, chunk_overlap)
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self._chunk_overlap

    def chunk(self, pages: list[PageText]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        chunk_index = 0
        for page in pages:
            words = page.text.split()
            for content in word_window_contents(
                words, self._chunk_size, self._chunk_overlap
            ):
                chunks.append(
                    TextChunk(
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        content=content,
                    )
                )
                chunk_index += 1
        logger.info(
            "Chunking completed (strategy=%s, chunks=%s)",
            self.name,
            len(chunks),
        )
        return chunks


class Chunker(FixedWordWindowChunker):
    """Backward-compatible name for the fixed word-window strategy."""


class RecursiveChunker:
    """Page-bounded recursive packing: paragraphs, then sentences, then words.

    Does not invent PDF headings, tables, or layout. Extracted text only
    provides newlines and punctuation, so those are the only boundaries used.
    """

    name = RECURSIVE

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        validate_chunk_window(chunk_size, chunk_overlap)
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self._chunk_overlap

    def chunk(self, pages: list[PageText]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        chunk_index = 0
        for page in pages:
            for content in self._chunk_page(page.text):
                chunks.append(
                    TextChunk(
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        content=content,
                    )
                )
                chunk_index += 1
        logger.info(
            "Chunking completed (strategy=%s, chunks=%s)",
            self.name,
            len(chunks),
        )
        return chunks

    def _chunk_page(self, text: str) -> list[str]:
        paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT.split(text) if part.strip()]
        if not paragraphs:
            words = text.split()
            if not words:
                return []
            if len(words) <= self._chunk_size:
                return [" ".join(words)]
            return word_window_contents(words, self._chunk_size, self._chunk_overlap)

        output: list[str] = []
        pending: list[str] = []

        def flush_pending() -> None:
            if pending:
                output.extend(self._pack_units(pending))
                pending.clear()

        for paragraph in paragraphs:
            words = paragraph.split()
            if not words:
                continue
            if len(words) <= self._chunk_size:
                pending.append(" ".join(words))
                continue
            for sentence in _split_sentences(paragraph):
                sentence_words = sentence.split()
                if not sentence_words:
                    continue
                if len(sentence_words) <= self._chunk_size:
                    pending.append(" ".join(sentence_words))
                else:
                    flush_pending()
                    output.extend(
                        word_window_contents(
                            sentence_words,
                            self._chunk_size,
                            self._chunk_overlap,
                        )
                    )
        flush_pending()
        return output

    def _pack_units(self, units: list[str]) -> list[str]:
        packed: list[list[str]] = []
        current: list[str] = []
        for unit in units:
            unit_words = unit.split()
            if not unit_words:
                continue
            if not current:
                current = list(unit_words)
                continue
            if len(current) + len(unit_words) <= self._chunk_size:
                current.extend(unit_words)
                continue
            packed.append(current)
            current = self._next_chunk_words(current, unit_words, packed[-1])
        if current and (not packed or current != packed[-1]):
            packed.append(current)
        return [" ".join(words) for words in packed if words]

    def _next_chunk_words(
        self,
        previous: list[str],
        new_words: list[str],
        emitted: list[str],
    ) -> list[str]:
        """Overlap up to chunk_overlap words, always including new content."""
        overlap = self._chunk_overlap
        prefix = previous[-overlap:] if overlap else []
        room = self._chunk_size - len(new_words)
        if room <= 0:
            prefix = []
        elif len(prefix) > room:
            prefix = prefix[-room:]
        nxt = prefix + new_words
        if nxt == emitted:
            nxt = list(new_words)
        return nxt


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    return parts or [text.strip()]
