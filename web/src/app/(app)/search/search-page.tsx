"use client";

import { PageHeader } from "@/components/shell/page-header";
import { SearchCommandPanel } from "@/components/shell/command-palette";
import { useOpenCapture } from "@/components/shell/app-shell";

export function SearchPage({
  initialQuery,
  enrollmentId,
}: {
  initialQuery: string;
  enrollmentId?: string;
}) {
  const onCapture = useOpenCapture();
  return (
    <section className="mx-auto max-w-3xl">
      <PageHeader title="Search" />
      <SearchCommandPanel
        autoFocus
        initialQuery={initialQuery}
        enrollmentId={enrollmentId}
        onCapture={onCapture}
      />
    </section>
  );
}
