// @vitest-environment node
/**
 * `PC-CM-SCOPE-AC-013`: the canonical, scoped single-Project Work route
 * exists and forwards to that Project's canonical Constraints route — the
 * one genuinely Project-scoped live surface this build has. See the
 * route's own doc comment for why a forward rather than a new dashboard.
 */
import { describe, expect, it, vi } from "vitest";

const { redirect } = vi.hoisted(() => ({ redirect: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect }));

import ProjectWorkPage from "./page";

describe("the canonical single-Project Work route", () => {
  it("forwards to that Project's canonical Constraints route", async () => {
    await ProjectWorkPage({ params: Promise.resolve({ projectId: "prj_syn_00000001" }) });
    expect(redirect).toHaveBeenCalledWith("/work/projects/prj_syn_00000001/constraints");
  });

  it("encodes the Project identifier in the forwarded route", async () => {
    await ProjectWorkPage({ params: Promise.resolve({ projectId: "prj syn/weird" }) });
    expect(redirect).toHaveBeenCalledWith(`/work/projects/${encodeURIComponent("prj syn/weird")}/constraints`);
  });
});
