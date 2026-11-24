import { useState } from "react";
import type { QueryTraceDetail, QueryTraceSpan } from "../../types";
import { Badge, Button, Modal, type BadgeVariant } from "../ui";
import { formatMs, formatStageName, formatDate } from "../../utils/format";

type TraceWaterfallViewProps = {
  trace: QueryTraceDetail;
  onClose: () => void;
  onExport?: (traceId: string) => void;
  isExporting?: boolean;
};

export function TraceWaterfallView({
  trace,
  onClose,
  onExport,
  isExporting,
}: TraceWaterfallViewProps) {
  const [selectedSpan, setSelectedSpan] = useState<QueryTraceSpan | null>(null);

  const totalDuration = trace.total_latency_ms || 1;
  const traceStart = new Date(trace.started_at).getTime();

  // Sort spans by start time
  const sortedSpans = [...(trace.spans || [])].sort((a, b) => {
    const startA = new Date(a.started_at).getTime();
    const startB = new Date(b.started_at).getTime();
    return startA - startB;
  });

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

  // Sanitize span metadata for display
  function getSafeSpanMetadata(metadata: Record<string, unknown> | null | undefined): Record<string, unknown> {
    if (!metadata || typeof metadata !== "object") return {};
    const safe: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(metadata)) {
      const lower = k.toLowerCase();
      // Blacklist sensitive contents
      if (
        lower.includes("query") ||
        lower.includes("prompt") ||
        lower.includes("chunk") ||
        lower.includes("response") ||
        lower.includes("content") ||
        lower.includes("token") ||
        lower.includes("secret") ||
        lower.includes("key")
      ) {
        if (typeof v === "number") {
          // Token counts or chunk counts are safe
          safe[k] = v;
        } else {
          safe[k] = "[REDACTED]";
        }
      } else {
        safe[k] = v;
      }
    }
    return safe;
  }

  return (
    <div className="space-y-5">
      {/* Header & Meta Strip */}
      <div className="rounded-xl border border-slate-200/90 bg-slate-50/70 p-4 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/60 pb-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-slate-500 hover:text-slate-800 font-medium cursor-pointer"
            >
              ← Back to Traces
            </button>
            <span className="text-slate-300">|</span>
            <span className="text-xs font-bold text-slate-900">Trace Timeline Waterfall</span>
          </div>

          <div className="flex items-center gap-2">
            {onExport && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onExport(trace.trace_id)}
                isLoading={isExporting}
              >
                Export Safe Diagnostics
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Trace ID</span>
            <span className="font-mono text-slate-800 font-semibold truncate block" title={trace.trace_id}>
              {trace.trace_id}
            </span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Request ID</span>
            <span className="font-mono text-slate-700 truncate block" title={trace.request_id}>
              {trace.request_id || "N/A"}
            </span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Total Latency</span>
            <span className="font-mono text-slate-900 font-bold">
              {formatMs(trace.total_latency_ms)}
            </span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Status</span>
            <Badge variant={getStatusBadgeVariant(trace.status)} size="sm">
              {trace.status}
            </Badge>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs pt-1 border-t border-slate-200/50">
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Operation</span>
            <span className="font-medium text-slate-800 capitalize">{trace.operation_type}</span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Retrieval Mode</span>
            <span className="font-mono text-slate-700">{trace.retrieval_mode || "dense"}</span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Workspace</span>
            <span className="font-mono text-slate-700 truncate block">
              {trace.workspace_id ? trace.workspace_id.slice(0, 8) + "..." : "Org-wide"}
            </span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Timestamp</span>
            <span className="text-slate-600">{formatDate(trace.started_at)}</span>
          </div>
        </div>
      </div>

      {/* Proportional Waterfall Timeline */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs space-y-3">
        <div className="flex items-center justify-between border-b border-slate-100 pb-2">
          <span className="text-xs font-bold text-slate-900">Execution Waterfall (Real Duration)</span>
          <span className="text-[11px] text-slate-400 font-mono">0 ms — {formatMs(totalDuration)}</span>
        </div>

        {sortedSpans.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400 italic">
            No granular span timings recorded for this trace.
          </div>
        ) : (
          <div className="space-y-2 pt-1">
            {sortedSpans.map((span) => {
              const spanStart = new Date(span.started_at).getTime();
              const startOffsetMs = Math.max(0, spanStart - traceStart);
              const durationMs = span.duration_ms || 1;

              // Proportional calculation
              const leftPercent = Math.min(95, Math.max(0, (startOffsetMs / totalDuration) * 100));
              const widthPercent = Math.min(
                100 - leftPercent,
                Math.max(2, (durationMs / totalDuration) * 100)
              );

              const isError = span.status.toUpperCase() === "ERROR" || Boolean(span.error_type);

              return (
                <div
                  key={span.id}
                  onClick={() => setSelectedSpan(span)}
                  className="group relative flex flex-col sm:flex-row sm:items-center gap-2 rounded-lg p-2 hover:bg-slate-50 cursor-pointer border border-transparent hover:border-slate-200 transition"
                  role="button"
                  tabIndex={0}
                >
                  {/* Span Label */}
                  <div className="w-full sm:w-48 shrink-0 flex items-center justify-between sm:justify-start gap-2">
                    <span className="text-xs font-semibold text-slate-800 truncate" title={span.span_name}>
                      {formatStageName(span.span_name)}
                    </span>
                    <Badge variant={getStatusBadgeVariant(span.status)} size="sm">
                      {span.duration_ms !== null ? formatMs(span.duration_ms) : "running"}
                    </Badge>
                  </div>

                  {/* Waterfall Bar Container */}
                  <div className="flex-1 relative h-6 bg-slate-100/80 rounded-md overflow-hidden flex items-center">
                    <div
                      className={`absolute h-4 rounded transition-all flex items-center px-1.5 ${
                        isError
                          ? "bg-rose-500 text-white"
                          : "bg-brand-600 text-white shadow-2xs"
                      }`}
                      style={{
                        left: `${leftPercent}%`,
                        width: `${widthPercent}%`,
                        minWidth: "24px",
                      }}
                    >
                      <span className="text-[10px] font-mono font-medium truncate select-none">
                        {formatMs(durationMs)}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Span Details Inspector Modal */}
      {selectedSpan && (
        <Modal
          isOpen={Boolean(selectedSpan)}
          onClose={() => setSelectedSpan(null)}
          title={`Span: ${formatStageName(selectedSpan.span_name)}`}
          description="Detailed execution metadata and safe latency parameters."
          size="md"
          footer={
            <Button variant="secondary" size="sm" onClick={() => setSelectedSpan(null)}>
              Close
            </Button>
          }
        >
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3.5">
              <div>
                <span className="text-[10px] font-bold uppercase text-slate-400 block">Span Type</span>
                <span className="font-mono text-slate-800">{selectedSpan.span_type}</span>
              </div>
              <div>
                <span className="text-[10px] font-bold uppercase text-slate-400 block">Duration</span>
                <span className="font-mono font-bold text-slate-900">
                  {formatMs(selectedSpan.duration_ms)}
                </span>
              </div>
              <div>
                <span className="text-[10px] font-bold uppercase text-slate-400 block">Started At</span>
                <span className="text-slate-700">{formatDate(selectedSpan.started_at)}</span>
              </div>
              <div>
                <span className="text-[10px] font-bold uppercase text-slate-400 block">Status</span>
                <Badge variant={getStatusBadgeVariant(selectedSpan.status)} size="sm">
                  {selectedSpan.status}
                </Badge>
              </div>
            </div>

            {selectedSpan.error_type && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
                <span className="font-bold block">Error Category:</span>
                <span className="font-mono">{selectedSpan.error_type}</span>
              </div>
            )}

            <div>
              <span className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                Safe Span Metadata
              </span>
              <pre className="rounded-xl border border-slate-800 bg-slate-900 p-3 font-mono text-[11px] text-slate-100 overflow-x-auto max-h-48 leading-relaxed">
                {JSON.stringify(getSafeSpanMetadata(selectedSpan.metadata as Record<string, unknown>), null, 2)}
              </pre>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
