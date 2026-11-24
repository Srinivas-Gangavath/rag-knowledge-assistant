"""Alert Evaluation Service for threshold checking, anomaly detection, cooldown, and deduplication."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.workspace_context import WorkspaceContext
from app.db.models import (
    AlertOperator,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AuditEventType,
    AuditOutcome,
    OrganizationRole,
    PlatformAlert,
    QueryTrace,
    QueryTraceSpan,
    Workspace,
    WorkspaceRole,
)
from app.schemas.alert import (
    AlertEvaluationResponse,
    AlertEvaluationResultItem,
)
from app.services.alerting.anomaly_service import AnomalyDetectionService
from app.services.alerting.diagnostics_service import PlatformDiagnosticsService
from app.services.alerting.taxonomy import (
    AlertMetricName,
    AlertType,
    DiagnosticCategory,
    InvestigationTarget,
    PlatformSubsystem,
)
from app.services.audit_service import AuditLogService
from app.services.tracing.analytics_service import (
    GENERATION_SPANS,
    RETRIEVAL_SPANS,
    _calculate_percentiles,
)
from app.services.tracing.taxonomy import SpanName, TraceStatus

logger = get_logger(__name__)


def _evaluate_operator(op: str, val: float, threshold: float) -> bool:
    """Evaluate comparison operator safely."""
    op_upper = op.upper()
    if op_upper == AlertOperator.GT.value:
        return val > threshold
    if op_upper == AlertOperator.GTE.value:
        return val >= threshold
    if op_upper == AlertOperator.LT.value:
        return val < threshold
    if op_upper == AlertOperator.LTE.value:
        return val <= threshold
    if op_upper == AlertOperator.EQ.value:
        return abs(val - threshold) < 1e-5
    return False


class AlertEvaluationService:
    """Evaluates telemetry against active rules and baseline anomalies without background workers."""

    @staticmethod
    def _verify_evaluation_access(
        context: WorkspaceContext,
        target_workspace_id: UUID | None = None,
    ) -> None:
        """Enforce role permissions for manual or operator-triggered evaluation."""
        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        is_ws_admin = context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN

        if not is_org_admin and not is_ws_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Manual alert evaluation requires Workspace Admin or Organization Admin privileges.",
            )

        if not is_org_admin and is_ws_admin:
            if target_workspace_id is not None and target_workspace_id != context.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin is restricted to evaluating alerts in their active workspace.",
                )

    @classmethod
    def evaluate(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        workspace_id: UUID | None = None,
    ) -> AlertEvaluationResponse:
        """Evaluate operational telemetry against rules and statistical baselines for an organization/workspace."""
        effective_ws_id = workspace_id if workspace_id is not None else (
            context.workspace_id if context.organization_role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN} else None
        )

        cls._verify_evaluation_access(context, target_workspace_id=effective_ws_id)
        settings = get_settings()
        now = datetime.now(timezone.utc)

        # 1. Fetch enabled rules for this scope
        rule_stmt = select(AlertRule).where(
            AlertRule.organization_id == context.organization_id,
            AlertRule.enabled.is_(True),
        )
        if effective_ws_id is not None:
            rule_stmt = rule_stmt.where(
                (AlertRule.workspace_id == effective_ws_id) | (AlertRule.workspace_id.is_(None))
            )
        db_rules = list(session.scalars(rule_stmt).all())

        # Construct evaluation candidates
        # If DB rules exist for a metric, prefer the DB rule; otherwise apply configured defaults
        db_metrics = {r.metric_name for r in db_rules}

        candidate_rules: list[dict[str, Any]] = []
        for r in db_rules:
            candidate_rules.append({
                "rule_id": str(r.id),
                "rule_type": r.rule_type,
                "metric_name": r.metric_name,
                "operator": r.operator,
                "threshold": r.threshold,
                "window_minutes": r.window_minutes,
                "minimum_sample_size": r.minimum_sample_size,
                "severity": r.severity,
                "cooldown_minutes": r.cooldown_minutes,
                "workspace_id": r.workspace_id or effective_ws_id,
            })

        # Add default rules if not overridden in DB
        default_specs = [
            (
                AlertMetricName.TOTAL_LATENCY_P95.value,
                AlertType.LATENCY_HIGH.value,
                AlertOperator.GT.value,
                settings.trace_alert_p95_latency_ms,
                AlertSeverity.WARNING.value,
            ),
            (
                AlertMetricName.ERROR_RATE.value,
                AlertType.LLM_ERROR_RATE_HIGH.value,
                AlertOperator.GT.value,
                settings.trace_alert_error_rate_percent,
                AlertSeverity.ERROR.value,
            ),
            (
                AlertMetricName.LLM_LATENCY_P95.value,
                AlertType.LLM_SLOW.value,
                AlertOperator.GT.value,
                settings.trace_alert_llm_p95_ms,
                AlertSeverity.WARNING.value,
            ),
            (
                AlertMetricName.RETRIEVAL_LATENCY_P95.value,
                AlertType.RETRIEVAL_SLOW.value,
                AlertOperator.GT.value,
                settings.trace_alert_retrieval_p95_ms,
                AlertSeverity.WARNING.value,
            ),
            (
                AlertMetricName.TTFT_P95.value,
                AlertType.STREAM_TTFT_HIGH.value,
                AlertOperator.GT.value,
                settings.trace_alert_ttft_p95_ms,
                AlertSeverity.WARNING.value,
            ),
            (
                AlertMetricName.PROVIDER_ERROR_RATE.value,
                AlertType.PROVIDER_FAILURE_SPIKE.value,
                AlertOperator.GT.value,
                settings.trace_alert_provider_error_percent,
                AlertSeverity.ERROR.value,
            ),
            (
                AlertMetricName.NO_CONTEXT_RATE.value,
                AlertType.NO_CONTEXT_RATE_HIGH.value,
                AlertOperator.GT.value,
                settings.trace_alert_no_context_percent,
                AlertSeverity.WARNING.value,
            ),
        ]

        for metric, alert_t, op, thresh, sev in default_specs:
            if metric not in db_metrics:
                candidate_rules.append({
                    "rule_id": None,
                    "rule_type": alert_t,
                    "metric_name": metric,
                    "operator": op,
                    "threshold": thresh,
                    "window_minutes": settings.alert_default_window_minutes,
                    "minimum_sample_size": settings.alert_default_min_sample_size,
                    "severity": sev,
                    "cooldown_minutes": settings.alert_default_cooldown_minutes,
                    "workspace_id": effective_ws_id,
                })

        rules_evaluated_count = len(candidate_rules)
        alerts_created = 0
        alerts_updated = 0
        anomalies_detected = 0
        result_items: list[AlertEvaluationResultItem] = []

        # 2. Evaluate each rule
        for candidate in candidate_rules:
            w_mins = candidate["window_minutes"]
            from_time = now - timedelta(minutes=w_mins)
            rule_ws = candidate["workspace_id"]

            # Query traces for this window
            trace_q = select(QueryTrace).where(
                QueryTrace.organization_id == context.organization_id,
                QueryTrace.started_at >= from_time,
            )
            if rule_ws is not None:
                trace_q = trace_q.where(QueryTrace.workspace_id == rule_ws)

            traces = list(session.scalars(trace_q.options(selectinload(QueryTrace.spans))).all())
            sample_size = len(traces)
            min_sample = candidate["minimum_sample_size"]

            # Compute metric value based on metric_name
            metric_name = candidate["metric_name"]
            metric_val: float | None = None
            sample_trace_id: str | None = traces[-1].trace_id if traces else None
            sample_request_id: str | None = traces[-1].request_id if traces else None

            if metric_name == AlertMetricName.TOTAL_LATENCY_P95.value:
                lats = [t.total_latency_ms for t in traces if t.total_latency_ms is not None]
                _, _, p95, _, _ = _calculate_percentiles(lats)
                metric_val = p95
            elif metric_name == AlertMetricName.ERROR_RATE.value:
                err_count = sum(1 for t in traces if t.status == TraceStatus.ERROR.value)
                metric_val = (err_count / sample_size * 100.0) if sample_size > 0 else 0.0
            elif metric_name == AlertMetricName.LLM_LATENCY_P95.value:
                llm_spans = [
                    s.duration_ms for t in traces for s in (t.spans or [])
                    if s.span_name in GENERATION_SPANS and s.duration_ms is not None
                ]
                _, _, p95, _, _ = _calculate_percentiles(llm_spans)
                metric_val = p95
            elif metric_name == AlertMetricName.RETRIEVAL_LATENCY_P95.value:
                ret_spans = [
                    s.duration_ms for t in traces for s in (t.spans or [])
                    if s.span_name in RETRIEVAL_SPANS and s.duration_ms is not None
                ]
                _, _, p95, _, _ = _calculate_percentiles(ret_spans)
                metric_val = p95
            elif metric_name == AlertMetricName.TTFT_P95.value:
                ttfts = [
                    float(s.metadata_["ttft_ms"])
                    for t in traces for s in (t.spans or [])
                    if s.span_name == SpanName.STREAM_GENERATION.value
                    and s.metadata_ and "ttft_ms" in s.metadata_
                ]
                _, _, p95, _, _ = _calculate_percentiles(ttfts)
                metric_val = p95
            elif metric_name == AlertMetricName.PROVIDER_ERROR_RATE.value:
                ai_spans = [
                    s for t in traces for s in (t.spans or [])
                    if s.span_name in GENERATION_SPANS or s.span_name == SpanName.EMBEDDING.value
                ]
                err_ai = sum(1 for s in ai_spans if s.status == TraceStatus.ERROR.value)
                metric_val = (err_ai / len(ai_spans) * 100.0) if ai_spans else 0.0
            elif metric_name == AlertMetricName.NO_CONTEXT_RATE.value:
                no_ctx_count = sum(
                    1 for t in traces
                    if t.grounded is False or (t.result_count is not None and t.result_count == 0)
                )
                metric_val = (no_ctx_count / sample_size * 100.0) if sample_size > 0 else 0.0
            elif metric_name == AlertMetricName.DATABASE_ERROR_RATE.value:
                db_spans = [
                    s for t in traces for s in (t.spans or [])
                    if s.span_name == SpanName.MESSAGE_PERSISTENCE.value or s.span_type == "DATABASE"
                ]
                err_db = sum(1 for s in db_spans if s.status == TraceStatus.ERROR.value)
                metric_val = (err_db / len(db_spans) * 100.0) if db_spans else 0.0

            # Minimum sample gate
            if sample_size < min_sample:
                result_items.append(
                    AlertEvaluationResultItem(
                        alert_id=None,
                        alert_type=candidate["rule_type"],
                        severity=candidate["severity"],
                        status="SKIPPED",
                        title=f"{candidate['rule_type']}: Insufficient samples",
                        metric_name=metric_name,
                        metric_value=metric_val,
                        threshold=candidate["threshold"],
                        action_taken="MINIMUM_SAMPLE_SIZE_GATE",
                    )
                )
                continue

            if metric_val is None:
                continue

            # Evaluate comparison
            is_breached = _evaluate_operator(candidate["operator"], metric_val, candidate["threshold"])

            if not is_breached:
                result_items.append(
                    AlertEvaluationResultItem(
                        alert_id=None,
                        alert_type=candidate["rule_type"],
                        severity=candidate["severity"],
                        status="OK",
                        title=f"{candidate['rule_type']}: Normal",
                        metric_name=metric_name,
                        metric_value=metric_val,
                        threshold=candidate["threshold"],
                        action_taken="NOOP",
                    )
                )
                continue

            # Alert breached! Build deduplication key
            alert_type_str = candidate["rule_type"]
            rule_id_str = candidate["rule_id"] or "default"
            ws_key = str(rule_ws) if rule_ws else "all"
            dedup_key = f"{context.organization_id}:{ws_key}:{alert_type_str}:{metric_name}:{rule_id_str}"

            # Check existing active alert within cooldown window
            existing_alert = session.scalars(
                select(PlatformAlert)
                .where(
                    PlatformAlert.deduplication_key == dedup_key,
                    PlatformAlert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
                )
                .order_by(PlatformAlert.detected_at.desc())
                .limit(1)
            ).first()

            cooldown_mins = candidate["cooldown_minutes"]
            if existing_alert is not None:
                elapsed_mins = (now - existing_alert.detected_at).total_seconds() / 60.0
                if elapsed_mins < cooldown_mins:
                    # Within cooldown window: suppress alert storm!
                    existing_alert.metric_value = metric_val
                    existing_alert.updated_at = now
                    alerts_updated += 1
                    result_items.append(
                        AlertEvaluationResultItem(
                            alert_id=existing_alert.id,
                            alert_type=alert_type_str,
                            severity=candidate["severity"],
                            status=existing_alert.status,
                            title=existing_alert.title,
                            metric_name=metric_name,
                            metric_value=metric_val,
                            threshold=candidate["threshold"],
                            action_taken="COOLDOWN_SUPPRESSED",
                        )
                    )
                    continue

            # Create new PlatformAlert
            title = f"{alert_type_str.replace('_', ' ').title()}: {metric_name} breached threshold"
            desc = (
                f"Metric '{metric_name}' value {metric_val:.2f} breached threshold "
                f"{candidate['operator']} {candidate['threshold']:.2f} over past {w_mins} minutes "
                f"({sample_size} samples)."
            )

            safe_meta = {
                "sample_trace_id": sample_trace_id,
                "sample_request_id": sample_request_id,
                "sample_size": sample_size,
                "window_minutes": w_mins,
                "rule_id": candidate["rule_id"],
                "operator": candidate["operator"],
            }

            alert = PlatformAlert(
                organization_id=context.organization_id,
                workspace_id=rule_ws,
                alert_type=alert_type_str,
                severity=candidate["severity"],
                status=AlertStatus.OPEN.value,
                title=title,
                description=desc,
                metric_name=metric_name,
                metric_value=metric_val,
                threshold_value=candidate["threshold"],
                detected_at=now,
                deduplication_key=dedup_key,
                metadata_=safe_meta,
            )
            session.add(alert)
            session.flush()  # populate alert.id

            # Emit Audit Log for ALERT_CREATED
            safe_audit_meta = {
                "alert_id": str(alert.id),
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "workspace_id": str(rule_ws) if rule_ws else None,
                "metric_name": metric_name,
                "metric_value": metric_val,
                "threshold_value": candidate["threshold"],
                "actor": str(context.user_id),
                "sample_trace_id": sample_trace_id,
                "sample_request_id": sample_request_id,
            }
            AuditLogService.record_event(
                session,
                organization_id=context.organization_id,
                workspace_id=rule_ws,
                actor_user_id=context.user_id,
                event_type=AuditEventType.ALERT_CREATED,
                action="ALERT_CREATED",
                outcome=AuditOutcome.SUCCESS,
                resource_type="platform_alert",
                resource_id=str(alert.id),
                metadata=safe_audit_meta,
            )

            alerts_created += 1
            result_items.append(
                AlertEvaluationResultItem(
                    alert_id=alert.id,
                    alert_type=alert.alert_type,
                    severity=alert.severity,
                    status=alert.status,
                    title=alert.title,
                    metric_name=metric_name,
                    metric_value=metric_val,
                    threshold=candidate["threshold"],
                    action_taken="CREATED",
                )
            )

        # 3. Anomaly Detection evaluation across historical baseline
        anomaly_result = cls._evaluate_anomalies(
            session,
            context,
            effective_ws_id=effective_ws_id,
            now=now,
            settings=settings,
        )
        if anomaly_result is not None:
            rules_evaluated_count += 1
            if anomaly_result.get("is_anomaly"):
                anomalies_detected += 1
                if anomaly_result.get("alert_created"):
                    alerts_created += 1
                result_items.append(anomaly_result["result_item"])

        session.commit()

        return AlertEvaluationResponse(
            evaluation_timestamp=now,
            rules_evaluated=rules_evaluated_count,
            alerts_created=alerts_created,
            alerts_updated=alerts_updated,
            anomalies_detected=anomalies_detected,
            details=result_items,
        )

    @classmethod
    def _evaluate_anomalies(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        effective_ws_id: UUID | None,
        now: datetime,
        settings: Any,
    ) -> dict[str, Any] | None:
        """Run statistical baseline anomaly detection on total request latency."""
        cur_window_mins = settings.alert_default_window_minutes
        cur_from = now - timedelta(minutes=cur_window_mins)
        hist_from = now - timedelta(days=1)  # 24 hours historical baseline

        base_q = select(QueryTrace.total_latency_ms).where(
            QueryTrace.organization_id == context.organization_id,
            QueryTrace.total_latency_ms.is_not(None),
        )
        if effective_ws_id is not None:
            base_q = base_q.where(QueryTrace.workspace_id == effective_ws_id)

        # Historical samples (up to 24h ago, excluding current window)
        hist_q = base_q.where(QueryTrace.started_at >= hist_from, QueryTrace.started_at < cur_from)
        hist_samples = [float(v) for v in session.scalars(hist_q).all()]

        # Current samples
        cur_q = base_q.where(QueryTrace.started_at >= cur_from)
        cur_samples = [float(v) for v in session.scalars(cur_q).all()]

        eval_res = AnomalyDetectionService.evaluate_metric(
            metric_name="total_latency_ms",
            current_samples=cur_samples,
            historical_samples=hist_samples,
            multiplier=settings.alert_anomaly_deviation_multiplier,
            minimum_sample_size=settings.alert_default_min_sample_size,
            window_minutes=cur_window_mins,
        )

        if not eval_res.is_anomaly:
            return None

        # Breach detected! Cooldown & Dedup check
        ws_key = str(effective_ws_id) if effective_ws_id else "all"
        dedup_key = f"{context.organization_id}:{ws_key}:{AlertType.ANOMALY_DETECTED.value}:total_latency_ms:default"

        existing = session.scalars(
            select(PlatformAlert)
            .where(
                PlatformAlert.deduplication_key == dedup_key,
                PlatformAlert.status.in_([AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value]),
            )
            .order_by(PlatformAlert.detected_at.desc())
            .limit(1)
        ).first()

        cooldown_mins = settings.alert_default_cooldown_minutes
        if existing is not None:
            elapsed_mins = (now - existing.detected_at).total_seconds() / 60.0
            if elapsed_mins < cooldown_mins:
                return {
                    "is_anomaly": True,
                    "alert_created": False,
                    "result_item": AlertEvaluationResultItem(
                        alert_id=existing.id,
                        alert_type=AlertType.ANOMALY_DETECTED.value,
                        severity=AlertSeverity.WARNING.value,
                        status=existing.status,
                        title=existing.title,
                        metric_name="total_latency_ms",
                        metric_value=eval_res.current_value,
                        threshold=eval_res.baseline_value * eval_res.multiplier,
                        action_taken="COOLDOWN_SUPPRESSED",
                    ),
                }

        title = f"Anomaly Detected: Latency increased by {eval_res.deviation_ratio}x"
        desc = (
            f"Observed total latency median ({eval_res.current_value:.1f}ms) breached statistical baseline "
            f"({eval_res.baseline_value:.1f}ms) by {eval_res.deviation_ratio:.2f}x over past {cur_window_mins}m "
            f"({eval_res.sample_size} current / {eval_res.historical_sample_size} historical samples)."
        )

        safe_meta = {
            "baseline_value": eval_res.baseline_value,
            "deviation_ratio": eval_res.deviation_ratio,
            "multiplier": eval_res.multiplier,
            "sample_size": eval_res.sample_size,
            "historical_sample_size": eval_res.historical_sample_size,
            "window_minutes": cur_window_mins,
        }

        alert = PlatformAlert(
            organization_id=context.organization_id,
            workspace_id=effective_ws_id,
            alert_type=AlertType.ANOMALY_DETECTED.value,
            severity=AlertSeverity.WARNING.value,
            status=AlertStatus.OPEN.value,
            title=title,
            description=desc,
            metric_name="total_latency_ms",
            metric_value=eval_res.current_value,
            threshold_value=eval_res.baseline_value * eval_res.multiplier,
            detected_at=now,
            deduplication_key=dedup_key,
            metadata_=safe_meta,
        )
        session.add(alert)
        session.flush()

        safe_audit_meta = {
            "alert_id": str(alert.id),
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "workspace_id": str(effective_ws_id) if effective_ws_id else None,
            "metric_name": "total_latency_ms",
            "metric_value": eval_res.current_value,
            "threshold_value": eval_res.baseline_value * eval_res.multiplier,
            "actor": str(context.user_id),
        }
        AuditLogService.record_event(
            session,
            organization_id=context.organization_id,
            workspace_id=effective_ws_id,
            actor_user_id=context.user_id,
            event_type=AuditEventType.ALERT_CREATED,
            action="ALERT_CREATED",
            outcome=AuditOutcome.SUCCESS,
            resource_type="platform_alert",
            resource_id=str(alert.id),
            metadata=safe_audit_meta,
        )

        return {
            "is_anomaly": True,
            "alert_created": True,
            "result_item": AlertEvaluationResultItem(
                alert_id=alert.id,
                alert_type=alert.alert_type,
                severity=alert.severity,
                status=alert.status,
                title=alert.title,
                metric_name="total_latency_ms",
                metric_value=eval_res.current_value,
                threshold=eval_res.baseline_value * eval_res.multiplier,
                action_taken="CREATED",
            ),
        }
