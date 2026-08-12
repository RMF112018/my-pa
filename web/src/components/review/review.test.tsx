import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewWorkbench } from "@/components/review/review-workbench";
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

  it("accepts a proposal, posts only the disposition, and shows the receipt", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(receiptResponse("rcpt-accept-1", "needs_review->accepted"));

    const [first] = syntheticReviewCases(PRINCIPAL);
    render(<ReviewWorkbench cases={[first]} />);

    await user.click(screen.getByTestId(`accept-${first.reviewCaseId}`));

    await waitFor(() =>
      expect(screen.getByTestId(`receipt-${first.reviewCaseId}`)).toHaveTextContent(
        "rcpt-accept-1",
      ),
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      `/api/review/${first.reviewCaseId}/decide`,
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.disposition).toBe("accept");
    // The payload must never carry identity fields.
    expect(Object.keys(body)).not.toContain("principalId");
    expect(Object.keys(body)).not.toContain("oid");
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
