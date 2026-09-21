import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { AppShell } from "@/components/shell/app-shell";
import { MobileNav, NavRail } from "@/components/shell/nav";
import { UtilityRegion } from "@/components/shell/utility-region";
import { Sheet } from "@/components/ui/sheet";
import { MutationFeedbackRegion } from "@/components/ui/mutation-feedback";
import type { PrincipalSession } from "@/contracts/identity";

/*
  WP09 corrective — the safe-area collision set under `viewport-fit=cover`.

  `viewport-fit=cover` moves the layout viewport's edges to the *physical*
  screen edges, so every element flush to a viewport edge is now exposed to the
  status bar / Dynamic Island band (top, ~47-59px), the home indicator (bottom,
  ~34px) and — in landscape on a notched device — the ~44px left and right
  insets. Three surfaces were found one at a time by three separate reviewers;
  this file pins the *whole* set at once so the next one cannot regress
  silently.

  The idiom under test is `max(<existing length>, env(safe-area-inset-<edge>))`,
  established in `sheet.tsx` and `mutation-feedback.tsx`. `max`, never a sum:
  the inset replaces the base length rather than stacking on it, so a device
  with a zero inset renders exactly as before.

  KNOWN LIMITATION, stated rather than faked. jsdom neither compiles Tailwind
  nor resolves `env()`, and its CSS parser rejects `max()` outright — setting
  `top: "max(...)"` inline yields `style.top === ""`. Geometry is therefore
  unassertable here; the class token (or, where the value is an inline style or
  the component is a server component, the source declaration) is the ceiling.
  No assertion below claims more than that. Real geometry is e2e/device ground.
*/

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/today",
  useRouter: () => ({ push: navigation.push, refresh: vi.fn() }),
}));

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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Class tokens of an element, so containment assertions are exact, not substring. */
function tokensOf(element: Element): string[] {
  return element.className.toString().split(/\s+/).filter(Boolean);
}

function renderShell() {
  render(
    <AppShell principal={PRINCIPAL} sessionEpoch="test-session-binding">
      content
    </AppShell>,
  );
}

