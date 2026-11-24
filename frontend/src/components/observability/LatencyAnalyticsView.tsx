import type { TraceAnalyticsResponse } from "../../types";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableEmpty,
} from "../ui";
import { formatMs, formatStageName } from "../../utils/format";

type LatencyAnalyticsViewProps = {
  analytics: TraceAnalyticsResponse | null;
  isLoading: boolean;
};

export function LatencyAnalyticsView({
  analytics,
  isLoading,
}: LatencyAnalyticsViewProps) {
  if (isLoading && !analytics) {
    return (
      <div className="py-12 text-center text-xs text-slate-400">
        Loading stage latency diagnostics...
      </div>
    );
  }

  if (!analytics || analytics.stages.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-xs text-slate-400">
        No latency data recorded for the selected window and filter scope.
      </div>
    );
  }

  const overview = analytics.overview;
  const stages = analytics.stages;

  return (
    <div className="space-y-6">
      {/* Latency Percentile Summary Strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Avg Request Latency
          </span>
          <span className="text-lg font-bold text-slate-900">
            {formatMs(overview.average_latency_ms)}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            P50 (Median)
          </span>
          <span className="text-lg font-bold text-slate-900">
            {formatMs(overview.p50_latency_ms)}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            P95 Percentile
          </span>
          <span className="text-lg font-bold text-slate-900">
            {formatMs(overview.p95_latency_ms)}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            P99 Percentile
          </span>
          <span className="text-lg font-bold text-slate-900">
            {formatMs(overview.p99_latency_ms)}
          </span>
        </div>
      </div>

      {/* Stage Bottleneck Analysis Table */}
      <div className="space-y-2">
        <div className="flex items-center justify-between px-1">
          <div>
            <h3 className="text-xs font-bold text-slate-900">Stage Bottleneck & Execution Distribution</h3>
            <p className="text-[11px] text-slate-500">
              Granular latency percentiles and execution contribution across the end-to-end RAG pipeline.
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Pipeline Stage</TableHead>
                <TableHead className="text-right">Samples</TableHead>
                <TableHead className="text-right">Average</TableHead>
                <TableHead className="text-right">P50</TableHead>
                <TableHead className="text-right">P95</TableHead>
                <TableHead className="text-right">P99</TableHead>
                <TableHead className="text-right">% of Total</TableHead>
                <TableHead className="w-36">Execution Share</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stages.length === 0 ? (
                <TableEmpty colSpan={8} message="No stage execution telemetry available." />
              ) : (
                stages.map((st) => {
                  const pct = st.percentage_of_total ?? 0;
                  const displayPct = pct > 0 ? (pct * 100).toFixed(1) + "%" : "0.0%";
                  const isHighImpact = pct >= 0.25;

                  return (
                    <TableRow key={st.stage} className="hover:bg-slate-50/70">
                      <TableCell className="font-semibold text-slate-800">
                        {formatStageName(st.stage)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-slate-600">
                        {st.count.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right font-mono font-medium text-slate-900">
                        {st.count > 0 ? formatMs(st.average_ms) : "N/A"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-slate-700">
                        {st.count > 0 ? formatMs(st.p50_ms) : "N/A"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-slate-700">
                        {st.count > 0 ? formatMs(st.p95_ms) : "N/A"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-slate-700">
                        {st.count > 0 ? formatMs(st.p99_ms) : "N/A"}
                      </TableCell>
                      <TableCell className="text-right font-mono font-semibold text-slate-900">
                        {st.count > 0 ? displayPct : "N/A"}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                isHighImpact ? "bg-amber-500" : "bg-brand-600"
                              }`}
                              style={{ width: `${Math.min(100, Math.max(0, pct * 100))}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-slate-400 font-mono w-9 text-right shrink-0">
                            {(pct * 100).toFixed(0)}%
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
