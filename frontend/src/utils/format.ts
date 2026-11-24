export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kb = bytes / 1024;
  if (kb < 1024) {
    return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`;
  }
  const mb = kb / 1024;
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Returns a human-friendly display name for an authenticated user.
 * Never invents a fake person name.
 */
export function getUserDisplayName(
  user?: { full_name?: string | null; email?: string | null } | null
): string {
  if (!user) return "Account";
  if (user.full_name && user.full_name.trim().length > 0) {
    return user.full_name.trim();
  }
  if (user.email && user.email.includes("@")) {
    const local = user.email.split("@")[0].trim();
    if (local.length > 0) {
      return local.charAt(0).toUpperCase() + local.slice(1);
    }
  }
  return "Account";
}

/**
 * Derives dynamic initials from an authenticated user identity.
 * Handles multi-word names, single-word names, and email-derived fallbacks.
 * Never hardcodes static initials like "KA".
 */
export function getInitials(
  user?: { full_name?: string | null; email?: string | null } | null
): string {
  if (!user) return "U";
  if (user.full_name && user.full_name.trim().length > 0) {
    const parts = user.full_name.trim().split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    if (parts.length === 1) {
      return parts[0].slice(0, 2).toUpperCase();
    }
  }
  if (user.email && user.email.includes("@")) {
    const local = user.email.split("@")[0].trim();
    if (local.length >= 2) {
      return local.slice(0, 2).toUpperCase();
    }
    if (local.length === 1) {
      return local.toUpperCase();
    }
  }
  return "U";
}

/**
 * Converts internal role enums into human-readable presentation labels.
 */
export function formatRole(role?: string | null): string {
  if (!role) return "Viewer";
  switch (role.toUpperCase()) {
    case "OWNER":
      return "Owner";
    case "ADMIN":
    case "ORGANIZATION_ADMIN":
      return "Organization Admin";
    case "WORKSPACE_ADMIN":
      return "Workspace Admin";
    case "CONTRIBUTOR":
      return "Contributor";
    case "VIEWER":
      return "Viewer";
    case "MEMBER":
      return "Member";
    case "BILLING":
      return "Billing";
    default:
      return role
        .replace(/_/g, " ")
        .toLowerCase()
        .replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

/**
 * Maps internal audit event enum keys to clear, human-readable labels.
 */
export function formatAuditEvent(eventType: string): string {
  const mapping: Record<string, string> = {
    LOGIN_SUCCESS: "Login Succeeded",
    LOGIN_FAILURE: "Login Failed",
    LOGOUT: "Signed Out",
    TOKEN_REFRESH: "Session Refreshed",
    AUTHENTICATION_DENIED: "Authentication Denied",
    MEMBER_ADDED: "Member Added",
    MEMBER_UPDATED: "Member Updated",
    MEMBER_REMOVED: "Member Removed",
    MEMBER_ROLE_CHANGED: "Member Role Changed",
    WORKSPACE_CREATED: "Workspace Created",
    WORKSPACE_UPDATED: "Workspace Updated",
    WORKSPACE_ARCHIVED: "Workspace Archived",
    WORKSPACE_RESTORED: "Workspace Restored",
    DOCUMENT_CREATED: "Document Uploaded",
    DOCUMENT_VIEWED: "Document Accessed",
    DOCUMENT_UPDATED: "Document Updated",
    DOCUMENT_DELETED: "Document Deleted",
    DOCUMENT_ACL_VIEWED: "Access Control Viewed",
    DOCUMENT_ACL_ADDED: "Access Permission Granted",
    DOCUMENT_ACL_REMOVED: "Access Permission Revoked",
    KNOWLEDGE_QUERY: "Knowledge Query",
    KNOWLEDGE_QUERY_DENIED: "Query Access Denied",
    PERMISSION_DENIED: "Permission Denied",
    CROSS_TENANT_ACCESS_DENIED: "Cross-Tenant Access Denied",
    ALERT_CREATED: "Operational Alert Created",
    ALERT_ACKNOWLEDGED: "Alert Acknowledged",
    ALERT_RESOLVED: "Alert Resolved",
  };
  return (
    mapping[eventType] ||
    eventType
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/**
 * Formats audit outcome enum for display.
 */
export function formatAuditOutcome(outcome: string): string {
  switch (outcome.toUpperCase()) {
    case "SUCCESS":
      return "Success";
    case "FAILURE":
      return "Failed";
    case "DENIED":
      return "Denied";
    default:
      return outcome;
  }
}

/**
 * Formats operational alert type keys for human-readable display.
 */
export function formatAlertType(alertType: string): string {
  const mapping: Record<string, string> = {
    LATENCY_HIGH: "Elevated Total Latency",
    LATENCY_REGRESSION: "Latency Regression",
    RETRIEVAL_SLOW: "Slow Retrieval Stage",
    RERANKER_SLOW: "Slow Reranking Stage",
    LLM_SLOW: "Slow Generation Stage",
    LLM_ERROR_RATE_HIGH: "High LLM Error Rate",
    EMBEDDING_ERROR_RATE_HIGH: "High Embedding Error Rate",
    DATABASE_ERROR_RATE_HIGH: "High Database Error Rate",
    PROVIDER_FAILURE_SPIKE: "Provider Failure Spike",
    STREAM_TTFT_HIGH: "Elevated Time to First Token",
    STREAM_FAILURE_RATE_HIGH: "High Stream Failure Rate",
    RETRIEVAL_DEGRADATION: "Retrieval Degradation",
    NO_CONTEXT_RATE_HIGH: "High No-Context Rate",
    TRACE_PERSISTENCE_FAILURE: "Trace Persistence Failure",
    AUDIT_PERSISTENCE_FAILURE: "Audit Persistence Failure",
    TOKEN_USAGE_SPIKE: "Token Consumption Spike",
    ANOMALY_DETECTED: "Statistical Anomaly Detected",
  };
  return (
    mapping[alertType] ||
    alertType
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/**
 * Formats millisecond latency durations into clean human labels.
 */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || isNaN(ms)) return "N/A";
  if (ms < 1 && ms > 0) return `${ms.toFixed(1)} ms`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

/**
 * Formats numeric percentage values (e.g. 0.052 -> 5.2% or 5.2 -> 5.2%).
 */
export function formatPercent(val: number | null | undefined, isFraction = true): string {
  if (val === null || val === undefined || isNaN(val)) return "N/A";
  const pct = isFraction ? val * 100 : val;
  return `${pct.toFixed(1)}%`;
}

/**
 * Formats query trace and pipeline stage identifiers into human-readable labels.
 */
export function formatStageName(stage: string): string {
  const mapping: Record<string, string> = {
    AUTHENTICATION: "Authentication",
    WORKSPACE_CONTEXT: "Workspace Context",
    EMBEDDING: "Embedding Generation",
    DENSE_RETRIEVAL: "Dense Retrieval",
    LEXICAL_RETRIEVAL: "Lexical Retrieval",
    RRF: "RRF Score Fusion",
    RERANKING: "Document Reranking",
    CONTEXT_ASSEMBLY: "Context Assembly",
    LLM_GENERATION: "LLM Generation",
    TRACE_PERSISTENCE: "Trace Persistence",
    AUDIT_PERSISTENCE: "Audit Logging",
  };
  return (
    mapping[stage.toUpperCase()] ||
    stage
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}


