import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewWorkbench } from "@/components/review/review-workbench";
import { BackendReviewWorkbench } from "@/components/review/backend-review-workbench";
import type {
  CaptureBackendReviewCase,
  GoodNotesRegionBackendReviewCase,
  GoodNotesSemanticBackendReviewCase,
} from "@/contracts/views";
import {
  syntheticReviewCases,
  syntheticDecisionReceipt,
  REVIEW_DISPOSITIONS,
} from "@/lib/fixtures/review";
import type { PrincipalSession } from "@/contracts/identity";

const PRINCIPAL: PrincipalSession = {
  principalId: "syn-aaaa0001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};

const OTHER: PrincipalSession = { ...PRINCIPAL, principalId: "syn-bbbb0002" };

function receiptResponse(receiptId: string, transition: string) {
  return new Response(
    JSON.stringify({
      receipt: {
        receiptId,
        principalId: PRINCIPAL.principalId,
        subjectKind: "review_case",
        subjectId: "rev-x",
        transition,
        policyVersion: "review-policy-v4.0",
        issuedAt: "2026-08-05T14:00:00+00:00",
        authority: "review_disposition:accept",
      },
      status: "acknowledged_not_persisted",
    }),
    { status: 200 },
  );
}


/**
 * This file's subject is the review workbench component, not which data provider is
 * configured. WP-06 made the synthetic fixtures refuse unless
 * `MYPA_DATA_PROVIDER=synthetic` is set explicitly, so the opt-in is stated here
 * rather than assumed — which is the point of the switch. The default-build
 * behaviour, where the fixtures refuse and the routes serve the backend or say
 * they cannot, is asserted in `src/app/api/routes.test.ts`.
 */
beforeEach(() => {
  vi.stubEnv("MYPA_DATA_PROVIDER", "synthetic");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("review fixtures", () => {
  it("stamps every case with the caller's own principal (never a foreign one)", () => {
    const cases = syntheticReviewCases(PRINCIPAL);
    expect(cases.length).toBeGreaterThan(0);
    for (const c of cases) {
      expect(c.principalId).toBe(PRINCIPAL.principalId);
      expect(c.reviewCaseId).toContain(PRINCIPAL.principalId);
    }
    // A different principal gets a disjoint set of case ids.
    const otherIds = syntheticReviewCases(OTHER).map((c) => c.reviewCaseId);
    const mineIds = cases.map((c) => c.reviewCaseId);
    expect(mineIds.some((id) => otherIds.includes(id))).toBe(false);
  });

  it("binds every decision receipt to the caller's principal and a real transition", () => {
    for (const disposition of REVIEW_DISPOSITIONS) {
      const receipt = syntheticDecisionReceipt(PRINCIPAL, "rev-1", disposition);
      expect(receipt.principalId).toBe(PRINCIPAL.principalId);
      expect(receipt.transition).toMatch(/^needs_review->/);
      expect(receipt.authority).toContain(disposition);
    }
  });
});

describe("review workbench", () => {
  it("renders each proposal as a case with evidence and a Proposed badge", () => {
    const cases = syntheticReviewCases(PRINCIPAL);
    render(<ReviewWorkbench cases={cases} />);
    expect(screen.getAllByTestId("review-case")).toHaveLength(cases.length);
    expect(screen.getAllByText("Proposed").length).toBe(cases.length);
    expect(screen.getAllByTestId("evidence-span").length).toBeGreaterThanOrEqual(cases.length);
  });

  it("shows an empty state when nothing is waiting", () => {
    render(<ReviewWorkbench cases={[]} />);
    expect(screen.getByText("No proposals are waiting for your review.")).toBeInTheDocument();
  });

  it("does not treat an acknowledged-not-persisted answer as a recorded decision", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(receiptResponse("rcpt-accept-1", "needs_review->accepted"));

    const [first] = syntheticReviewCases(PRINCIPAL);
    render(<ReviewWorkbench cases={[first]} />);

    await user.click(screen.getByTestId(`accept-${first.reviewCaseId}`));

    await waitFor(() =>
      expect(screen.getByTestId(`review-not-persisted-${first.reviewCaseId}`)).toHaveTextContent(
        "acknowledged_not_persisted",
      ),
    );
    expect(screen.queryByTestId(`receipt-${first.reviewCaseId}`)).not.toBeInTheDocument();

    expect(fetchSpy).toHaveBeenCalledWith(
      `/api/review/${first.reviewCaseId}/decide`,
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.disposition).toBe("accept");
    expect(Object.keys(body)).not.toContain("principalId");
    expect(Object.keys(body)).not.toContain("oid");
  });

  it("shows the receipt only when the server reports a persisted decision", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          receipt: {
            receiptId: "rcpt-accept-1",
            principalId: PRINCIPAL.principalId,
            subjectKind: "review_case",
            subjectId: "rev-x",
            transition: "needs_review->accepted",
            policyVersion: "review-policy-v4.0",
            issuedAt: "2026-08-05T14:00:00+00:00",
            authority: "review_disposition:accept",
          },
          status: "persisted",
        }),
        { status: 200 },
      ),
    );

    const [first] = syntheticReviewCases(PRINCIPAL);
    render(<ReviewWorkbench cases={[first]} />);
    await user.click(screen.getByTestId(`accept-${first.reviewCaseId}`));
    await waitFor(() =>
      expect(screen.getByTestId(`receipt-${first.reviewCaseId}`)).toHaveTextContent(
        "rcpt-accept-1",
      ),
    );
  });

  it("requires a corrected value before a correct-and-accept can be recorded", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(receiptResponse("rcpt-correct-1", "needs_review->corrected_accepted"));

    const [first] = syntheticReviewCases(PRINCIPAL);
    render(<ReviewWorkbench cases={[first]} />);

    await user.click(screen.getByTestId(`correct-${first.reviewCaseId}`));

    const submit = screen.getByTestId("correction-submit");
    expect(submit).toBeDisabled();

    await user.type(screen.getByTestId("correction-field"), "send by Thursday instead");
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.disposition).toBe("correct");
    expect(body.correctedValue).toBe("send by Thursday instead");
  });

  it("surfaces an error without recording a disposition when the server refuses", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { message: "no such review case" } }), {
        status: 404,
      }),
    );

    const [first] = syntheticReviewCases(PRINCIPAL);
    render(<ReviewWorkbench cases={[first]} />);

    await user.click(screen.getByTestId(`reject-${first.reviewCaseId}`));

    const card = screen.getByTestId("review-case");
    await waitFor(() =>
      expect(within(card).getByRole("alert")).toHaveTextContent("no such review case"),
    );
    expect(screen.queryByTestId(`receipt-${first.reviewCaseId}`)).not.toBeInTheDocument();
  });
});

