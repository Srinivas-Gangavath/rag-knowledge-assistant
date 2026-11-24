import { useState } from "react";
import type { TraceRetentionPreviewResponse } from "../../types";
import { Modal, Button } from "../ui";
import { formatDate } from "../../utils/format";

type RetentionCleanupModalProps = {
  isOpen: boolean;
  onClose: () => void;
  preview: TraceRetentionPreviewResponse | null;
  days: number;
  onConfirm: () => Promise<void>;
};

export function RetentionCleanupModal({
  isOpen,
  onClose,
  preview,
  days,
  onConfirm,
}: RetentionCleanupModalProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);

  if (!isOpen || !preview) return null;

  async function handleExecute() {
    if (!confirmed) return;
    setIsExecuting(true);
    try {
      await onConfirm();
      onClose();
    } finally {
      setIsExecuting(false);
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Confirm Telemetry Purge"
      description="This action will permanently delete historical query traces and spans older than the specified retention window."
      size="md"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={isExecuting}>
            Cancel
          </Button>
          <Button
            variant="danger-solid"
            size="sm"
            onClick={handleExecute}
            disabled={!confirmed || isExecuting}
            isLoading={isExecuting}
          >
            Permanently Purge Telemetry
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-xs">
        {/* Critical Notice */}
        <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-3.5 text-rose-900 space-y-1">
          <p className="font-bold flex items-center gap-1.5 text-rose-800">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-rose-200 text-rose-800 font-bold text-[10px]">
              !
            </span>
            Irreversible Telemetry Deletion
          </p>
          <p className="text-[11px] text-rose-800 leading-normal">
            Query traces, individual stage spans, and associated performance timestamps created before the cutoff date will be permanently deleted from the database.
          </p>
        </div>

        {/* Audit Log Safety Guarantee */}
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-3.5 text-emerald-900 space-y-1">
          <p className="font-bold flex items-center gap-1.5 text-emerald-800">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-200 text-emerald-800 font-bold text-[10px]">
              ✓
            </span>
            Audit Logs Are NOT Deleted
          </p>
          <p className="text-[11px] text-emerald-800 leading-normal">
            Compliance and security audit logs are stored in a tamper-evident, append-only cryptographic ledger and are strictly exempt from telemetry lifecycle purges.
          </p>
        </div>

        {/* Target Counts */}
        <div className="grid grid-cols-3 gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Cutoff Date</span>
            <span className="font-mono text-slate-800 font-semibold">{formatDate(preview.cutoff)}</span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Eligible Traces</span>
            <span className="font-mono text-rose-700 font-bold text-sm">
              {preview.eligible_trace_count.toLocaleString()}
            </span>
          </div>
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Eligible Spans</span>
            <span className="font-mono text-rose-700 font-bold text-sm">
              {preview.eligible_span_count.toLocaleString()}
            </span>
          </div>
        </div>

        {/* Explicit Confirmation Checkbox */}
        <div className="pt-2">
          <label className="flex items-start gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-0.5 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            />
            <span className="text-slate-700 leading-normal">
              I understand that this action is permanent and will permanently purge {preview.eligible_trace_count.toLocaleString()} traces older than {days} days.
            </span>
          </label>
        </div>
      </div>
    </Modal>
  );
}
