import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { useEffect, useState, type ReactNode } from "react";
import {
  MutationFeedbackEvent,
  MutationFeedbackProvider,
  useMutationFeedback,
} from "@/components/ui/mutation-feedback";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function Publisher({
  onReady,
}: {
  readonly onReady: (api: ReturnType<typeof useMutationFeedback>) => void;
}) {
  const feedback = useMutationFeedback();
  useEffect(() => {
    onReady(feedback);
  }, [feedback, onReady]);
  return null;
}

function renderFeedback(ui?: ReactNode) {
  const apiRef: { current: ReturnType<typeof useMutationFeedback> | null } = { current: null };
  const view = render(
    <MutationFeedbackProvider>
      <Publisher
        onReady={(value) => {
          apiRef.current = value;
        }}
      />
      {ui}
    </MutationFeedbackProvider>,
  );
  if (!apiRef.current) {
    throw new Error("feedback API not ready");
  }
  return { ...view, api: apiRef.current };
}

/**
 * Acceptance traceability: TASK-AC-030, TASK-AC-035.
 *
 * Create success outlives the form that published it (030), and mutation outcomes are made
 * perceptible to a screen reader — alert semantics for conflicts, a live region that is not
 * spammed by background poll notices, and no focus steal (035). The VoiceOver leg of
 * TASK-AC-046 is operator-gated and is not claimed here.
 */
