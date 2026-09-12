import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  TaskCommentCount,
  TaskComments,
  type TaskCommentPending,
  type TaskCommentsProps,
} from "@/components/tasks/task-comments";
import type { TaskComment } from "@/contracts/work";

let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function comment(overrides: Partial<TaskComment> = {}): TaskComment {
  return {
    comment_id: "cmt-000000000001",
    task_id: "task-1",
    body: "First note",
    author_kind: "principal",
    author_id: "prn-zzzzzzzzzzzz",
    created_at: "2026-09-01T10:00:00.000Z",
    ...overrides,
  };
}

function renderComments(overrides: Partial<TaskCommentsProps> = {}) {
  const props: TaskCommentsProps = {
    comments: [],
    onSubmit: vi.fn(),
    onRetry: vi.fn(),
    onLoadMore: vi.fn(),
    ...overrides,
  };
  render(<TaskComments {...props} />);
  return props;
}

describe("TaskCommentCount", () => {
  it("invites a first comment when there are none", () => {
    render(<TaskCommentCount count={0} />);
    expect(screen.getByRole("button", { name: "Add comment" })).toBeInTheDocument();
  });

  it("uses the singular for one comment", () => {
    render(<TaskCommentCount count={1} />);
    expect(screen.getByRole("button", { name: "1 comment" })).toBeInTheDocument();
  });

  it("uses the plural beyond one comment", () => {
    render(<TaskCommentCount count={4} />);
    expect(screen.getByRole("button", { name: "4 comments" })).toBeInTheDocument();
  });
});

