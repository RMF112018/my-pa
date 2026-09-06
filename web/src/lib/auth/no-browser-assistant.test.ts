/**
 * Browser-native MossAIc / ChatLLM is superseded. The signed-in shell must not
 * revive an iframe embed or a MossAIc utility sidebar.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  DESTINATIONS,
  MOBILE_MORE,
  MOBILE_PRIMARY,
  UTILITY_DESTINATIONS,
} from "@/components/shell/destinations";

const here = dirname(fileURLToPath(import.meta.url));
const webSrc = join(here, "../..");

const SHELL_SOURCES = [
  "components/shell/destinations.ts",
  "components/shell/app-shell.tsx",
  "components/shell/nav.tsx",
  "components/shell/utility-region.tsx",
  "components/shell/command-palette.tsx",
  "app/layout.tsx",
  "app/(app)/layout.tsx",
] as const;

const FORBIDDEN = [
  /<iframe\b/i,
  /ChatLLM/i,
  /MossAIc/i,
  /mossaic/i,
  /abacus\.ai/i,
];

describe("no browser-native assistant surface", () => {
  it("does not place ChatLLM or MossAIc among shell destinations", () => {
    const destinations = [...DESTINATIONS, ...UTILITY_DESTINATIONS, ...MOBILE_PRIMARY, ...MOBILE_MORE];
    const labels = destinations.map((destination) => destination.label.toLowerCase());
    const hrefs = destinations.map((destination) => destination.href.toLowerCase());
    expect(labels.some((label) => /chat|mossaic|assistant|chatllm/.test(label))).toBe(false);
    expect(hrefs.some((href) => /chat|mossaic|assistant|chatllm/.test(href))).toBe(false);
    expect(labels).toContain("system");
    expect(labels).not.toContain("chat");
  });

  it("does not embed a ChatLLM iframe or MossAIc sidebar in shell layouts", () => {
    for (const relative of SHELL_SOURCES) {
      const source = readFileSync(join(webSrc, relative), "utf8");
      for (const pattern of FORBIDDEN) {
        expect(source, `${relative} must not match ${pattern}`).not.toMatch(pattern);
      }
    }
  });
});
