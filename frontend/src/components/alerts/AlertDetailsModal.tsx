import { useState } from "react";
import type { PlatformAlertDetail } from "../../types";
import { Modal, Badge, Button, type BadgeVariant } from "../ui";
import { formatAlertType, formatDate } from "../../utils/format";

type AlertDetailsModalProps = {
  alert: PlatformAlertDetail | null;
  onClose: () => void;
  onAcknowledge: (alertId: string) => Promise<void>;
  onResolve: (alertId: string, reason?: string) => Promise<void>;
  onNavigateToTrace?: (traceId: string) => void;
};

export function AlertDetailsModal({
  alert,
  onClose,
  onAcknowledge,
  onResolve,
  onNavigateToTrace,
}: AlertDetailsModalProps) {
  const [resolveReason, setResolveReason] = useState("");
  const [showResolveInput, setShowResolveInput] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  if (!alert) return null;

  function getSeverityBadgeVariant(sev: string): BadgeVariant {
    switch (sev.toUpperCase()) {
      case "CRITICAL":
      case "ERROR":
        return "danger";
      case "WARNING":
        return "warning";
      case "INFO":
        return "info";
      default:
        return "neutral";
    }
  }

  function getStatusBadgeVariant(status: string): BadgeVariant {
    switch (status.toUpperCase()) {
      case "OPEN":
        return "danger";
      case "ACKNOWLEDGED":
        return "warning";
      case "RESOLVED":
        return "success";
      default:
        return "neutral";
    }
  }

  async function handleAcknowledgeClick() {
    if (!alert) return;
    setActionLoading(true);
    try {
      await onAcknowledge(alert.id);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleResolveSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!alert) return;
    setActionLoading(true);
    try {
      await onResolve(alert.id, resolveReason.trim() || undefined);
      setShowResolveInput(false);
      setResolveReason("");
    } finally {
      setActionLoading(false);
    }
  }

  const diagnostic = alert.diagnostic;

  return (
    <Modal
      isOpen={Boolean(alert)}
      onClose={onClose}
      title={alert.title || formatAlertType(alert.alert_type)}
      description="Operational alert diagnostic findings, evidence telemetry, and lifecycle status."
      size="lg"
      footer={
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2">
            {alert.status === "OPEN" && (
              <Button
                variant="secondary"
                size="sm"
                onClick={handleAcknowledgeClick}
                isLoading={actionLoading}
              >
                Acknowledge Alert
              </Button>
            )}

            {alert.status !== "RESOLVED" && !showResolveInput && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setShowResolveInput(true)}
              >
                Resolve Incident
              </Button>
            )}
          </div>

          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-xs">
        {/* Core Attributes */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Severity</span>
            <Badge variant={getSeverityBadgeVariant(alert.severity)} size="sm">
              {alert.severity}
            </Badge>
          </div>

          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Incident Status</span>
            <Badge variant={getStatusBadgeVariant(alert.status)} size="sm">
              {alert.status}
            </Badge>
          </div>

          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Detected Time</span>
            <span className="text-slate-800 font-medium">{formatDate(alert.detected_at)}</span>
          </div>

          <div>
            <span className="text-[10px] uppercase font-bold text-slate-400 block">Workspace</span>
            <span className="font-mono text-slate-700 truncate block">
              {alert.workspace_id ? alert.workspace_id.slice(0, 8) + "..." : "Org-wide"}
            </span>
          </div>
        </div>

        {/* Resolve Input Box when triggered */}
        {showResolveInput && (
          <form onSubmit={handleResolveSubmit} className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3.5 space-y-2.5">
            <span className="font-semibold text-emerald-900 block">Resolution Summary</span>
            <input
              type="text"
              placeholder="Enter resolution reason or root-cause notes..."
              value={resolveReason}
              onChange={(e) => setResolveReason(e.target.value)}
              className="w-full rounded-lg border border-emerald-300 bg-white py-1.5 px-3 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              autoFocus
            />
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowResolveInput(false)}
                className="text-xs text-slate-600 hover:text-slate-900 px-2 py-1 cursor-pointer"
              >
                Cancel
              </button>
              <Button variant="primary" size="sm" type="submit" isLoading={actionLoading}>
                Confirm Resolution
              </Button>
            </div>
          </form>
        )}

        {/* Observed Telemetry & Thresholds */}
        <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-2.5">
          <h4 className="font-bold text-slate-900 flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-brand-600" />
            Observed Metrics
          </h4>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-1 text-xs">
            <div>
              <span className="text-slate-400 block text-[11px]">Metric Name</span>
              <span className="font-mono text-slate-800">{alert.metric_name || "N/A"}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[11px]">Current Observed Value</span>
              <span className="font-mono font-bold text-rose-600">
                {alert.metric_value !== null ? alert.metric_value.toLocaleString() : "N/A"}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[11px]">Configured Threshold</span>
              <span className="font-mono text-slate-800">
                {alert.threshold_value !== null ? alert.threshold_value.toLocaleString() : "N/A"}
              </span>
            </div>
          </div>

          <p className="text-slate-600 pt-1 text-[11px] leading-relaxed">
            {alert.description}
          </p>
        </div>

        {/* Diagnostic Context & Inferences */}
        {diagnostic && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
            <h4 className="font-bold text-slate-900 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-amber-500" />
              Diagnostic Inferences
            </h4>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-slate-400 block text-[11px]">Subsystem</span>
                <span className="font-medium text-slate-800 capitalize">{diagnostic.subsystem}</span>
              </div>
              <div>
                <span className="text-slate-400 block text-[11px]">Dominant Pipeline Stage</span>
                <span className="font-medium text-slate-800">
                  {diagnostic.dominant_stage || "Global Pipeline"}
                </span>
              </div>
            </div>

            {diagnostic.inferred && (
              <div className="rounded-lg bg-amber-50 border border-amber-200/70 p-3 text-[11px] text-amber-900">
                <span className="font-bold block mb-0.5">Inferred Root Cause Hypothesis:</span>
                <p>{diagnostic.inferred}</p>
              </div>
            )}

            {/* Trace Correlation */}
            {diagnostic.sample_trace_id && onNavigateToTrace && (
              <div className="pt-1 flex items-center justify-between border-t border-slate-100 text-xs">
                <span className="text-slate-500">Correlated Sample Trace:</span>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onNavigateToTrace(diagnostic.sample_trace_id!);
                  }}
                  className="font-mono text-brand-600 hover:text-brand-800 font-semibold hover:underline cursor-pointer"
                >
                  {diagnostic.sample_trace_id} → Open Trace Waterfall
                </button>
              </div>
            )}
          </div>
        )}

        {/* Incident Lifecycle History */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5 space-y-2 text-xs">
          <span className="font-semibold text-slate-700 block">Incident History</span>
          <div className="space-y-1 text-slate-600 text-[11px]">
            <p>• Detected on {formatDate(alert.detected_at)}</p>
            {alert.acknowledged_at && (
              <p>
                • Acknowledged by {alert.acknowledged_by || "Administrator"} on{" "}
                {formatDate(alert.acknowledged_at)}
              </p>
            )}
            {alert.resolved_at && (
              <p className="text-emerald-700 font-medium">
                • Resolved by {alert.resolved_by || "Administrator"} on{" "}
                {formatDate(alert.resolved_at)}{" "}
                {alert.resolution_reason ? `("${alert.resolution_reason}")` : ""}
              </p>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
