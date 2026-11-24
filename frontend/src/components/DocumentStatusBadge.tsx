import type { DocumentStatus } from "../types";

const STATUS_UI: Record<
  DocumentStatus,
  { label: string; badgeClass: string; dotClass: string; pulsing?: boolean }
> = {
  UPLOADED: {
    label: "Uploaded",
    badgeClass: "badge-neutral",
    dotClass: "bg-slate-400",
  },
  PROCESSING: {
    label: "Processing",
    badgeClass: "badge-warning",
    dotClass: "bg-amber-500",
    pulsing: true,
  },
  COMPLETED: {
    label: "Ready",
    badgeClass: "badge-success",
    dotClass: "bg-emerald-500",
  },
  FAILED: {
    label: "Failed",
    badgeClass: "badge-danger",
    dotClass: "bg-rose-500",
  },
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const ui = STATUS_UI[status] ?? STATUS_UI.UPLOADED;

  return (
    <span className={`badge ${ui.badgeClass}`} aria-label={`Status: ${ui.label}`}>
      <span
        className={`h-1.5 w-1.5 rounded-full ${ui.dotClass} ${
          ui.pulsing ? "animate-pulse" : ""
        }`}
        aria-hidden="true"
      />
      <span>{ui.label}</span>
    </span>
  );
}
