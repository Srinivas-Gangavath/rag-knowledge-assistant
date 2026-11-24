import React from "react";
import { Badge, type BadgeSize } from "./Badge";

export type StatusType =
  | "ok"
  | "success"
  | "warning"
  | "processing"
  | "error"
  | "failed"
  | "loading"
  | "neutral"
  | "info";

export interface StatusBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  status: StatusType;
  label?: string;
  size?: BadgeSize;
}

export function StatusBadge({
  status,
  label,
  size = "md",
  className = "",
  children,
  ...props
}: StatusBadgeProps) {
  const normalizedStatus = status.toLowerCase() as StatusType;

  let variant: "neutral" | "brand" | "success" | "warning" | "danger" | "info" = "neutral";
  let defaultLabel = "Neutral";
  let isPulsing = false;

  switch (normalizedStatus) {
    case "ok":
    case "success":
      variant = "success";
      defaultLabel = "Success";
      break;
    case "warning":
      variant = "warning";
      defaultLabel = "Warning";
      break;
    case "processing":
      variant = "warning";
      defaultLabel = "Processing";
      isPulsing = true;
      break;
    case "error":
    case "failed":
      variant = "danger";
      defaultLabel = "Failed";
      break;
    case "loading":
      variant = "neutral";
      defaultLabel = "Loading";
      isPulsing = true;
      break;
    case "info":
      variant = "info";
      defaultLabel = "Info";
      break;
    default:
      variant = "neutral";
      defaultLabel = "Neutral";
  }

  const dotClasses = {
    neutral: "bg-slate-400",
    brand: "bg-indigo-500",
    success: "bg-emerald-500",
    warning: "bg-amber-500",
    danger: "bg-rose-500",
    info: "bg-sky-500",
  }[variant];

  return (
    <Badge variant={variant} size={size} className={className} {...props}>
      <span
        className={`h-1.5 w-1.5 rounded-full ${dotClasses} ${
          isPulsing ? "animate-pulse" : ""
        }`}
        aria-hidden="true"
      />
      <span>{label || children || defaultLabel}</span>
    </Badge>
  );
}
