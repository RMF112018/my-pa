import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CorrectionForm } from "@/components/goodnotes/correction-form";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CorrectionForm", () => {
  it("posts occurrenceId and transcription only", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            shape: "backend",
            occurrence_id: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
            revision_id: "gnrev_aaaaaaaaaaaaaaaaaaaaaaaa",
            prior_revision_id: "gnrev_bbbbbbbbbbbbbbbbbbbbbbbb",
            replayed: false,
            disposition: "canonical_revision_appended",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<CorrectionForm occurrenceId="gnocc_bbbbbbbbbbbbbbbbbbbbbbbb" />);
    await userEvent.type(
      screen.getByRole("textbox", { name: /corrected transcription/i }),
      "revised note",
    );
    await userEvent.click(screen.getByRole("button", { name: "Record correction" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const first = fetchMock.mock.calls[0] as unknown as [unknown, RequestInit] | undefined;
    expect(String(first?.[0])).toBe("/api/goodnotes/correct");
    expect(first?.[1]?.method).toBe("POST");
    const body = JSON.parse(String(first?.[1]?.body ?? "{}")) as Record<string, unknown>;
    expect(body).toEqual({
      occurrenceId: "gnocc_bbbbbbbbbbbbbbbbbbbbbbbb",
      transcription: "revised note",
    });
    expect(body).not.toHaveProperty("principalId");
    expect(body).not.toHaveProperty("principal_id");
    await waitFor(() =>
      expect(screen.getByTestId("goodnotes-correction-appended").textContent).toMatch(
        /canonical revision was appended/i,
      ),
    );
  });

  it("understates when the server does not report a stored canonical revision", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ shape: "backend", disposition: "accepted" }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    render(
      <CorrectionForm occurrenceId="gnocc_bbbbbbbbbbbbbbbbbbbbbbbb" initialTranscription="note" />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Record correction" }));
    await waitFor(() => expect(screen.getByTestId("goodnotes-correction-understated")).toBeTruthy());
    expect(screen.queryByTestId("goodnotes-correction-appended")).toBeNull();
  });
});
