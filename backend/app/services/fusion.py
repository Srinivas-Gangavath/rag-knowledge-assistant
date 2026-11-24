"""Reciprocal Rank Fusion for dense + lexical candidate lists.

RRF uses ranks only. Cosine similarity and ts_rank_cd are not mixed as scores.
This is not BM25 and not a reranker.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.retrieval import RetrievedChunk


def rrf_fuse(
    dense: list[RetrievedChunk],
    lexical: list[RetrievedChunk],
    *,
    rrf_k: int,
    top_k: int,
) -> list[RetrievedChunk]:
    """Fuse two 1-based ranked lists. Missing branch contributes nothing."""
    if top_k <= 0:
        return []
    dense_rank = {chunk.chunk_id: index for index, chunk in enumerate(dense, start=1)}
    lexical_rank = {chunk.chunk_id: index for index, chunk in enumerate(lexical, start=1)}

    by_id: dict = {}
    for chunk in dense:
        by_id[chunk.chunk_id] = chunk
    lexical_by_id = {chunk.chunk_id: chunk for chunk in lexical}
    for chunk in lexical:
        if chunk.chunk_id not in by_id:
            by_id[chunk.chunk_id] = chunk

    fused: list[RetrievedChunk] = []
    for chunk_id, chunk in by_id.items():
        score = 0.0
        dense_position = dense_rank.get(chunk_id)
        lexical_position = lexical_rank.get(chunk_id)
        if dense_position is not None:
            score += 1.0 / (rrf_k + dense_position)
        if lexical_position is not None:
            score += 1.0 / (rrf_k + lexical_position)
        lexical_chunk = lexical_by_id.get(chunk_id)
        fused.append(
            replace(
                chunk,
                dense_rank=dense_position,
                lexical_rank=lexical_position,
                rrf_score=score,
                lexical_score=(
                    None if lexical_chunk is None else lexical_chunk.lexical_score
                ),
                retrieval_mode="hybrid",
            )
        )

    fused.sort(
        key=lambda item: (
            -(item.rrf_score or 0.0),
            -item.similarity_score,
            str(item.chunk_id),
        )
    )
    return fused[:top_k]
