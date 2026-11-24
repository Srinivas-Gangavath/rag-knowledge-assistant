import React from "react";

export interface SectionHeaderProps {
  title?: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function SectionHeader({
  title,
  description,
  action,
  className = "",
}: SectionHeaderProps) {
  if (!title && !description && !action) return null;

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 ${className}`}
    >
      <div>
        {title && (
          <h2 className="text-sm font-semibold text-slate-900 tracking-tight">
            {title}
          </h2>
        )}
        {description && (
          <p className="mt-0.5 text-xs text-slate-500 leading-normal">
            {description}
          </p>
        )}
      </div>
      {action && <div className="flex items-center gap-2">{action}</div>}
    </div>
  );
}
