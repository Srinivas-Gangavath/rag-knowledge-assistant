import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { SlowTraceItem } from "../../types";
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
} from "../ui";
import { formatMs, formatStageName, formatDate } from "../../utils/format";

type SlowQueriesViewProps = {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
  onSelectTrace: (traceId: string) => void;
};

export function SlowQueriesView({
  workspaceId,
  isOrgAdminOrOwner,
  onSelectTrace,
}: SlowQueriesViewProps) {
  const [slowTraces, setSlowTraces] = useState<SlowTraceItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(15);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [scopeFilter, setScopeFilter] = useState<"workspace" | "organization">(
    workspaceId ? "workspace" : "organization"
  );
  const [operationFilter, setOperationFilter] = useState("");
  const [retrievalModeFilter, setRetrievalModeFilter] = useState("");
  const [timeWindow, setTimeWindow] = useState<"1h" | "24h" | "7d" | "all">("24h");

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

  async function loadSlowQueries(targetOffset: number) {
    setIsLoading(true);
    setError(null);
    try {
      const { from_time, to_time } = getTimeRange();
      const res = await api.listSlowTraces({
        workspace_id: scopeFilter === "workspace" ? workspaceId : undefined,
        operation_type: operationFilter || undefined,
        retrieval_mode: retrievalModeFilter || undefined,
        from_time,
        to_time,
        limit,
        offset: targetOffset,
      });
      setSlowTraces(res.items);
      setTotal(res.total);
      setOffset(res.offset);
    } catch (err) {
      setError(userFacingError(err, "list"));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadSlowQueries(0);
  }, [
    workspaceId,
    scopeFilter,
    operationFilter,
    retrievalModeFilter,
    timeWindow,
  ]);

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="space-y-4">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold text-slate-900">Slow Queries</h2>
            <Badge variant="warning" size="sm">
              &gt; 3,000 ms threshold
            </Badge>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Operational log of queries exceeding performance SLA thresholds with dominant stage attribution.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => loadSlowQueries(offset)}
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

      {/* Filter Bar */}
      <div className="rounded-xl border border-slate-200/90 bg-slate-50/60 p-3 flex flex-wrap items-center gap-2.5 text-xs text-slate-700">
        {isOrgAdminOrOwner && workspaceId && (
          <div className="flex items-center gap-1">
            <label htmlFor="slow-scope" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Scope:
            </label>
            <select
              id="slow-scope"
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
          <label htmlFor="slow-window" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
            Window:
          </label>
          <select
            id="slow-window"
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
          <label htmlFor="slow-op" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
            Operation:
          </label>
          <select
            id="slow-op"
            value={operationFilter}
            onChange={(e) => setOperationFilter(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
          >
            <option value="">All Operations</option>
            <option value="chat_stream">Chat Stream</option>
            <option value="chat_blocking">Chat Blocking</option>
            <option value="retrieval">Direct Retrieval</option>
          </select>
        </div>

        <div className="flex items-center gap-1">
          <label htmlFor="slow-mode" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
            Mode:
          </label>
          <select
            id="slow-mode"
            value={retrievalModeFilter}
            onChange={(e) => setRetrievalModeFilter(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
          >
            <option value="">All Modes</option>
            <option value="dense">Dense</option>
            <option value="lexical">Lexical</option>
            <option value="hybrid">Hybrid</option>
          </select>
        </div>
      </div>

      {/* Slow Queries Table */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-40">Timestamp</TableHead>
              <TableHead>Trace ID</TableHead>
              <TableHead className="text-right">Total Latency</TableHead>
              <TableHead>Dominant Bottleneck</TableHead>
              <TableHead>Classification</TableHead>
              <TableHead>Retrieval Mode</TableHead>
              <TableHead className="text-right">Diagnostics</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && slowTraces.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-slate-400">
                  Loading slow query list...
                </TableCell>
              </TableRow>
            ) : slowTraces.length === 0 ? (
              <TableEmpty colSpan={7} message="No slow queries exceeded the latency threshold during this period." />
            ) : (
              slowTraces.map((item) => (
                <TableRow key={item.trace_id} className="hover:bg-slate-50/70">
                  <TableCell className="whitespace-nowrap font-mono text-[11px] text-slate-500">
                    {formatDate(item.started_at)}
                  </TableCell>
                  <TableCell className="font-mono text-slate-900 font-medium max-w-[140px] truncate" title={item.trace_id}>
                    {item.trace_id}
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold text-rose-600">
                    {formatMs(item.total_latency_ms)}
                  </TableCell>
                  <TableCell>
                    {item.dominant_stage ? (
                      <div className="flex flex-col">
                        <span className="font-semibold text-slate-800">
                          {formatStageName(item.dominant_stage)}
                        </span>
                        <span className="text-[10px] text-slate-500 font-mono">
                          {formatMs(item.dominant_stage_duration_ms)}{" "}
                          {item.dominant_stage_percentage !== null
                            ? `(${(item.dominant_stage_percentage * 100).toFixed(0)}%)`
                            : ""}
                        </span>
                      </div>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        item.is_generation_dominant
                          ? "brand"
                          : item.is_retrieval_dominant
                          ? "warning"
                          : "neutral"
                      }
                      size="sm"
                    >
                      {item.slow_classification.replace(/_/g, " ")}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-slate-600 text-[11px]">
                    {item.retrieval_mode || "dense"}
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => onSelectTrace(item.trace_id)}
                      className="text-brand-600 hover:text-brand-800 font-semibold hover:underline text-xs cursor-pointer"
                    >
                      Inspect Timeline →
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
          <span className="font-semibold text-slate-800">{totalPages}</span> ({total} slow queries)
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadSlowQueries(Math.max(0, offset - limit))}
            disabled={offset === 0 || isLoading}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadSlowQueries(offset + limit)}
            disabled={offset + limit >= total || isLoading}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
