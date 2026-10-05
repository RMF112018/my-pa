import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * WP07 §8.7 — case, run, page-version and review-version receipts are
 * diagnostics. This file's subject is those identifiers, so it runs in the
 * mode that renders them; the OFF side is asserted in `surfaces.test.tsx`.
 */
const { diagnostics } = vi.hoisted(() => ({ diagnostics: { enabled: true } }));
vi.mock("@/components/diagnostics/diagnostics-provider", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/diagnostics/diagnostics-provider")>();
  return {
    ...actual,
    useDiagnosticsEnabled: () => diagnostics.enabled,
    WhenDiagnostics: ({ children }: { children: React.ReactNode }) =>
      diagnostics.enabled ? children : null,
  };
});
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewWorkbench } from "@/components/review/review-workbench";
import { BackendReviewWorkbench } from "@/components/review/backend-review-workbench";
import type {
  CaptureBackendReviewCase,
  GoodNotesRegionBackendReviewCase,
  GoodNotesSemanticBackendReviewCase,
  KnowledgeAssertionBackendReviewCase,
  UnknownBackendReviewCase,
} from "@/contracts/views";
import {
  syntheticReviewCases,
  syntheticDecisionReceipt,
  REVIEW_DISPOSITIONS,
} from "@/lib/fixtures/review";
import type { PrincipalSession } from "@/contracts/identity";

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

const OTHER: PrincipalSession = { ...PRINCIPAL, principalId: "bbbb0002-0000-0000-0000-000000000002" };

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
    expect(screen.getByText(/nothing to review right now/i)).toBeInTheDocument();
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
      expect(within(card).getByRole("alert")).toHaveTextContent("This item could not be found."),
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

/**
 * KLP-AC-037 (web half) and KLP-AC-135: Knowledge Assertion cases offer exactly
 * accept / reject / defer / mark-unresolved / invalidate, hide Correct, never
 * reach extraction Reveal, and read the stored fact through
 * `knowledge.assertions.read`; unknown cases render inert; dropped rows are
 * counted.
 */
