"use client";

import { useState, type ReactNode } from "react";

/**
 * Source and interpretation together. On `md+` both panes stay visible
 * side-by-side; below `md` a tablist switches between them. The panes are not
 * duplicated, so the raster is requested once.
 */
export function EvidenceSplit({
  source,
  interpretation,
}: {
  source: ReactNode;
  interpretation: ReactNode;
}) {
  const [tab, setTab] = useState<"source" | "interpretation">("source");

  return (
    <div data-testid="goodnotes-evidence">
      <div
        role="tablist"
        aria-label="Source and interpretation"
        className="mb-3 flex gap-1 md:hidden"
        data-testid="goodnotes-evidence-tablist"
      >
        <button
          type="button"
          role="tab"
          id="goodnotes-tab-source"
          aria-controls="goodnotes-panel-source"
          aria-selected={tab === "source"}
          tabIndex={tab === "source" ? 0 : -1}
          className="inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium text-moss-slate aria-selected:bg-moss-sand"
          onClick={() => setTab("source")}
        >
          Source
        </button>
        <button
          type="button"
          role="tab"
          id="goodnotes-tab-interpretation"
          aria-controls="goodnotes-panel-interpretation"
          aria-selected={tab === "interpretation"}
          tabIndex={tab === "interpretation" ? 0 : -1}
          className="inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium text-moss-slate aria-selected:bg-moss-sand"
          onClick={() => setTab("interpretation")}
        >
          Interpretation
        </button>
      </div>
      <div className="grid gap-4 md:grid-cols-2" data-testid="goodnotes-evidence-split">
        <section
          id="goodnotes-panel-source"
          role="tabpanel"
          aria-labelledby="goodnotes-source-heading"
          className={tab === "source" ? "block" : "hidden md:block"}
        >
          <h2 id="goodnotes-source-heading" className="mb-2 text-base font-semibold text-moss-slate">
            Source
          </h2>
          {source}
        </section>
        <section
          id="goodnotes-panel-interpretation"
          role="tabpanel"
          aria-labelledby="goodnotes-interpretation-heading"
          className={tab === "interpretation" ? "block" : "hidden md:block"}
        >
          <h2
            id="goodnotes-interpretation-heading"
            className="mb-2 text-base font-semibold text-moss-slate"
          >
            Interpretation
          </h2>
          {interpretation}
        </section>
      </div>
    </div>
  );
}
