import React from "react";

export type BadgeVariant = "neutral" | "brand" | "success" | "warning" | "danger" | "info";
export type BadgeSize = "sm" | "md";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
}

export function Badge({
  variant = "neutral",
  size = "md",
  dot = false,
  className = "",
  children,
  ...props
}: BadgeProps) {
  const variantClasses = {
    neutral: "badge-neutral",
    brand: "badge-brand",
    success: "badge-success",
    warning: "badge-warning",
    danger: "badge-danger",
    info: "badge-info",
  }[variant];

  const sizeClasses = {
    sm: "px-2 py-0.2 text-[10px]",
    md: "px-2.5 py-0.5 text-xs",
  }[size];

  const dotColorClasses = {
    neutral: "bg-slate-400",
    brand: "bg-indigo-500",
    success: "bg-emerald-500",
    warning: "bg-amber-500",
    danger: "bg-rose-500",
    info: "bg-sky-500",
  }[variant];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium tracking-tight select-none ${variantClasses} ${sizeClasses} ${className}`}
      {...props}
    >
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${dotColorClasses}`}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}
