import React from "react";

export interface PageShellProps extends React.HTMLAttributes<HTMLDivElement> {
  maxWidth?: "default" | "full" | "narrow" | "wide";
}

export function PageShell({
  maxWidth = "default",
  className = "",
  children,
  ...props
}: PageShellProps) {
  const maxWidthClasses = {
    narrow: "max-w-4xl",
    default: "max-w-5xl",
    wide: "max-w-6xl",
    full: "max-w-none",
  }[maxWidth];

  return (
    <div
      className={`mx-auto flex w-full ${maxWidthClasses} flex-col gap-6 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