describe("TaskComments", () => {
  it("renders the empty state with the composer", () => {
    renderComments();
    expect(screen.getByTestId("task-comments")).toBeInTheDocument();
    expect(screen.getByText("No comments yet.")).toBeInTheDocument();
    expect(screen.getByLabelText("Add comment")).toBeInTheDocument();
    expect(screen.getByTestId("task-comments-submit")).toBeInTheDocument();
  });

  it("renders the loading state", () => {
    renderComments({ loading: true });
    expect(screen.getByText("Loading comments…")).toBeInTheDocument();
  });

  it("renders the unavailable state with a working Retry", async () => {
    const user = userEvent.setup();
    const onRetryLoad = vi.fn();
    renderComments({ unavailable: true, onRetryLoad });

    expect(screen.getByText("Comments unavailable right now.")).toBeInTheDocument();
    await user.click(screen.getByTestId("task-comments-retry-load"));
    expect(onRetryLoad).toHaveBeenCalledTimes(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("renders each comment with a human author label and an ISO dateTime, and never leaks ids", () => {
    renderComments({
      comments: [
        comment({ comment_id: "cmt-aaaaaaaaaaaa", body: "Mine", author_kind: "principal", author_id: "prn-111111111111" }),
        comment({
          comment_id: "cmt-bbbbbbbbbbbb",
          body: "From the assistant",
          author_kind: "assistant",
          author_id: "asst-222222222222",
          created_at: "2026-09-02T11:30:00.000Z",
        }),
        comment({
          comment_id: "cmt-cccccccccccc",
          body: "System said so",
          author_kind: "system",
          author_id: "sys-333333333333",
          created_at: "2026-09-03T12:45:00.000Z",
        }),
      ],
    });

    expect(screen.getByText("Mine")).toBeInTheDocument();
    expect(screen.getByText("From the assistant")).toBeInTheDocument();
    expect(screen.getByText("System said so")).toBeInTheDocument();

    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();

    const thread = screen.getByTestId("task-comments-thread");
    const times = thread.querySelectorAll("time");
    expect(times).toHaveLength(3);
    expect(times[0]).toHaveAttribute("dateTime", "2026-09-01T10:00:00.000Z");
    expect(times[1]).toHaveAttribute("dateTime", "2026-09-02T11:30:00.000Z");
    expect(times[2]).toHaveAttribute("dateTime", "2026-09-03T12:45:00.000Z");

    const rendered = screen.getByTestId("task-comments").textContent ?? "";
    for (const opaque of [
      "cmt-aaaaaaaaaaaa",
      "cmt-bbbbbbbbbbbb",
      "cmt-cccccccccccc",
      "prn-111111111111",
      "asst-222222222222",
      "sys-333333333333",
    ]) {
      expect(rendered).not.toContain(opaque);
    }
  });

  it("blocks submission until there is real text, then submits trimmed and clears", async () => {
    const user = userEvent.setup();
    const props = renderComments();
    const submit = screen.getByTestId("task-comments-submit");
    const field = screen.getByLabelText("Add comment");

    expect(submit).toBeDisabled();

    await user.type(field, "   ");
    expect(submit).toBeDisabled();

    await user.clear(field);
    await user.type(field, "  a real note  ");
    expect(submit).toBeEnabled();

    await user.click(submit);
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
    expect(props.onSubmit).toHaveBeenCalledWith("a real note");
    expect(field).toHaveValue("");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("blocks submission while submitting", async () => {
    const user = userEvent.setup();
    const props = renderComments({ submitting: true });
    const field = screen.getByLabelText("Add comment");
    await user.type(field, "note");
    const submit = screen.getByTestId("task-comments-submit");
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(props.onSubmit).not.toHaveBeenCalled();
  });

  it("blocks submission while no canonical snapshot is held", async () => {
    const user = userEvent.setup();
    const props = renderComments({ disabled: true, comments: [comment()] });
    expect(screen.getByLabelText("Add comment")).toBeDisabled();
    const submit = screen.getByTestId("task-comments-submit");
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(props.onSubmit).not.toHaveBeenCalled();
  });

  it("shows a pending row marked as sending", () => {
    const pending: TaskCommentPending[] = [
      { localId: "local-1", body: "Not yet saved", status: "pending" },
    ];
    renderComments({ comments: [comment()], pending });

    const row = screen.getByTestId("task-comment-pending-local-1");
    expect(within(row).getByText("Not yet saved")).toBeInTheDocument();
    expect(within(row).getByText("Sending…")).toBeInTheDocument();
    expect(row.querySelector("time")).toBeNull();
  });

  it("keeps a failed row visible with its text and retries under the same localId", async () => {
    const user = userEvent.setup();
    const pending: TaskCommentPending[] = [
      { localId: "local-9", body: "Failed body", status: "failed", message: "Network was unreachable." },
    ];
    const props = renderComments({ pending });

    const row = screen.getByTestId("task-comment-pending-local-9");
    expect(within(row).getByText("Failed body")).toBeInTheDocument();
    expect(within(row).getByText("Network was unreachable.")).toBeInTheDocument();

    await user.click(within(row).getByRole("button", { name: "Retry" }));
    expect(props.onRetry).toHaveBeenCalledTimes(1);
    expect(props.onRetry).toHaveBeenCalledWith("local-9");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("falls back to concise failure copy when no message is supplied", () => {
    renderComments({ pending: [{ localId: "local-3", body: "b", status: "failed" }] });
    expect(screen.getByText("Comment not sent.")).toBeInTheDocument();
  });

  it("offers Load more only when there is more, and calls onLoadMore", async () => {
    const user = userEvent.setup();
    renderComments({ comments: [comment()] });
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();

    cleanup();
    const props = renderComments({ comments: [comment()], hasMore: true });
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(props.onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("offers no edit, delete, or remove affordance", () => {
    renderComments({
      comments: [comment(), comment({ comment_id: "cmt-2", body: "Second", author_kind: "assistant" })],
      pending: [{ localId: "local-1", body: "p", status: "failed", message: "nope" }],
      hasMore: true,
    });
    expect(screen.queryAllByRole("button", { name: /edit|delete|remove/i })).toHaveLength(0);
  });

  it("does not autofocus the composer", () => {
    renderComments();
    expect(screen.getByLabelText("Add comment")).not.toHaveFocus();
    expect(document.activeElement).toBe(document.body);
  });

  it("never performs a network call across a full interaction pass", async () => {
    const user = userEvent.setup();
    renderComments({
      comments: [comment()],
      pending: [{ localId: "local-1", body: "p", status: "failed" }],
      hasMore: true,
      onRetryLoad: vi.fn(),
    });

    await user.type(screen.getByLabelText("Add comment"), "hello");
    await user.click(screen.getByTestId("task-comments-submit"));
    await user.click(screen.getByRole("button", { name: "Load more" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
