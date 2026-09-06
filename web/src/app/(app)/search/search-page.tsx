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
  const openCapture = useOpenCapture();
  return (
    <section className="mx-auto max-w-3xl">
      <PageHeader
        title="Search"
        description="Federated search over Work, Capture, Intelligence, People, and enrolled Knowledge. Empty search lists destinations and Quick Capture. Omitted domains stay omitted."
      />
      <SearchCommandPanel
        autoFocus
        initialQuery={initialQuery}
        enrollmentId={enrollmentId}
        onCapture={openCapture}
      />
    </section>
  );
}
