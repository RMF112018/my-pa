// @vitest-environment node
/**
 * Structural lock: browser gateway.json admits the WP21 GoodNotes set and
 * does not admit GSQS start/status or the analyzer/orchestration verbs.
 */
import { describe, expect, it } from "vitest";
import contract from "@/contracts/gateway.json";
import type { PrincipalSession } from "@/contracts/identity";
import { buildRequestDocument } from "@/lib/api/gateway";

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "11111111-2222-3333-4444-555555555555:aaaa0001-0000-0000-0000-000000000001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const WP21_BROWSER = [
  "goodnotes.notebooks.list",
  "goodnotes.pages.list",
  "goodnotes.runs.list",
  "goodnotes.read",
  "goodnotes.search",
  "goodnotes.correct",
  "goodnotes.work",
  "goodnotes.content",
] as const;

const NOT_BROWSER_ADMITTED = [
  "gsqs.start",
  "gsqs.status",
  "goodnotes.pull",
  "goodnotes.complete",
  "goodnotes.propose",
  "goodnotes.status",
] as const;

describe("gateway.json browser admission", () => {
  const admitted = Object.keys(contract.capabilities);

  it("does not admit GSQS start/status or GoodNotes pull/complete/propose/status", () => {
    for (const capability of NOT_BROWSER_ADMITTED) {
      expect(admitted, capability).not.toContain(capability);
    }
  });

  it("admits the WP21 browser GoodNotes set", () => {
    for (const capability of WP21_BROWSER) {
      expect(admitted).toContain(capability);
    }
  });

  it("forwards an explicit Capture Project identifier unchanged", async () => {
    const projectId = "prj_aaaaaaaa11111111";
    const document = await buildRequestDocument(PRINCIPAL, "capture.create", {
      text: "a synthetic capture",
      idempotency_key: "idem-project-probe-0001",
      project_id: projectId,
    });

    expect(contract.capabilities["capture.create"].probe).not.toHaveProperty("project_id");
    expect(document[contract.payloadKey]).toMatchObject({ project_id: projectId });
  });
});
