"use client";

/**
 * Compact Task comment thread (WP-TUX-03).
 *
 * Comments are append-only human activity. They are not the Task description,
 * not system history, not evidence, and not a transport log. Nothing here
 * fetches, mints an idempotency key, schedules a retry, or reorders the
 * thread: the caller owns the transport and hands this component exactly the
 * rows it should render, in the order the contract returned them.
 *
 * The contract has no edit and no delete, so this component offers neither.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import type { TaskComment, TaskCommentAuthorKind } from "@/contracts/work";

/** Frozen copy for the states this thread can be in. */
const LOADING_COPY = "Loading comments…";
const UNAVAILABLE_COPY = "Comments unavailable right now.";
const EMPTY_COPY = "No comments yet.";
const SENDING_COPY = "Sending…";
const FAILED_FALLBACK_COPY = "Comment not sent.";
const COMPOSER_LABEL = "Add comment";

/**
 * Author labels derive from `author_kind` alone. A person's name is never
 * fabricated, and `author_id` is an opaque identifier that is never shown.
 */
const AUTHOR_LABELS: Record<TaskCommentAuthorKind, string> = {
  principal: "You",
  assistant: "Assistant",
  system: "System",
};

/** Localized rendering of an ISO instant; the raw ISO stays in `dateTime`. */
function formatCreatedAt(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString();
}

export interface TaskCommentCountProps {
  count: number;
  onOpen?(): void;
  disabled?: boolean;
}

/** Compact affordance: "Add comment" when none, otherwise "1 comment" / "N comments". */
export function TaskCommentCount({
  count,
  onOpen,
  disabled = false,
}: TaskCommentCountProps): React.JSX.Element {
  const label =
    count <= 0 ? COMPOSER_LABEL : count === 1 ? "1 comment" : `${count} comments`;

  return (
    <Button
      variant="ghost"
      size="sm"
      className="min-h-11"
      disabled={disabled}
      onClick={onOpen}
      data-testid="task-comment-count"
    >
      {label}
    </Button>
  );
}

export type TaskCommentPendingStatus = "pending" | "failed";

export interface TaskCommentPending {
  readonly localId: string;
  readonly body: string;
  readonly status: TaskCommentPendingStatus;
  /** Concise failure copy when status is "failed". */
  readonly message?: string;
}

export interface TaskCommentsProps {
  comments: readonly TaskComment[];
  pending?: readonly TaskCommentPending[];
  loading?: boolean;
  unavailable?: boolean;
  hasMore?: boolean;
  loadingMore?: boolean;
  /** True until a canonical current Task snapshot is held. */
  disabled?: boolean;
  submitting?: boolean;
  onSubmit(body: string): void;
  onRetry(localId: string): void;
  onLoadMore(): void;
  onRetryLoad?(): void;
}

export function TaskComments({
  comments,
  pending = [],
  loading = false,
  unavailable = false,
  hasMore = false,
  loadingMore = false,
  disabled = false,
  submitting = false,
  onSubmit,
  onRetry,
  onLoadMore,
  onRetryLoad,
}: TaskCommentsProps): React.JSX.Element {
  const [draft, setDraft] = useState("");
  const trimmed = draft.trim();
  const canSubmit = trimmed.length > 0 && !disabled && !submitting;

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit(trimmed);
    setDraft("");
  }

  const composer = (
    <form className="flex flex-col gap-2" onSubmit={handleSubmit}>
      <TextField
        label={COMPOSER_LABEL}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
      />
      <div>
        <Button
          type="submit"
          className="min-h-11"
          disabled={!canSubmit}
          pending={submitting}
          data-testid="task-comments-submit"
        >
          {COMPOSER_LABEL}
        </Button>
      </div>
    </form>
  );

  let body: React.JSX.Element;

  if (loading) {
    body = <p className="text-sm text-muted">{LOADING_COPY}</p>;
  } else if (unavailable) {
    body = (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted">{UNAVAILABLE_COPY}</p>
        {onRetryLoad ? (
          <div>
            <Button
              variant="secondary"
              className="min-h-11"
              onClick={onRetryLoad}
              data-testid="task-comments-retry-load"
            >
              Retry
            </Button>
          </div>
        ) : null}
      </div>
    );
  } else if (comments.length === 0 && pending.length === 0) {
    body = (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">{EMPTY_COPY}</p>
        {composer}
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col gap-3">
        <ol className="flex flex-col gap-3" data-testid="task-comments-thread">
          {comments.map((comment) => (
            <li key={comment.comment_id} className="flex flex-col gap-1">
              <p className="text-xs text-muted">
                <span>{AUTHOR_LABELS[comment.author_kind]}</span>{" "}
                <time dateTime={comment.created_at}>{formatCreatedAt(comment.created_at)}</time>
              </p>
              <p className="text-sm whitespace-pre-wrap text-text-primary">{comment.body}</p>
            </li>
          ))}
          {pending.map((row) => (
            <li
              key={row.localId}
              className="flex flex-col gap-1 opacity-80"
              data-testid={`task-comment-pending-${row.localId}`}
              data-status={row.status}
            >
              <p className="text-xs text-muted">
                <span>{AUTHOR_LABELS.principal}</span>{" "}
                <span>{row.status === "failed" ? "Not sent" : SENDING_COPY}</span>
              </p>
              <p className="text-sm whitespace-pre-wrap text-text-primary">{row.body}</p>
              {row.status === "failed" ? (
                <div className="flex flex-col gap-1">
                  <p className="text-xs text-destructive">{row.message ?? FAILED_FALLBACK_COPY}</p>
                  <div>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="min-h-11"
                      onClick={() => onRetry(row.localId)}
                    >
                      Retry
                    </Button>
                  </div>
                </div>
              ) : null}
            </li>
          ))}
        </ol>

        {hasMore ? (
          <div>
            <Button
              variant="secondary"
              className="min-h-11"
              pending={loadingMore}
              onClick={onLoadMore}
              data-testid="task-comments-load-more"
            >
              Load more
            </Button>
          </div>
        ) : null}

        {composer}
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3" data-testid="task-comments">
      <h3 className="text-sm font-medium text-text-primary">Comments</h3>
      {body}
    </section>
  );
}
