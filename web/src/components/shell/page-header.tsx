import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  headingId,
}: {
  title: string;
  description?: string;
  eyebrow?: string;
  actions?: ReactNode;
  headingId?: string;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        {eyebrow ? (
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">{eyebrow}</p>
        ) : null}
        <h1 id={headingId} className="text-2xl font-semibold tracking-tight text-text-primary">
          {title}
        </h1>
        {description ? (
          <p className="mt-1 max-w-3xl text-sm text-text-secondary">{description}</p>
        ) : null}
      </div>
      {actions}
    </header>
  );
}