describe("safe-area collision set — shell chrome", () => {
  it("insets the context header from the top, left and right physical edges", () => {
    renderShell();
    // The header is the first in-flow child of the `min-h-screen` shell root and
    // the first content in `<body>` (which has `margin: 0` and no padding), so
    // its box starts at the physical screen top: under cover its ~48px sits
    // inside the status bar / Dynamic Island band, taking the brand, the Review
    // link and the Account button with it. It spans the full width at every
    // breakpoint, so its left and right edges are physical edges too.
    const tokens = tokensOf(screen.getByRole("banner"));
    expect(tokens).toContain("pt-[max(0.375rem,env(safe-area-inset-top))]");
    expect(tokens).toContain("pl-[max(0.75rem,env(safe-area-inset-left))]");
    expect(tokens).toContain("pr-[max(0.75rem,env(safe-area-inset-right))]");
    // The uniform shorthands cannot express a per-edge inset and must be gone,
    // not merely overridden — an override would depend on Tailwind's emit order.
    expect(tokens).not.toContain("px-3");
    expect(tokens).not.toContain("py-1.5");
    // The header is not bottom-anchored: content flows below it, so it can never
    // reach the home indicator and spends no bottom inset.
    expect(tokens).toContain("pb-1.5");
  });

  it("insets the mobile nav from the landscape left and right edges without disturbing its bottom inset", () => {
    render(<MobileNav onCapture={() => undefined} />);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const tokens = tokensOf(nav);
    // `fixed inset-x-0 bottom-0`: all three of bottom, left and right are
    // physical edges. `lg:hidden` does not save it — the largest iPhone in
    // landscape is still below the `lg` breakpoint, which is exactly the
    // orientation where the 44px side insets are live.
    expect(tokens).toContain("pl-[env(safe-area-inset-left)]");
    expect(tokens).toContain("pr-[env(safe-area-inset-right)]");
    // Pre-existing and correct: the bar has no base horizontal or vertical
    // padding, so the bare `env()` on a zero base *is* this file's `max()`.
    // Assert it is untouched, and supplied exactly once (no double-count).
    expect(tokens).toContain("pb-[env(safe-area-inset-bottom)]");
    expect(tokens.filter((token) => token.startsWith("pb-"))).toHaveLength(1);
  });

  it("insets the main region from the landscape left and right edges and keeps its single bottom supplier", () => {
    renderShell();
    const tokens = tokensOf(screen.getByRole("main"));
    expect(tokens).toContain("pl-[max(1rem,env(safe-area-inset-left))]");
    expect(tokens).toContain("pr-[max(1rem,env(safe-area-inset-right))]");
    expect(tokens).not.toContain("p-4");
    expect(tokens).toContain("pt-4");
    // Unchanged and still the single supplier of the bottom inset for the main
    // subtree (see the note in work-detail.tsx, which gave its own up).
    expect(tokens).toContain("pb-[calc(var(--nav-height)+env(safe-area-inset-bottom))]");
    expect(tokens.filter((token) => token.startsWith("pb-"))).toHaveLength(1);
  });

  it("insets the desktop nav rail from the bottom edge", () => {
    render(
      <NavRail collapsed={false} onCollapsedChange={() => undefined} onCapture={() => undefined} />,
    );
    const tokens = tokensOf(screen.getByRole("navigation", { name: "Primary" }));
    // The rail stretches the full height of the shell row inside `min-h-screen`,
    // so its bottom — which carries the collapse control under `mt-auto` — is
    // the physical bottom edge on a tablet, where the home indicator lives.
    expect(tokens).toContain("pb-[max(0.5rem,env(safe-area-inset-bottom))]");
    expect(tokens).not.toContain("p-2");
  });

  it("insets the utility region body from the right physical edge", () => {
    render(
      <UtilityRegion
        open
        onOpenChange={() => undefined}
        pinned={false}
        onPinnedChange={() => undefined}
        width={360}
        onWidthChange={() => undefined}
      />,
    );
    // The aside is `md:block`, and a notched phone in landscape is above `md`,
    // so it becomes the right-most in-flow element there: its right edge is the
    // physical right edge, behind the 44px landscape inset.
    const body = screen.getByRole("heading", { name: "Inspector" }).closest("div")?.parentElement
      ?.parentElement;
    expect(body).toBeTruthy();
    const tokens = tokensOf(body as Element);
    expect(tokens).toContain("pr-[max(1rem,env(safe-area-inset-right))]");
    expect(tokens).not.toContain("p-4");
    expect(tokens).toContain("pt-4");
    expect(tokens).toContain("pl-4");
    expect(tokens).toContain("pb-4");
  });
});

