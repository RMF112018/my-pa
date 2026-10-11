/**
 * Level-1 copy on the shipped Today Intelligence pulse.
 *
 * The helper in user-copy.test.ts only classifies strings it is handed. This
 * file renders `IntelligencePulse` through the real gateway/surfaceAnswer path
 * and fails if the primary copy still leads with plane/artifact doctrine.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { PrincipalSession } from "@/contracts/identity";
import { collectLevel1Copy } from "@/lib/ui/user-copy";

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

vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next/navigation")>();
  return {
    ...actual,
    useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  };
});

import { IntelligencePulse } from "./intelligence-pulse";

function whole(overrides: Record<string, unknown> = {}) {
  return {
    coverage: { state: "not_enrolled" },
    freshness: { observed_at: "2026-01-01T00:00:00Z", state: "current_for_observed_version" },
    trust: { level: "source_original", basis: ["user_authored_record"] },
    truncation: { is_truncated: false },
    limitations: [],
    partial_result: false,
    ...overrides,
  };
}

function answerReportsList(result: unknown, disclosure: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const capability = String(url).match(/\/v1\/([^/?#]+)/)?.[1] ?? "";
      const payload = capability === "reports.list" ? result : {};
      return new Response(JSON.stringify({ result: payload, disclosure }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

const REPORTS_LIST = {
  items: [
    {
      report_id: "rpt_aaaaaaaa11111111",
      cycle_run_id: "micr_aaaaaaaa11111111",
      stage: "collector",
      artifact_kind: "collector_candidates",
      focus_area_id: "communications",
      source_lane: null,
      title: "Morning brief collector",
      content_sha256: "a".repeat(64),
      artifact_state: "final",
    },
  ],
  next_cursor: null,
};

function resolveMember(member_id: string, readiness: string, required: boolean) {
  const ready = readiness === "READY";
  return {
    member_id,
    focus_area_id: member_id,
    source_lane: null,
    readiness,
    required,
    artifact_id: ready ? "rpt_aaaaaaaa11111111" : null,
    producer_run_id: ready ? "prun_aaaaaaaa11111111" : null,
    content_sha256: ready ? "a".repeat(64) : null,
    committed_at: ready ? "2026-08-20T12:00:00Z" : null,
    readiness_reason: readiness.toLowerCase(),
  };
}

function resolveSet(overrides: Record<string, unknown>) {
  return {
    cycle_run_id: "micr_aaaaaaaa11111111",
    cycle_id: "morning_intelligence",
    business_date: "2026-08-20",
    set_id: "morning_brief_inputs",
    aggregate: "DEGRADED",
    members: [],
    missing_focus_areas: [],
    partial_focus_areas: [],
    ...overrides,
  };
}

function answerListAndResolve(resolve: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown) => {
      const capability = String(url).match(/\/v1\/([^/?#]+)/)?.[1] ?? "";
      const payload =
        capability === "reports.list"
          ? REPORTS_LIST
          : capability === "reports.resolve_set"
            ? resolve
            : {};
      return new Response(JSON.stringify({ result: payload, disclosure: whole() }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
}

async function renderPulse() {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "window");
  Reflect.deleteProperty(globalThis, "window");
  let tree: React.ReactNode;
  try {
    tree = await IntelligencePulse({ principal: PRINCIPAL });
  } finally {
    if (saved) Object.defineProperty(globalThis, "window", saved);
  }
  return render(tree);
}

function expectUserTaskLevel1() {
  const card = screen.getByTestId("intelligence-pulse");
  const level1 = collectLevel1Copy(card);
  expect(level1).not.toMatch(/\bplane\b/i);
  expect(level1).not.toMatch(/\bartifacts?\b/i);
  expect(level1).not.toMatch(/report plane/i);
  expect(level1).not.toMatch(/^the report/i);
}

beforeEach(() => {
  vi.stubEnv("MYPA_GATEWAY_URL", "http://gateway.invalid");
  vi.stubEnv("MYPA_GATEWAY_AUTH_MODE", "local_operator");
  vi.stubEnv("MYPA_DATA_PROVIDER", "");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("IntelligencePulse Level-1 copy on Today", () => {
  it("does not lead empty with artifact-system wording", async () => {
    answerReportsList({ items: [], next_cursor: null }, whole());
    await renderPulse();
    expect(screen.getByTestId("intelligence-pulse")).toHaveAttribute("data-state", "empty");
    expect(screen.getByTestId("intelligence-pulse-none").textContent).toMatch(/no briefings yet/i);
    expectUserTaskLevel1();
  });

  it("does not say the report plane was read incompletely in degraded Level-1", async () => {
    answerReportsList({ items: [], next_cursor: null }, whole({ partial_result: true }));
    await renderPulse();
    expect(screen.getByTestId("intelligence-pulse")).toHaveAttribute("data-state", "degraded");
    const announcement = screen.getByTestId("intelligence-pulse-degraded");
    expect(announcement.textContent).toMatch(/could not be read completely/i);
    expect(announcement.textContent).not.toMatch(/\bplane\b/i);
    expectUserTaskLevel1();
    // WP07: the technical explanation lived in a Details disclosure carrying the
    // raw cycle id. With diagnostics off it is not rendered at all, so the word
    // the Level-1 copy was forbidden from using appears nowhere on the surface.
    expect(screen.queryByTestId("intelligence-pulse-details")).toBeNull();
    expect(document.body.textContent ?? "").not.toMatch(/report plane/i);
  });

  it("does not treat an unread list as empty or all-clear", async () => {
    answerReportsList(
      { items: [], next_cursor: null },
      whole({ coverage: { state: "unavailable" } }),
    );
    await renderPulse();
    const pulse = screen.getByTestId("intelligence-pulse");
    expect(pulse).toHaveAttribute("data-state", "unavailable");
    expect(screen.getByTestId("intelligence-pulse-unavailable").textContent).toMatch(
      /could not be read/i,
    );
    expect(screen.getByTestId("intelligence-pulse-unavailable").textContent).toMatch(
      /not all-clear/i,
    );
    expect(screen.queryByTestId("intelligence-pulse-none")).toBeNull();
    expect(collectLevel1Copy(pulse)).not.toMatch(/no briefings yet/i);
    expect(collectLevel1Copy(pulse)).not.toMatch(/this scope was not searched/i);
  });
});

describe("IntelligencePulse readiness summary", () => {
  it("names the Daily Briefing gaps instead of counting zero required members", async () => {
    answerListAndResolve(
      resolveSet({
        members: [
          resolveMember("communications", "READY", false),
          resolveMember("people", "MISSING", false),
          resolveMember("research", "PARTIAL", false),
        ],
        missing_focus_areas: ["people"],
        partial_focus_areas: ["research"],
      }),
    );
    await renderPulse();
    expect(screen.getByTestId("intelligence-pulse")).toHaveAttribute("data-state", "degraded");
    const summary = screen.getByTestId("intelligence-pulse-summary");
    expect(summary).toHaveAttribute("role", "status");
    expect(summary.textContent).toMatch(
      /Daily Briefing will publish as partial — missing: people; partial: research\. Not all-clear\./,
    );
    expect(summary.textContent).not.toMatch(/required member/);
  });

  it("keeps the required-member count for a set that names no gaps", async () => {
    answerListAndResolve(
      resolveSet({
        set_id: "collectors",
        aggregate: "BLOCKED",
        members: [
          resolveMember("communications", "READY", true),
          resolveMember("people", "MISSING", true),
        ],
      }),
    );
    await renderPulse();
    const summary = screen.getByTestId("intelligence-pulse-summary");
    expect(summary.textContent).toMatch(/1 required member is not READY\. Not all-clear\./);
    expect(summary.textContent).not.toMatch(/Daily Briefing/);
  });
});
