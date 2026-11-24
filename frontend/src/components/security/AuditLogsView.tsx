import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { AuditLogItem } from "../../types";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableEmpty,
  Badge,
  Button,
  type BadgeVariant,
} from "../ui";
import {
  formatAuditEvent,
  formatAuditOutcome,
  formatDate,
} from "../../utils/format";
import { AuditEventDetailsModal } from "./AuditEventDetailsModal";

type AuditLogsViewProps = {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
  onNavigateToCompliance?: () => void;
};

export function AuditLogsView({
  workspaceId,
  isOrgAdminOrOwner,
  onNavigateToCompliance,
}: AuditLogsViewProps) {
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(15);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [scopeFilter, setScopeFilter] = useState<"workspace" | "organization">(
    workspaceId ? "workspace" : "organization"
  );
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [outcomeFilter, setOutcomeFilter] = useState("");
  const [actorUserIdFilter, setActorUserIdFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [fromTimeFilter, setFromTimeFilter] = useState("");
  const [toTimeFilter, setToTimeFilter] = useState("");

  // Modal State
  const [selectedLog, setSelectedLog] = useState<AuditLogItem | null>(null);

  async function loadLogs(targetPage: number) {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.listAuditLogs({
        workspace_id: scopeFilter === "workspace" ? workspaceId : undefined,
        event_type: eventTypeFilter || undefined,
        outcome: outcomeFilter || undefined,
        actor_user_id: actorUserIdFilter.trim() || undefined,
        resource_type: resourceTypeFilter || undefined,
        from_time: fromTimeFilter ? new Date(fromTimeFilter).toISOString() : undefined,
        to_time: toTimeFilter ? new Date(toTimeFilter).toISOString() : undefined,
        page: targetPage,
        page_size: pageSize,
      });
      setLogs(res.items);
      setTotal(res.total);
      setPage(res.page);
      setHasMore(res.has_more);
    } catch (err) {
      setError(userFacingError(err, "list"));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadLogs(1);
  }, [
    workspaceId,
    scopeFilter,
    eventTypeFilter,
    outcomeFilter,
    resourceTypeFilter,
    fromTimeFilter,
    toTimeFilter,
  ]);

  function handleFilterSubmit(e: React.FormEvent) {
    e.preventDefault();
    loadLogs(1);
  }

  function handleClearFilters() {
    setEventTypeFilter("");
    setOutcomeFilter("");
    setActorUserIdFilter("");
    setResourceTypeFilter("");
    setFromTimeFilter("");
    setToTimeFilter("");
  }

  function getOutcomeBadgeVariant(outcome: string): BadgeVariant {
    switch (outcome.toUpperCase()) {
      case "SUCCESS":
        return "success";
      case "FAILURE":
        return "danger";
      case "DENIED":
        return "warning";
      default:
        return "neutral";
    }
  }

  const hasActiveFilters = Boolean(
    eventTypeFilter ||
      outcomeFilter ||
      actorUserIdFilter ||
      resourceTypeFilter ||
      fromTimeFilter ||
      toTimeFilter
  );

  return (
    <div className="space-y-4">
      {/* Top Header & Actions Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Audit Logs</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Security and governance activity for your organization and workspaces.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {onNavigateToCompliance && (
            <Button
              variant="secondary"
              size="sm"
              onClick={onNavigateToCompliance}
            >
              Verify Integrity
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadLogs(page)}
            isLoading={isLoading}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800" role="alert">
          {error}
        </div>
      )}

      {/* Compact Filters Toolbar */}
      <form
        onSubmit={handleFilterSubmit}
        className="rounded-xl border border-slate-200/90 bg-slate-50/60 p-3 space-y-2.5 text-xs text-slate-700"
      >
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Scope Selector */}
          {isOrgAdminOrOwner && workspaceId && (
            <div className="flex items-center gap-1">
              <label htmlFor="audit-scope" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Scope:
              </label>
              <select
                id="audit-scope"
                value={scopeFilter}
                onChange={(e) => setScopeFilter(e.target.value as "workspace" | "organization")}
                className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                <option value="workspace">Active Workspace</option>
                <option value="organization">Organization-wide</option>
              </select>
            </div>
          )}

          {/* Event Type Filter */}
          <div className="flex items-center gap-1">
            <label htmlFor="audit-event" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Event:
            </label>
            <select
              id="audit-event"
              value={eventTypeFilter}
              onChange={(e) => setEventTypeFilter(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
            >
              <option value="">All Events</option>
              <option value="LOGIN_SUCCESS">Login Succeeded</option>
              <option value="LOGIN_FAILURE">Login Failed</option>
              <option value="LOGOUT">Signed Out</option>
              <option value="TOKEN_REFRESH">Session Refreshed</option>
              <option value="AUTHENTICATION_DENIED">Authentication Denied</option>
              <option value="MEMBER_ADDED">Member Added</option>
              <option value="MEMBER_UPDATED">Member Updated</option>
              <option value="MEMBER_REMOVED">Member Removed</option>
              <option value="MEMBER_ROLE_CHANGED">Member Role Changed</option>
              <option value="WORKSPACE_CREATED">Workspace Created</option>
              <option value="WORKSPACE_UPDATED">Workspace Updated</option>
              <option value="WORKSPACE_ARCHIVED">Workspace Archived</option>
              <option value="WORKSPACE_RESTORED">Workspace Restored</option>
              <option value="DOCUMENT_CREATED">Document Uploaded</option>
              <option value="DOCUMENT_VIEWED">Document Accessed</option>
              <option value="DOCUMENT_UPDATED">Document Updated</option>
              <option value="DOCUMENT_DELETED">Document Deleted</option>
              <option value="DOCUMENT_ACL_VIEWED">Access Control Viewed</option>
              <option value="DOCUMENT_ACL_ADDED">Access Granted</option>
              <option value="DOCUMENT_ACL_REMOVED">Access Revoked</option>
              <option value="KNOWLEDGE_QUERY">Knowledge Query</option>
              <option value="KNOWLEDGE_QUERY_DENIED">Query Access Denied</option>
              <option value="PERMISSION_DENIED">Permission Denied</option>
              <option value="CROSS_TENANT_ACCESS_DENIED">Cross-Tenant Denied</option>
              <option value="ALERT_CREATED">Alert Created</option>
              <option value="ALERT_ACKNOWLEDGED">Alert Acknowledged</option>
              <option value="ALERT_RESOLVED">Alert Resolved</option>
            </select>
          </div>

          {/* Outcome Filter */}
          <div className="flex items-center gap-1">
            <label htmlFor="audit-outcome" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Outcome:
            </label>
            <select
              id="audit-outcome"
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
            >
              <option value="">All Outcomes</option>
              <option value="SUCCESS">Success</option>
              <option value="FAILURE">Failed</option>
              <option value="DENIED">Denied</option>
            </select>
          </div>

          {/* Resource Type Filter */}
          <div className="flex items-center gap-1">
            <label htmlFor="audit-resource" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Resource:
            </label>
            <select
              id="audit-resource"
              value={resourceTypeFilter}
              onChange={(e) => setResourceTypeFilter(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
            >
              <option value="">All Resources</option>
              <option value="DOCUMENT">Document</option>
              <option value="WORKSPACE">Workspace</option>
              <option value="ORGANIZATION">Organization</option>
              <option value="USER">User</option>
              <option value="CONVERSATION">Conversation</option>
              <option value="QUERY">Query</option>
              <option value="ALERT">Alert</option>
            </select>
          </div>

          {/* Actor User ID Filter */}
          <div className="flex items-center gap-1">
            <input
              type="text"
              placeholder="Filter actor ID..."
              value={actorUserIdFilter}
              onChange={(e) => setActorUserIdFilter(e.target.value)}
              className="w-36 rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none"
            />
          </div>

          {hasActiveFilters && (
            <button
              type="button"
              onClick={handleClearFilters}
              className="text-xs text-slate-500 hover:text-slate-800 underline ml-auto cursor-pointer"
            >
              Reset Filters
            </button>
          )}
        </div>
      </form>

      {/* Audit Event Table */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-40">Timestamp</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Event</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Outcome</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead className="text-right">Inspection</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && logs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-slate-400">
                  Loading audit logs...
                </TableCell>
              </TableRow>
            ) : logs.length === 0 ? (
              <TableEmpty
                colSpan={7}
                message={
                  hasActiveFilters
                    ? "No audit records match the current filter criteria."
                    : "No audit activity yet."
                }
              />
            ) : (
              logs.map((log) => (
                <TableRow key={log.id} className="hover:bg-slate-50/70">
                  <TableCell className="whitespace-nowrap font-mono text-[11px] text-slate-500">
                    {formatDate(log.created_at)}
                  </TableCell>
                  <TableCell className="max-w-[160px] truncate font-medium text-slate-800" title={log.actor_email_snapshot || log.actor_user_id || "System"}>
                    {log.actor_email_snapshot || (log.actor_user_id ? log.actor_user_id.slice(0, 8) + "..." : "System")}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <span className="font-medium text-slate-900" title={log.event_type}>
                      {formatAuditEvent(log.event_type)}
                    </span>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-slate-600 font-mono text-[11px]">
                    {log.action}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <Badge variant={getOutcomeBadgeVariant(log.outcome)} size="sm">
                      {formatAuditOutcome(log.outcome)}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-[140px] truncate text-slate-600 text-[11px]" title={`${log.resource_type || "N/A"}: ${log.resource_id || ""}`}>
                    {log.resource_type ? `${log.resource_type}${log.resource_id ? `: ${log.resource_id.slice(0, 8)}...` : ""}` : "—"}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => setSelectedLog(log)}
                      className="text-brand-600 hover:text-brand-800 font-semibold hover:underline text-xs cursor-pointer"
                    >
                      View
                    </button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination Controls */}
      <div className="flex items-center justify-between text-xs text-slate-500 px-1">
        <span>
          Showing page <span className="font-semibold text-slate-800">{page}</span> of{" "}
          <span className="font-semibold text-slate-800">{Math.max(1, Math.ceil(total / pageSize))}</span> ({total} total records)
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadLogs(page - 1)}
            disabled={page <= 1 || isLoading}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadLogs(page + 1)}
            disabled={!hasMore || isLoading}
          >
            Next
          </Button>
        </div>
      </div>

      {/* Event Details Modal */}
      <AuditEventDetailsModal
        log={selectedLog}
        onClose={() => setSelectedLog(null)}
      />
    </div>
  );
}
