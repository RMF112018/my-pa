import { describe, expect, it } from "vitest";
import {
  COMMAND_DESTINATIONS,
  DESKTOP_GLOBAL,
  DESKTOP_PRIMARY,
  DESTINATIONS,
  MOBILE_MORE,
  MOBILE_PRIMARY,
  UTILITY_DESTINATIONS,
  activeFor,
} from "@/components/shell/destinations";

describe("IA destination registry", () => {
  it("keeps desktop primary as the six named workspaces (Reports after Intelligence, WP07)", () => {
    expect(DESKTOP_PRIMARY.map(({ label }) => label)).toEqual([
      "Today",
      "Work",
      "People",
      "Knowledge",
      "Intelligence",
      "Reports",
    ]);
    expect(UTILITY_DESTINATIONS.map(({ label }) => label)).toEqual(["System"]);
  });

  it("keeps mobile tabs as Today, Work, People", () => {
    expect(MOBILE_PRIMARY.map(({ label }) => label)).toEqual(["Today", "Work", "People"]);
    expect(MOBILE_MORE.map(({ label }) => label)).toEqual([
      "Intelligence",
      "Reports",
      "Knowledge",
      "Map",
      "Review",
      "System",
    ]);
  });

  it("keeps Review and Map in desktop global while Search is launcher-only", () => {
    expect(DESKTOP_GLOBAL.map(({ label }) => label)).toEqual(["Review", "Map"]);
    expect(MOBILE_MORE.map(({ label }) => label)).not.toContain("Search");
    expect(DESKTOP_PRIMARY.map(({ href }) => href)).not.toContain("/review");
    expect(DESKTOP_PRIMARY.map(({ href }) => href)).not.toContain("/search");
    expect(DESKTOP_PRIMARY.map(({ href }) => href)).not.toContain("/canvas");
    expect(MOBILE_PRIMARY.map(({ href }) => href)).not.toContain("/review");
    expect(MOBILE_PRIMARY.map(({ href }) => href)).not.toContain("/search");
    expect(MOBILE_PRIMARY.map(({ href }) => href)).not.toContain("/canvas");
  });

  it("keeps safe legacy destinations reachable without publishing Search navigation", () => {
    const hrefs = COMMAND_DESTINATIONS.map(({ href }) => href);
    for (const href of [
      "/today",
      "/work",
      "/people",
      "/knowledge",
      "/intelligence",
      "/reports",
      "/review",
      "/canvas",
      "/system",
    ]) {
      expect(hrefs).toContain(href);
    }
    expect(DESTINATIONS.map(({ label }) => label)).not.toContain("Library");
    expect(DESTINATIONS.map(({ label }) => label)).not.toContain("Briefings");
    expect(DESTINATIONS.map(({ href }) => href)).not.toContain("/search");
    expect(activeFor("/search", "/search")).toBe(true);
    for (const forbidden of ["/home", "/tasks", "/projects", "/utilities"]) {
      expect(DESTINATIONS.map(({ href }) => href)).not.toContain(forbidden);
    }
  });

  it.each([
    ["/today", "/today"],
    ["/work", "/work"],
    ["/work/tasks/tsk_1", "/work"],
    ["/situations", "/work"],
    ["/situations/sit_1", "/work"],
    ["/people", "/people"],
    ["/people/ent_1", "/people"],
    ["/relationships/per_1", "/people"],
    ["/knowledge", "/knowledge"],
    ["/knowledge/goodnotes", "/knowledge"],
    ["/library", "/knowledge"],
    ["/library?q=x", "/knowledge"],
    ["/intelligence", "/intelligence"],
    ["/intelligence/history", "/intelligence"],
    ["/intelligence/reports/rpt_1", "/intelligence"],
    ["/reports", "/reports"],
    ["/reports/new", "/reports"],
    ["/reports/trash", "/reports"],
    ["/reports/grpt_1", "/reports"],
    ["/reports/grpt_1/edit", "/reports"],
    ["/review", "/review"],
    ["/search", "/search"],
    ["/canvas", "/canvas"],
    ["/system", "/system"],
    ["/system/security", "/system"],
  ] as const)("activeFor(%s, %s)", (pathname, href) => {
    const path = pathname.split("?")[0] ?? pathname;
    expect(activeFor(path, href)).toBe(true);
  });

  it("keeps Reports and Intelligence apart: pipeline report pages stay Intelligence (WP07)", () => {
    expect(DESTINATIONS.find(({ label }) => label === "Reports")?.href).toBe("/reports");
    expect(activeFor("/intelligence/reports/rpt_1", "/reports")).toBe(false);
    expect(activeFor("/reports/grpt_1", "/intelligence")).toBe(false);
    expect(activeFor("/reportsx", "/reports")).toBe(false);
  });
});
