import type { HTMLAttributes, ReactNode } from "react";

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-lg border border-border bg-surface p-4 shadow-sm ${className}`}
      {...props}
    />
  );
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-base font-semibold text-moss-slate">{children}</h3>;
}

export function CardBody({ children }: { children: ReactNode }) {
  return <div className="mt-2 text-sm text-muted">{children}</div>;
}
