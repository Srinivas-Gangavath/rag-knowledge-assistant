import type {
  AuditLogFilters,
  AuditLogListResponse,
  AuditLogVerifyResponse,
  AuthResponse,
  ChatResponse,
  ChatSource,
  ConversationDetail,
  ConversationListResponse,
  DocumentAcl,
  DocumentListResponse,
  DocumentRecord,
  DocumentSourceEvidence,
  HealthResponse,
  OrganizationMember,
  QueryTraceDetail,
  QueryTraceFilters,
  QueryTraceListResponse,
  SlowTraceListResponse,
  TokenRefreshResponse,
  TraceAnalyticsResponse,
  TraceExportResponse,
  TraceRetentionCleanupResponse,
  TraceRetentionPreviewResponse,
  AlertEvaluationResponse,
  AlertRule,
  AlertRuleCreateRequest,
  AlertRuleListResponse,
  PlatformAlertDetail,
  PlatformAlertListResponse,
  PlatformAlertSummary,
  User,
  WorkspaceItem,
  WorkspaceMember,
} from "../types";
import { ApiClientError, errorFromResponse, StreamAbortedError } from "./errors";
import { consumeSse } from "./sse";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/** Safety net above the backend Gemini timeout (default 20s × 2 attempts). */
const CHAT_TIMEOUT_MS = 90_000;

let inMemoryAccessToken: string | null = null;
let activeWorkspaceId: string | null = null;
let refreshPromise: Promise<string | null> | null = null;
let onAuthExpiredCallback: (() => void) | null = null;

export function setAuthToken(token: string | null): void {
  inMemoryAccessToken = token;
}

export function getAuthToken(): string | null {
  return inMemoryAccessToken;
}

export function setActiveWorkspaceId(id: string | null): void {
  activeWorkspaceId = id;
}

export function getActiveWorkspaceId(): string | null {
  return activeWorkspaceId;
}

export function setOnAuthExpired(callback: (() => void) | null): void {
  onAuthExpiredCallback = callback;
}

export type ChatStreamHandlers = {
  onStart?: (data: { conversation_id: string; user_message_id: string }) => void;
  onToken?: (text: string) => void;
  onSources?: (sources: ChatSource[]) => void;
  onDone?: (data: {
    conversation_id: string;
    message_id: string;
    user_message_id: string;
  }) => void;
};

function dispatchStreamEvent(
  eventName: string,
  raw: string,
  handlers: ChatStreamHandlers,
): void {
  const data = JSON.parse(raw) as Record<string, unknown>;
  if (eventName === "start") {
    handlers.onStart?.({
      conversation_id: String(data.conversation_id ?? ""),
      user_message_id: String(data.user_message_id ?? ""),
    });
    return;
  }
  if (eventName === "token") {
    handlers.onToken?.(typeof data.text === "string" ? data.text : "");
    return;
  }
  if (eventName === "sources") {
    handlers.onSources?.(Array.isArray(data.sources) ? (data.sources as ChatSource[]) : []);
    return;
  }
  if (eventName === "done") {
    handlers.onDone?.({
      conversation_id: String(data.conversation_id ?? ""),
      message_id: String(data.message_id ?? ""),
      user_message_id: String(data.user_message_id ?? ""),
    });
    return;
  }
  if (eventName === "error") {
    const detail =
      typeof data.detail === "string" && data.detail.trim()
        ? data.detail
        : "The assistant is temporarily unavailable. Please try again.";
    throw new ApiClientError(detail, 502);
  }
}

