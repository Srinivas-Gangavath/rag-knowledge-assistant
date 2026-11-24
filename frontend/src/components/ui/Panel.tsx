import React from "react";

export interface PanelProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "subtle";
}

export function Panel({
  variant = "default",
  className = "",
  children,
  ...props
}: PanelProps) {
  const variantClass = variant === "subtle" ? "panel-subtle" : "panel";
  return (
    <div className={`${variantClass} p-5 ${className}`} {...props}>
      {children}
    </div>
  );
}