describe("safe-area collision set — overlays", () => {
  const PLACEMENTS = [
    { placement: "menu" as const, left: true },
    { placement: "detail" as const, left: true },
    // `inspector` is right-anchored at `w-[min(90vw,32rem)]`: its left edge sits
    // at 10vw, which on the narrowest landscape notched device is still wider
    // than the 44px left inset. It never reaches the left edge, so it keeps the
    // plain 1.25rem there.
    { placement: "inspector" as const, left: false },
  ];

  for (const { placement, left } of PLACEMENTS) {
    it(`insets the ${placement} sheet from the right edge${left ? " and the left edge" : ""}`, () => {
      render(
        <Sheet open onOpenChange={() => undefined} title="Panel" placement={placement}>
          Body
        </Sheet>,
      );
      const tokens = tokensOf(screen.getByRole("dialog"));
      expect(tokens).toContain("pr-[max(1.25rem,env(safe-area-inset-right))]");
      if (left) {
        expect(tokens).toContain("pl-[max(1.25rem,env(safe-area-inset-left))]");
      } else {
        expect(tokens).toContain("pl-5");
      }
      // `px-5` cannot express a per-edge inset and must be gone.
      expect(tokens).not.toContain("px-5");
    });
  }

  it("insets the sheet close control from the right edge on every placement", () => {
    for (const { placement } of PLACEMENTS) {
      cleanup();
      render(
        <Sheet open onOpenChange={() => undefined} title="Panel" placement={placement}>
          Body
        </Sheet>,
      );
      const tokens = tokensOf(screen.getByRole("button", { name: "Close panel" }));
      // The close control is absolutely positioned against the Content's padding
      // box, so the container's `pr-[max(...)]` above does NOT move it: a bare
      // `right-3` stays 12px from the physical right edge whatever the container
      // pads. This is exactly how it was missed the first time round.
      expect(tokens).toContain("right-[max(0.75rem,env(safe-area-inset-right))]");
      expect(tokens).not.toContain("right-3");
    }
  });

  it("supplies each horizontal inset exactly once in a detail sheet subtree", () => {
    render(
      <Sheet open onOpenChange={() => undefined} title="Panel" placement="detail">
        <div data-testid="sheet-body">Body</div>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog");
    const padders = [dialog, ...Array.from(dialog.querySelectorAll("*"))].filter((element) =>
      tokensOf(element).some(
        (token) => /^p[lrxs]-/.test(token) && token.includes("safe-area-inset-"),
      ),
    );
    // The sheet container is the single supplier of the horizontal insets for
    // its subtree; a descendant adding its own would double-count the space.
    expect(padders).toHaveLength(1);
    expect(padders[0]).toBe(dialog);
  });

  it("insets the mutation feedback region from the landscape left and right edges", () => {
    render(
      <MutationFeedbackRegion
        items={[
          {
            eventId: "placement",
            kind: "success",
            message: "Create confirmed",
            tone: "status",
            createdAt: 0,
          },
        ]}
        onDismiss={() => undefined}
      />,
    );
    const tokens = tokensOf(screen.getByTestId("mutation-feedback-region"));
    // `fixed inset-x-0`: both horizontal edges are physical.
    expect(tokens).toContain("pl-[max(0.75rem,env(safe-area-inset-left))]");
    expect(tokens).toContain("pr-[max(0.75rem,env(safe-area-inset-right))]");
    expect(tokens).not.toContain("px-3");
  });
});

/*
  The two surfaces below are asserted on their source declaration rather than on
  rendered DOM, and the reason is specific in each case, not convenience:

  * `offline-queue-status.tsx` renders nothing until an IndexedDB-backed queue
    read returns a non-zero held count, so there is no element to query without
    standing up a fake store whose only purpose would be to reach a className.
  * `layout.tsx` is the root server component; it returns `<html>`/`<body>`,
    which React Testing Library cannot mount into a jsdom document body.

  A source assertion proves the declaration exists and would fail if it were
  deleted or reworded. It does not prove the class is emitted by Tailwind or
  that the geometry is right — that is the compiled-CSS check and device ground.
*/
const read = (relative: string) => readFileSync(join(process.cwd(), "src", relative), "utf8");

describe("safe-area collision set — surfaces asserted at source", () => {
  it("insets the offline queue status from the bottom and left physical edges", () => {
    const source = read("components/offline/offline-queue-status.tsx");
    // `fixed bottom-2 left-2`: 8px against a ~34px home indicator and a ~44px
    // landscape left inset. This is the `role="status"` element whose entire job
    // is telling the reader their captured work is held on-device and not lost,
    // so it is the last thing that may be clipped.
    expect(source).toContain("bottom-[max(0.5rem,env(safe-area-inset-bottom))]");
    expect(source).toContain("left-[max(0.5rem,env(safe-area-inset-left))]");
    expect(source).not.toContain("fixed bottom-2 left-2");
  });

  it("insets the skip link from the top and left physical edges when it is focused", () => {
    const source = read("app/layout.tsx");
    // The skip link is `sr-only` until focused, then `focus:absolute`. `<body>`
    // is not positioned, so its containing block is the initial containing
    // block — the physical viewport under cover. At `top-2 left-2` the first
    // control a keyboard or screen-reader user reaches appears under the notch.
    expect(source).toContain("focus:top-[max(0.5rem,env(safe-area-inset-top))]");
    expect(source).toContain("focus:left-[max(0.5rem,env(safe-area-inset-left))]");
    expect(source).not.toContain("focus:left-2");
    expect(source).not.toContain("focus:top-2");
  });
});
