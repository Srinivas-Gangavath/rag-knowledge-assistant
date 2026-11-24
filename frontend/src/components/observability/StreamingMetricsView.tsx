import type { StreamingAnalytics } from "../../types";
import { formatMs, formatPercent } from "../../utils/format";

type StreamingMetricsViewProps = {
  streaming: StreamingAnalytics | null;
  isLoading: boolean;
};

export function StreamingMetricsView({
  streaming,
  isLoading,
}: StreamingMetricsViewProps) {
  if (isLoading && !streaming) {
    return (
      <div className="py-12 text-center text-xs text-slate-400">
        Loading streaming analytics...
      </div>
    );
  }

  if (!streaming || streaming.stream_count === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-xs text-slate-400">
        No active or historical SSE streaming sessions recorded for this window.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Streaming Overview Cards Grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Total SSE Streams
          </span>
          <span className="text-lg font-bold text-slate-900">
            {streaming.stream_count.toLocaleString()}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Success Rate
          </span>
          <span className="text-lg font-bold text-emerald-600">
            {formatPercent(streaming.success_rate)}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Client Cancellation
          </span>
          <span className="text-lg font-bold text-slate-700">
            {formatPercent(streaming.cancellation_rate)}
          </span>
        </div>
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Partial Response Rate
          </span>
          <span className="text-lg font-bold text-amber-600">
            {formatPercent(streaming.partial_rate)}
          </span>
        </div>
      </div>

      {/* TTFT & Duration Metrics */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-4 shadow-2xs">
        <div>
          <h3 className="text-xs font-bold text-slate-900">Time to First Token (TTFT) & Stream Durations</h3>
          <p className="text-[11px] text-slate-500">
            Metrics measuring server response latency before initial stream emission and overall token delivery time.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 border-t border-slate-100 pt-4 text-xs">
          <div>
            <span className="text-slate-400 block text-[11px]">Avg TTFT</span>
            <span className="text-base font-bold text-slate-900">
              {formatMs(streaming.average_ttft_ms)}
            </span>
          </div>

          <div>
            <span className="text-slate-400 block text-[11px]">P50 TTFT (Median)</span>
            <span className="text-base font-bold text-slate-900">
              {formatMs(streaming.p50_ttft_ms)}
            </span>
          </div>

          <div>
            <span className="text-slate-400 block text-[11px]">P95 TTFT</span>
            <span className="text-base font-bold text-slate-900">
              {formatMs(streaming.p95_ttft_ms)}
            </span>
          </div>

          <div>
            <span className="text-slate-400 block text-[11px]">P99 TTFT</span>
            <span className="text-base font-bold text-slate-900">
              {formatMs(streaming.p99_ttft_ms)}
            </span>
          </div>
        </div>

        <div className="border-t border-slate-100 pt-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
          <span className="text-slate-500">Average Total Stream Duration:</span>
          <span className="font-mono font-bold text-slate-800">
            {formatMs(streaming.average_stream_duration_ms)}
          </span>
        </div>
      </div>
    </div>
  );
}