describe("backend review workbench GoodNotes cases", () => {
  const CAPTURE_CASE: CaptureBackendReviewCase = {
    reviewCaseId: "rvc_aaaa0001aaaa0001aaaa0001",
    proposalId: "prop_aaaa0001aaaa0001aaaa0001",
    subjectKind: "capture_proposal",
    captureId: "cap_aaaa0001aaaa0001aaaa0001",
    versionId: "capver_aaaa0001aaaa0001aaaa0001",
    proposalType: "commitment",
    proposalState: "proposed",
    riskClass: "high",
    openedAt: "2026-01-01T00:00:00Z",
    reviewVersion: 3,
    latestDisposition: null,
  };

  const SEMANTIC_CASE: GoodNotesSemanticBackendReviewCase = {
    reviewCaseId: "rvc_cccc0001cccc0001cccc0001",
    proposalId: "prop_cccc0001cccc0001cccc0001",
    subjectKind: "goodnotes_semantic",
    runId: "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
    pageVersionId: "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
    proposalType: "goodnotes_semantic",
    proposalState: "proposed",
    riskClass: "moderate",
    openedAt: "2026-01-01T00:00:00Z",
    reviewVersion: 4,
    latestDisposition: null,
  };

  const REGION_CASE: GoodNotesRegionBackendReviewCase = {
    reviewCaseId: "rvc_dddd0001dddd0001dddd0001",
    proposalId: "prop_dddd0001dddd0001dddd0001",
    subjectKind: "goodnotes_region",
    regionId: "gnreg_aaaaaaaaaaaaaaaaaaaaaaaa",
    pageVersionId: "gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
    confidence: 0.82,
    proposalType: "goodnotes_region",
    proposalState: "needs_review",
    riskClass: "low",
    openedAt: "2026-01-01T00:00:00Z",
    reviewVersion: 2,
    latestDisposition: null,
  };

  it("still renders a capture case as capture and version identifiers with Reveal", () => {
    render(<BackendReviewWorkbench cases={[CAPTURE_CASE]} />);
    const card = screen.getByTestId("backend-review-case");
    expect(card).toHaveAttribute("data-subject-kind", "capture_proposal");
    expect(within(card).getByTestId("review-capture-id")).toHaveTextContent(CAPTURE_CASE.captureId);
    expect(within(card).getByTestId("review-version-id")).toHaveTextContent(CAPTURE_CASE.versionId);
    expect(within(card).getByTestId("review-reveal")).toBeInTheDocument();
    expect(within(card).queryByTestId("review-goodnotes-link")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-run-id")).not.toBeInTheDocument();
    expect(screen.queryByText(/proposal summary/i)).not.toBeInTheDocument();
  });

  it("does not render a goodnotes_semantic row as capture identifiers", () => {
    render(<BackendReviewWorkbench cases={[SEMANTIC_CASE]} />);
    const card = screen.getByTestId("backend-review-case");
    expect(within(card).getByTestId("review-subject-kind")).toHaveTextContent("goodnotes_semantic");
    expect(within(card).getByTestId("review-run-id")).toHaveTextContent(SEMANTIC_CASE.runId);
    expect(within(card).getByTestId("review-page-version-id")).toHaveTextContent(
      SEMANTIC_CASE.pageVersionId,
    );
    expect(within(card).queryByTestId("review-capture-id")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-version-id")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-reveal")).not.toBeInTheDocument();
    const href = within(card).getByTestId("review-goodnotes-link").getAttribute("href");
    expect(href).toBe(
      "/knowledge/goodnotes?runId=gnrun_aaaaaaaaaaaaaaaaaaaaaaaa&pageVersionId=gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
    );
    expect(href).not.toContain("captureId=");
    expect(href).not.toContain("notebookId=");
    expect(href).not.toContain(SEMANTIC_CASE.reviewCaseId);
  });

  it("links a goodnotes_region row by pageVersionId only and lists the stated confidence", () => {
    render(<BackendReviewWorkbench cases={[REGION_CASE]} />);
    const card = screen.getByTestId("backend-review-case");
    expect(within(card).getByTestId("review-subject-kind")).toHaveTextContent("goodnotes_region");
    expect(within(card).getByTestId("review-region-id")).toHaveTextContent(REGION_CASE.regionId);
    expect(within(card).getByTestId("review-page-version-id")).toHaveTextContent(
      REGION_CASE.pageVersionId,
    );
    expect(within(card).getByTestId("review-confidence")).toHaveTextContent("0.82");
    expect(within(card).queryByTestId("review-capture-id")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-run-id")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-reveal")).not.toBeInTheDocument();
    const href = within(card).getByTestId("review-goodnotes-link").getAttribute("href");
    expect(href).toBe("/knowledge/goodnotes?pageVersionId=gnver_bbbbbbbbbbbbbbbbbbbbbbbb");
    expect(href).not.toContain("runId=");
    expect(href).not.toContain("captureId=");
  });

  it("decides a pending GoodNotes case with expectedReviewVersion from the row", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "persisted",
          receipt: {
            decisionId: "rvd_aaaaaaaaaaaaaaaaaaaaaaaa",
            reviewVersion: 5,
            proposalState: "accepted",
            assertionId: null,
            receiptId: null,
          },
        }),
        { status: 200 },
      ),
    );

    render(<BackendReviewWorkbench cases={[SEMANTIC_CASE]} />);
    await user.click(screen.getByTestId("review-accept"));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(fetchSpy.mock.calls[0]?.[0]).toBe(
      `/api/review/${SEMANTIC_CASE.reviewCaseId}/decide`,
    );
    const body = JSON.parse((fetchSpy.mock.calls[0]?.[1] as RequestInit).body as string);
    expect(body).toEqual({
      disposition: "accept",
      expectedReviewVersion: SEMANTIC_CASE.reviewVersion,
    });
    expect(body).not.toHaveProperty("principalId");
  });
});
