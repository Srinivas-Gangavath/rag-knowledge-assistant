export type HealthResponse = {
  status: string;
};

export type ApiError = {
  detail: string;
};

export type UserOrg = {
  id: string;
  name: string;
  slug: string;
  role: string;
};

export type UserWorkspace = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  role: string;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  organizations: UserOrg[];
  workspaces: UserWorkspace[];
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

export type TokenRefreshResponse = {
  access_token: string;
  token_type: string;
};

export type AppView = "dashboard" | "documents" | "assistant" | "settings";

export type DocumentStatus = "UPLOADED" | "PROCESSING" | "COMPLETED" | "FAILED";

export type DocumentRecord = {
  id: string;
  filename: string;
  original_filename: string;
  file_type: string;
  file_size: number;
  status: DocumentStatus;
  page_count: number | null;
  category: string | null;
  source: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type DocumentListResponse = {
  documents: DocumentRecord[];
};

export type ChatRequest = {
  question: string;
  conversation_id?: string | null;
};

export type ChatSource = {
  document_id: string;
  filename: string;
  page_number: number | null;
  chunk_index: number;
  similarity_score: number;
};

export type DocumentSourceEvidence = {
  document_id: string;
  filename: string;
  page_number: number | null;
  chunk_index: number;
  content: string;
  is_truncated?: boolean;
};

export type ChatResponse = {
  answer: string;
  sources: ChatSource[];
  conversation_id: string;
  message_id: string;
  user_message_id: string;
};

export type ConversationSummary = {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type ConversationListResponse = {
  conversations: ConversationSummary[];
};

export type ConversationMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
  created_at: string;
};

export type ConversationDetail = ConversationSummary & {
  messages: ConversationMessage[];
};

export type WorkspaceItem = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  is_archived: boolean;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  role: string | null;
};

export type WorkspaceMember = {
  id: string;
  user_id: string;
  workspace_id: string;
  email: string;
  full_name: string;
  role: string;
  created_at: string;
};

export type OrganizationMember = {
  id: string;
  user_id: string;
  organization_id: string;
  email: string;
  full_name: string;
  role: string;
  created_at: string;
};

export type DocumentAcl = {
  id: string;
  document_id: string;
  principal_type: "USER" | "WORKSPACE_ROLE";
  principal_id: string;
  permission: "READ" | "WRITE" | "ADMIN";
  created_at: string;
  updated_at: string;
};

export type AuditLogItem = {
  id: string;
  organization_id: string;
  workspace_id: string | null;
  actor_user_id: string | null;
  actor_email_snapshot: string | null;
  event_type: string;
  action: string;
  outcome: string;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  user_agent: string | null;
  request_id: string | null;
  created_at: string;
  previous_hash: string | null;
  event_hash: string;
};

