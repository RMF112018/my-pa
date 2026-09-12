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

  it("places the region with nav-height / safe-area aware offset", () => {
    const { api } = renderFeedback();
    act(() => {
      api.publish({
        eventId: "placement",
        kind: "success",
        message: "Create confirmed",
      });
    });
    const region = screen.getByTestId("mutation-feedback-region");
    expect(region.style.paddingBottom).toContain("--nav-height");
    expect(region.style.paddingBottom).toContain("safe-area-inset-bottom");
  });
});
