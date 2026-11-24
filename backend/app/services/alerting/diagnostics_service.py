"""Platform Self-Diagnostics Service.

Performs deterministic diagnosis from operational alerts and telemetry observations,
distinguishing observed facts from inferred correlations without claiming root cause.
"""

from __future__ import annotations

from typing import Any

from app.db.models import PlatformAlert
from app.schemas.alert import DiagnosticEvidence
from app.services.alerting.taxonomy import (
    AlertMetricName,
    AlertType,
    DiagnosticCategory,
    InvestigationTarget,
    PlatformSubsystem,
)
from app.services.tracing.taxonomy import SpanName


class PlatformDiagnosticsService:
    """Deterministic diagnostic engine for platform alerts and telemetry observations."""

    @classmethod
    def diagnose_alert(
        cls,
        alert: PlatformAlert,
        *,
        telemetry_context: dict[str, Any] | None = None,
    ) -> DiagnosticEvidence:
        """Produce deterministic diagnostic explanation from an active or historical alert."""
        meta = alert.metadata_ or {}
        context = telemetry_context or meta.get("diagnostic_context") or {}

        alert_type = alert.alert_type
        metric_name = alert.metric_name or ""
        metric_val = alert.metric_value
        thresh_val = alert.threshold_value

        sample_trace_id = meta.get("sample_trace_id") or context.get("sample_trace_id")
        sample_request_id = meta.get("sample_request_id") or context.get("sample_request_id")
        sample_size = meta.get("sample_size") or context.get("sample_size") or 0
        window_minutes = meta.get("window_minutes") or context.get("window_minutes") or 15

        evidence: dict[str, Any] = {
            "metric_name": metric_name,
            "metric_value": metric_val,
            "threshold_value": thresh_val,
            "sample_size": sample_size,
            "window_minutes": window_minutes,
            "sample_trace_id": sample_trace_id,
            "sample_request_id": sample_request_id,
        }

        # Merge additional safe numerical signals
        for k in ("baseline_value", "deviation_ratio", "provider", "model", "dominant_span_duration_ms"):
            if k in meta:
                evidence[k] = meta[k]
            elif k in context:
                evidence[k] = context[k]

        # Case 1: LLM Latency or LLM slow
        if alert_type == AlertType.LLM_SLOW or metric_name == AlertMetricName.LLM_LATENCY_P95:
            provider = evidence.get("provider", "configured AI provider")
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.LATENCY.value,
                dominant_stage=SpanName.LLM_GENERATION.value,
                subsystem=PlatformSubsystem.AI_PROVIDER.value,
                observed=f"Observed elevated p95 LLM generation latency of {metric_val:.1f}ms exceeding threshold {thresh_val:.1f}ms.",
                inferred=f"Inferred latency concentration within LLM generation stage; upstream retrieval completed within normal tolerances. Downstream {provider} responsiveness is the primary contributing factor.",
                evidence=evidence,
                investigation_target=InvestigationTarget.AI_PROVIDER_METRICS.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 2: Retrieval slow or degradation
        if (
            alert_type in (AlertType.RETRIEVAL_SLOW, AlertType.RETRIEVAL_DEGRADATION)
            or metric_name in (AlertMetricName.RETRIEVAL_LATENCY_P95, AlertMetricName.ZERO_RESULT_RATE)
        ):
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.RETRIEVAL_QUALITY.value if "DEGRADATION" in alert_type else DiagnosticCategory.LATENCY.value,
                dominant_stage=SpanName.DENSE_RETRIEVAL.value,
                subsystem=PlatformSubsystem.RETRIEVAL_ENGINE.value,
                observed=f"Observed elevated retrieval latency/degradation ({metric_name}={metric_val}) relative to operational threshold ({thresh_val}).",
                inferred="Inferred possible vector index search latency or degraded chunk matching efficiency under current tenant query volume.",
                evidence=evidence,
                investigation_target=InvestigationTarget.RETRIEVAL_INDEX_HEALTH.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 3: Reranker slow
        if alert_type == AlertType.RERANKER_SLOW or metric_name == AlertMetricName.RERANKER_LATENCY_P95:
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.LATENCY.value,
                dominant_stage=SpanName.RERANKING.value,
                subsystem=PlatformSubsystem.AI_PROVIDER.value,
                observed=f"Observed elevated reranker latency of {metric_val:.1f}ms exceeding threshold of {thresh_val:.1f}ms.",
                inferred="Inferred execution bottleneck during two-stage cross-encoder re-ranking pass.",
                evidence=evidence,
                investigation_target=InvestigationTarget.AI_PROVIDER_METRICS.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 4: High Total Latency / Latency Regression
        if alert_type in (AlertType.LATENCY_HIGH, AlertType.LATENCY_REGRESSION) or metric_name == AlertMetricName.TOTAL_LATENCY_P95:
            # Check if context tells us dominant stage
            dom_stage = context.get("dominant_stage", SpanName.LLM_GENERATION.value)
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.LATENCY.value,
                dominant_stage=dom_stage,
                subsystem=PlatformSubsystem.AI_PROVIDER.value if dom_stage == SpanName.LLM_GENERATION.value else PlatformSubsystem.SYSTEM.value,
                observed=f"Observed total end-to-end request latency (p95={metric_val:.1f}ms) breaching operational limit of {thresh_val:.1f}ms.",
                inferred=f"Inferred cumulative pipeline latency heavily dominated by stage '{dom_stage}'.",
                evidence=evidence,
                investigation_target=InvestigationTarget.AI_PROVIDER_METRICS.value if dom_stage == SpanName.LLM_GENERATION.value else InvestigationTarget.SYSTEM_DIAGNOSTICS.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 5: Error rates & provider spikes
        if alert_type in (
            AlertType.LLM_ERROR_RATE_HIGH,
            AlertType.EMBEDDING_ERROR_RATE_HIGH,
            AlertType.PROVIDER_FAILURE_SPIKE,
        ) or metric_name in (
            AlertMetricName.LLM_ERROR_RATE,
            AlertMetricName.EMBEDDING_ERROR_RATE,
            AlertMetricName.PROVIDER_ERROR_RATE,
        ):
            stage = SpanName.EMBEDDING.value if "EMBEDDING" in alert_type else SpanName.LLM_GENERATION.value
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.PROVIDER_OUTAGE.value,
                dominant_stage=stage,
                subsystem=PlatformSubsystem.AI_PROVIDER.value,
                observed=f"Observed failure rate of {metric_val:.1f}% on AI provider interactions exceeding threshold of {thresh_val:.1f}%.",
                inferred="Inferred downstream external API connectivity, rate limit or status failure during model invocation.",
                evidence=evidence,
                investigation_target=InvestigationTarget.AI_PROVIDER_METRICS.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 6: Database / Audit / Trace Persistence failures
        if alert_type in (
            AlertType.DATABASE_ERROR_RATE_HIGH,
            AlertType.TRACE_PERSISTENCE_FAILURE,
            AlertType.AUDIT_PERSISTENCE_FAILURE,
        ) or metric_name == AlertMetricName.DATABASE_ERROR_RATE:
            sub = (
                PlatformSubsystem.AUDIT_SUBSYSTEM.value
                if "AUDIT" in alert_type
                else PlatformSubsystem.TRACING_SUBSYSTEM.value
                if "TRACE" in alert_type
                else PlatformSubsystem.DATABASE.value
            )
            target = (
                InvestigationTarget.AUDIT_STORAGE.value
                if "AUDIT" in alert_type
                else InvestigationTarget.TRACE_STORAGE.value
                if "TRACE" in alert_type
                else InvestigationTarget.DATABASE_CONNECTIONS.value
            )
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.DATA_INTEGRITY.value,
                dominant_stage=SpanName.MESSAGE_PERSISTENCE.value,
                subsystem=sub,
                observed=f"Observed persistence or transactional error rate of {metric_val:.1f}% breaching threshold {thresh_val:.1f}%.",
                inferred="Inferred database connection exhaustion, query failure, or transactional integrity constraint conflict.",
                evidence=evidence,
                investigation_target=target,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 7: Stream TTFT or Streaming failure
        if alert_type in (AlertType.STREAM_TTFT_HIGH, AlertType.STREAM_FAILURE_RATE_HIGH) or metric_name == AlertMetricName.TTFT_P95:
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.LATENCY.value if "TTFT" in alert_type else DiagnosticCategory.ERROR_RATE.value,
                dominant_stage=SpanName.STREAM_GENERATION.value,
                subsystem=PlatformSubsystem.STREAMING_PIPELINE.value,
                observed=f"Observed streaming metric ({metric_name}={metric_val:.1f}) breaching operational threshold ({thresh_val:.1f}).",
                inferred="Inferred delayed chunk delivery or premature client disconnection during server-sent event streaming.",
                evidence=evidence,
                investigation_target=InvestigationTarget.NETWORK_STREAMING.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 8: No context rate high
        if alert_type == AlertType.NO_CONTEXT_RATE_HIGH or metric_name == AlertMetricName.NO_CONTEXT_RATE:
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.RETRIEVAL_QUALITY.value,
                dominant_stage=SpanName.CONTEXT_BUILD.value,
                subsystem=PlatformSubsystem.RETRIEVAL_ENGINE.value,
                observed=f"Observed elevated no-context generation rate of {metric_val:.1f}% exceeding threshold of {thresh_val:.1f}%.",
                inferred="Inferred semantic mismatch between submitted questions and indexed workspace corpus or restrictive similarity thresholds.",
                evidence=evidence,
                investigation_target=InvestigationTarget.RETRIEVAL_INDEX_HEALTH.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Case 9: Anomaly Detected
        if alert_type == AlertType.ANOMALY_DETECTED:
            baseline = evidence.get("baseline_value", 0.0)
            ratio = evidence.get("deviation_ratio", 1.0)
            return DiagnosticEvidence(
                diagnosis_category=DiagnosticCategory.ANOMALOUS_DRIFT.value,
                dominant_stage=None,
                subsystem=PlatformSubsystem.SYSTEM.value,
                observed=f"Observed metric '{metric_name}' value {metric_val:.2f} deviating by {ratio:.2f}x against historical baseline of {baseline:.2f}.",
                inferred="Inferred statistically significant operational variance from typical historical rolling baseline.",
                evidence=evidence,
                investigation_target=InvestigationTarget.SYSTEM_DIAGNOSTICS.value,
                sample_trace_id=sample_trace_id,
                sample_request_id=sample_request_id,
            )

        # Fallback generic diagnostic
        return DiagnosticEvidence(
            diagnosis_category=DiagnosticCategory.LATENCY.value,
            dominant_stage=None,
            subsystem=PlatformSubsystem.SYSTEM.value,
            observed=f"Observed condition on '{metric_name}' value {metric_val} vs threshold {thresh_val}.",
            inferred="Inferred operational excursion based on active rule criteria.",
            evidence=evidence,
            investigation_target=InvestigationTarget.SYSTEM_DIAGNOSTICS.value,
            sample_trace_id=sample_trace_id,
            sample_request_id=sample_request_id,
        )
