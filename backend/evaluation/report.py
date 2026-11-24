"""Human-readable retrieval and generation evaluation reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.embedders import embedder_display_name
from evaluation.generation import (
    DIAGNOSIS_GENERATION_SUCCESS,
    DIAGNOSIS_NO_CONTEXT_CORRECT,
    GenerationMetrics,
)
from evaluation.generation_evaluator import CONTEXT_PREVIEW_CHARS
from evaluation.metrics import RetrievalMetrics
from evaluation.progress import (
    STATUS_COMPLETE,
    apply_run_status,
    error_breakdown_from_records,
    summary_from_records,
)

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def _score(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _pass(flag: bool | None) -> str:
    if flag is None:
        return "n/a"
    return "PASS" if flag else "FAIL"


def format_report(
    metrics: RetrievalMetrics,
    *,
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    similarity_threshold: float,
    embedder: str,
    embedding_model: str,
    dataset_version: str = "1.1.1",
    chunking_strategy: str = "fixed_word_window",
    chunk_stats: dict | None = None,
    retrieval_mode: str | None = None,
    average_retrieval_ms: float | None = None,
    average_rerank_ms: float | None = None,
) -> str:
    label = embedder_display_name(embedder)
    lines = [
        "RAG V1.1 BASELINE",
        "=================",
        "",
        f"Embedding provider: {label}",
        f"Embedding model: {embedding_model}",
        f"Dataset version: {dataset_version}",
        "",
        f"Chunking strategy: {chunking_strategy}",
        f"Chunk size: {chunk_size}",
        f"Chunk overlap: {chunk_overlap}",
        f"Top K: {top_k}",
        f"Candidate pool K: {metrics.candidate_pool_k}",
        f"Similarity threshold: {similarity_threshold}",
    ]
    if retrieval_mode:
        lines.append(f"Retrieval mode: {retrieval_mode}")
    if average_retrieval_ms is not None:
        lines.append(f"Average retrieval: {average_retrieval_ms:.1f} ms")
    if average_rerank_ms is not None:
        lines.append(f"Average rerank: {average_rerank_ms:.1f} ms")
    lines.extend(
        [
        "",
        "Hit@K is scored from a candidate pool of max(5, top_k) after the",
        "similarity threshold. Hit@5 is omitted when that pool is smaller than 5.",
        "Production chat still sends only RAG_TOP_K chunks to the LLM.",
        "",
        "---------------------------------",
        "RETRIEVAL",
        "---------------------------------",
        "",
        f"Grounded questions: {metrics.grounded_questions}",
        "",
        f"Hit@1: {_pct(metrics.hit_at_1)}",
        f"Hit@3: {_pct(metrics.hit_at_3)}",
        f"Hit@5: {_pct(metrics.hit_at_5)}",
        f"Recall@5: {_pct(metrics.recall_at_5)}",
        f"MRR: {_score(metrics.mrr)}",
        "",
        f"Average top-1 similarity: {_score(metrics.average_similarity)}",
        ]
    )
    if metrics.span_hit_at_5 is not None:
        lines.extend(["", f"Span@5: {_pct(metrics.span_hit_at_5)}"])
    if chunk_stats:
        lines.extend(
            [
                "",
                f"Total chunks: {chunk_stats.get('total_chunk_count')}",
                f"Average words/chunk: {_score(chunk_stats.get('average_words_per_chunk'))}",
            ]
        )
    lines.extend(
        [
            "",
            "---------------------------------",
            "NO-CONTEXT",
            "---------------------------------",
            "",
            f"No-context questions: {metrics.no_context_total}",
            "",
            f"Correctly rejected: {metrics.no_context_correct}/{metrics.no_context_total}",
            f"False retrieval: {metrics.no_context_false_retrieval}/{metrics.no_context_total}",
            "",
            "---------------------------------",
            "FAILURES",
            "---------------------------------",
            "",
        ]
    )
    failures = [
        item
        for item in metrics.question_results
        if not item.expect_no_context and item.hit_at_1 is False
    ]
    if not failures:
        lines.append("None.")
        lines.append("")
    for item in failures:
        expected = ", ".join(
            f"{source.document} / page {source.page}" for source in item.expected_sources
        )
        top = item.retrieved[:3]
        retrieved_text = (
            "none"
            if not top
            else "; ".join(
                f"{row['rank']}. {row['filename']} / page {row['page_number']} "
                f"({row['score']:.3f})"
                for row in top
            )
        )
        if not item.retrieved:
            observation = "No chunks passed the similarity threshold."
        else:
            top1 = item.retrieved[0]
            observation = (
                f"Top-1 was {top1['filename']} page {top1['page_number']} "
                f"with score {top1['score']:.3f}."
            )
        lines.extend(
            [
                f"{item.question_id}: {item.question}",
                f"Expected: {expected}",
                f"Retrieved: {retrieved_text}",
                f"Observation: {observation}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def format_chunk_comparison(rows: list[dict]) -> str:
    lines = [
        "Chunking configuration comparison",
        "--------------------------------",
        "",
        "Page-level Hit@K can tie when the chunker never crosses pages.",
        "Span@5 checks whether the expected answer string is inside a retrieved chunk.",
        "",
        f"{'Configuration':<16}{'Hit@1':<10}{'Hit@3':<10}{'Hit@5':<10}{'Span@5':<10}{'Recall@5':<12}",
    ]
    for row in rows:
        config = f"{row['chunk_size']} / {row['chunk_overlap']}"
        lines.append(
            f"{config:<16}{_pct(row['hit_at_1']):<10}{_pct(row['hit_at_3']):<10}"
            f"{_pct(row['hit_at_5']):<10}{_pct(row.get('span_hit_at_5')):<10}"
            f"{_pct(row['recall_at_5']):<12}"
        )
    return "\n".join(lines) + "\n"


def format_strategy_comparison(rows: list[dict]) -> str:
    lines = [
        "Chunking strategy comparison",
        "----------------------------",
        "",
        "Size and overlap stay constant. Only the chunking strategy changes.",
        "Page-level Hit@K can tie when pages are shorter than the chunk size.",
        "Span@5 checks whether the expected answer string is inside a retrieved chunk.",
        "",
        f"{'Strategy':<22}{'Hit@1':<10}{'Hit@3':<10}{'Hit@5':<10}{'Span@5':<10}"
        f"{'Recall@5':<12}{'Chunks':<10}{'Avg words':<12}",
    ]
    for row in rows:
        lines.append(
            f"{row['chunking_strategy']:<22}{_pct(row['hit_at_1']):<10}"
            f"{_pct(row['hit_at_3']):<10}{_pct(row['hit_at_5']):<10}"
            f"{_pct(row.get('span_hit_at_5')):<10}{_pct(row['recall_at_5']):<12}"
            f"{str(row.get('total_chunk_count', 'n/a')):<10}"
            f"{_score(row.get('average_words_per_chunk')):<12}"
        )
    return "\n".join(lines) + "\n"


def format_metadata_filter_comparison(
    results: list,
    *,
    average_retrieval_ms: float | None = None,
) -> str:
    lines = [
        "Metadata filter comparison",
        "--------------------------",
        "",
        "Same corpus, embeddings, Top-K, and threshold as the unfiltered run.",
        "Filters are applied in PostgreSQL before cosine ORDER BY / LIMIT.",
        "Metadata filters are retrieval controls, not authorization.",
        "",
    ]
    if average_retrieval_ms is not None:
        lines.append(f"Average retrieval (filter cases): {average_retrieval_ms:.1f} ms")
        lines.append("")
    lines.append(
        f"{'Case':<8}{'Name':<28}{'Hit@1':<10}{'Hit@5':<10}{'Recall@5':<12}"
        f"{'Retrieved':<12}{'No-ctx':<10}"
    )
    for item in results:
        no_ctx = "n/a" if item.no_context_correct is None else _pass(item.no_context_correct)
        lines.append(
            f"{item.question_id:<8}{item.question_type:<28}"
            f"{_pct(item.hit_at_1):<10}{_pct(item.hit_at_5):<10}"
            f"{_pct(item.recall_at_5):<12}{item.retrieved_count:<12}{no_ctx:<10}"
        )
    lines.append("")
    for item in results:
        top = item.retrieved[:3]
        retrieved_text = (
            "none"
            if not top
            else "; ".join(
                f"{row.get('filename')} p.{row.get('page_number')} "
                f"({row.get('score', 0):.3f})"
                for row in top
            )
        )
        lines.extend(
            [
                f"{item.question_id} {item.question_type}: {item.question}",
                f"  retrieved_count={item.retrieved_count}  top={retrieved_text}",
                "",
            ]
        )
    return "\n".join(lines)


def format_span_inspection(rows: list[dict]) -> str:
    lines = [
        "Span questions (Q27 / Q28 / Q29)",
        "--------------------------------",
        "",
    ]
    for row in rows:
        lines.append(
            f"Strategy: {row['chunking_strategy']}  "
            f"(size {row.get('chunk_size')} / overlap {row.get('chunk_overlap')})"
        )
        if row.get("average_retrieval_ms") is not None:
            lines.append(f"Average retrieval: {row['average_retrieval_ms']:.1f} ms")
        for item in row.get("span_questions") or []:
            score = item.get("score")
            score_text = "n/a" if score is None else f"{score:.4f}"
            lines.extend(
                [
                    f"  {item.get('id')}: {item.get('question')}",
                    f"    expected span: {item.get('expected_span')}",
                    f"    span@5: {_pass(item.get('span_hit_at_5'))}",
                    f"    top chunk: {item.get('filename')} page {item.get('page_number')} "
                    f"index {item.get('chunk_index')} score {score_text}",
                    f"    span in top chunk: {_yn(item.get('span_in_top_chunk'))}",
                    f"    content: {_preview(item.get('content') or '', 280)}",
                    "",
                ]
            )
        lines.append("")
    return "\n".join(lines)


def format_retrieval_comparison(rows: list[dict]) -> str:
    lines = [
        "Retrieval configuration comparison",
        "---------------------------------",
        "",
        f"{'top_k':<8}{'threshold':<12}{'Hit@1':<10}{'Hit@3':<10}{'Hit@5':<10}"
        f"{'Recall@5':<12}{'MRR':<8}{'No-context':<14}{'Avg sim':<10}",
    ]
    for row in rows:
        no_context = f"{row['no_context_correct']}/{row['no_context_total']}"
        lines.append(
            f"{row['top_k']:<8}{row['similarity_threshold']:<12}"
            f"{_pct(row['hit_at_1']):<10}{_pct(row['hit_at_3']):<10}"
            f"{_pct(row['hit_at_5']):<10}{_pct(row.get('recall_at_5')):<12}"
            f"{_score(row.get('mrr')):<8}"
            f"{no_context:<14}{_score(row.get('average_similarity')):<10}"
        )
    return "\n".join(lines) + "\n"


def retrieval_mode_outcomes(dense, lexical, hybrid) -> dict:
    """Compare Hit@5 presence of gold — not which mode retrieved more chunks."""
    dense_by = {item.question_id: item for item in dense.question_results}
    lexical_by = {item.question_id: item for item in lexical.question_results}
    hybrid_by = {item.question_id: item for item in hybrid.question_results}
    dense_only = lexical_only = both = neither = hybrid_wins = 0
    for question_id, item in dense_by.items():
        if item.expect_no_context:
            continue
        dense_hit = bool(item.hit_at_5)
        lexical_hit = bool(lexical_by[question_id].hit_at_5)
        hybrid_hit = bool(hybrid_by[question_id].hit_at_5)
        if dense_hit and not lexical_hit:
            dense_only += 1
        elif lexical_hit and not dense_hit:
            lexical_only += 1
        elif dense_hit and lexical_hit:
            both += 1
        else:
            neither += 1
        if hybrid_hit and not dense_hit:
            hybrid_wins += 1
    return {
        "dense_only_wins": dense_only,
        "lexical_only_wins": lexical_only,
        "both_retrieve": both,
        "hybrid_wins": hybrid_wins,
        "neither_retrieves": neither,
    }


def format_retrieval_mode_comparison(rows: list[dict], outcomes: dict | None = None) -> str:
    lines = [
        "Retrieval mode comparison",
        "-------------------------",
        "",
        "Dense is cosine + threshold. Lexical is PostgreSQL FTS (not BM25) plus",
        "identifier ILIKE. Hybrid fuses both with Reciprocal Rank Fusion.",
        "Success is gold Hit@K, not retrieving more chunks.",
        "",
        f"{'Mode':<12}{'Hit@1':<10}{'Hit@3':<10}{'Hit@5':<10}{'Recall@5':<12}"
        f"{'Span@5':<10}{'Retrieved':<12}{'Latency ms':<12}",
    ]
    for row in rows:
        latency = row.get("average_retrieval_ms")
        latency_text = "n/a" if latency is None else f"{latency:.1f}"
        retrieved = row.get("average_retrieved_count")
        retrieved_text = "n/a" if retrieved is None else f"{retrieved:.1f}"
        lines.append(
            f"{row['retrieval_mode']:<12}{_pct(row['hit_at_1']):<10}"
            f"{_pct(row['hit_at_3']):<10}{_pct(row['hit_at_5']):<10}"
            f"{_pct(row['recall_at_5']):<12}{_pct(row.get('span_hit_at_5')):<10}"
            f"{retrieved_text:<12}{latency_text:<12}"
        )
    if outcomes:
        lines.extend(
            [
                "",
                "Grounded-question retrieval outcomes (Hit@5):",
                f"  dense-only wins: {outcomes.get('dense_only_wins')}",
                f"  lexical-only wins: {outcomes.get('lexical_only_wins')}",
                f"  both retrieve: {outcomes.get('both_retrieve')}",
                f"  hybrid wins vs dense: {outcomes.get('hybrid_wins')}",
                f"  neither retrieves: {outcomes.get('neither_retrieves')}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def format_reranking_comparison(
    rows: list[dict],
    *,
    question_highlights: list[dict] | None = None,
) -> str:
    lines = [
        "Retrieval + reranking comparison",
        "--------------------------------",
        "",
        "Dense is cosine + threshold. Hybrid is dense + lexical RRF.",
        "Hybrid+rerank expands the RRF pool to RERANK_CANDIDATE_K, scores",
        "candidates with a local cross-encoder, then returns RAG_TOP_K.",
        "Rerank scores are an internal ranking signal; citations stay cosine.",
        "",
        f"{'Mode':<18}{'Hit@1':<10}{'Hit@3':<10}{'Hit@5':<10}{'Recall@5':<12}"
        f"{'Span@5':<10}{'Retrieved':<12}{'Rerank ms':<12}{'Retr ms':<12}",
    ]
    for row in rows:
        retrieval_ms = row.get("average_retrieval_ms")
        rerank_ms = row.get("average_rerank_ms")
        retrieved = row.get("average_retrieved_count")
        lines.append(
            f"{row['retrieval_mode']:<18}{_pct(row['hit_at_1']):<10}"
            f"{_pct(row['hit_at_3']):<10}{_pct(row['hit_at_5']):<10}"
            f"{_pct(row['recall_at_5']):<12}{_pct(row.get('span_hit_at_5')):<10}"
            f"{'n/a' if retrieved is None else f'{retrieved:.1f}':<12}"
            f"{'n/a' if rerank_ms is None else f'{rerank_ms:.1f}':<12}"
            f"{'n/a' if retrieval_ms is None else f'{retrieval_ms:.1f}':<12}"
        )
    if question_highlights:
        lines.extend(["", "Rank movement (gold chunk):", ""])
        lines.append(
            f"{'ID':<8}{'Mode':<18}{'Hit@1':<10}{'RRF rank':<12}{'Rerank rank':<14}"
            f"{'Top-1 rerank':<14}"
        )
        for item in question_highlights:
            pre = item.get("gold_pre_rerank_rank")
            post = item.get("gold_post_rerank_rank")
            top1 = item.get("top1_rerank_score")
            lines.append(
                f"{item.get('id', ''):<8}{item.get('retrieval_mode', ''):<18}"
                f"{_pass(item.get('hit_at_1')):<10}"
                f"{'n/a' if pre is None else str(pre):<12}"
                f"{'n/a' if post is None else str(post):<14}"
                f"{'n/a' if top1 is None else f'{top1:.4f}':<14}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def metrics_to_dict(
    metrics: RetrievalMetrics,
    *,
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    similarity_threshold: float,
    embedder: str,
    embedding_model: str,
    dataset_version: str,
    timestamp: str | None = None,
    chunking_strategy: str = "fixed_word_window",
    chunk_stats: dict | None = None,
    retrieval_mode: str | None = None,
    average_retrieval_ms: float | None = None,
    average_rerank_ms: float | None = None,
) -> dict:
    payload = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "embedder": embedder,
        "embedder_label": embedder_display_name(embedder),
        "embedding_model": embedding_model,
        "dataset_version": dataset_version,
        "chunking_strategy": chunking_strategy,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "top_k": top_k,
        "candidate_pool_k": metrics.candidate_pool_k,
        "similarity_threshold": similarity_threshold,
        "retrieval_mode": retrieval_mode,
        "average_retrieval_ms": average_retrieval_ms,
        "average_rerank_ms": average_rerank_ms,
        "summary": {
            "questions_evaluated": metrics.questions_evaluated,
            "grounded_questions": metrics.grounded_questions,
            "hit_at_1": metrics.hit_at_1,
            "hit_at_3": metrics.hit_at_3,
            "hit_at_5": metrics.hit_at_5,
            "recall_at_5": metrics.recall_at_5,
            "mrr": metrics.mrr,
            "mean_reciprocal_rank": metrics.mean_reciprocal_rank,
            "span_hit_at_5": metrics.span_hit_at_5,
            "average_similarity": metrics.average_similarity,
            "no_context_correct": metrics.no_context_correct,
            "no_context_total": metrics.no_context_total,
            "no_context_false_retrieval": metrics.no_context_false_retrieval,
        },
        "questions": [
            {
                "id": item.question_id,
                "question": item.question,
                "type": item.question_type,
                "expect_no_context": item.expect_no_context,
                "expected_answer": item.expected_answer,
                "expected_span": item.expected_span,
                "generated_answer": item.generated_answer,
                "expected_sources": [
                    {"document": source.document, "page": source.page}
                    for source in item.expected_sources
                ],
                "retrieved": item.retrieved,
                "retrieved_count": item.retrieved_count,
                "candidate_pool_k": item.candidate_pool_k,
                "hit_at_1": item.hit_at_1,
                "hit_at_3": item.hit_at_3,
                "hit_at_5": item.hit_at_5,
                "recall_at_5": item.recall_at_5,
                "reciprocal_rank": item.reciprocal_rank,
                "span_hit_at_5": item.span_hit_at_5,
                "no_context_correct": item.no_context_correct,
                "top1_similarity": item.top1_similarity,
                "gold_pre_rerank_rank": item.gold_pre_rerank_rank,
                "gold_post_rerank_rank": item.gold_post_rerank_rank,
                "top1_rerank_score": item.top1_rerank_score,
                "rerank_candidate_count": item.rerank_candidate_count,
                "final_count": item.final_count or item.retrieved_count,
            }
            for item in metrics.question_results
        ],
    }
    if chunk_stats:
        payload["chunk_stats"] = chunk_stats
        payload["summary"]["total_chunk_count"] = chunk_stats.get("total_chunk_count")
        payload["summary"]["average_words_per_chunk"] = chunk_stats.get(
            "average_words_per_chunk"
        )
    return payload


def default_report_path(
    embedder: str,
    when: datetime | None = None,
    *,
    kind: str = "retrieval",
) -> Path:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORTS_DIR / f"{kind}_{embedder}_{stamp}.json"


def write_json_report(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _preview(text: str, limit: int = CONTEXT_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _yn(flag: bool | None) -> str:
    if flag is None:
        return "n/a"
    return "yes" if flag else "no"


def format_generation_report(
    metrics: GenerationMetrics,
    *,
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    similarity_threshold: float,
    embedder: str,
    embedding_model: str,
    embedding_dimension: int,
    llm_provider: str,
    llm_model: str,
    dataset_version: str,
    verbose: bool = False,
) -> str:
    retrieval = metrics.retrieval_metrics
    lines = [
        "RAG GENERATION EVALUATION",
        "=========================",
        "",
        f"Dataset: {dataset_version}",
        f"Embedding: {embedder_display_name(embedder)} / {embedding_model}",
        f"Embedding dimension: {embedding_dimension}",
        f"LLM: {llm_provider} / {llm_model}",
        "",
        f"Chunk size: {chunk_size}",
        f"Chunk overlap: {chunk_overlap}",
        f"Top K: {top_k}",
        f"Similarity threshold: {similarity_threshold}",
        "",
    ]
    if metrics.incomplete:
        lines.extend(
            [
                "INCOMPLETE RUN",
                metrics.incomplete_reason or "The generation evaluation did not finish.",
                "Metrics below cover only the questions that completed.",
                "Do not treat these as the full V1.1.5 baseline.",
                "",
            ]
        )
    else:
        lines.extend(["Status: COMPLETE", ""])
    lines.extend(
        [
        "--------------------------------",
        "RETRIEVAL",
        "--------------------------------",
        "",
        f"Hit@1: {_pct(retrieval.hit_at_1)}",
        f"Hit@3: {_pct(retrieval.hit_at_3)}",
        f"Hit@5: {_pct(retrieval.hit_at_5)}",
        f"Recall@5: {_pct(retrieval.recall_at_5)}",
        f"MRR: {_score(retrieval.mrr)}",
        "",
        "--------------------------------",
        "GENERATION",
        "--------------------------------",
        "",
        f"Correct: {metrics.generation_correct_count} / {metrics.grounded_total}",
        f"Grounded: {metrics.generation_grounded_count} / {metrics.grounded_total}",
        f"No-context refusal: {metrics.no_context_correct_refusals} / {metrics.no_context_total}",
        f"Hallucinated / unsupported: {metrics.hallucinated_or_unsupported} / {metrics.retrieval_metrics.questions_evaluated}",
        "",
        "--------------------------------",
        "ERROR BREAKDOWN",
        "--------------------------------",
        "",
        f"Retrieval failures: {metrics.retrieval_failures}",
        f"Context failures: {metrics.context_failures}",
        f"Generation failures: {metrics.generation_failures}",
        f"Correct refusals: {metrics.correct_refusals}",
        f"Generation successes: {metrics.generation_successes}",
        f"Unknown: {metrics.unknown_diagnoses}",
        "",
        ]
    )
    if metrics.prompt_injection_passed is not None:
        lines.extend(
            [
                f"Prompt-injection case: {'PASS' if metrics.prompt_injection_passed else 'FAIL'}",
                "",
            ]
        )
    lines.extend(
        [
            "--------------------------------",
            "FAILED QUESTIONS",
            "--------------------------------",
            "",
        ]
    )
    failures = [
        item
        for item in metrics.question_results
        if item.score.diagnosis
        not in {DIAGNOSIS_GENERATION_SUCCESS, DIAGNOSIS_NO_CONTEXT_CORRECT}
    ]
    if not failures:
        lines.append("None.")
        lines.append("")
    for item in failures:
        retrieval_item = item.retrieval
        expected_sources = ", ".join(
            f"{source.document} / page {source.page}"
            for source in retrieval_item.expected_sources
        ) or "none"
        top = retrieval_item.retrieved[:3]
        retrieved_text = (
            "none"
            if not top
            else "; ".join(
                f"{row['rank']}. {row['filename']} / page {row['page_number']} "
                f"({row['score']:.3f})"
                for row in top
            )
        )
        lines.extend(
            [
                f"{retrieval_item.question_id}:",
                "Question:",
                retrieval_item.question,
                "",
                "Expected:",
                retrieval_item.expected_answer or "(refusal)",
                "",
                f"Expected source: {expected_sources}",
                f"Retrieved source: {retrieved_text}",
                "",
                "Generated:",
                item.score.generated_answer,
                "",
                f"Diagnosis: {item.score.diagnosis}",
                f"Correct: {_yn(item.score.generation_correct)}  "
                f"Grounded: {_yn(item.score.grounded)}",
                "",
            ]
        )
    if verbose:
        lines.extend(
            [
                "--------------------------------",
                "VERBOSE QUESTION DETAIL",
                "--------------------------------",
                "",
            ]
        )
        for item in metrics.question_results:
            retrieval_item = item.retrieval
            retrieved_text = (
                "none"
                if not retrieval_item.retrieved
                else "; ".join(
                    f"{row['rank']}. {row['filename']} p{row['page_number']} "
                    f"chunk {row['chunk_index']} ({row['score']:.3f})"
                    for row in retrieval_item.retrieved
                )
            )
            lines.extend(
                [
                    f"{retrieval_item.question_id}  {item.score.diagnosis}",
                    f"Question: {retrieval_item.question}",
                    f"Retrieved: {retrieved_text}",
                    f"Context ({len(item.context)} chars):",
                    item.context or "(empty)",
                    "",
                    f"Generated: {item.score.generated_answer}",
                    f"Expected: {retrieval_item.expected_answer}",
                    f"Correct: {_yn(item.score.generation_correct)}",
                    f"Grounded: {_yn(item.score.grounded)} ({item.score.grounded_label})",
                    f"LLM called: {_yn(item.score.llm_called)}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def result_to_record(item, *, include_full_context: bool = False) -> dict:
    retrieval_item = item.retrieval
    context_value = item.context if include_full_context else _preview(item.context)
    return {
        "id": retrieval_item.question_id,
        "question": retrieval_item.question,
        "type": retrieval_item.question_type,
        "expect_no_context": retrieval_item.expect_no_context,
        "expected_answer": retrieval_item.expected_answer,
        "generated_answer": item.score.generated_answer,
        "generation_correct": item.score.generation_correct,
        "grounded": item.score.grounded,
        "grounded_label": item.score.grounded_label,
        "diagnosis": item.score.diagnosis,
        "unsupported_claims": item.score.unsupported_claims,
        "context_has_answer": item.score.context_has_answer,
        "llm_called": item.score.llm_called,
        "is_refusal": item.score.is_refusal,
        "chunks_sent_to_llm": item.chunks_sent_to_llm,
        "context_characters": len(item.context),
        "context": context_value,
        "prompt_contains_expected_answer": item.score.prompt_contains_expected_answer,
        "prompt_contains_gold_metadata": item.score.prompt_contains_gold_metadata,
        "followed_document_injection": item.score.followed_document_injection,
        "judge_correct": item.score.judge_correct,
        "judge_grounded": item.score.judge_grounded,
        "judge_notes": item.score.judge_notes,
        "judge_model": item.score.judge_model,
        "retrieval": {
            "hit_at_1": retrieval_item.hit_at_1,
            "hit_at_3": retrieval_item.hit_at_3,
            "hit_at_5": retrieval_item.hit_at_5,
            "recall_at_5": retrieval_item.recall_at_5,
            "reciprocal_rank": retrieval_item.reciprocal_rank,
            "retrieved": retrieval_item.retrieved,
            "retrieved_count": retrieval_item.retrieved_count,
        },
    }


def generation_to_dict(
    metrics: GenerationMetrics,
    *,
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    similarity_threshold: float,
    embedder: str,
    embedding_model: str,
    embedding_dimension: int,
    llm_provider: str,
    llm_model: str,
    dataset_version: str,
    include_full_context: bool = False,
    timestamp: str | None = None,
) -> dict:
    retrieval = metrics.retrieval_metrics
    questions = [
        result_to_record(item, include_full_context=include_full_context)
        for item in metrics.question_results
    ]
    return {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset_version,
        "embedder": embedder,
        "embedder_label": embedder_display_name(embedder),
        "embedding_provider": "Gemini" if embedder == "gemini" else "local-hash",
        "embedding_model": embedding_model,
        "embedding_dimension": embedding_dimension,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "top_k": top_k,
        "candidate_pool_k": retrieval.candidate_pool_k,
        "similarity_threshold": similarity_threshold,
        "incomplete": metrics.incomplete,
        "incomplete_reason": metrics.incomplete_reason,
        "summary": {
            "questions_evaluated": retrieval.questions_evaluated,
            "grounded_questions": retrieval.grounded_questions,
            "hit_at_1": retrieval.hit_at_1,
            "hit_at_3": retrieval.hit_at_3,
            "hit_at_5": retrieval.hit_at_5,
            "recall_at_5": retrieval.recall_at_5,
            "mrr": retrieval.mrr,
            "mean_reciprocal_rank": retrieval.mean_reciprocal_rank,
            "generation_correct": metrics.generation_correct_count,
            "generation_correct_total": metrics.grounded_total,
            "generation_grounded": metrics.generation_grounded_count,
            "generation_grounded_total": metrics.grounded_total,
            "no_context_correct_refusals": metrics.no_context_correct_refusals,
            "no_context_total": metrics.no_context_total,
            "hallucinated_or_unsupported": metrics.hallucinated_or_unsupported,
            "prompt_injection_passed": metrics.prompt_injection_passed,
        },
        "error_breakdown": {
            "retrieval_failures": metrics.retrieval_failures,
            "context_failures": metrics.context_failures,
            "generation_failures": metrics.generation_failures,
            "correct_refusals": metrics.correct_refusals,
            "generation_successes": metrics.generation_successes,
            "unknown": metrics.unknown_diagnoses,
        },
        "questions": questions,
    }


def payload_from_records(
    records: list[dict],
    *,
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    similarity_threshold: float,
    embedder: str,
    embedding_model: str,
    embedding_dimension: int,
    llm_provider: str,
    llm_model: str,
    dataset_version: str,
    dataset_ids: list[str] | tuple[str, ...],
    candidate_pool_k: int,
    stop_reason: str | None = None,
    timestamp: str | None = None,
    chunking_strategy: str = "fixed_word_window",
) -> dict:
    payload = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset_version,
        "embedder": embedder,
        "embedder_label": embedder_display_name(embedder),
        "embedding_provider": "Gemini" if embedder == "gemini" else "local-hash",
        "embedding_model": embedding_model,
        "embedding_dimension": embedding_dimension,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "chunking_strategy": chunking_strategy,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "top_k": top_k,
        "candidate_pool_k": candidate_pool_k,
        "similarity_threshold": similarity_threshold,
        "summary": summary_from_records(records),
        "error_breakdown": error_breakdown_from_records(records),
        "questions": records,
    }
    return apply_run_status(payload, dataset_ids, stop_reason=stop_reason)


def format_generation_payload(payload: dict, *, verbose: bool = False) -> str:
    status = payload.get("status") or ("PARTIAL" if payload.get("incomplete") else "COMPLETE")
    summary = payload.get("summary") or {}
    breakdown = payload.get("error_breakdown") or {}
    questions = payload.get("questions") or []
    final = bool(payload.get("metrics_are_final"))
    lines = [
        "RAG GENERATION EVALUATION",
        "=========================",
        "",
        f"Dataset: {payload.get('dataset_version')}",
        f"Embedding: {payload.get('embedder_label')} / {payload.get('embedding_model')}",
        f"Embedding dimension: {payload.get('embedding_dimension')}",
        f"LLM: {payload.get('llm_provider')} / {payload.get('llm_model')}",
        "",
        f"Chunk size: {payload.get('chunk_size')}",
        f"Chunk overlap: {payload.get('chunk_overlap')}",
        f"Top K: {payload.get('top_k')}",
        f"Similarity threshold: {payload.get('similarity_threshold')}",
        "",
        f"Status: {status}",
        f"Completed questions: {payload.get('completed_questions', len(questions))}/"
        f"{payload.get('dataset_questions', len(questions))}",
        f"Remaining questions: {payload.get('remaining_questions', 0)}",
        "",
    ]
    if status != STATUS_COMPLETE:
        lines.extend(
            [
                f"Generation evaluation is {status}.",
                f"{payload.get('completed_questions', len(questions))}/"
                f"{payload.get('dataset_questions', len(questions))} questions completed.",
                "Do not interpret aggregate generation metrics as final.",
                payload.get("incomplete_reason") or payload.get("stop_reason") or "",
                "",
            ]
        )
    correct_total = summary.get("generation_correct_total") or 0
    grounded_total = summary.get("generation_grounded_total") or 0
    no_context_total = summary.get("no_context_total") or 0
    lines.extend(
        [
            "--------------------------------",
            "RETRIEVAL",
            "--------------------------------",
            "",
            f"Hit@1: {_pct(summary.get('hit_at_1'))}",
            f"Hit@3: {_pct(summary.get('hit_at_3'))}",
            f"Hit@5: {_pct(summary.get('hit_at_5'))}",
            f"Recall@5: {_pct(summary.get('recall_at_5'))}",
            f"MRR: {_score(summary.get('mrr'))}",
            "",
            "--------------------------------",
            "AUGMENTATION",
            "--------------------------------",
            "",
            f"Context construction failures: {breakdown.get('context_failures', 0)}",
            "",
            "--------------------------------",
            "GENERATION",
            "--------------------------------",
            "",
            f"Correct: {summary.get('generation_correct', 0)} / {correct_total}"
            + ("" if not final else _accuracy_suffix(summary.get("generation_correct"), correct_total)),
            f"Grounded: {summary.get('generation_grounded', 0)} / {grounded_total}"
            + ("" if not final else _accuracy_suffix(summary.get("generation_grounded"), grounded_total)),
            f"No-context refusal: {summary.get('no_context_correct_refusals', 0)} / {no_context_total}"
            + ("" if not final else _accuracy_suffix(summary.get("no_context_correct_refusals"), no_context_total)),
            f"Hallucinated / unsupported: {summary.get('hallucinated_or_unsupported', 0)} / {summary.get('questions_evaluated', 0)}",
            "",
            "--------------------------------",
            "ERROR BREAKDOWN",
            "--------------------------------",
            "",
            f"Retrieval failures: {breakdown.get('retrieval_failures', 0)}",
            f"Context failures: {breakdown.get('context_failures', 0)}",
            f"Generation failures: {breakdown.get('generation_failures', 0)}",
            f"Correct refusals: {breakdown.get('correct_refusals', 0)}",
            f"Generation successes: {breakdown.get('generation_successes', 0)}",
            f"Unknown: {breakdown.get('unknown', 0)}",
            "",
        ]
    )
    injection = next((item for item in questions if item.get("type") == "prompt_injection" or item.get("id") == "Q29"), None)
    lines.extend(
        [
            "--------------------------------",
            "PROMPT INJECTION (Q29)",
            "--------------------------------",
            "",
        ]
    )
    if injection is None:
        lines.extend(["Q29 has not been evaluated yet.", ""])
    else:
        lines.extend(
            [
                f"Generated: {injection.get('generated_answer')}",
                f"Expected: {injection.get('expected_answer')}",
                f"Correct: {_yn(injection.get('generation_correct'))}",
                f"Grounded: {_yn(injection.get('grounded'))}",
                f"Followed document injection: {_yn(injection.get('followed_document_injection'))}",
                f"Diagnosis: {injection.get('diagnosis')}",
                "",
            ]
        )
    if summary.get("prompt_injection_passed") is not None:
        lines.extend(
            [
                f"Prompt-injection case: {'PASS' if summary.get('prompt_injection_passed') else 'FAIL'}",
                "",
            ]
        )
    lines.extend(
        [
            "--------------------------------",
            "FAILED QUESTIONS",
            "--------------------------------",
            "",
        ]
    )
    failures = [
        item
        for item in questions
        if item.get("diagnosis") not in {DIAGNOSIS_GENERATION_SUCCESS, DIAGNOSIS_NO_CONTEXT_CORRECT}
    ]
    if not failures:
        lines.append("None.")
        lines.append("")
    for item in failures:
        retrieval = item.get("retrieval") or {}
        retrieved = retrieval.get("retrieved") or []
        top = retrieved[:3]
        retrieved_text = (
            "none"
            if not top
            else "; ".join(
                f"{row.get('rank')}. {row.get('filename')} / page {row.get('page_number')} "
                f"({row.get('score', 0):.3f})"
                for row in top
            )
        )
        lines.extend(
            [
                f"{item.get('id')}:",
                "Question:",
                item.get("question") or "",
                "",
                "Expected:",
                item.get("expected_answer") or "(refusal)",
                "",
                f"Retrieved source: {retrieved_text}",
                "",
                "Generated:",
                item.get("generated_answer") or "",
                "",
                f"Diagnosis: {item.get('diagnosis')}",
                f"Correct: {_yn(item.get('generation_correct'))}  "
                f"Grounded: {_yn(item.get('grounded'))}",
                "",
            ]
        )
    if verbose:
        lines.extend(
            [
                "--------------------------------",
                "VERBOSE QUESTION DETAIL",
                "--------------------------------",
                "",
            ]
        )
        for item in questions:
            retrieval = item.get("retrieval") or {}
            retrieved = retrieval.get("retrieved") or []
            retrieved_text = (
                "none"
                if not retrieved
                else "; ".join(
                    f"{row.get('rank')}. {row.get('filename')} p{row.get('page_number')} "
                    f"({row.get('score', 0):.3f})"
                    for row in retrieved
                )
            )
            lines.extend(
                [
                    f"{item.get('id')}  {item.get('diagnosis')}",
                    f"Question: {item.get('question')}",
                    f"Retrieved: {retrieved_text}",
                    f"Context ({item.get('context_characters', 0)} chars):",
                    item.get("context") or "(empty)",
                    "",
                    f"Generated: {item.get('generated_answer')}",
                    f"Expected: {item.get('expected_answer')}",
                    f"Correct: {_yn(item.get('generation_correct'))}",
                    f"Grounded: {_yn(item.get('grounded'))}",
                    f"LLM called: {_yn(item.get('llm_called'))}",
                    "",
                ]
            )
    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def _accuracy_suffix(count: object, total: object) -> str:
    if not isinstance(count, int) or not isinstance(total, int) or total <= 0:
        return ""
    return f"  Accuracy: {count / total * 100:.0f}%"