async function tryRefreshToken(): Promise<string | null> {
  if (refreshPromise) {
    return refreshPromise;
  }
  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        setAuthToken(null);
        onAuthExpiredCallback?.();
        return null;
      }
      const data = (await response.json()) as TokenRefreshResponse;
      setAuthToken(data.access_token);
      return data.access_token;
    } catch {
      setAuthToken(null);
      onAuthExpiredCallback?.();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs?: number,
  isRetry = false,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (init?.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (inMemoryAccessToken) {
    headers.set("Authorization", `Bearer ${inMemoryAccessToken}`);
  }
  if (activeWorkspaceId) {
    headers.set("X-Workspace-Id", activeWorkspaceId);
  }

  const controller = new AbortController();
  const timeoutId =
    timeoutMs != null
      ? window.setTimeout(() => controller.abort(), timeoutMs)
      : undefined;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiClientError(
        "The assistant is temporarily unavailable. Please try again.",
        503,
      );
    }
    throw new TypeError("Unable to connect to the server.");
  } finally {
    if (timeoutId != null) {
      window.clearTimeout(timeoutId);
    }
  }

  if (response.status === 401 && !isRetry && !path.startsWith("/api/v1/auth/")) {
    const newToken = await tryRefreshToken();
    if (newToken) {
      return request<T>(path, init, timeoutMs, true);
    }
  }

  if (!response.ok) {
    throw await errorFromResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  // Auth methods
  async register(email: string, password: string, full_name: string): Promise<AuthResponse> {
    const res = await request<AuthResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name }),
    });
    setAuthToken(res.access_token);
    return res;
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    const res = await request<AuthResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setAuthToken(res.access_token);
    return res;
  },

  async refresh(): Promise<TokenRefreshResponse> {
    const res = await request<TokenRefreshResponse>("/api/v1/auth/refresh", {
      method: "POST",
    });
    setAuthToken(res.access_token);
    return res;
  },

  async logout(): Promise<void> {
    try {
      await request<void>("/api/v1/auth/logout", {
        method: "POST",
      });
    } finally {
      setAuthToken(null);
      setActiveWorkspaceId(null);
    }
  },

  getMe(): Promise<User> {
    return request<User>("/api/v1/auth/me");
  },

  getHealth(): Promise<HealthResponse> {
    return request<HealthResponse>("/api/v1/health");
  },

  listDocuments(): Promise<DocumentListResponse> {
    return request<DocumentListResponse>("/api/v1/documents");
  },

  getDocument(documentId: string): Promise<DocumentRecord> {
    return request<DocumentRecord>(`/api/v1/documents/${documentId}`);
  },

  getDocumentSourceEvidence(documentId: string, chunkIndex: number): Promise<DocumentSourceEvidence> {
    return request<DocumentSourceEvidence>(`/api/v1/documents/${documentId}/sources/${chunkIndex}`);
  },

  uploadDocument(file: File): Promise<DocumentRecord> {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentRecord>("/api/v1/documents", {
      method: "POST",
      body: form,
    });
  },

  chat(question: string, conversationId?: string | null): Promise<ChatResponse> {
    return request<ChatResponse>(
      "/api/v1/chat",
      {
        method: "POST",
        body: JSON.stringify({
          question,
          ...(conversationId ? { conversation_id: conversationId } : {}),
        }),
      },
      CHAT_TIMEOUT_MS,
    );
  },

  async chatStream(
    question: string,
    conversationId: string | null | undefined,
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
  ): Promise<void> {
    const headers = new Headers();
    headers.set("Accept", "text/event-stream");
    headers.set("Content-Type", "application/json");
    if (inMemoryAccessToken) {
      headers.set("Authorization", `Bearer ${inMemoryAccessToken}`);
    }
    if (activeWorkspaceId) {
      headers.set("X-Workspace-Id", activeWorkspaceId);
    }

    const controller = new AbortController();
    const onAbort = () => controller.abort();
    if (signal) {
      if (signal.aborted) {
        controller.abort();
      } else {
        signal.addEventListener("abort", onAbort);
      }
    }
    const timeoutId = window.setTimeout(() => {
      if (!signal?.aborted) {
        controller.abort();
      }
    }, CHAT_TIMEOUT_MS);

    let response: Response;
    try {
      try {
        response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
          method: "POST",
          credentials: "include",
          headers,
          body: JSON.stringify({
            question,
            ...(conversationId ? { conversation_id: conversationId } : {}),
          }),
          signal: controller.signal,
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          if (signal?.aborted) {
            throw new StreamAbortedError();
          }
          throw new ApiClientError(
            "The assistant is temporarily unavailable. Please try again.",
            503,
          );
        }
        throw new TypeError("Unable to connect to the server.");
      }

      if (response.status === 401) {
        const newToken = await tryRefreshToken();
        if (newToken) {
          headers.set("Authorization", `Bearer ${newToken}`);
          response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
            method: "POST",
            credentials: "include",
            headers,
            body: JSON.stringify({
              question,
              ...(conversationId ? { conversation_id: conversationId } : {}),
            }),
            signal: controller.signal,
          });
        }
      }

      if (!response.ok) {
        throw await errorFromResponse(response);
      }

      if (!response.body) {
        throw new ApiClientError(
          "The assistant is temporarily unavailable. Please try again.",
          502,
        );
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          const consumed = consumeSse(buffer);
          buffer = consumed.rest;
          for (const event of consumed.events) {
            dispatchStreamEvent(event.event, event.data, handlers);
          }
        }
        buffer += decoder.decode();
        if (buffer.trim()) {
          const consumed = consumeSse(buffer.endsWith("\n\n") ? buffer : `${buffer}\n\n`);
          for (const event of consumed.events) {
            dispatchStreamEvent(event.event, event.data, handlers);
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new StreamAbortedError();
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      signal?.removeEventListener("abort", onAbort);
    }
  },

  listConversations(): Promise<ConversationListResponse> {
    return request<ConversationListResponse>("/api/v1/conversations");
  },

  createConversation(): Promise<ConversationDetail> {
    return request<ConversationDetail>("/api/v1/conversations", {
      method: "POST",
    });
  },

  getConversation(conversationId: string): Promise<ConversationDetail> {
    return request<ConversationDetail>(`/api/v1/conversations/${conversationId}`);
  },

  deleteConversation(conversationId: string): Promise<void> {
    return request<void>(`/api/v1/conversations/${conversationId}`, {
      method: "DELETE",
    });
  },

  deleteDocument(documentId: string): Promise<void> {
    return request<void>(`/api/v1/documents/${documentId}`, {
      method: "DELETE",
    });
  },

  // Workspace management
  listWorkspaces(): Promise<{ workspaces: WorkspaceItem[] }> {
    return request<{ workspaces: WorkspaceItem[] }>("/api/v1/workspaces");
  },

  createWorkspace(data: {
    organization_id: string;
    name: string;
    slug?: string;
    settings?: Record<string, unknown>;
  }): Promise<WorkspaceItem> {
    return request<WorkspaceItem>("/api/v1/workspaces", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getWorkspace(workspaceId: string): Promise<WorkspaceItem> {
    return request<WorkspaceItem>(`/api/v1/workspaces/${workspaceId}`);
  },

  updateWorkspace(
    workspaceId: string,
    data: {
      name?: string;
      slug?: string;
      settings?: Record<string, unknown>;
      is_archived?: boolean;
    },
  ): Promise<WorkspaceItem> {
    return request<WorkspaceItem>(`/api/v1/workspaces/${workspaceId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  archiveWorkspace(workspaceId: string): Promise<void> {
    return request<void>(`/api/v1/workspaces/${workspaceId}`, {
      method: "DELETE",
    });
  },

  listWorkspaceMembers(workspaceId: string): Promise<{ members: WorkspaceMember[] }> {
    return request<{ members: WorkspaceMember[] }>(`/api/v1/workspaces/${workspaceId}/members`);
  },

  addWorkspaceMember(
    workspaceId: string,
    data: { user_id?: string; email?: string; role: string },
  ): Promise<WorkspaceMember> {
    return request<WorkspaceMember>(`/api/v1/workspaces/${workspaceId}/members`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  updateWorkspaceMemberRole(
    workspaceId: string,
    userId: string,
    role: string,
  ): Promise<WorkspaceMember> {
    return request<WorkspaceMember>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
  },

  removeWorkspaceMember(workspaceId: string, userId: string): Promise<void> {
    return request<void>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      method: "DELETE",
    });
  },

  // Organization member management
  listOrgMembers(orgId: string): Promise<{ members: OrganizationMember[] }> {
    return request<{ members: OrganizationMember[] }>(`/api/v1/organizations/${orgId}/members`);
  },

  addOrgMember(
    orgId: string,
    data: { user_id?: string; email?: string; role: string },
  ): Promise<OrganizationMember> {
    return request<OrganizationMember>(`/api/v1/organizations/${orgId}/members`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  updateOrgMemberRole(
    orgId: string,
    userId: string,
    role: string,
  ): Promise<OrganizationMember> {
    return request<OrganizationMember>(`/api/v1/organizations/${orgId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
  },

  removeOrgMember(orgId: string, userId: string): Promise<void> {
    return request<void>(`/api/v1/organizations/${orgId}/members/${userId}`, {
      method: "DELETE",
    });
  },

  // Document ACL Management
  listDocumentAcls(documentId: string): Promise<{ acls: DocumentAcl[] }> {
    return request<{ acls: DocumentAcl[] }>(`/api/v1/documents/${documentId}/acl`);
  },

  addDocumentAcl(
    documentId: string,
    data: {
      principal_type: "USER" | "WORKSPACE_ROLE";
      principal_id: string;
      permission: "READ" | "WRITE" | "ADMIN";
    },
  ): Promise<DocumentAcl> {
    return request<DocumentAcl>(`/api/v1/documents/${documentId}/acl`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  deleteDocumentAcl(documentId: string, aclId: string): Promise<void> {
    return request<void>(`/api/v1/documents/${documentId}/acl/${aclId}`, {
      method: "DELETE",
    });
  },

  // Audit Logs & Compliance
  listAuditLogs(filters?: AuditLogFilters): Promise<AuditLogListResponse> {
    const params = new URLSearchParams();
    if (filters) {
      if (filters.workspace_id) params.set("workspace_id", filters.workspace_id);
      if (filters.event_type) params.set("event_type", filters.event_type);
      if (filters.actor_user_id) params.set("actor_user_id", filters.actor_user_id);
      if (filters.resource_type) params.set("resource_type", filters.resource_type);
      if (filters.resource_id) params.set("resource_id", filters.resource_id);
      if (filters.outcome) params.set("outcome", filters.outcome);
      if (filters.from_time) params.set("from_time", filters.from_time);
      if (filters.to_time) params.set("to_time", filters.to_time);
      if (filters.page) params.set("page", String(filters.page));
      if (filters.page_size) params.set("page_size", String(filters.page_size));
    }
    const qs = params.toString();
    return request<AuditLogListResponse>(`/api/v1/audit-logs${qs ? `?${qs}` : ""}`);
  },

  verifyAuditLogs(workspaceId?: string): Promise<AuditLogVerifyResponse> {
    const params = new URLSearchParams();
    if (workspaceId) params.set("workspace_id", workspaceId);
    const qs = params.toString();
    return request<AuditLogVerifyResponse>(`/api/v1/audit-logs/verify${qs ? `?${qs}` : ""}`);
  },

  // Platform Observability & Query Tracing
  listTraces(filters?: QueryTraceFilters): Promise<QueryTraceListResponse> {
    const params = new URLSearchParams();
    if (filters) {
      if (filters.workspace_id) params.set("workspace_id", filters.workspace_id);
      if (filters.status) params.set("status", filters.status);
      if (filters.operation_type) params.set("operation_type", filters.operation_type);
      if (filters.from_time) params.set("from_time", filters.from_time);
      if (filters.to_time) params.set("to_time", filters.to_time);
      if (filters.min_latency_ms !== undefined) params.set("min_latency_ms", String(filters.min_latency_ms));
      if (filters.request_id) params.set("request_id", filters.request_id);
      if (filters.actor_user_id) params.set("actor_user_id", filters.actor_user_id);
      if (filters.limit !== undefined) params.set("limit", String(filters.limit));
      if (filters.offset !== undefined) params.set("offset", String(filters.offset));
    }
    const qs = params.toString();
    return request<QueryTraceListResponse>(`/api/v1/traces${qs ? `?${qs}` : ""}`);
  },

  getTraceDetail(traceId: string): Promise<QueryTraceDetail> {
    return request<QueryTraceDetail>(`/api/v1/traces/${encodeURIComponent(traceId)}`);
  },

  getTraceAnalytics(filters?: {
    workspace_id?: string;
    from_time?: string;
    to_time?: string;
    operation_type?: string;
    retrieval_mode?: string;
  }): Promise<TraceAnalyticsResponse> {
    const params = new URLSearchParams();
    if (filters) {
      if (filters.workspace_id) params.set("workspace_id", filters.workspace_id);
      if (filters.from_time) params.set("from_time", filters.from_time);
      if (filters.to_time) params.set("to_time", filters.to_time);
      if (filters.operation_type) params.set("operation_type", filters.operation_type);
      if (filters.retrieval_mode) params.set("retrieval_mode", filters.retrieval_mode);
    }
    const qs = params.toString();
    return request<TraceAnalyticsResponse>(`/api/v1/traces/analytics${qs ? `?${qs}` : ""}`);
  },

  listSlowTraces(filters?: {
    workspace_id?: string;
    from_time?: string;
    to_time?: string;
    operation_type?: string;
    retrieval_mode?: string;
    limit?: number;
    offset?: number;
  }): Promise<SlowTraceListResponse> {
    const params = new URLSearchParams();
    if (filters) {
      if (filters.workspace_id) params.set("workspace_id", filters.workspace_id);
      if (filters.from_time) params.set("from_time", filters.from_time);
      if (filters.to_time) params.set("to_time", filters.to_time);
      if (filters.operation_type) params.set("operation_type", filters.operation_type);
      if (filters.retrieval_mode) params.set("retrieval_mode", filters.retrieval_mode);
      if (filters.limit !== undefined) params.set("limit", String(filters.limit));
      if (filters.offset !== undefined) params.set("offset", String(filters.offset));
    }
    const qs = params.toString();
    return request<SlowTraceListResponse>(`/api/v1/traces/slow${qs ? `?${qs}` : ""}`);
  },

  exportTrace(traceId: string): Promise<TraceExportResponse> {
    return request<TraceExportResponse>(`/api/v1/traces/${encodeURIComponent(traceId)}/export`);
  },

  previewTraceRetention(days?: number): Promise<TraceRetentionPreviewResponse> {
    const params = new URLSearchParams();
    if (days !== undefined) params.set("days", String(days));
    const qs = params.toString();
    return request<TraceRetentionPreviewResponse>(`/api/v1/traces/retention/preview${qs ? `?${qs}` : ""}`);
  },

  cleanupTraceRetention(data?: { days?: number; dry_run?: boolean }): Promise<TraceRetentionCleanupResponse> {
    return request<TraceRetentionCleanupResponse>("/api/v1/traces/retention/cleanup", {
      method: "POST",
      body: JSON.stringify(data || {}),
    });
  },

  // Alerting & Diagnostics
  listAlerts(filters?: {
    workspace_id?: string;
    alert_type?: string;
    severity?: string;
    status?: string;
    from_time?: string;
    to_time?: string;
    limit?: number;
    offset?: number;
  }): Promise<PlatformAlertListResponse> {
    const params = new URLSearchParams();
    if (filters) {
      if (filters.workspace_id) params.set("workspace_id", filters.workspace_id);
      if (filters.alert_type) params.set("alert_type", filters.alert_type);
      if (filters.severity) params.set("severity", filters.severity);
      if (filters.status) params.set("status", filters.status);
      if (filters.from_time) params.set("from_time", filters.from_time);
      if (filters.to_time) params.set("to_time", filters.to_time);
      if (filters.limit !== undefined) params.set("limit", String(filters.limit));
      if (filters.offset !== undefined) params.set("offset", String(filters.offset));
    }
    const qs = params.toString();
    return request<PlatformAlertListResponse>(`/api/v1/alerts${qs ? `?${qs}` : ""}`);
  },

  getAlertDetail(alertId: string): Promise<PlatformAlertDetail> {
    return request<PlatformAlertDetail>(`/api/v1/alerts/${encodeURIComponent(alertId)}`);
  },

  acknowledgeAlert(alertId: string): Promise<PlatformAlertSummary> {
    return request<PlatformAlertSummary>(`/api/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
      method: "POST",
    });
  },

  resolveAlert(alertId: string, reason?: string): Promise<PlatformAlertSummary> {
    return request<PlatformAlertSummary>(`/api/v1/alerts/${encodeURIComponent(alertId)}/resolve`, {
      method: "POST",
      body: JSON.stringify(reason ? { resolution_reason: reason } : {}),
    });
  },

  evaluateAlerts(workspaceId?: string): Promise<AlertEvaluationResponse> {
    return request<AlertEvaluationResponse>("/api/v1/alerts/evaluate", {
      method: "POST",
      body: JSON.stringify(workspaceId ? { workspace_id: workspaceId } : {}),
    });
  },

  listAlertRules(workspaceId?: string, enabledOnly: boolean = false): Promise<AlertRuleListResponse> {
    const params = new URLSearchParams();
    if (workspaceId) params.set("workspace_id", workspaceId);
    if (enabledOnly) params.set("enabled_only", "true");
    const qs = params.toString();
    return request<AlertRuleListResponse>(`/api/v1/alert-rules${qs ? `?${qs}` : ""}`);
  },

  createAlertRule(data: AlertRuleCreateRequest): Promise<AlertRule> {
    return request<AlertRule>("/api/v1/alert-rules", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  updateAlertRule(ruleId: string, data: Partial<AlertRuleCreateRequest>): Promise<AlertRule> {
    return request<AlertRule>(`/api/v1/alert-rules/${encodeURIComponent(ruleId)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  deleteAlertRule(ruleId: string): Promise<void> {
    return request<void>(`/api/v1/alert-rules/${encodeURIComponent(ruleId)}`, {
      method: "DELETE",
    });
  },
};



