import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { TraceAnalyticsResponse } from "../../types";
import { Button, Tabs, TabList, TabTrigger, TabContent } from "../ui";
import { formatMs, formatPercent } from "../../utils/format";
import { LatencyAnalyticsView } from "./LatencyAnalyticsView";
import { ProviderMetricsView } from "./ProviderMetricsView";
import { StreamingMetricsView } from "./StreamingMetricsView";

type ObservabilityOverviewProps = {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
};

export function ObservabilityOverview({
  workspaceId,
  isOrgAdminOrOwner,
}: ObservabilityOverviewProps) {
  const [analytics, setAnalytics] = useState<TraceAnalyticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [scopeFilter, setScopeFilter] = useState<"workspace" | "organization">(
    workspaceId ? "workspace" : "organization"
  );
  const [timeWindow, setTimeWindow] = useState<"1h" | "24h" | "7d" | "all">("24h");
  const [operationFilter, setOperationFilter] = useState("");
  const [retrievalModeFilter, setRetrievalModeFilter] = useState("");

  const [activeTab, setActiveTab] = useState("latency");

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

  async function loadAnalytics() {
    setIsLoading(true);
    setError(null);
    try {
      const { from_time, to_time } = getTimeRange();
      const res = await api.getTraceAnalytics({
        workspace_id: scopeFilter === "workspace" ? workspaceId : undefined,
        from_time,
        to_time,
        operation_type: operationFilter || undefined,
        retrieval_mode: retrievalModeFilter || undefined,
      });
      setAnalytics(res);
    } catch (err) {
      setError(userFacingError(err, "list"));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadAnalytics();
  }, [
    workspaceId,
    scopeFilter,
    timeWindow,
    operationFilter,
    retrievalModeFilter,
  ]);

  const overview = analytics?.overview;

  return (
    <div className="space-y-5">
      {/* Top Header & Actions Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Observability & Performance</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Monitor knowledge workload, latency, generation performance, and system behavior.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={loadAnalytics}
          isLoading={isLoading}
        >
          Refresh Metrics
        </Button>
      </div>

      {/* Error Feedback */}
      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800" role="alert">
          {error}
        </div>
      )}

      {/* Filters Toolbar */}
      <div className="rounded-xl border border-slate-200/90 bg-slate-50/60 p-3 flex flex-wrap items-center gap-2.5 text-xs text-slate-700">
        {isOrgAdminOrOwner && workspaceId && (
          <div className="flex items-center gap-1">
            <label htmlFor="obs-scope" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Scope:
            </label>
            <select
              id="obs-scope"
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
          <label htmlFor="obs-window" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
            Time Range:
          </label>
          <select
            id="obs-window"
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
          <label htmlFor="obs-op" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
            Operation:
          </label>
          <select
            id="obs-op"
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
          <label htmlFor="obs-mode" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
            Retrieval Mode:
          </label>
          <select
            id="obs-mode"
            value={retrievalModeFilter}
            onChange={(e) => setRetrievalModeFilter(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
          >
            <option value="">All Modes</option>
            <option value="dense">Dense Embedding</option>
            <option value="lexical">Lexical (BM25)</option>
            <option value="hybrid">Hybrid (RRF Fusion)</option>
          </select>
        </div>
      </div>

      {/* Top-Level Compact Metric Strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5 rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Total Requests
          </span>
          <span className="text-xl font-bold text-slate-900">
            {overview ? overview.request_count.toLocaleString() : "—"}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Error Rate
          </span>
          <span className={`text-xl font-bold ${overview && overview.error_rate > 0.05 ? "text-rose-600" : "text-emerald-600"}`}>
            {overview ? formatPercent(overview.error_rate) : "—"}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Avg Latency
          </span>
          <span className="text-xl font-bold text-slate-900">
            {overview ? formatMs(overview.average_latency_ms) : "—"}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            P95 Latency
          </span>
          <span className="text-xl font-bold text-slate-900">
            {overview ? formatMs(overview.p95_latency_ms) : "—"}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            P99 Latency
          </span>
          <span className="text-xl font-bold text-slate-900">
            {overview ? formatMs(overview.p99_latency_ms) : "—"}
          </span>
        </div>
      </div>

      {/* Performance Subsections Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabList>
          <TabTrigger value="latency">Overall & Stage Bottlenecks</TabTrigger>
          <TabTrigger value="providers">Providers & Models</TabTrigger>
          <TabTrigger value="streaming">Streaming & TTFT</TabTrigger>
        </TabList>

        <TabContent value="latency">
          <LatencyAnalyticsView analytics={analytics} isLoading={isLoading} />
        </TabContent>

        <TabContent value="providers">
          <ProviderMetricsView
            providers={analytics?.providers || []}
            isLoading={isLoading}
          />
        </TabContent>

        <TabContent value="streaming">
          <StreamingMetricsView
            streaming={analytics?.streaming || null}
            isLoading={isLoading}
          />
        </TabContent>
      </Tabs>
    </div>
  );
}
