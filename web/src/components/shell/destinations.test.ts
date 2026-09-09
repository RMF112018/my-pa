import { describe, expect, it } from "vitest";
import {
  COMMAND_DESTINATIONS,
  DESKTOP_PRIMARY,
  DESTINATIONS,
  MOBILE_MORE,
  MOBILE_PRIMARY,
  UTILITY_DESTINATIONS,
  activeFor,
} from "@/components/shell/destinations";

describe("IA destination registry", () => {
  it("keeps desktop primary as the five named workspaces", () => {
    expect(DESKTOP_PRIMARY.map(({ label }) => label)).toEqual([
      "Today",
      "Work",
      "People",
      "Knowledge",
      "Intelligence",
    ]);
    expect(UTILITY_DESTINATIONS.map(({ label }) => label)).toEqual(["System"]);
  });

  it("keeps mobile tabs as Today, Work, People", () => {
    expect(MOBILE_PRIMARY.map(({ label }) => label)).toEqual(["Today", "Work", "People"]);
    expect(MOBILE_MORE.map(({ label }) => label)).toEqual([
      "Intelligence",
      "Knowledge",
      "Map",
      "Review",
      "Search",
      "System",
    ]);
  });

  it("does not put Review, Search, or Map on the desktop rail or mobile tabs", () => {
    expect(DESKTOP_PRIMARY.map(({ href }) => href)).not.toContain("/review");
    expect(DESKTOP_PRIMARY.map(({ href }) => href)).not.toContain("/search");
    expect(DESKTOP_PRIMARY.map(({ href }) => href)).not.toContain("/canvas");
    expect(MOBILE_PRIMARY.map(({ href }) => href)).not.toContain("/review");
    expect(MOBILE_PRIMARY.map(({ href }) => href)).not.toContain("/search");
  });

  it("keeps every canonical href command-reachable under current names", () => {
    const hrefs = COMMAND_DESTINATIONS.map(({ href }) => href);
    for (const href of [
      "/today",
      "/work",
      "/people",
      "/knowledge",
      "/intelligence",
      "/review",
      "/search",
      "/canvas",
      "/system",
    ]) {
      expect(hrefs).toContain(href);
    }
    expect(DESTINATIONS.map(({ label }) => label)).not.toContain("Library");
    expect(DESTINATIONS.map(({ label }) => label)).not.toContain("Briefings");
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
    ["/review", "/review"],
    ["/search", "/search"],
    ["/canvas", "/canvas"],
    ["/system", "/system"],
    ["/system/security", "/system"],
  ] as const)("activeFor(%s, %s)", (pathname, href) => {
    const path = pathname.split("?")[0] ?? pathname;
    expect(activeFor(path, href)).toBe(true);
  });
});
