import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  NotebookList,
  PageList,
  RunList,
  goodnotesCatalogHref,
} from "@/components/goodnotes/catalog";

const NOTEBOOK = {
  notebook_id: "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa",
  title: "Synthetic notebook",
  updated_at: "2026-08-09T12:00:00.000Z",
  page_count: 2,
  liveness: "unknown" as const,
};

const PAGE = {
  logical_page_id: "gnlp_aaaaaaaaaaaaaaaaaaaaaaaa",
  page_version_id: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  content_sha256: "a".repeat(64),
  is_latest: true,
  updated_at: "2026-08-09T12:00:00.000Z",
};

const RUN = {
  run_id: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
  state: "succeeded",
  failure_class: null,
  started_at: "2026-08-09T12:00:00.000Z",
  completed_at: "2026-08-09T12:01:00.000Z",
};

describe("goodnotesCatalogHref", () => {
  it("builds identifier-only query strings", () => {
    expect(
      goodnotesCatalogHref({
        notebookId: NOTEBOOK.notebook_id,
        logicalPageId: PAGE.logical_page_id,
        pageVersionId: PAGE.page_version_id,
        runId: PAGE.run_id ?? undefined,
        contentSha256: PAGE.content_sha256,
      }),
    ).toBe(
      "/knowledge/goodnotes?notebookId=gnnb_aaaaaaaaaaaaaaaaaaaaaaaa&logicalPageId=gnlp_aaaaaaaaaaaaaaaaaaaaaaaa&pageVersionId=gnver_aaaaaaaaaaaaaaaaaaaaaaaa&runId=gnrun_aaaaaaaaaaaaaaaaaaaaaaaa&contentSha256=" +
        "a".repeat(64),
    );
  });
});

describe("GoodNotes catalog", () => {
  it("does not treat unknown liveness as a NAS outage and leaks no extra path", () => {
    render(<NotebookList notebooks={[NOTEBOOK]} selectedNotebookId="" />);
    expect(screen.getByTestId("goodnotes-notebook-liveness").textContent).toBe("unknown");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.body.textContent).not.toMatch(/\/nas\//);
    expect(document.body.textContent).not.toMatch(/\/Users\//);
    expect(document.body.textContent).not.toContain("/secret");
  });

  it("does not invent an evidence link when a page has no run id", () => {
    render(
      <PageList
        notebookId={NOTEBOOK.notebook_id}
        pages={[{ ...PAGE, run_id: null }]}
        selectedLogicalPageId=""
      />,
    );
    expect(screen.getByTestId("goodnotes-page-no-run")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open evidence" })).toBeNull();
  });

  it("does not invent an evidence link when a run has no page version id", () => {
    render(<RunList notebookId={NOTEBOOK.notebook_id} runs={[RUN]} />);
    expect(screen.getByTestId("goodnotes-run-no-page")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open evidence" })).toBeNull();
  });
});
