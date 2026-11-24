import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type {
  TraceRetentionCleanupResponse,
  TraceRetentionPreviewResponse,
} from "../../types";
import { Button, Card, CardHeader, CardTitle, CardDescription, CardContent } from "../ui";
import { formatDate } from "../../utils/format";
import { RetentionCleanupModal } from "./RetentionCleanupModal";

type RetentionManagementViewProps = {
  isOrgAdminOrOwner: boolean;
};

export function RetentionManagementView({
  isOrgAdminOrOwner,
}: RetentionManagementViewProps) {
  const [retentionDays, setRetentionDays] = useState<number>(30);
  const [preview, setPreview] = useState<TraceRetentionPreviewResponse | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<TraceRetentionCleanupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  async function loadPreview(days: number) {
    setIsLoadingPreview(true);
    setError(null);
    try {
      const res = await api.previewTraceRetention(days);
      setPreview(res);
    } catch (err) {
      setError(userFacingError(err));
    } finally {
      setIsLoadingPreview(false);
    }
  }

  useEffect(() => {
    loadPreview(retentionDays);
  }, [retentionDays]);

  async function handleExecuteCleanup() {
    setError(null);
    try {
      const res = await api.cleanupTraceRetention({
        days: retentionDays,
        dry_run: false,
      });
      setCleanupResult(res);
      await loadPreview(retentionDays);
    } catch (err) {
      setError(userFacingError(err));
    }
  }

  return (
    <div className="space-y-5">
      {/* Top Header & Actions Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Telemetry Retention & Lifecycle</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Automated maintenance, dry-run previews, and lifecycle purge of historical query traces.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadPreview(retentionDays)}
            isLoading={isLoadingPreview}
          >
            Preview Cleanup (Dry Run)
          </Button>

          {isOrgAdminOrOwner && (
            <Button
              variant="danger-solid"
              size="sm"
              onClick={() => setModalOpen(true)}
              disabled={!preview || preview.eligible_trace_count === 0}
            >
              Execute Purge...
            </Button>
          )}
        </div>
      </div>

      {/* Error Feedback */}
      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800" role="alert">
          {error}
        </div>
      )}

      {/* Execution Result Banner */}
      {cleanupResult && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4 text-xs text-emerald-900 space-y-1">
          <p className="font-bold flex items-center gap-1.5 text-emerald-800">
            <span>✓</span> Telemetry Cleanup Successfully Executed
          </p>
          <p className="text-[11px] text-emerald-800">
            Permanently purged {cleanupResult.deleted_traces_count.toLocaleString()} query traces and{" "}
            {cleanupResult.deleted_spans_count.toLocaleString()} granular spans older than cutoff{" "}
            {formatDate(cleanupResult.cutoff)}.
          </p>
        </div>
      )}

      {/* Policy Selector & Summary */}
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <CardTitle>Trace Retention Policy Configuration</CardTitle>
              <CardDescription>
                Select a retention period to evaluate eligible traces and spans ready for lifecycle purge.
              </CardDescription>
            </div>

            <div className="flex items-center gap-2">
              <label htmlFor="retention-days" className="text-xs font-semibold text-slate-600">
                Retention Window:
              </label>
              <select
                id="retention-days"
                value={retentionDays}
                onChange={(e) => setRetentionDays(Number(e.target.value))}
                className="rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs font-medium text-slate-800 focus:border-brand-500 focus:outline-none shadow-2xs"
              >
                <option value={7}>7 Days</option>
                <option value={14}>14 Days</option>
                <option value={30}>30 Days (Default)</option>
                <option value={60}>60 Days</option>
                <option value={90}>90 Days</option>
                <option value={180}>180 Days</option>
                <option value={365}>365 Days</option>
              </select>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {isLoadingPreview && !preview ? (
            <div className="py-8 text-center text-xs text-slate-400">
              Evaluating eligible telemetry targets...
            </div>
          ) : preview ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 rounded-xl border border-slate-200/90 bg-slate-50/60 p-4 text-xs">
                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block mb-0.5">
                    Retention Threshold
                  </span>
                  <span className="text-base font-bold text-slate-900">
                    {retentionDays} Days
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block mb-0.5">
                    Cutoff Timestamp
                  </span>
                  <span className="font-mono text-slate-800 text-[11px] block truncate">
                    {formatDate(preview.cutoff)}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block mb-0.5">
                    Eligible Traces
                  </span>
                  <span className="text-base font-bold text-slate-900">
                    {preview.eligible_trace_count.toLocaleString()}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block mb-0.5">
                    Eligible Spans
                  </span>
                  <span className="text-base font-bold text-slate-900">
                    {preview.eligible_span_count.toLocaleString()}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div className="rounded-lg border border-slate-200 bg-white p-3">
                  <span className="text-slate-400 block text-[11px]">Oldest Trace Timestamp</span>
                  <span className="font-mono text-slate-800 font-medium">
                    {preview.oldest_trace_timestamp ? formatDate(preview.oldest_trace_timestamp) : "None (No traces recorded)"}
                  </span>
                </div>

                <div className="rounded-lg border border-slate-200 bg-white p-3">
                  <span className="text-slate-400 block text-[11px]">Newest Eligible Purge Timestamp</span>
                  <span className="font-mono text-slate-800 font-medium">
                    {preview.newest_eligible_timestamp ? formatDate(preview.newest_eligible_timestamp) : "None (No eligible traces)"}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-slate-400">
              No retention preview available.
            </div>
          )}

          {/* Audit Trail Invariant Guarantee Banner */}
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 text-xs text-emerald-900 flex items-start gap-3">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 font-bold text-xs mt-0.5">
              ✓
            </span>
            <div>
              <p className="font-semibold text-emerald-900">Compliance Invariant: Audit Logs Are Never Deleted</p>
              <p className="text-[11px] text-emerald-800 mt-0.5 leading-relaxed">
                Telemetry retention exclusively purges ephemeral query diagnostic spans and execution traces. All governance audit logs remain immutably preserved in the SHA-256 hash-chained ledger for enterprise compliance and auditing.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Confirmation Modal */}
      <RetentionCleanupModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        preview={preview}
        days={retentionDays}
        onConfirm={handleExecuteCleanup}
      />
    </div>
  );
}
