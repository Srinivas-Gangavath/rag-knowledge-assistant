from uuid import uuid4

import pytest

from app.services.fusion import rrf_fuse
from app.services.retrieval import RetrievedChunk


def _chunk(name: str, score: float, chunk_id=None) -> RetrievedChunk:
    document_id = uuid4()
    return RetrievedChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id,
        content=name,
        page_number=1,
        chunk_index=0,
        filename=f"{name}.pdf",
        similarity_score=score,
        metadata={},
        retrieval_mode="dense",
    )


def test_rrf_dense_only_chunk():
    dense = [_chunk("dense-only", 0.9)]
    fused = rrf_fuse(dense, [], rrf_k=60, top_k=5)
    assert len(fused) == 1
    assert fused[0].content == "dense-only"
    assert fused[0].dense_rank == 1
    assert fused[0].lexical_rank is None
    assert fused[0].rrf_score == 1 / 61
    assert fused[0].retrieval_mode == "hybrid"
    assert fused[0].similarity_score == 0.9


def test_rrf_lexical_only_chunk():
    lexical = [_chunk("lex-only", 0.2)]
    fused = rrf_fuse([], lexical, rrf_k=60, top_k=5)
    assert fused[0].content == "lex-only"
    assert fused[0].dense_rank is None
    assert fused[0].lexical_rank == 1
    assert fused[0].rrf_score == 1 / 61


def test_rrf_same_chunk_in_both_is_deduplicated():
    chunk_id = uuid4()
    dense = [_chunk("shared", 0.95, chunk_id=chunk_id)]
    lexical = [_chunk("shared-copy", 0.4, chunk_id=chunk_id)]
    fused = rrf_fuse(dense, lexical, rrf_k=60, top_k=5)
    assert len(fused) == 1
    assert fused[0].chunk_id == chunk_id
    assert fused[0].content == "shared"
    assert fused[0].similarity_score == 0.95
    assert fused[0].dense_rank == 1
    assert fused[0].lexical_rank == 1
    assert fused[0].rrf_score == pytest.approx(1 / 61 + 1 / 61)


def test_rrf_rank_contributions_example():
    dense_id = uuid4()
    other_dense = uuid4()
    extra_lex = [uuid4(), uuid4(), uuid4()]
    dense = [
        _chunk("d1", 0.9, chunk_id=other_dense),
        _chunk("shared", 0.8, chunk_id=dense_id),
    ]
    lexical = [
        _chunk("l1", 0.3, chunk_id=extra_lex[0]),
        _chunk("l2", 0.2, chunk_id=extra_lex[1]),
        _chunk("l3", 0.1, chunk_id=extra_lex[2]),
        _chunk("shared", 0.4, chunk_id=dense_id),
    ]
    fused = rrf_fuse(dense, lexical, rrf_k=60, top_k=10)
    shared = next(item for item in fused if item.chunk_id == dense_id)
    assert shared.dense_rank == 2
    assert shared.lexical_rank == 4
    assert shared.rrf_score == pytest.approx(1 / 62 + 1 / 64)


def test_rrf_tie_break_cosine_then_chunk_id():
    dense = [_chunk("high", 0.99)]
    lexical = [_chunk("low", 0.01)]
    fused = rrf_fuse(dense, lexical, rrf_k=60, top_k=5)
    assert fused[0].content == "high"
    assert fused[1].content == "low"

    low_id, high_id = sorted([uuid4(), uuid4()], key=str)
    dense = [_chunk("x", 0.5, chunk_id=high_id)]
    lexical = [_chunk("y", 0.5, chunk_id=low_id)]
    fused = rrf_fuse(dense, lexical, rrf_k=60, top_k=5)
    assert [item.chunk_id for item in fused] == [low_id, high_id]


def test_rrf_final_top_k_after_fusion():
    dense = [_chunk(f"d{i}", 0.9 - i * 0.01) for i in range(8)]
    lexical = [_chunk(f"l{i}", 0.2) for i in range(8)]
    fused = rrf_fuse(dense, lexical, rrf_k=60, top_k=5)
    assert len(fused) == 5
    scores = [item.rrf_score or 0 for item in fused]
    assert scores == sorted(scores, reverse=True)
