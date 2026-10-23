import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import fixtures from "@/lib/api/decode/fixtures/python/success.json";
import { syntheticConstraintWorkspace, SYNTHETIC_CONSTRAINT_PROJECT_ID } from "@/lib/fixtures/constraints";
import { ConstraintInspector, type ConstraintInspectorProps } from "./constraint-inspector";

/*
 * AT-024 (S1, mounting): the Constraint inspector carries the one related-Issue
 * panel once the canonical detail is read, fed by one lineage read.
 */
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("Constraint inspector related Issues", () => {
  it("mounts the related-Issue panel in the Constraint inspector", async () => {
    vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
    const workspace = syntheticConstraintWorkspace(SYNTHETIC_CONSTRAINT_PROJECT_ID)!;
    const detail = Object.values(workspace.details)[0]!;
    const constraintId = "cst_aaaaaaaa11111111";
    const lineage = structuredClone(fixtures["records.lineage"]);
    const root = { family: "constraint", record_id: constraintId };
    lineage.root = root;
    // S3 lockstep: the root node's path step is null.
    lineage.nodes[0] = { family: "constraint", record_id: constraintId, depth: 0, reached_from: null, reached_via: null };
    lineage.typed_edges[0]!.to = root;
    lineage.typed_edges[1]!.from = root;
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/records/constraint/${constraintId}/related-issues`) return Response.json({ shape: "backend", ...lineage, disclosure: {} });
      throw new Error(`unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);

    const props: ConstraintInspectorProps = {
      entry: null,
      detail: { ...detail, constraintId } as ConstraintInspectorProps["detail"],
      history: [],
      onClose: () => undefined,
      onNavigateToConstraint: () => undefined,
      onLifecycleAction: () => undefined,
      readOnly: true,
    };
    render(<ConstraintInspector {...props} />);
    const panel = await screen.findByRole("region", { name: "Related Issues" });
    expect(within(panel).getByRole("heading", { level: 3, name: "Related Issues" })).toBeInTheDocument();
    expect(await within(panel).findByText("Member of this Issue as work")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