describe("MutationFeedbackProvider", () => {
  it("keeps create success feedback after the source form unmounts", () => {
    function SourceForm({ open }: { readonly open: boolean }) {
      const feedback = useMutationFeedback();
      useEffect(() => {
        if (!open) return;
        feedback.publish({
          eventId: MutationFeedbackEvent.createConfirmed("intent-1"),
          kind: "success",
          message: "Create confirmed",
        });
      }, [feedback, open]);
      return open ? <form aria-label="Create task">title</form> : null;
    }

    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <MutationFeedbackProvider>
          <SourceForm open={open} />
          <button type="button" onClick={() => setOpen(false)}>
            Close form
          </button>
        </MutationFeedbackProvider>
      );
    }

    render(<Harness />);
    expect(screen.getByRole("status")).toHaveTextContent("Create confirmed");
    expect(screen.getByRole("form", { name: "Create task" })).toBeTruthy();

    act(() => {
      screen.getByRole("button", { name: "Close form" }).click();
    });

    expect(screen.queryByRole("form", { name: "Create task" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Create confirmed");
    expect(screen.getByTestId("mutation-feedback-region")).toBeTruthy();
  });

  it("dedupes duplicate publication by stable event identity", () => {
    const { api } = renderFeedback();

    act(() => {
      api.publish({
        eventId: MutationFeedbackEvent.closeConfirmed("task-1", "intent-a"),
        kind: "success",
        message: "Close confirmed",
      });
      api.publish({
        eventId: MutationFeedbackEvent.closeConfirmed("task-1", "intent-a"),
        kind: "success",
        message: "Close confirmed (duplicate)",
      });
    });

    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Close confirmed");
    expect(screen.queryByText("Close confirmed (duplicate)")).toBeNull();
  });

  it("uses alert semantics for conflicts and keeps them dismissible", () => {
    const { api } = renderFeedback();

    act(() => {
      api.publish({
        eventId: MutationFeedbackEvent.conflict("task-9", "intent-c"),
        kind: "conflict",
        message: "Conflict: compare the current Task, then reapply deliberately.",
      });
    });

    expect(screen.getByRole("alert")).toHaveAttribute("aria-live", "assertive");
    expect(screen.getByTestId("mutation-feedback-dismiss-task:conflict:task-9:intent-c")).toBeTruthy();

    act(() => {
      screen.getByTestId("mutation-feedback-dismiss-task:conflict:task-9:intent-c").click();
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not steal focus when feedback is published from a pending control", () => {
    function PendingControl() {
      const feedback = useMutationFeedback();
      return (
        <button
          type="button"
          onClick={() =>
            feedback.publish({
              eventId: MutationFeedbackEvent.cancelConfirmed("task-2", "intent-b"),
              kind: "success",
              message: "Cancel confirmed",
            })
          }
        >
          Cancel task
        </button>
      );
    }

    render(
      <MutationFeedbackProvider>
        <PendingControl />
      </MutationFeedbackProvider>,
    );

    const button = screen.getByRole("button", { name: "Cancel task" });
    act(() => {
      button.focus();
    });
    expect(document.activeElement).toBe(button);

    act(() => {
      button.click();
    });

    expect(screen.getByRole("status")).toHaveTextContent("Cancel confirmed");
    expect(document.activeElement).toBe(button);
  });

  it("does not spam live regions for repeated background poll notices", () => {
    const { api } = renderFeedback();
    const eventId = MutationFeedbackEvent.pollDegraded("tasks|list|active");

    act(() => {
      api.publishPollNotice({
        eventId,
        kind: "info",
        message: "Task updates are temporarily unavailable.",
      });
      api.publishPollNotice({
        eventId,
        kind: "info",
        message: "Task updates are temporarily unavailable.",
      });
      api.publishPollNotice({
        eventId,
        kind: "info",
        message: "Task updates are temporarily unavailable.",
      });
    });

    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Task updates are temporarily unavailable.",
    );
  });

  it("expires routine success after about five seconds", () => {
    vi.useFakeTimers();
    const { api } = renderFeedback();

    act(() => {
      api.publish({
        eventId: MutationFeedbackEvent.filterRemoval("task-3", "intent-d"),
        kind: "success",
        message: "Task left the current filter.",
      });
    });
    expect(screen.getByRole("status")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("bounds the visible stack", () => {
    const { api } = renderFeedback();

    act(() => {
      for (let i = 0; i < 5; i += 1) {
        api.publish({
          eventId: `overflow-${i}`,
          kind: "error",
          message: `Failure ${i}`,
        });
      }
    });

    expect(screen.getAllByRole("alert")).toHaveLength(3);
    expect(screen.getByText("Failure 4")).toBeTruthy();
    expect(screen.getByText("Failure 3")).toBeTruthy();
    expect(screen.getByText("Failure 2")).toBeTruthy();
    expect(screen.queryByText("Failure 1")).toBeNull();
    expect(screen.queryByText("Failure 0")).toBeNull();
  });

  /*
    WP09 corrective. The previous assertion here only checked that the string
    `safe-area-inset-bottom` appeared in `paddingBottom`. It did, and the
    declaration was inert: the region is top-anchored with `bottom` auto, so
    padding below its content cannot move that content up and cannot keep it
    clear of the nav. A substring assertion cannot tell a live rule from a dead
    one, which is how the dead rule survived. The name of this test claims only
    what the body proves: the inert offset is gone. The load-bearing top offset
    is unassertable here for the reason given below.
  */
  it("leaves no inert bottom offset on the top-anchored feedback region", () => {
    const { api } = renderFeedback();
    act(() => {
      api.publish({
        eventId: "placement",
        kind: "success",
        message: "Create confirmed",
      });
    });
    const region = screen.getByTestId("mutation-feedback-region");
    // The region is top-anchored (bottom auto), so it never sets a bottom edge,
    // and it no longer pads below its own content pretending to hold the nav off.
    expect(region.style.bottom).toBe("");
    expect(region.style.paddingBottom).toBe("");
    // The load-bearing offset — `top: max(0.75rem, env(safe-area-inset-top))` —
    // cannot be asserted here: jsdom's CSS parser rejects `max()` outright and
    // drops the whole declaration, so `region.style.top` is `""` whatever the
    // component sets. Stated rather than faked; the real offset is e2e ground.
    expect(region.style.top).toBe("");
  });
});
