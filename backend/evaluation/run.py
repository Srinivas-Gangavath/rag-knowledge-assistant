"""CLI: python -m evaluation.run

Default embedder is local hashed n-grams so evaluation does not call Gemini.
Use --embedder gemini to score the production embedding model.
Use --generation to score production generation (opt-in, paid LLM).
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.database import SessionLocal, check_connection
from app.services.ai import get_ai_provider
from app.services.ai.errors import AIConfigurationError, AIProviderError
from app.services.chunker import SUPPORTED_CHUNKING_STRATEGIES, normalize_chunking_strategy
from app.services.embedding_service import EmbeddingService
from evaluation.embedders import (
    GEMINI_EMBEDDER_NAME,
    LOCAL_EMBEDDER_NAME,
    embedding_model_label,
    embedding_service_for,
)
from evaluation.evaluator import (
    EVAL_RETRIEVAL_MODES,
    RetrievalEvaluator,
    load_dataset,
)
from evaluation.filter_cases import FILTER_CASES
from evaluation.generation_evaluator import (
    DEFAULT_GENERATION_MIN_INTERVAL_SECONDS,
    GenerationEvaluator,
)
from evaluation.judge import JUDGE_MODEL_SOURCE, judge_generation
from evaluation.metrics import candidate_pool_k
from evaluation.progress import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PARTIAL,
    completed_question_ids,
    load_generation_report,
    merge_question_records,
)
from evaluation.report import (
    default_report_path,
    format_chunk_comparison,
    format_generation_payload,
    format_report,
    format_retrieval_comparison,
    format_retrieval_mode_comparison,
    format_reranking_comparison,
    format_span_inspection,
    format_strategy_comparison,
    format_metadata_filter_comparison,
    metrics_to_dict,
    payload_from_records,
    result_to_record,
    retrieval_mode_outcomes,
    write_json_report,
)
from evaluation.selection import format_selection, select_questions

logger = get_logger(__name__)

CHUNK_EXPERIMENTS = ((500, 50), (700, 100), (1000, 150))
STRATEGY_EXPERIMENTS = SUPPORTED_CHUNKING_STRATEGIES
SPAN_QUESTION_IDS = ("Q27", "Q28", "Q29")
RERANK_HIGHLIGHT_IDS = (
    "Q15",
    "Q14",
    "Q28",
    "L1",
    "L2",
    "L3",
    "L4",
    "L5",
    "L6",
    "L8",
    "L9",
    "L10",
)
TOP_K_EXPERIMENTS = (3, 5, 8)
THRESHOLD_EXPERIMENTS = (0.5, 0.6, 0.7, 0.8)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAG retrieval and generation evaluation.")
    parser.add_argument("--dataset", type=Path, default=None, help="Path to rag_eval.json")
    parser.add_argument("--output", type=Path, default=None, help="JSON report path")
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write a JSON report",
    )
    parser.add_argument(
        "--embedder",
        choices=(LOCAL_EMBEDDER_NAME, GEMINI_EMBEDDER_NAME),
        default=None,
        help="local (offline) or gemini (production embeddings). "
        "Generation evaluation defaults to gemini.",
    )
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-overlap", type=int, default=None)
    parser.add_argument(
        "--chunking-strategy",
        choices=STRATEGY_EXPERIMENTS,
        default=None,
        help="fixed_word_window (production default) or recursive. "
        "Does not change production settings.",
    )
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--similarity-threshold", type=float, default=None)
    parser.add_argument(
        "--compare-chunks",
        action="store_true",
        help="Compare chunk size/overlap without changing production settings",
    )
    parser.add_argument(
        "--compare-retrieval",
        action="store_true",
        help="Compare top_k and similarity threshold without changing production settings",
    )
    parser.add_argument(
        "--compare-chunking-strategies",
        action="store_true",
        help="Compare fixed_word_window vs recursive at the same size/overlap. "
        "Does not change production settings.",
    )
    parser.add_argument(
        "--compare-metadata-filters",
        action="store_true",
        help="Compare unfiltered retrieval with Stage 2 metadata filters. "
        "Does not change production settings.",
    )
    parser.add_argument(
        "--compare-retrieval-modes",
        action="store_true",
        help="Compare dense, lexical-only (eval), and hybrid retrieval. "
        "Does not change production RETRIEVAL_MODE.",
    )
    parser.add_argument(
        "--compare-reranking",
        action="store_true",
        help="Compare dense, hybrid, and hybrid+rerank. "
        "Does not change production RERANKING_ENABLED.",
    )
    parser.add_argument(
        "--enable-rerank",
        action="store_true",
        help="Evaluate hybrid retrieval with reranking enabled. "
        "Evaluation never falls back to RRF if reranking fails.",
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=EVAL_RETRIEVAL_MODES,
        default=None,
        help="Evaluate a single retrieval mode. lexical is evaluation-only. "
        "Default follows production dense unless this flag is set.",
    )
    parser.add_argument(
        "--generation",
        action="store_true",
        help="Opt-in generation evaluation using the production LLM. "
        "Does not run during pytest.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print retrieved sources, constructed context, and generated answers",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Optional LLM-as-a-judge after production generation. Not used by pytest.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Skip the first N dataset questions (0-based). Generation evaluation only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate at most N not-yet-completed questions this run. Generation only.",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Resume generation evaluation from an existing JSON report.",
    )
    parser.add_argument(
        "--check-baseline",
        action="store_true",
        help="Assert evaluated metrics meet or exceed baseline reference in baseline_reference.json.",
    )
    return parser.parse_args(argv)


def check_baseline(
    metrics: RetrievalMetrics,
    *,
    dataset_path: Path | None = None,
) -> tuple[bool, list[str]]:
    baseline_path = Path(__file__).resolve().parent / "baseline_reference.json"
    if not baseline_path.exists():
        return False, [f"Baseline reference file not found at {baseline_path}"]

    import json
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    dataset_name = dataset_path.name if dataset_path else "rag_eval.json"

    if "lexical" in dataset_name.lower():
        baseline_key = "offline_lexical_baseline"
    else:
        baseline_key = "offline_retrieval_baseline"

    config = data.get(baseline_key, {})
    expected = config.get("metrics", {})
    tolerances = config.get("tolerances", {})

    errors: list[str] = []
    checks = ("hit_at_1", "hit_at_3", "hit_at_5", "recall_at_5", "mrr")
    for metric_name in checks:
        baseline_val = expected.get(metric_name)
        if baseline_val is None:
            continue
        actual_val = getattr(metrics, metric_name, None)
        tol = tolerances.get(metric_name, 0.0)
        if actual_val is None or actual_val < (baseline_val - tol - 1e-4):
            eval_str = "None" if actual_val is None else f"{actual_val:.4f}"
            errors.append(
                f"REGRESSION: {metric_name} evaluated={eval_str} < baseline={baseline_val:.4f} (tolerance={tol})"
            )

    return (len(errors) == 0), errors


def _evaluator(
    session: Session,
    settings,
    embedding_service: EmbeddingService,
    storage_path: str,
    chunk_size: int,
    chunk_overlap: int,
    chunking_strategy: str,
) -> RetrievalEvaluator:
    return RetrievalEvaluator(
        session,
        embedding_service,
        settings,
        storage_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunking_strategy=chunking_strategy,
    )


def _quiet_app_loggers() -> None:
    logging.getLogger("app.services.document_service").setLevel(logging.WARNING)
    logging.getLogger("app.services.storage").setLevel(logging.WARNING)
    logging.getLogger("app.services.chunker").setLevel(logging.WARNING)
    logging.getLogger("app.services.embedding_service").setLevel(logging.WARNING)
    logging.getLogger("app.db.database").setLevel(logging.WARNING)
    logging.getLogger("app.services.retrieval").setLevel(logging.WARNING)
    logging.getLogger("app.services.rerank").setLevel(logging.WARNING)
    logging.getLogger("app.services.ai.gemini_provider").setLevel(logging.WARNING)
    logging.getLogger("app.services.context_builder").setLevel(logging.WARNING)
    logging.getLogger("app.services.rag").setLevel(logging.WARNING)


def _apply_optional_judge(metrics, provider, llm_model: str) -> None:
    for item in metrics.question_results:
        correct, grounded, notes = judge_generation(
            provider,
            question=item.retrieval.question,
            context=item.context,
            generated_answer=item.score.generated_answer,
            expected_answer=item.retrieval.expected_answer,
            expect_no_context=item.retrieval.expect_no_context,
        )
        item.score.judge_correct = correct
        item.score.judge_grounded = grounded
        item.score.judge_notes = notes
        item.score.judge_model = f"{JUDGE_MODEL_SOURCE} ({llm_model})"


def _run_generation(
    *,
    args,
    session: Session,
    settings,
    dataset: dict,
    dataset_version: str,
    embedding_service: EmbeddingService,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
    chunking_strategy: str,
    top_k: int,
    threshold: float,
    storage_path: str,
    output_path: Path | None,
) -> dict:
    prior = load_generation_report(args.resume) if args.resume else {"questions": []}
    dataset_ids = [item["id"] for item in dataset["questions"]]
    selection = select_questions(
        dataset["questions"],
        start=args.start,
        limit=args.limit,
        completed_ids=completed_question_ids(prior),
    )
    print(format_selection(selection, dataset_total=len(dataset_ids)))
    print()

    include_full_context = args.verbose
    records = merge_question_records(dataset_ids, prior.get("questions") or [])

    def persist(stop_reason: str | None = None) -> dict:
        payload = payload_from_records(
            records,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunking_strategy=chunking_strategy,
            top_k=top_k,
            similarity_threshold=threshold,
            embedder=args.embedder,
            embedding_model=embedding_model,
            embedding_dimension=settings.embedding_dimension,
            llm_provider="Gemini",
            llm_model=settings.llm_model,
            dataset_version=dataset_version,
            dataset_ids=dataset_ids,
            candidate_pool_k=candidate_pool_k(top_k),
            stop_reason=stop_reason,
        )
        if output_path is not None:
            write_json_report(payload, output_path)
        return payload

    payload = persist()
    if not selection.selected:
        print("No unanswered questions in this selection.")
        print()
        print(format_generation_payload(payload, verbose=args.verbose), end="")
        return payload

    provider = get_ai_provider()
    evaluator = GenerationEvaluator(
        session,
        embedding_service,
        settings,
        storage_path,
        provider=provider,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunking_strategy=chunking_strategy,
        generation_min_interval_seconds=DEFAULT_GENERATION_MIN_INTERVAL_SECONDS,
    )
    document_ids = evaluator.ingest_corpus()

    def on_result(result) -> None:
        records[:] = merge_question_records(
            dataset_ids,
            records,
            [result_to_record(result, include_full_context=include_full_context)],
        )
        persist()

    metrics = evaluator.evaluate(
        {**dataset, "questions": list(selection.selected)},
        document_ids,
        top_k=top_k,
        similarity_threshold=threshold,
        on_result=on_result,
    )
    if args.judge:
        _apply_optional_judge(metrics, provider, settings.llm_model)
        records[:] = merge_question_records(
            dataset_ids,
            records,
            [
                result_to_record(item, include_full_context=include_full_context)
                for item in metrics.question_results
            ],
        )
    payload = persist(stop_reason=metrics.incomplete_reason)
    print(format_generation_payload(payload, verbose=args.verbose), end="")
    return payload


def _span_question_details(metrics) -> list[dict]:
    by_id = {item.question_id: item for item in metrics.question_results}
    details: list[dict] = []
    for question_id in SPAN_QUESTION_IDS:
        item = by_id.get(question_id)
        if item is None:
            continue
        top = item.retrieved[0] if item.retrieved else None
        content = "" if top is None else str(top.get("content") or "")
        expected_span = item.expected_span
        details.append(
            {
                "id": question_id,
                "question": item.question,
                "expected_span": expected_span,
                "span_hit_at_5": item.span_hit_at_5,
                "retrieved_count": item.retrieved_count,
                "chunk_index": None if top is None else top.get("chunk_index"),
                "page_number": None if top is None else top.get("page_number"),
                "filename": None if top is None else top.get("filename"),
                "score": None if top is None else top.get("score"),
                "content": content,
                "span_in_top_chunk": (
                    None
                    if not expected_span
                    else expected_span.casefold() in content.casefold()
                ),
            }
        )
    return details


def _rerank_highlights(mode_metrics: dict) -> list[dict]:
    highlights: list[dict] = []
    for mode, metrics in mode_metrics.items():
        by_id = {item.question_id: item for item in metrics.question_results}
        for question_id in RERANK_HIGHLIGHT_IDS:
            item = by_id.get(question_id)
            if item is None:
                continue
            highlights.append(
                {
                    "id": question_id,
                    "retrieval_mode": mode,
                    "hit_at_1": item.hit_at_1,
                    "hit_at_5": item.hit_at_5,
                    "gold_pre_rerank_rank": item.gold_pre_rerank_rank,
                    "gold_post_rerank_rank": item.gold_post_rerank_rank,
                    "top1_rerank_score": item.top1_rerank_score,
                    "rerank_candidate_count": item.rerank_candidate_count,
                    "final_count": item.final_count or item.retrieved_count,
                }
            )
    return highlights


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging()
    settings = get_settings()
    compare_flags = (
        args.compare_chunks,
        args.compare_retrieval,
        args.compare_chunking_strategies,
        args.compare_metadata_filters,
        args.compare_retrieval_modes,
        args.compare_reranking,
    )
    if sum(bool(flag) for flag in compare_flags) > 1:
        print(
            "Use only one of --compare-chunks, --compare-retrieval, "
            "--compare-chunking-strategies, --compare-metadata-filters, "
            "--compare-retrieval-modes, or --compare-reranking.",
            file=sys.stderr,
        )
        return 2
    if args.generation and any(compare_flags):
        print(
            "--generation cannot be combined with comparison flags.",
            file=sys.stderr,
        )
        return 2
    if args.generation and args.retrieval_mode is not None:
        print(
            "--retrieval-mode cannot be combined with --generation. "
            "Generation uses production RETRIEVAL_MODE from settings.",
            file=sys.stderr,
        )
        return 2
    if args.generation and args.enable_rerank:
        print(
            "--enable-rerank cannot be combined with --generation. "
            "Generation uses production RERANKING_ENABLED from settings.",
            file=sys.stderr,
        )
        return 2
    if args.compare_retrieval_modes and args.retrieval_mode is not None:
        print(
            "--retrieval-mode cannot be combined with --compare-retrieval-modes.",
            file=sys.stderr,
        )
        return 2
    if args.compare_reranking and args.retrieval_mode is not None:
        print(
            "--retrieval-mode cannot be combined with --compare-reranking.",
            file=sys.stderr,
        )
        return 2
    if args.compare_reranking and args.enable_rerank:
        print(
            "--enable-rerank cannot be combined with --compare-reranking.",
            file=sys.stderr,
        )
        return 2
    if args.enable_rerank and args.retrieval_mode not in (None, "hybrid"):
        print(
            "--enable-rerank requires hybrid retrieval. "
            "Omit --retrieval-mode or pass --retrieval-mode hybrid.",
            file=sys.stderr,
        )
        return 2
    if args.embedder is None:
        args.embedder = GEMINI_EMBEDDER_NAME if args.generation else LOCAL_EMBEDDER_NAME
    if args.generation and args.embedder != GEMINI_EMBEDDER_NAME:
        print(
            "Generation evaluation requires the production Gemini LLM path. "
            "Re-run with --generation (defaults to --embedder gemini).",
            file=sys.stderr,
        )
        return 2
    if args.judge and not args.generation:
        print("--judge requires --generation.", file=sys.stderr)
        return 2
    if args.resume and not args.generation:
        print("--resume requires --generation.", file=sys.stderr)
        return 2
    if args.limit is not None and not args.generation:
        print("--limit requires --generation.", file=sys.stderr)
        return 2
    if args.start != 0 and not args.generation:
        print("--start requires --generation.", file=sys.stderr)
        return 2
    if args.start < 0:
        print("--start must be 0 or greater.", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit <= 0:
        print("--limit must be greater than 0.", file=sys.stderr)
        return 2
    if args.resume is not None and not args.resume.exists():
        print(f"Resume report not found: {args.resume}", file=sys.stderr)
        return 2

    dataset = load_dataset(args.dataset)
    dataset_version = str(dataset.get("version", "unknown"))
    chunk_size = settings.chunk_size if args.chunk_size is None else args.chunk_size
    chunk_overlap = settings.chunk_overlap if args.chunk_overlap is None else args.chunk_overlap
    chunking_strategy = (
        settings.chunking_strategy
        if args.chunking_strategy is None
        else normalize_chunking_strategy(args.chunking_strategy)
    )
    top_k = settings.rag_top_k if args.top_k is None else args.top_k
    try:
        embedding_service = embedding_service_for(args.embedder, settings)
    except AIConfigurationError as exc:
        print(
            "Gemini evaluation is not configured. Set GEMINI_API_KEY, "
            "EMBEDDING_MODEL, and EMBEDDING_DIMENSION to the same values used "
            f"by production RAG. ({exc})",
            file=sys.stderr,
        )
        return 2
    if args.similarity_threshold is not None:
        threshold = args.similarity_threshold
    elif args.embedder == LOCAL_EMBEDDER_NAME:
        threshold = 0.0
    else:
        threshold = settings.rag_similarity_threshold
    embedding_model = embedding_model_label(args.embedder, settings)

    _quiet_app_loggers()
    if args.generation:
        print(
            "PRODUCTION GENERATION EVALUATION: "
            f"embedding={embedding_model} dim={settings.embedding_dimension}, "
            f"llm={settings.llm_model}."
        )
        print()
    elif args.embedder == LOCAL_EMBEDDER_NAME and args.similarity_threshold is None:
        print(
            "OFFLINE / LOCAL EMBEDDER: ranking uses similarity_threshold=0.0. "
            "This is not a production RAG score. "
            f"Production RAG_SIMILARITY_THRESHOLD={settings.rag_similarity_threshold} "
            f"and EMBEDDING_MODEL={settings.embedding_model}."
        )
        print()
    elif args.embedder == GEMINI_EMBEDDER_NAME:
        print(
            "PRODUCTION EMBEDDING BASELINE: "
            f"model={embedding_model}, dimension={settings.embedding_dimension}."
        )
        print()

    try:
        check_connection()
    except Exception:
        logger.exception("Evaluation requires PostgreSQL")
        print("PostgreSQL is not available. Start the stack and retry.", file=sys.stderr)
        return 1

    session = SessionLocal()
    payload: dict = {"runs": []}
    generation_output: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="rag-eval-") as storage_path:
            if args.generation:
                if args.no_save:
                    generation_output = None
                elif args.output is not None:
                    generation_output = args.output
                elif args.resume is not None:
                    generation_output = args.resume
                else:
                    generation_output = default_report_path(args.embedder, kind="generation")
                payload = _run_generation(
                    args=args,
                    session=session,
                    settings=settings,
                    dataset=dataset,
                    dataset_version=dataset_version,
                    embedding_service=embedding_service,
                    embedding_model=embedding_model,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    chunking_strategy=chunking_strategy,
                    top_k=top_k,
                    threshold=threshold,
                    storage_path=storage_path,
                    output_path=generation_output,
                )
            elif args.compare_chunks:
                rows = []
                for size, overlap in CHUNK_EXPERIMENTS:
                    evaluator = _evaluator(
                        session,
                        settings,
                        embedding_service,
                        storage_path,
                        size,
                        overlap,
                        chunking_strategy,
                    )
                    document_ids = evaluator.ingest_corpus()
                    metrics = evaluator.evaluate(
                        dataset,
                        document_ids,
                        top_k=top_k,
                        similarity_threshold=threshold,
                    )
                    rows.append(
                        {
                            "chunk_size": size,
                            "chunk_overlap": overlap,
                            "hit_at_1": metrics.hit_at_1,
                            "hit_at_3": metrics.hit_at_3,
                            "hit_at_5": metrics.hit_at_5,
                            "recall_at_5": metrics.recall_at_5,
                            "span_hit_at_5": metrics.span_hit_at_5,
                        }
                    )
                    payload["runs"].append(
                        metrics_to_dict(
                            metrics,
                            chunk_size=size,
                            chunk_overlap=overlap,
                            chunking_strategy=chunking_strategy,
                            top_k=top_k,
                            similarity_threshold=threshold,
                            embedder=args.embedder,
                            embedding_model=embedding_model,
                            dataset_version=dataset_version,
                        )
                    )
                    session.rollback()
                print(format_chunk_comparison(rows), end="")
            elif args.compare_retrieval:
                evaluator = _evaluator(
                    session,
                    settings,
                    embedding_service,
                    storage_path,
                    chunk_size,
                    chunk_overlap,
                    chunking_strategy,
                )
                document_ids = evaluator.ingest_corpus()
                ranked = evaluator.rank_all(dataset, document_ids)
                rows = []
                for candidate_k in TOP_K_EXPERIMENTS:
                    for candidate_threshold in THRESHOLD_EXPERIMENTS:
                        metrics = evaluator.metrics_from_ranking(
                            dataset,
                            ranked,
                            top_k=candidate_k,
                            similarity_threshold=candidate_threshold,
                        )
                        rows.append(
                            {
                                "top_k": candidate_k,
                                "similarity_threshold": candidate_threshold,
                                "hit_at_1": metrics.hit_at_1,
                                "hit_at_3": metrics.hit_at_3,
                                "hit_at_5": metrics.hit_at_5,
                                "recall_at_5": metrics.recall_at_5,
                                "no_context_correct": metrics.no_context_correct,
                                "no_context_total": metrics.no_context_total,
                                "mrr": metrics.mrr,
                                "average_similarity": metrics.average_similarity,
                            }
                        )
                        payload["runs"].append(
                            metrics_to_dict(
                                metrics,
                                chunk_size=chunk_size,
                                chunk_overlap=chunk_overlap,
                                chunking_strategy=chunking_strategy,
                                top_k=candidate_k,
                                similarity_threshold=candidate_threshold,
                                embedder=args.embedder,
                                embedding_model=embedding_model,
                                dataset_version=dataset_version,
                            )
                        )
                print(format_retrieval_comparison(rows), end="")
            elif args.compare_chunking_strategies:
                rows = []
                for strategy in STRATEGY_EXPERIMENTS:
                    evaluator = _evaluator(
                        session,
                        settings,
                        embedding_service,
                        storage_path,
                        chunk_size,
                        chunk_overlap,
                        strategy,
                    )
                    document_ids = evaluator.ingest_corpus()
                    stats = evaluator.chunk_stats(document_ids)
                    metrics = evaluator.evaluate(
                        dataset,
                        document_ids,
                        top_k=top_k,
                        similarity_threshold=threshold,
                    )
                    rows.append(
                        {
                            "chunking_strategy": strategy,
                            "chunk_size": chunk_size,
                            "chunk_overlap": chunk_overlap,
                            "hit_at_1": metrics.hit_at_1,
                            "hit_at_3": metrics.hit_at_3,
                            "hit_at_5": metrics.hit_at_5,
                            "recall_at_5": metrics.recall_at_5,
                            "span_hit_at_5": metrics.span_hit_at_5,
                            "total_chunk_count": stats["total_chunk_count"],
                            "average_words_per_chunk": stats["average_words_per_chunk"],
                            "per_document": stats["per_document"],
                            "average_retrieval_ms": evaluator.average_retrieval_ms,
                            "span_questions": _span_question_details(metrics),
                        }
                    )
                    payload["runs"].append(
                        metrics_to_dict(
                            metrics,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            chunking_strategy=strategy,
                            top_k=top_k,
                            similarity_threshold=threshold,
                            embedder=args.embedder,
                            embedding_model=embedding_model,
                            dataset_version=dataset_version,
                            chunk_stats=stats,
                        )
                    )
                    session.rollback()
                print(format_strategy_comparison(rows), end="")
                print(format_span_inspection(rows), end="")
            elif args.compare_metadata_filters:
                evaluator = _evaluator(
                    session,
                    settings,
                    embedding_service,
                    storage_path,
                    chunk_size,
                    chunk_overlap,
                    chunking_strategy,
                )
                document_ids = evaluator.ingest_corpus()
                stats = evaluator.chunk_stats(document_ids)
                unfiltered = evaluator.evaluate(
                    dataset,
                    document_ids,
                    top_k=top_k,
                    similarity_threshold=threshold,
                )
                print(
                    format_report(
                        unfiltered,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        chunking_strategy=chunking_strategy,
                        top_k=top_k,
                        similarity_threshold=threshold,
                        embedder=args.embedder,
                        embedding_model=embedding_model,
                        dataset_version=dataset_version,
                        chunk_stats=stats,
                    ),
                    end="",
                )
                case_results = evaluator.evaluate_filter_cases(
                    document_ids,
                    FILTER_CASES,
                    top_k=top_k,
                    similarity_threshold=threshold,
                )
                print(
                    format_metadata_filter_comparison(
                        case_results,
                        average_retrieval_ms=evaluator.average_retrieval_ms,
                    ),
                    end="",
                )
                payload = {
                    "unfiltered": metrics_to_dict(
                        unfiltered,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        chunking_strategy=chunking_strategy,
                        top_k=top_k,
                        similarity_threshold=threshold,
                        embedder=args.embedder,
                        embedding_model=embedding_model,
                        dataset_version=dataset_version,
                        chunk_stats=stats,
                    ),
                    "filter_cases": [
                        {
                            "id": item.question_id,
                            "question": item.question,
                            "expect_no_context": item.expect_no_context,
                            "hit_at_1": item.hit_at_1,
                            "hit_at_3": item.hit_at_3,
                            "hit_at_5": item.hit_at_5,
                            "recall_at_5": item.recall_at_5,
                            "span_hit_at_5": item.span_hit_at_5,
                            "retrieved_count": item.retrieved_count,
                            "no_context_correct": item.no_context_correct,
                            "top1_similarity": item.top1_similarity,
                            "retrieved": item.retrieved,
                        }
                        for item in case_results
                    ],
                    "average_retrieval_ms": evaluator.average_retrieval_ms,
                }
            elif args.compare_retrieval_modes:
                evaluator = _evaluator(
                    session,
                    settings,
                    embedding_service,
                    storage_path,
                    chunk_size,
                    chunk_overlap,
                    chunking_strategy,
                )
                document_ids = evaluator.ingest_corpus()
                stats = evaluator.chunk_stats(document_ids)
                rows = []
                mode_metrics = {}
                for mode in EVAL_RETRIEVAL_MODES:
                    metrics = evaluator.evaluate(
                        dataset,
                        document_ids,
                        top_k=top_k,
                        similarity_threshold=threshold,
                        retrieval_mode=mode,
                    )
                    retrieved_counts = [
                        item.retrieved_count for item in metrics.question_results
                    ]
                    average_retrieved = (
                        None
                        if not retrieved_counts
                        else sum(retrieved_counts) / len(retrieved_counts)
                    )
                    rows.append(
                        {
                            "retrieval_mode": mode,
                            "hit_at_1": metrics.hit_at_1,
                            "hit_at_3": metrics.hit_at_3,
                            "hit_at_5": metrics.hit_at_5,
                            "recall_at_5": metrics.recall_at_5,
                            "span_hit_at_5": metrics.span_hit_at_5,
                            "average_retrieved_count": average_retrieved,
                            "average_retrieval_ms": evaluator.average_retrieval_ms,
                        }
                    )
                    mode_metrics[mode] = metrics
                    payload.setdefault("runs", []).append(
                        metrics_to_dict(
                            metrics,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            chunking_strategy=chunking_strategy,
                            top_k=top_k,
                            similarity_threshold=threshold,
                            embedder=args.embedder,
                            embedding_model=embedding_model,
                            dataset_version=dataset_version,
                            chunk_stats=stats,
                            retrieval_mode=mode,
                            average_retrieval_ms=evaluator.average_retrieval_ms,
                        )
                    )
                outcomes = retrieval_mode_outcomes(
                    mode_metrics["dense"],
                    mode_metrics["lexical"],
                    mode_metrics["hybrid"],
                )
                print(format_retrieval_mode_comparison(rows, outcomes), end="")
                payload["outcomes"] = outcomes
                payload["chunk_stats"] = stats
            elif args.compare_reranking:
                evaluator = _evaluator(
                    session,
                    settings,
                    embedding_service,
                    storage_path,
                    chunk_size,
                    chunk_overlap,
                    chunking_strategy,
                )
                document_ids = evaluator.ingest_corpus()
                stats = evaluator.chunk_stats(document_ids)
                rows = []
                mode_metrics = {}
                runs = (
                    ("dense", "dense", False),
                    ("hybrid", "hybrid", False),
                    ("hybrid+rerank", "hybrid", True),
                )
                for label, mode, enable_rerank in runs:
                    metrics = evaluator.evaluate(
                        dataset,
                        document_ids,
                        top_k=top_k,
                        similarity_threshold=threshold,
                        retrieval_mode=mode,
                        enable_rerank=enable_rerank,
                    )
                    retrieved_counts = [
                        item.retrieved_count for item in metrics.question_results
                    ]
                    average_retrieved = (
                        None
                        if not retrieved_counts
                        else sum(retrieved_counts) / len(retrieved_counts)
                    )
                    rows.append(
                        {
                            "retrieval_mode": label,
                            "hit_at_1": metrics.hit_at_1,
                            "hit_at_3": metrics.hit_at_3,
                            "hit_at_5": metrics.hit_at_5,
                            "recall_at_5": metrics.recall_at_5,
                            "span_hit_at_5": metrics.span_hit_at_5,
                            "average_retrieved_count": average_retrieved,
                            "average_retrieval_ms": evaluator.average_retrieval_ms,
                            "average_rerank_ms": evaluator.average_rerank_ms,
                        }
                    )
                    mode_metrics[label] = metrics
                    payload.setdefault("runs", []).append(
                        metrics_to_dict(
                            metrics,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            chunking_strategy=chunking_strategy,
                            top_k=top_k,
                            similarity_threshold=threshold,
                            embedder=args.embedder,
                            embedding_model=embedding_model,
                            dataset_version=dataset_version,
                            chunk_stats=stats,
                            retrieval_mode=label,
                            average_retrieval_ms=evaluator.average_retrieval_ms,
                            average_rerank_ms=evaluator.average_rerank_ms,
                        )
                    )
                highlights = _rerank_highlights(mode_metrics)
                print(format_reranking_comparison(rows, question_highlights=highlights), end="")
                payload["highlights"] = highlights
                payload["chunk_stats"] = stats
            else:
                evaluator = _evaluator(
                    session,
                    settings,
                    embedding_service,
                    storage_path,
                    chunk_size,
                    chunk_overlap,
                    chunking_strategy,
                )
                document_ids = evaluator.ingest_corpus()
                stats = evaluator.chunk_stats(document_ids)
                enable_rerank = bool(args.enable_rerank)
                retrieval_mode = args.retrieval_mode or ("hybrid" if enable_rerank else "dense")
                metrics = evaluator.evaluate(
                    dataset,
                    document_ids,
                    top_k=top_k,
                    similarity_threshold=threshold,
                    retrieval_mode=retrieval_mode,
                    enable_rerank=enable_rerank,
                )
                report_mode = "hybrid+rerank" if enable_rerank else retrieval_mode
                report = format_report(
                    metrics,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    chunking_strategy=chunking_strategy,
                    top_k=top_k,
                    similarity_threshold=threshold,
                    embedder=args.embedder,
                    embedding_model=embedding_model,
                    dataset_version=dataset_version,
                    chunk_stats=stats,
                    retrieval_mode=report_mode,
                    average_retrieval_ms=evaluator.average_retrieval_ms,
                    average_rerank_ms=evaluator.average_rerank_ms,
                )
                print(report, end="")
                payload = metrics_to_dict(
                    metrics,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    chunking_strategy=chunking_strategy,
                    top_k=top_k,
                    similarity_threshold=threshold,
                    embedder=args.embedder,
                    embedding_model=embedding_model,
                    dataset_version=dataset_version,
                    chunk_stats=stats,
                    retrieval_mode=report_mode,
                    average_retrieval_ms=evaluator.average_retrieval_ms,
                    average_rerank_ms=evaluator.average_rerank_ms,
                )
        if args.generation:
            if generation_output is not None:
                print(f"Wrote JSON report to {generation_output}")
            status = payload.get("status")
            if status == STATUS_COMPLETE:
                return 0
            if status == STATUS_PARTIAL:
                print(
                    "Generation evaluation is PARTIAL.\n"
                    f"{payload.get('completed_questions', 0)}/"
                    f"{payload.get('dataset_questions', 0)} questions completed.\n"
                    "Do not interpret aggregate generation metrics as final.",
                    file=sys.stderr,
                )
                return 3
            if status == STATUS_FAILED:
                print(
                    "Generation evaluation FAILED before any question completed.",
                    file=sys.stderr,
                )
                return 1
            return 0
        if args.check_baseline:
            target_metrics = metrics if "metrics" in locals() else None
            if target_metrics is None:
                print("Cannot check baseline: no retrieval metrics evaluated in this run mode.", file=sys.stderr)
                return 2
            passed, errors = check_baseline(target_metrics, dataset_path=args.dataset)
            if not passed:
                print("\nBASELINE REGRESSION CHECK FAILED:", file=sys.stderr)
                for err in errors:
                    print(f"  {err}", file=sys.stderr)
                return 1
            print("\nBASELINE REGRESSION CHECK PASSED: All metrics meet or exceed baseline.")
        if not args.no_save:
            output = args.output or default_report_path(args.embedder)
            write_json_report(payload, output)
            print(f"Wrote JSON report to {output}")
        return 0
    except AIConfigurationError as exc:
        print(
            "Gemini evaluation is not configured. Set GEMINI_API_KEY, "
            "EMBEDDING_MODEL, and LLM_MODEL to match production. "
            f"({exc})",
            file=sys.stderr,
        )
        return 2
    except AIProviderError:
        logger.exception("Gemini request failed")
        print(
            "Gemini request failed. Evaluation did not finish. "
            "Production chat settings were not changed.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        logger.exception("Evaluation failed")
        print("Evaluation failed. See logs for details.", file=sys.stderr)
        return 1
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
