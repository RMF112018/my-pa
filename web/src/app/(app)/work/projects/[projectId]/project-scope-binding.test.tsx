// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

const { applyResolution, apiPost, cleanups } = vi.hoisted(() => ({
  applyResolution: vi.fn(),
  apiPost: vi.fn(),
  cleanups: [] as Array<() => void>,
}));
vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useRef: <T,>(value: T) => ({ current: value }),
  useLayoutEffect: (effect: () => void | (() => void)) => {
    const cleanup = effect();
    if (cleanup) cleanups.push(cleanup);
  },
  // The persistence effect (`useEffect`) is run synchronously here too, the
  // same way `useLayoutEffect` above is: this file calls the component as a
  // plain function rather than through a real renderer, so no hook can rely
  // on React's own scheduler.
  useEffect: (effect: () => void | (() => void)) => {
    const cleanup = effect();
    if (cleanup) cleanups.push(cleanup);
  },
}));
vi.mock("@/components/shell/project-scope-provider", () => ({
  useProjectScope: () => ({ applyResolution }),
}));
vi.mock("@/lib/api/client", () => ({ apiPost }));

import { ProjectRouteScopeBinding } from "./project-scope-binding";

const LINKED = {
  scope: { kind: "PROJECT", projectId: "prj_aaaaaaaa11111111" },
  source: "deep_link",
  project: {
    project_id: "prj_aaaaaaaa11111111",
    name: "Linked Project",
    state: "active",
    version: 3,
  },
  normalized: false,
} as const;
const SAVED = {
  scope: { kind: "PROJECT", projectId: "prj_bbbbbbbb22222222" },
  source: "preference",
  project: {
    project_id: "prj_bbbbbbbb22222222",
    name: "Saved Project",
    state: "on_hold",
    version: 6,
  },
  normalized: false,
} as const;
const NORMALIZED_ALL = {
  scope: { kind: "ALL_PROJECTS" },
  source: "deep_link",
  project: null,
  normalized: true,
} as const;

function reset() {
  applyResolution.mockReset();
  apiPost.mockReset();
  apiPost.mockResolvedValue({ ok: true, status: 200, data: { scope: "PROJECT" }, error: null, errorClass: null, code: null });
  cleanups.length = 0;
}

describe("ProjectRouteScopeBinding", () => {
  it("applies the deep link, then restores the authenticated parent scope on leave", () => {
    reset();
    expect(
      ProjectRouteScopeBinding({
        resolution: LINKED,
        fallbackResolution: SAVED,
        children: "content",
      }),
    ).toBe("content");
    expect(applyResolution).toHaveBeenCalledTimes(1);
    expect(applyResolution).toHaveBeenLastCalledWith(LINKED);

    for (const cleanup of [...cleanups].reverse()) cleanup();
    expect(applyResolution).toHaveBeenCalledTimes(2);
    expect(applyResolution).toHaveBeenLastCalledWith(SAVED);
  });

  it("persists an accepted deep-linked Project as the remembered preference, through the Phase 2 route", () => {
    reset();
    ProjectRouteScopeBinding({ resolution: LINKED, fallbackResolution: SAVED, children: "content" });
    expect(apiPost).toHaveBeenCalledExactlyOnceWith({ hasSession: true }, "/api/project-scope", {
      scope: "PROJECT",
      projectId: "prj_aaaaaaaa11111111",
    });
  });

  it("never persists a deep link that normalized to ALL_PROJECTS (malformed/unknown/foreign/closed)", () => {
    reset();
    ProjectRouteScopeBinding({
      resolution: NORMALIZED_ALL,
      fallbackResolution: SAVED,
      children: "content",
    });
    expect(apiPost).not.toHaveBeenCalled();
    // Rendering is still authorized from `resolution`, independent of persistence.
    expect(applyResolution).toHaveBeenCalledExactlyOnceWith(NORMALIZED_ALL);
  });

  it("renders and applies the route-authorized resolution even when the persistence write fails", async () => {
    reset();
    apiPost.mockRejectedValue(new Error("network unavailable"));
    ProjectRouteScopeBinding({ resolution: LINKED, fallbackResolution: SAVED, children: "content" });
    // The apply effect ran synchronously, off `resolution` — not off the
    // write's outcome, which this test never lets resolve before asserting.
    expect(applyResolution).toHaveBeenCalledExactlyOnceWith(LINKED);
    await Promise.resolve().then(() => Promise.resolve());
    // Still exactly the one call: a failed write does not retro-apply, revert,
    // or otherwise touch the provider.
    expect(applyResolution).toHaveBeenCalledTimes(1);
  });
});
