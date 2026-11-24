import React from "react";

export function PageContent({
  className = "",
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`flex flex-col gap-6 ${className}`} {...props}>
      {children}
    </div>
  );
}
