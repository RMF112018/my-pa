// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PrincipalSession } from "@/contracts/identity";

import { canonicalGatewayProjectReader } from "./gateway-reader";

const PRINCIPAL = {
  principalId: "aaaaaaaa-1111-1111-1111-111111111111",
  identityProvider: "synthetic",
  identitySubject: "synthetic:aaaaaaaa",
  tid: "tenant",
  oid: "object",
  upn: "operator@example.invalid",
  displayName: "Operator",
  lifecycleState: "active",
  synthetic: true,
} satisfies PrincipalSession;

const PROJECT = {
  project_id: "prj_aaaaaaaa11111111",
  state: "active" as const,
  version: 5,
};

const invokeGateway = vi.fn();

beforeEach(() => invokeGateway.mockReset());

describe("canonicalGatewayProjectReader", () => {
  it("uses exact canonical read with no caller-supplied Principal", async () => {
    invokeGateway.mockResolvedValue({ ok: true, result: PROJECT, disclosure: {} });
    await expect(
      canonicalGatewayProjectReader(PRINCIPAL, invokeGateway).readProject(PROJECT.project_id),
    ).resolves.toEqual({ kind: "found", project: PROJECT });
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "continuity.projects.read", {
      project_id: PROJECT.project_id,
    });
    expect(invokeGateway.mock.calls[0]![2]).not.toHaveProperty("principal_id");
  });

  it.each([404, 403])("does not expose missing/foreign detail for status %s", async (status) => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status,
      error: { errorClass: status === 404 ? "not_found" : "authorization" },
    });
    await expect(
      canonicalGatewayProjectReader(PRINCIPAL, invokeGateway).readProject(PROJECT.project_id),
    ).resolves.toEqual(status === 404 ? { kind: "not_found" } : { kind: "unavailable" });
  });

  it("retains canonical version/state and the disclosure cursor from bounded discovery", async () => {
    invokeGateway.mockResolvedValue({
      ok: true,
      result: { projects: [PROJECT] },
      disclosure: { truncation: { next_cursor: "prj_bbbbbbbb22222222" } },
    });
    const page = await canonicalGatewayProjectReader(PRINCIPAL, invokeGateway).listProjects({
      pageSize: 25,
      state: "active",
      query: "north",
      after: "prj_cursor00000001",
    });
    expect(page).toEqual({ projects: [PROJECT], nextCursor: "prj_bbbbbbbb22222222" });
    expect(invokeGateway).toHaveBeenCalledWith(PRINCIPAL, "continuity.projects", {
      page_size: 25,
      state: "active",
      query: "north",
      after: "prj_cursor00000001",
    });
    expect(invokeGateway.mock.calls[0]![2]).not.toHaveProperty("principal_id");
  });

  it("turns unavailable discovery into an empty unavailable page without guessing a cursor", async () => {
    invokeGateway.mockResolvedValue({
      ok: false,
      status: 503,
      error: { errorClass: "unavailable" },
    });
    await expect(
      canonicalGatewayProjectReader(PRINCIPAL, invokeGateway).listProjects({ pageSize: 25 }),
    ).resolves.toEqual({ projects: [], nextCursor: null });
  });
});
