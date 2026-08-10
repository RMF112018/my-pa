/**
 * The Reveal dialog renders three answers as three, and two of them carry
 * identical data.
 *
 * **This file exists for one assertion**: `unavailable` and `no_evidence` arrive
 * with byte-identical `spans`, `proposed` and `accepted` — all empty — and must
 * still render differently. A component that decided what to show by measuring
 * those arrays would pass every other test in this tree and fail here, which is
 * exactly what makes the backend's typed outcome worth having at this tier too.
 *
 * The second subject is proposed-versus-accepted: an evidence answer holding both
 * must put them in two separate labelled regions, so a reader cannot take a
 * candidate for a promoted fact by missing a badge.
 *
 * Nothing here is a fixture from `lib/fixtures`: the responses are written in
 * this file in the shape the route publishes, so the subject is the rendering
 * rather than the fixture package. Every value is synthetic.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RevealDialog } from "@/components/shell/reveal-dialog";

const VERSION = "capver_aaaa0001aaaa0001";
const SPAN = "span_aaaa0001aaaa0001";

/** The disclosure an unavailable backend answer carries, in the web tier's shape. */
const UNAVAILABLE_DISCLOSURE = {
  scope: "reveal:knowledge.reveal",
  coverage: "unavailable" as const,
  freshnessAt: "2026-08-10T12:00:00Z",
  authority: "accepted" as const,
  limitations: ["evidence_scope_was_not_searched"],
  truncated: false,
};

const SEARCHED_DISCLOSURE = { ...UNAVAILABLE_DISCLOSURE, coverage: "complete" as const, limitations: [] };

/** The empty collections both of the two states carry. Shared deliberately. */
const NOTHING = { spans: [], proposed: [], accepted: [] };

function stubReveal(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
}

