import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { QueryTraceDetail, QueryTraceSummary } from "../../types";
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
import { formatMs, formatDate } from "../../utils/format";
import { TraceWaterfallView } from "./TraceWaterfallView";

type TraceExplorerViewProps = {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
  selectedTraceIdFromExternal?: string | null;
  onClearExternalTraceId?: () => void;
};

export function TraceExplorerView({
  workspaceId,
  isOrgAdminOrOwner,
  selectedTraceIdFromExternal,
  onClearExternalTraceId,
}: TraceExplorerViewProps) {
  const [traces, setTraces] = useState<QueryTraceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(15);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [scopeFilter, setScopeFilter] = useState<"workspace" | "organization">(
    workspaceId ? "workspace" : "organization"
  );
  const [statusFilter, setStatusFilter] = useState("");
  const [operationFilter, setOperationFilter] = useState("");
  const [minLatencyMs, setMinLatencyMs] = useState<number | undefined>(undefined);
  const [requestIdFilter, setRequestIdFilter] = useState("");
  const [timeWindow, setTimeWindow] = useState<"1h" | "24h" | "7d" | "all">("24h");

  // Selected Trace Detail State
  const [traceDetail, setTraceDetail] = useState<QueryTraceDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  function getTimeRange(): { from_time?: string; to_time?: string } {
    if (timeWindow === "all") return {};
    const now = new Date();
    const to_time = now.toISOString();
    let fromDate = new Date();
    if (timeWindow === "1h") {
      fromDate = new Date(now.getTime() - 60 * 60 * 1000);
    } else if (timeWindow === "24h") {
      fromDate = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    } else if (timeWindow === "7d") {
      fromDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    }
    return { from_time: fromDate.toISOString(), to_time };
  }

  async function loadTraces(targetOffset: number) {
    setIsLoading(true);
    setError(null);
    try {
      const { from_time, to_time } = getTimeRange();
      const res = await api.listTraces({
        workspace_id: scopeFilter === "workspace" ? workspaceId : undefined,
        status: statusFilter || undefined,
        operation_type: operationFilter || undefined,
        min_latency_ms: minLatencyMs,
        request_id: requestIdFilter.trim() || undefined,
        from_time,
        to_time,
        limit,
        offset: targetOffset,
      });
      setTraces(res.items);
      setTotal(res.total);
      setOffset(res.offset);
    } catch (err) {
      setError(userFacingError(err, "list"));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadTraces(0);
  }, [
    workspaceId,
    scopeFilter,
    statusFilter,
    operationFilter,
    minLatencyMs,
    timeWindow,
  ]);

  async function handleInspectTrace(traceId: string) {
    setLoadingDetail(true);
    setDetailError(null);
    try {
      const detail = await api.getTraceDetail(traceId);
      setTraceDetail(detail);
    } catch (err) {
      setDetailError(userFacingError(err));
    } finally {
      setLoadingDetail(false);
    }
  }

  useEffect(() => {
    if (selectedTraceIdFromExternal) {
      handleInspectTrace(selectedTraceIdFromExternal);
    }
  }, [selectedTraceIdFromExternal]);

  async function handleExportTrace(traceId: string) {
    setIsExporting(true);
    try {
      const exported = await api.exportTrace(traceId);
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exported, null, 2));
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", `trace-${traceId}-diagnostics.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    } catch (err) {
      alert("Failed to export trace: " + userFacingError(err));
    } finally {
      setIsExporting(false);
    }
  }

  function handleCloseDetail() {
    setTraceDetail(null);
    if (onClearExternalTraceId) {
      onClearExternalTraceId();
    }
  }

  function getStatusBadgeVariant(status: string): BadgeVariant {
    switch (status.toUpperCase()) {
      case "SUCCESS":
      case "OK":
        return "success";
      case "ERROR":
      case "FAILURE":
        return "danger";
      case "CANCELLED":
      case "TIMEOUT":
        return "warning";
      default:
        return "neutral";
    }
  }

  if (traceDetail || loadingDetail) {
    if (loadingDetail) {
      return (
        <div className="py-16 text-center text-xs text-slate-400">
          Loading trace timeline diagnostics...
        </div>
      );
    }
    if (detailError || !traceDetail) {
      return (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800 space-y-2">
          <p className="font-semibold">Unable to load trace timeline</p>
          <p>{detailError || "Trace not found"}</p>
          <Button variant="secondary" size="sm" onClick={handleCloseDetail}>
            Back to Trace Explorer
          </Button>
        </div>
      );
    }
    return (
      <TraceWaterfallView
        trace={traceDetail}
        onClose={handleCloseDetail}
        onExport={handleExportTrace}
        isExporting={isExporting}
      />
    );
  }

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="space-y-4">
      {/* Top Header & Actions Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Trace Explorer</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            End-to-end query diagnostic timeline and pipeline stage telemetry.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => loadTraces(offset)}
          isLoading={isLoading}
        >
          Refresh
        </Button>
      </div>

      {/* Error Feedback */}
      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800" role="alert">
          {error}
        </div>
      )}

      {/* Compact Filters Toolbar */}
      <div className="rounded-xl border border-slate-200/90 bg-slate-50/60 p-3 space-y-2.5 text-xs text-slate-700">
        <div className="flex flex-wrap items-center gap-2.5">
          {isOrgAdminOrOwner && workspaceId && (
            <div className="flex items-center gap-1">
              <label htmlFor="trace-scope" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Scope:
              </label>
              <select
                id="trace-scope"
                value={scopeFilter}
                onChange={(e) => setScopeFilter(e.target.value as "workspace" | "organization")}
                className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                <option value="workspace">Active Workspace</option>
                <option value="organization">Organization-wide</option>
              </select>
            </div>
          )}

          <div className="flex items-center gap-1">
            <label htmlFor="trace-window" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Window:
            </label>
            <select
              id="trace-window"
              value={timeWindow}
              onChange={(e) => setTimeWindow(e.target.value as "1h" | "24h" | "7d" | "all")}
              className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
            >
              <option value="1h">Last 1 hour</option>
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="all">All time</option>
            </select>
          </div>

          <div className="flex items-center gap-1">
            <label htmlFor="trace-status" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Status:
            </label>
            <select
              id="trace-status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
            >
              <option value="">All Statuses</option>
              <option value="SUCCESS">Success</option>
              <option value="ERROR">Error</option>
              <option value="CANCELLED">Cancelled</option>
              <option value="PARTIAL">Partial</option>
            </select>
          </div>

          <div className="flex items-center gap-1">
            <label htmlFor="trace-op" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Operation:
            </label>
            <select
              id="trace-op"
              value={operationFilter}
              onChange={(e) => setOperationFilter(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
            >
              <option value="">All Operations</option>
              <option value="chat_stream">Chat Stream</option>
              <option value="chat_blocking">Chat Blocking</option>
              <option value="retrieval">Direct Retrieval</option>
              <option value="document_indexing">Document Ingestion</option>
            </select>
          </div>

          <div className="flex items-center gap-1">
            <label htmlFor="trace-min-lat" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Min Latency:
            </label>
            <input
              id="trace-min-lat"
              type="number"
              placeholder="ms..."
              value={minLatencyMs !== undefined ? minLatencyMs : ""}
              onChange={(e) => setMinLatencyMs(e.target.value ? Number(e.target.value) : undefined)}
              className="w-20 rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none font-mono"
            />
          </div>

          <div className="flex items-center gap-1">
            <input
              type="text"
              placeholder="Search Request ID..."
              value={requestIdFilter}
              onChange={(e) => setRequestIdFilter(e.target.value)}
              className="w-36 rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none"
            />
          </div>
        </div>
      </div>

      {/* Traces Table */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-40">Timestamp</TableHead>
              <TableHead>Trace ID</TableHead>
              <TableHead>Operation</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Total Latency</TableHead>
              <TableHead>Retrieval Mode</TableHead>
              <TableHead className="text-right">Spans</TableHead>
              <TableHead className="text-right">Diagnostics</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && traces.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-slate-400">
                  Loading query traces...
                </TableCell>
              </TableRow>
            ) : traces.length === 0 ? (
              <TableEmpty colSpan={8} message="No query traces recorded for the selected window and filters." />
            ) : (
              traces.map((trace) => (
                <TableRow key={trace.id} className="hover:bg-slate-50/70">
                  <TableCell className="whitespace-nowrap font-mono text-[11px] text-slate-500">
                    {formatDate(trace.started_at)}
                  </TableCell>
                  <TableCell className="font-mono text-slate-900 font-medium max-w-[150px] truncate" title={trace.trace_id}>
                    {trace.trace_id}
                  </TableCell>
                  <TableCell className="capitalize text-slate-700">
                    {trace.operation_type}
                  </TableCell>
                  <TableCell>
                    <Badge variant={getStatusBadgeVariant(trace.status)} size="sm">
                      {trace.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold text-slate-900">
                    {formatMs(trace.total_latency_ms)}
                  </TableCell>
                  <TableCell className="font-mono text-slate-600 text-[11px]">
                    {trace.retrieval_mode || "dense"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-600">
                    {trace.span_count}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => handleInspectTrace(trace.trace_id)}
                      className="text-brand-600 hover:text-brand-800 font-semibold hover:underline text-xs cursor-pointer"
                    >
                      Inspect Timeline
                    </button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-slate-500 px-1">
        <span>
          Showing page <span className="font-semibold text-slate-800">{currentPage}</span> of{" "}
          <span className="font-semibold text-slate-800">{totalPages}</span> ({total} total traces)
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadTraces(Math.max(0, offset - limit))}
            disabled={offset === 0 || isLoading}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadTraces(offset + limit)}
            disabled={offset + limit >= total || isLoading}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
