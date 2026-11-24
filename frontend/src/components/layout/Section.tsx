import React from "react";
import { SectionHeader } from "./SectionHeader";

export interface SectionProps extends React.HTMLAttributes<HTMLElement> {
  title?: string;
  description?: string;
  action?: React.ReactNode;
}

export function Section({
  title,
  description,
  action,
  className = "",
  children,
  ...props
}: SectionProps) {
  return (
    <section className={`flex flex-col gap-4 ${className}`} {...props}>
      {(title || description || action) && (
        <SectionHeader title={title} description={description} action={action} />
      )}
      {children}
    </section>
  );
}
