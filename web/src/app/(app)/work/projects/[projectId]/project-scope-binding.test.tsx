// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

const { applyResolution, cleanups } = vi.hoisted(() => ({
  applyResolution: vi.fn(),
  cleanups: [] as Array<() => void>,
}));
vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useRef: <T,>(value: T) => ({ current: value }),
  useLayoutEffect: (effect: () => void | (() => void)) => {
    const cleanup = effect();
    if (cleanup) cleanups.push(cleanup);
  },
}));
vi.mock("@/components/shell/project-scope-provider", () => ({
  useProjectScope: () => ({ applyResolution }),
}));

import { ProjectRouteScopeBinding } from "./project-scope-binding";

describe("ProjectRouteScopeBinding", () => {
  it("applies the deep link, then restores the authenticated parent scope on leave", () => {
    applyResolution.mockReset();
    cleanups.length = 0;
    const resolution = {
      scope: { kind: "PROJECT", projectId: "prj_aaaaaaaa11111111" },
      source: "deep_link",
      project: { project_id: "prj_aaaaaaaa11111111", name: "Linked Project", state: "active", version: 3 },
      normalized: false,
    } as const;
    const fallbackResolution = {
      scope: { kind: "PROJECT", projectId: "prj_bbbbbbbb22222222" },
      source: "preference",
      project: { project_id: "prj_bbbbbbbb22222222", name: "Saved Project", state: "on_hold", version: 6 },
      normalized: false,
    } as const;
    expect(
      ProjectRouteScopeBinding({ resolution, fallbackResolution, children: "content" }),
    ).toBe("content");
    expect(applyResolution).toHaveBeenCalledTimes(1);
    expect(applyResolution).toHaveBeenLastCalledWith(resolution);

    for (const cleanup of [...cleanups].reverse()) cleanup();
    expect(applyResolution).toHaveBeenCalledTimes(2);
    expect(applyResolution).toHaveBeenLastCalledWith(fallbackResolution);
  });
});
