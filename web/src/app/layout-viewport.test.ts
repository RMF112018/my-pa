import { describe, expect, it } from "vitest";
import { viewport } from "@/app/layout";

/*
  WP09 corrective. `viewport-fit=cover` is the precondition for every
  `env(safe-area-inset-*)` in this application: without it iOS resolves each
  inset to `0px`, so the safe-area padding in the mobile nav, the app shell
  main region, the sheets and the mutation feedback region is silently inert.
  WP02-AC-032 and WP03-AC-083 deferred that proof to WP09, so it is pinned
  here on the `Viewport` export Next.js actually consumes.
*/
describe("root layout viewport export", () => {
  it("opts into viewport-fit=cover so env(safe-area-inset-*) resolves non-zero on iOS", () => {
    expect(viewport.viewportFit).toBe("cover");
  });

  it("still carries the brand themeColor", () => {
    expect(viewport.themeColor).toBe("#173F67");
  });
});