async function openAndReveal() {
  render(<RevealDialog open onClose={() => {}} subjectId="cap_aaaa0001aaaa0001" />);
  await userEvent.click(screen.getByRole("button", { name: "Reveal" }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("unavailable is not empty", () => {
  it("renders an unavailable scope differently from a searched empty one", async () => {
    stubReveal({
      shape: "backend",
      state: "unavailable",
      result: {
        state: "unavailable",
        gap: "derivation_has_not_completed_for_every_version",
        subject_kind: "capture",
        capture_id: "cap_aaaa0001aaaa0001",
        versions: [
          {
            version_id: VERSION,
            version_number: 1,
            is_current: true,
            derivation_state: null,
            derivation_is_complete: false,
          },
        ],
        ...NOTHING,
        versions_with_completed_derivation: 0,
      },
      disclosure: UNAVAILABLE_DISCLOSURE,
    });
    await openAndReveal();

    await waitFor(() => expect(screen.getByTestId("reveal-unavailable")).toBeTruthy());
    expect(screen.queryByTestId("reveal-no-evidence")).toBeNull();
    expect(screen.queryByTestId("reveal-evidence")).toBeNull();
    const unavailableText = screen.getByTestId("reveal-unavailable").textContent ?? "";
    expect(unavailableText).toMatch(/not searched/i);
    // And it never claims the absence of evidence.
    expect(unavailableText).not.toMatch(/no evidence is recorded/i);

    cleanup();
    vi.unstubAllGlobals();

    // The same empty collections, one state apart.
    stubReveal({
      shape: "backend",
      state: "no_evidence",
      result: {
        state: "no_evidence",
        gap: null,
        subject_kind: "capture",
        capture_id: "cap_aaaa0001aaaa0001",
        versions: [
          {
            version_id: VERSION,
            version_number: 1,
            is_current: true,
            derivation_state: "complete",
            derivation_is_complete: true,
          },
        ],
        ...NOTHING,
        versions_with_completed_derivation: 1,
      },
      disclosure: SEARCHED_DISCLOSURE,
    });
    await openAndReveal();

    await waitFor(() => expect(screen.getByTestId("reveal-no-evidence")).toBeTruthy());
    expect(screen.queryByTestId("reveal-unavailable")).toBeNull();
    const searchedText = screen.getByTestId("reveal-no-evidence").textContent ?? "";
    expect(searchedText).toMatch(/no evidence is recorded/i);
    expect(searchedText).not.toEqual(unavailableText);
  });

  it("states the coverage the backend disclosed rather than deriving one", async () => {
    stubReveal({
      shape: "backend",
      state: "unavailable",
      result: {
        state: "unavailable",
        gap: "subject_kind_is_outside_the_evidence_model",
        subject_kind: null,
        capture_id: null,
        versions: [],
        ...NOTHING,
        versions_with_completed_derivation: 0,
      },
      disclosure: UNAVAILABLE_DISCLOSURE,
    });
    await openAndReveal();

    await waitFor(() => expect(screen.getByTestId("reveal-unavailable")).toBeTruthy());
    expect(screen.getByText(/Coverage: unavailable/)).toBeTruthy();
    expect(screen.getByTestId("reveal-unavailable").textContent).toMatch(
      /outside the evidence model/i,
    );
  });
});

describe("proposed and accepted are structurally distinct", () => {
  it("renders a candidate and a promoted record in separate labelled regions", async () => {
    stubReveal({
      shape: "backend",
      state: "evidence",
      result: {
        state: "evidence",
        gap: null,
        subject_kind: "capture",
        capture_id: "cap_aaaa0001aaaa0001",
        versions: [
          {
            version_id: VERSION,
            version_number: 1,
            is_current: true,
            derivation_state: "complete",
            derivation_is_complete: true,
          },
        ],
        spans: [
          {
            span_id: SPAN,
            version_id: VERSION,
            start_offset: 0,
            end_offset: 22,
            character_count: 22,
            offset_basis: "unicode_code_point_v1",
            line_start: 1,
            column_start: 1,
            span_role: "direct",
            quoted_text_sha256: "a".repeat(64),
          },
        ],
        proposed: [
          {
            proposal_id: "prop_aaaa0001aaaa0001",
            proposal_type: "commitment",
            state: "needs_review",
            method: "deterministic_rule",
            method_version: "m1",
            review_case_id: "rvw_aaaa0001aaaa0001",
            latest_disposition: null,
            span_ids: [SPAN],
          },
        ],
        accepted: [
          {
            assertion_id: "asrt_aaaa0001aaaa0001",
            assertion_type: "commitment",
            state: "accepted",
            proposal_id: "prop_bbbb0002bbbb0002",
            decision_id: "rdec_aaaa0001aaaa0001",
            disposition: "accept",
            receipt_id: "rcpt_aaaa0001aaaa0001",
            policy_version: "policy-v1",
            span_ids: [SPAN],
          },
        ],
        versions_with_completed_derivation: 1,
      },
      disclosure: SEARCHED_DISCLOSURE,
    });
    await openAndReveal();

    await waitFor(() => expect(screen.getByTestId("reveal-evidence")).toBeTruthy());
    const proposed = screen.getByTestId("reveal-proposed");
    const accepted = screen.getByTestId("reveal-accepted");
    // Two regions, and neither contains the other.
    expect(proposed.contains(accepted)).toBe(false);
    expect(accepted.contains(proposed)).toBe(false);
    expect(proposed.textContent).toMatch(/not asserted/i);
    expect(accepted.textContent).toMatch(/promoted by your review/i);
    // The candidate's identifier is in the proposed region and nowhere else.
    expect(proposed.textContent).toContain("prop_aaaa0001aaaa0001");
    expect(accepted.textContent).not.toContain("prop_aaaa0001aaaa0001");

    // The span is a locator, and the dialog renders offsets rather than text.
    const spans = screen.getByTestId("reveal-spans").textContent ?? "";
    expect(spans).toContain(VERSION);
    expect(spans).toContain("[0–22)");
    expect(spans).toContain("unicode_code_point_v1");
  });
});