export type AuditLogListResponse = {
  items: AuditLogItem[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

export type AuditLogVerifyResponse = {
  is_valid: boolean;
  events_verified: number;
  message: string;
  error_detail: string | null;
};

export type AuditLogFilters = {
  workspace_id?: string;
  event_type?: string;
  actor_user_id?: string;
  resource_type?: string;
  resource_id?: string;
  outcome?: string;
  from_time?: string;
  to_time?: string;
  page?: number;
  page_size?: number;
};

export type QueryTraceSpan = {
  id: string;
  trace_id: string;
  parent_span_id: string | null;
  span_name: string;
  span_type: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  status: string;
  error_type: string | null;
  metadata: Record<string, unknown>;
};

export type QueryTraceSummary = {
  id: string;
  trace_id: string;
  request_id: string;
  organization_id: string;
  workspace_id: string | null;
  actor_user_id: string | null;
  conversation_id: string | null;
  operation_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  total_latency_ms: number | null;
  error_type: string | null;
  error_code: string | null;
  retrieval_mode: string | null;
  grounded: boolean | null;
  result_count: number | null;
  span_count: number;
};

export type QueryTraceDetail = QueryTraceSummary & {
  metadata: Record<string, unknown>;
  spans: QueryTraceSpan[];
};

export type QueryTraceListResponse = {
  items: QueryTraceSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type QueryTraceFilters = {
  workspace_id?: string;
  status?: string;
  operation_type?: string;
  from_time?: string;
  to_time?: string;
  min_latency_ms?: number;
  request_id?: string;
  actor_user_id?: string;
  limit?: number;
  offset?: number;
};

export type StageLatencyStats = {
  stage: string;
  count: number;
  average_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  max_ms: number;
  percentage_of_total: number;
};

export type TraceAnalyticsOverview = {
  request_count: number;
  successful_count: number;
  error_count: number;
  cancelled_count: number;
  partial_count: number;
  error_rate: number;
  average_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
};

export type SlowQuerySummary = {
  slow_count: number;
  very_slow_count: number;
  slow_rate: number;
  threshold_ms: number;
};

export type ErrorAnalytics = {
  total_errors: number;
  error_rate: number;
  errors_by_category: Record<string, number>;
  errors_by_operation: Record<string, number>;
  top_failing_stages: { stage: string; error_count: number }[];
};

export type ProviderModelStats = {
  provider: string;
  model: string;
  request_count: number;
  error_count: number;
  average_latency_ms: number;
  p95_latency_ms: number;
  input_token_count: number;
  output_token_count: number;
  total_token_count: number;
  token_usage_available: boolean;
};

export type StreamingAnalytics = {
  stream_count: number;
  success_rate: number;
  cancellation_rate: number;
  partial_rate: number;
  provider_error_rate: number;
  average_ttft_ms: number | null;
  p50_ttft_ms: number | null;
  p95_ttft_ms: number | null;
  p99_ttft_ms: number | null;
  average_stream_duration_ms: number | null;
};

export type TraceAnalyticsResponse = {
  overview: TraceAnalyticsOverview;
  stages: StageLatencyStats[];
  slow_queries: SlowQuerySummary;
  errors: ErrorAnalytics;
  providers: ProviderModelStats[];
  streaming: StreamingAnalytics;
};

export type SlowTraceItem = {
  trace_id: string;
  request_id: string;
  organization_id: string;
  workspace_id: string | null;
  started_at: string;
  total_latency_ms: number;
  status: string;
  operation_type: string;
  retrieval_mode: string | null;
  slow_classification: string;
  dominant_stage: string | null;
  dominant_stage_duration_ms: number | null;
  dominant_stage_percentage: number | null;
  is_retrieval_dominant: boolean;
  is_generation_dominant: boolean;
};

export type SlowTraceListResponse = {
  items: SlowTraceItem[];
  total: number;
  limit: number;
  offset: number;
};

export type TraceExportResponse = QueryTraceDetail & {
  diagnostics: {
    slow_classification: string;
    dominant_stage: string | null;
    dominant_stage_duration_ms: number | null;
    dominant_stage_percentage: number | null;
    stage_durations_ms: Record<string, number>;
    stage_percentages: Record<string, number>;
    is_retrieval_dominant: boolean;
    is_generation_dominant: boolean;
  };
};

export type TraceRetentionPreviewResponse = {
  cutoff: string;
  eligible_trace_count: number;
  eligible_span_count: number;
  oldest_trace_timestamp: string | null;
  newest_eligible_timestamp: string | null;
};

export type TraceRetentionCleanupResponse = {
  cutoff: string;
  deleted_traces_count: number;
  deleted_spans_count: number;
  dry_run: boolean;
};

// Alerting & Diagnostics Types
export type PlatformAlertSummary = {
  id: string;
  organization_id: string;
  workspace_id: string | null;
  alert_type: string;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "SUPPRESSED";
  title: string;
  description: string;
  metric_name: string | null;
  metric_value: number | null;
  threshold_value: number | null;
  detected_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  acknowledged_by: string | null;
  resolved_by: string | null;
  resolution_reason: string | null;
  deduplication_key: string;
  created_at: string;
  updated_at: string;
};

export type DiagnosticEvidence = {
  diagnosis_category: string;
  dominant_stage: string | null;
  subsystem: string;
  observed: string;
  inferred: string;
  evidence: Record<string, any>;
  investigation_target: string;
  sample_trace_id: string | null;
  sample_request_id: string | null;
};

export type PlatformAlertDetail = PlatformAlertSummary & {
  metadata: Record<string, any>;
  diagnostic: DiagnosticEvidence | null;
};

export type PlatformAlertListResponse = {
  items: PlatformAlertSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type AlertRule = {
  id: string;
  organization_id: string | null;
  workspace_id: string | null;
  rule_type: string;
  metric_name: string;
  operator: "GT" | "GTE" | "LT" | "LTE" | "EQ";
  threshold: number;
  window_minutes: number;
  minimum_sample_size: number;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  enabled: boolean;
  cooldown_minutes: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type AlertRuleListResponse = {
  items: AlertRule[];
  total: number;
};

export type AlertRuleCreateRequest = {
  workspace_id?: string | null;
  rule_type: string;
  metric_name: string;
  operator: "GT" | "GTE" | "LT" | "LTE" | "EQ";
  threshold: number;
  window_minutes?: number;
  minimum_sample_size?: number;
  severity?: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  enabled?: boolean;
  cooldown_minutes?: number;
};

export type AlertEvaluationResultItem = {
  alert_id: string | null;
  alert_type: string;
  severity: string;
  status: string;
  title: string;
  metric_name: string | null;
  metric_value: number | null;
  threshold: number | null;
  action_taken: string;
};

export type AlertEvaluationResponse = {
  evaluation_timestamp: string;
  rules_evaluated: number;
  alerts_created: number;
  alerts_updated: number;
  anomalies_detected: number;
  details: AlertEvaluationResultItem[];
};


