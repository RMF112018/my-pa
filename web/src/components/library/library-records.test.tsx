import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { BackendCaptureEntry, BackendCaptureMatch } from "@/contracts/views";
import { CaptureItem, CaptureListing, CaptureMatches } from "./library-records";
import type { CaptureReadResult } from "@/lib/api/decode/capabilities/capture.read";

afterEach(cleanup);

const ENTRY: BackendCaptureEntry = {
  captureId: "cap_aaaa0001aaaa0001aaaa0001",
  ownerPrincipalId: "prn_aaaa0001aaaa0001aaaa0001",
  createdAt: "2026-01-01T00:00:00Z",
  versionCount: 2,
  latestVersionId: "capver_aaaa0001aaaa0001aaaa0001",
  latestVersionNumber: 2,
  latestRecordedAt: "2026-01-02T00:00:00Z",
};

const MATCH: BackendCaptureMatch = {
  captureId: "cap_bbbb0001bbbb0001bbbb0001",
  versionId: "capver_bbbb0001bbbb0001bbbb0001",
  versionNumber: 3,
  characterCount: 42,
  recordedAt: "2026-03-04T15:30:00Z",
};

const BODY_LEAK = "SECRET BODY TEXT THAT MUST NOT LEAK";

describe("CaptureListing cards", () => {
  it("titles the card with a human date, not the captureId", () => {
    render(<CaptureListing entries={[ENTRY]} />);
    const card = screen.getByTestId("library-capture");
    const title = within(card).getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Capture · 2026-01-01 00:00 UTC");
    expect(title.textContent).not.toBe(ENTRY.captureId);
    expect(title.textContent).not.toContain(ENTRY.captureId);
  });

  it("does not render capture body text even when a fake body field is present", () => {
    const leaky = { ...ENTRY, text: BODY_LEAK };
    render(<CaptureListing entries={[leaky as BackendCaptureEntry]} />);
    expect(screen.queryByText(BODY_LEAK)).toBeNull();
    expect(screen.queryByTestId("library-capture-text")).toBeNull();
  });

  it("offers an Open link whose href includes the captureId", () => {
    render(<CaptureListing entries={[ENTRY]} />);
    const open = screen.getByRole("link", { name: "Open" });
    expect(open).toHaveAttribute(
      "href",
      `/knowledge?captureId=${encodeURIComponent(ENTRY.captureId)}`,
    );
  });

  it("keeps the captureId in Details so the card still contains the identifier", () => {
    render(<CaptureListing entries={[ENTRY]} />);
    const card = screen.getByTestId("library-capture");
    const details = within(card).getByText("Details").closest("details");
    expect(details).toBeTruthy();
    expect(details?.textContent).toContain(ENTRY.captureId);
    expect(details?.textContent).toContain(ENTRY.latestVersionId);
    expect(details?.textContent).toContain(ENTRY.ownerPrincipalId);
    expect(card.textContent).toMatch(/cap_[A-Za-z0-9]+/);
  });

  it("does not repeat a per-card explanation of missing text", () => {
    render(<CaptureListing entries={[ENTRY]} />);
    expect(screen.queryByText(/captured text is not shown here/i)).toBeNull();
    expect(screen.queryByText(/listing carries no content/i)).toBeNull();
  });
});

describe("CaptureMatches cards", () => {
  it("titles the match with the recorded date, not the captureId", () => {
    render(<CaptureMatches matches={[MATCH]} />);
    const card = screen.getByTestId("library-match");
    const title = within(card).getByRole("heading", { level: 3 });
    expect(title.textContent).toBe("Capture · 2026-03-04 15:30 UTC");
    expect(title.textContent).not.toBe(MATCH.captureId);
    expect(within(card).getByText("version 3")).toBeTruthy();
  });

  it("does not render capture body text even when a fake body field is present", () => {
    const leaky = { ...MATCH, text: BODY_LEAK, snippet: BODY_LEAK };
    render(<CaptureMatches matches={[leaky as BackendCaptureMatch]} />);
    expect(screen.queryByText(BODY_LEAK)).toBeNull();
  });

  it("opens the matched version by captureId and versionId", () => {
    render(<CaptureMatches matches={[MATCH]} />);
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      `/knowledge?captureId=${encodeURIComponent(MATCH.captureId)}&versionId=${encodeURIComponent(MATCH.versionId)}`,
    );
  });

  it("keeps capture and version identifiers in Details", () => {
    render(<CaptureMatches matches={[MATCH]} />);
    const card = screen.getByTestId("library-match");
    const details = within(card).getByText("Details").closest("details");
    expect(details?.textContent).toContain(MATCH.captureId);
    expect(details?.textContent).toContain(MATCH.versionId);
  });
});

describe("CaptureItem read path", () => {
  it("may still show capture text from capture.read", () => {
    const version: CaptureReadResult = {
      capture_id: ENTRY.captureId,
      version_id: ENTRY.latestVersionId,
      version_number: 2,
      supersedes_version_id: null,
      is_current: true,
      owner_principal_id: ENTRY.ownerPrincipalId,
      classification: "synthetic_test",
      processing_policy: "local_only",
      content_sha256: "a".repeat(64),
      character_count: BODY_LEAK.length,
      text: BODY_LEAK,
      is_truncated: false,
      client_created_at: null,
      server_received_at: ENTRY.latestRecordedAt,
      occurred_at: null,
      accepted_at: ENTRY.latestRecordedAt,
      recorded_at: ENTRY.latestRecordedAt,
    };
    render(<CaptureItem version={version} />);
    expect(screen.getByTestId("library-capture-text").textContent).toBe(BODY_LEAK);
  });
});