describe("backend review workbench Knowledge Assertion and unknown cases", () => {
  const KNOWLEDGE_CASE: KnowledgeAssertionBackendReviewCase = {
    reviewCaseId: "rvw_aa77ff0d68d72af5b4771d736a0f789e",
    proposalId: "kaprp_7a88c3d12e4066cd1e9f007ebf89c4b0",
    subjectKind: "knowledge_assertion",
    subjectKindOfFact: "entity",
    subjectId: "ent_66fb736038ea9e42d480f6f466210679",
    predicateCode: "organization.payment_terms",
    reviewRequirement: "requires_operator",
    proposalType: "organization.payment_terms",
    proposalState: "needs_review",
    riskClass: "high",
    openedAt: "2026-10-04T12:00:00.000Z",
    reviewVersion: 0,
    latestDisposition: null,
  };

  const UNKNOWN_CASE: UnknownBackendReviewCase = {
    subjectKind: "unknown",
    reviewCaseId: "rvw_unknown0001unknown0001",
    reportedSubjectKind: "future_kind",
  };

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

  function persisted(receipt: Record<string, unknown>) {
    return new Response(JSON.stringify({ shape: "backend", status: "persisted", receipt }), {
      status: 200,
    });
  }

  const ASSERTION_BODY = {
    shape: "backend",
    assertion: {
      assertion_id: "kasr_284d7c980ceccde51e55e10874e1c270",
      subject_kind: "entity",
      subject_id: "ent_66fb736038ea9e42d480f6f466210679",
      predicate_code: "organization.payment_terms",
      predicate_version: 1,
      value_type: "text",
      value: "net 30",
      qualifier: null,
      effective_from: "2026-10-04T12:00:00+00:00",
      effective_to: null,
      epistemic_status: "review_accepted",
      classification: "private_local",
      lifecycle: "active",
      version: 1,
      supersedes_assertion_id: null,
      created_at: "2026-10-04T12:00:00+00:00",
      updated_at: "2026-10-04T12:00:00+00:00",
    },
  };

  it("offers exactly accept, reject, defer, mark unresolved and invalidate; no Correct, no Reveal", () => {
    render(<BackendReviewWorkbench cases={[KNOWLEDGE_CASE]} />);
    const card = screen.getByTestId("backend-review-case");
    expect(card).toHaveAttribute("data-subject-kind", "knowledge_assertion");
    const offered = within(card)
      .getAllByRole("button")
      .map((button) => button.getAttribute("data-testid"));
    expect(offered).toEqual([
      "review-accept",
      "review-reject",
      "review-defer",
      "review-unresolved",
      "review-invalidate",
    ]);
    expect(within(card).queryByTestId("review-correct")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-reveal")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-correction-field")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-capture-id")).not.toBeInTheDocument();
    expect(within(card).queryByTestId("review-goodnotes-link")).not.toBeInTheDocument();
    expect(within(card).getByTestId("review-fact-subject-kind")).toHaveTextContent("entity");
    expect(within(card).getByTestId("review-requires-operator")).toBeInTheDocument();
    expect(within(card).getByTestId("review-fact-subject")).toHaveTextContent(
      KNOWLEDGE_CASE.subjectId,
    );
  });

  it("keeps Correct and Reveal on a capture case beside it, and never offers it Invalidate", () => {
    render(<BackendReviewWorkbench cases={[CAPTURE_CASE, KNOWLEDGE_CASE]} />);
    const [capture, knowledge] = screen.getAllByTestId("backend-review-case");
    expect(within(capture!).getByTestId("review-correct")).toBeInTheDocument();
    expect(within(capture!).getByTestId("review-reveal")).toBeInTheDocument();
    expect(within(capture!).queryByTestId("review-invalidate")).not.toBeInTheDocument();
    expect(within(knowledge!).queryByTestId("review-correct")).not.toBeInTheDocument();
  });

  it("sends the typed invalidate verb with the row's version and no correction", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      persisted({
        decisionId: "kadec_0c1d2e3f405162738495a6b7c8d9eaf0",
        reviewVersion: 1,
        proposalState: "invalidated",
        assertionId: null,
        receiptId: null,
      }),
    );
    render(<BackendReviewWorkbench cases={[KNOWLEDGE_CASE]} />);
    await user.click(screen.getByTestId("review-invalidate"));
    await waitFor(() => expect(screen.getByTestId("review-decided")).toBeInTheDocument());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0]?.[0]).toBe(`/api/review/${KNOWLEDGE_CASE.reviewCaseId}/decide`);
    const body = JSON.parse((fetchSpy.mock.calls[0]?.[1] as RequestInit).body as string);
    expect(body).toEqual({ disposition: "invalidate", expectedReviewVersion: 0 });
    expect(screen.getByTestId("review-decided")).toHaveTextContent("invalidated");
    // Nothing was stored as a fact, so there is nothing to read.
    expect(screen.queryByTestId("review-read-fact")).not.toBeInTheDocument();
  });

  it("reads the accepted fact through knowledge.assertions.read, never through Reveal", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        persisted({
          decisionId: "kadec_9adb6ea38eaeb5e05e1f635c96828236",
          reviewVersion: 1,
          proposalState: "accepted",
          assertionId: "kasr_284d7c980ceccde51e55e10874e1c270",
          receiptId: "kamut_3f7606c8c83bd6129e2301e3bac303ae",
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(ASSERTION_BODY), { status: 200 }));
    render(<BackendReviewWorkbench cases={[KNOWLEDGE_CASE]} />);
    // Before a decision stores a fact there is nothing to read.
    expect(screen.queryByTestId("review-read-fact")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("review-accept"));
    await waitFor(() => expect(screen.getByTestId("review-read-fact")).toBeInTheDocument());
    // A decided case offers no further dispositions.
    expect(screen.queryByTestId("review-accept")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("review-read-fact"));
    await waitFor(() => expect(screen.getByTestId("review-fact")).toBeInTheDocument());
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls[1]?.[0]).toBe(
      "/api/knowledge/assertions/kasr_284d7c980ceccde51e55e10874e1c270",
    );
    expect((fetchSpy.mock.calls[1]?.[1] as RequestInit).method).toBe("GET");
    expect(screen.getByTestId("review-fact-value")).toHaveTextContent("net 30");
    for (const call of fetchSpy.mock.calls) {
      expect(String(call[0])).not.toContain("/api/reveal");
    }
  });

  it("reports an unreadable fact as unreadable rather than rendering a guess", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        persisted({
          decisionId: "kadec_9adb6ea38eaeb5e05e1f635c96828236",
          reviewVersion: 1,
          proposalState: "accepted",
          assertionId: "kasr_284d7c980ceccde51e55e10874e1c270",
          receiptId: "kamut_3f7606c8c83bd6129e2301e3bac303ae",
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ error: { errorClass: "not_found", code: "not_found", message: "x" } }),
          { status: 404 },
        ),
      );
    render(<BackendReviewWorkbench cases={[KNOWLEDGE_CASE]} />);
    await user.click(screen.getByTestId("review-accept"));
    await user.click(await screen.findByTestId("review-read-fact"));
    await waitFor(() => expect(screen.getByTestId("review-fact-failed")).toBeInTheDocument());
    expect(screen.queryByTestId("review-fact")).not.toBeInTheDocument();
  });

  it("offers no decision on a Knowledge case already in a terminal state", () => {
    render(
      <BackendReviewWorkbench
        cases={[
          { ...KNOWLEDGE_CASE, proposalState: "rejected", latestDisposition: "reject", reviewVersion: 1 },
        ]}
      />,
    );
    const card = screen.getByTestId("backend-review-case");
    expect(within(card).queryAllByRole("button")).toEqual([]);
    expect(within(card).getByTestId("review-already-decided")).toBeInTheDocument();
  });

  it("renders an unknown case inert: its id and reported kind, and no control", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<BackendReviewWorkbench cases={[CAPTURE_CASE, UNKNOWN_CASE]} />);
    const cards = screen.getAllByTestId("backend-review-case");
    expect(cards).toHaveLength(2);
    const unknown = cards[1]!;
    expect(unknown).toHaveAttribute("data-subject-kind", "unknown");
    expect(unknown).toHaveAttribute("data-review-case-id", UNKNOWN_CASE.reviewCaseId);
    expect(within(unknown).queryAllByRole("button")).toEqual([]);
    expect(within(unknown).getByTestId("review-unknown-case")).toBeInTheDocument();
    expect(within(unknown).getByText("future_kind")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("states how many listed rows were dropped instead of hiding them", () => {
    const { rerender } = render(<BackendReviewWorkbench cases={[KNOWLEDGE_CASE]} droppedRows={2} />);
    expect(screen.getByTestId("review-dropped-rows")).toHaveTextContent(
      "2 listed cases could not be read",
    );
    rerender(<BackendReviewWorkbench cases={[]} droppedRows={1} />);
    expect(screen.getByTestId("review-dropped-rows")).toHaveTextContent(
      "1 listed case could not be read",
    );
    rerender(<BackendReviewWorkbench cases={[KNOWLEDGE_CASE]} />);
    expect(screen.queryByTestId("review-dropped-rows")).not.toBeInTheDocument();
  });
});
