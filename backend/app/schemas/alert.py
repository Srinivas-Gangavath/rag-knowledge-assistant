"""Pydantic schemas for Operational Alerting, Rules, Anomaly Detection & Self-Diagnostics."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AlertOperator, AlertSeverity, AlertStatus


class AlertRuleBase(BaseModel):
    rule_type: str = Field(..., max_length=64, description="Rule category (e.g. THRESHOLD, ANOMALY, DEGRADATION)")
    metric_name: str = Field(..., max_length=64, description="Metric to evaluate")
    operator: AlertOperator = Field(..., description="Comparison operator (GT, GTE, LT, LTE, EQ)")
    threshold: float = Field(..., description="Numeric threshold")
    window_minutes: int = Field(15, ge=1, le=1440, description="Evaluation window in minutes")
    minimum_sample_size: int = Field(5, ge=1, le=10000, description="Minimum trace samples required to trigger")
    severity: AlertSeverity = Field(AlertSeverity.WARNING, description="Alert severity level")
    enabled: bool = Field(True, description="Whether rule is active")
    cooldown_minutes: int = Field(60, ge=1, le=10080, description="Cooldown window to avoid duplicate alerts")

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Threshold must be a valid finite number")
        return v


class AlertRuleCreateRequest(AlertRuleBase):
    organization_id: UUID | None = Field(None, description="Optional organization ID (Org Admin only)")
    workspace_id: UUID | None = Field(None, description="Optional workspace ID")


class AlertRuleUpdateRequest(BaseModel):
    rule_type: str | None = Field(None, max_length=64)
    metric_name: str | None = Field(None, max_length=64)
    operator: AlertOperator | None = None
    threshold: float | None = None
    window_minutes: int | None = Field(None, ge=1, le=1440)
    minimum_sample_size: int | None = Field(None, ge=1, le=10000)
    severity: AlertSeverity | None = None
    enabled: bool | None = None
    cooldown_minutes: int | None = Field(None, ge=1, le=10080)

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: float | None) -> float | None:
        if v is not None and (math.isnan(v) or math.isinf(v)):
            raise ValueError("Threshold must be a valid finite number")
        return v


class AlertRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None
    workspace_id: UUID | None
    rule_type: str
    metric_name: str
    operator: str
    threshold: float
    window_minutes: int
    minimum_sample_size: int
    severity: str
    enabled: bool
    cooldown_minutes: int
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class AlertRuleListResponse(BaseModel):
    items: list[AlertRuleResponse]
    total: int


class PlatformAlertSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    workspace_id: UUID | None
    alert_type: str
    severity: str
    status: str
    title: str
    description: str
    metric_name: str | None
    metric_value: float | None
    threshold_value: float | None
    detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    acknowledged_by: UUID | None
    resolved_by: UUID | None
    resolution_reason: str | None
    deduplication_key: str
    created_at: datetime
    updated_at: datetime


class DiagnosticEvidence(BaseModel):
    diagnosis_category: str
    dominant_stage: str | None = None
    subsystem: str
    observed: str
    inferred: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    investigation_target: str
    sample_trace_id: str | None = None
    sample_request_id: str | None = None


class PlatformAlertDetailResponse(PlatformAlertSummaryResponse):
    metadata: dict[str, Any] = Field(default_factory=dict)
    diagnostic: DiagnosticEvidence | None = None


class PlatformAlertListResponse(BaseModel):
    items: list[PlatformAlertSummaryResponse]
    total: int
    limit: int
    offset: int


class AlertAcknowledgeRequest(BaseModel):
    pass


class AlertResolveRequest(BaseModel):
    resolution_reason: str | None = Field(None, max_length=1000, description="Safe explanation of resolution")


class AlertEvaluationRequest(BaseModel):
    workspace_id: UUID | None = Field(None, description="Optional workspace scope for evaluation")


class AlertEvaluationResultItem(BaseModel):
    alert_id: UUID | None = None
    alert_type: str
    severity: str
    status: str
    title: str
    metric_name: str | None
    metric_value: float | None
    threshold: float | None
    action_taken: str  # "CREATED", "COOLDOWN_SUPPRESSED", "UPDATED", "NOOP"


class AlertEvaluationResponse(BaseModel):
    evaluation_timestamp: datetime
    rules_evaluated: int
    alerts_created: int
    alerts_updated: int
    anomalies_detected: int
    details: list[AlertEvaluationResultItem] = Field(default_factory=list)


class DiagnosticReportResponse(BaseModel):
    alert_id: UUID | None = None
    diagnosis_category: str
    dominant_stage: str | None = None
    subsystem: str
    observed: str
    inferred: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    investigation_target: str
    sample_trace_id: str | None = None
    sample_request_id: str | None = None
