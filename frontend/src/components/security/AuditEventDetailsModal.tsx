import { Modal, Badge, Button, type BadgeVariant } from "../ui";
import type { AuditLogItem } from "../../types";
import { formatAuditEvent, formatAuditOutcome, formatDate } from "../../utils/format";

type AuditEventDetailsModalProps = {
  log: AuditLogItem | null;
  onClose: () => void;
};

export function AuditEventDetailsModal({
  log,
  onClose,
}: AuditEventDetailsModalProps) {
  if (!log) return null;

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

  // Filter any sensitive keys just in case from metadata before presentation
  const safeMetadata: Record<string, unknown> = {};
  if (log.metadata && typeof log.metadata === "object") {
    for (const [key, value] of Object.entries(log.metadata)) {
      const lowerKey = key.toLowerCase();
      if (
        lowerKey.includes("password") ||
        lowerKey.includes("token") ||
        lowerKey.includes("secret") ||
        lowerKey.includes("key") ||
        lowerKey.includes("credential")
      ) {
        safeMetadata[key] = "[REDACTED]";
      } else {
        safeMetadata[key] = value;
      }
    }
  }

  return (
    <Modal
      isOpen={Boolean(log)}
      onClose={onClose}
      title="Audit Event Details"
      description="Cryptographically recorded event telemetry for governance and compliance."
      size="lg"
      footer={
        <Button variant="secondary" size="sm" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className="space-y-5 text-xs">
        {/* Core Attributes Grid */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 rounded-xl border border-slate-200/90 bg-slate-50/60 p-4">
          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-0.5">
              Timestamp
            </span>
            <p className="font-medium text-slate-800">
              {formatDate(log.created_at)}
            </p>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">
              {new Date(log.created_at).toISOString()}
            </p>
          </div>

          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-0.5">
              Outcome
            </span>
            <div className="flex items-center gap-2">
              <Badge variant={getOutcomeBadgeVariant(log.outcome)} size="sm">
                {formatAuditOutcome(log.outcome)}
              </Badge>
              <span className="text-slate-500 text-[11px]">Action: {log.action}</span>
            </div>
          </div>

          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-0.5">
              Event Type
            </span>
            <p className="font-semibold text-slate-800">
              {formatAuditEvent(log.event_type)}
            </p>
            <p className="text-[10px] text-slate-500 font-mono">{log.event_type}</p>
          </div>

          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-0.5">
              Actor Identity
            </span>
            <p className="font-medium text-slate-800 truncate" title={log.actor_email_snapshot || log.actor_user_id || "System"}>
              {log.actor_email_snapshot || "System / Service"}
            </p>
            {log.actor_user_id && (
              <p className="text-[10px] text-slate-500 font-mono truncate" title={log.actor_user_id}>
                ID: {log.actor_user_id}
              </p>
            )}
          </div>

          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-0.5">
              Resource
            </span>
            <p className="font-medium text-slate-800">
              {log.resource_type ? `${log.resource_type}` : "None"}
            </p>
            {log.resource_id && (
              <p className="text-[10px] text-slate-500 font-mono truncate" title={log.resource_id}>
                ID: {log.resource_id}
              </p>
            )}
          </div>

          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-0.5">
              Workspace & Context
            </span>
            <p className="font-mono text-slate-700 truncate" title={log.workspace_id || "Organization-wide"}>
              {log.workspace_id ? `Workspace: ${log.workspace_id}` : "Scope: Organization-wide"}
            </p>
            {log.request_id && (
              <p className="text-[10px] text-slate-500 font-mono truncate" title={log.request_id}>
                Req: {log.request_id}
              </p>
            )}
          </div>

          {log.ip_address && (
            <div className="sm:col-span-2 border-t border-slate-200/60 pt-2 mt-1">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-0.5">
                Client Network Origin
              </span>
              <p className="font-mono text-slate-700">{log.ip_address}</p>
            </div>
          )}
        </div>

        {/* Cryptographic Hash Chain Signatures */}
        <div className="rounded-xl border border-slate-200/90 bg-white p-4 space-y-3">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2">
            <span className="font-semibold text-slate-800 flex items-center gap-1.5">
              <svg className="h-4 w-4 text-brand-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              Cryptographic Integrity Signatures
            </span>
            <Badge variant="brand" size="sm">SHA-256 Chained</Badge>
          </div>

          <div className="space-y-2">
            <div>
              <span className="text-[10px] uppercase font-bold text-slate-400 block mb-0.5">
                Previous Record Hash:
              </span>
              <div className="rounded-md bg-slate-50 border border-slate-200/80 px-2.5 py-1.5 font-mono text-[11px] text-slate-700 break-all select-all">
                {log.previous_hash || "GENESIS_BLOCK (None)"}
              </div>
            </div>

            <div>
              <span className="text-[10px] uppercase font-bold text-slate-400 block mb-0.5">
                Current Record Hash:
              </span>
              <div className="rounded-md bg-brand-50/50 border border-brand-200/80 px-2.5 py-1.5 font-mono text-[11px] text-brand-700 font-semibold break-all select-all">
                {log.event_hash}
              </div>
            </div>
          </div>
        </div>

        {/* Sanitized Structured Metadata */}
        <div>
          <span className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1.5">
            Safe Structured Metadata
          </span>
          {Object.keys(safeMetadata).length > 0 ? (
            <pre className="rounded-xl border border-slate-800 bg-slate-900 p-3.5 font-mono text-[11px] text-slate-100 overflow-x-auto max-h-48 leading-relaxed">
              {JSON.stringify(safeMetadata, null, 2)}
            </pre>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-200 p-3 text-slate-400 italic text-[11px]">
              No extra metadata recorded for this event.
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
