"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SurfaceState } from "@/components/ui/surface-state";
import { TaskCompactSheet } from "@/components/tasks/task-compact-sheet";

import {
  admittedEnrollmentId,
  fetchFederatedSearch,
  type FederatedSearchResponse,
} from "@/lib/search/client";
import {
  federatedZeroHitKind,
  presentFederatedHits,
  type PresentedGroup,
  type PresentedTaskActivation,
  type SearchCoverage,
} from "@/lib/search/presentation";
import type { ApiFailure } from "@/lib/api/work-client";

type SearchAnswer =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly result: FederatedSearchResponse }
  | { readonly kind: "not_implemented"; readonly message: string }
  | { readonly kind: "unavailable"; readonly message: string };

function isAbort(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

function classifyFailure(error: unknown): SearchAnswer {
  const failure = error as ApiFailure;
  if (failure.status === 501 || failure.code === "not_implemented") {
    return {
      kind: "not_implemented",
      message:
        failure.message ||
        "Search is not available in this build.",
    };
  }
  return {
    kind: "unavailable",
    message: failure.message || "Search could not be read.",
  };
}

function heldEnrollment(explicit?: string): string | undefined {
  const fromProp = admittedEnrollmentId(explicit);
  if (fromProp) return fromProp;
  if (typeof window === "undefined") return undefined;
  return admittedEnrollmentId(new URLSearchParams(window.location.search).get("enrollmentId"));
}

export function SearchCommandPanel({
  onCapture,
  onDismiss,
  autoFocus = false,
  initialQuery = "",
  enrollmentId,
}: {
  onCapture: () => void;
  onDismiss?: () => void;
  autoFocus?: boolean;
  initialQuery?: string;
  enrollmentId?: string;
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  /**
   * Focus contract for the in-place Task sheet. The element that opened the
   * sheet is held so closing can hand focus back to it; the index is held as the
   * fallback address for when a refresh has removed that exact row.
   */
  const taskTrigger = useRef<HTMLElement | null>(null);
  const taskTriggerIndex = useRef(0);
  const inputId = useId();
  const listId = useId();
  const [query, setQuery] = useState(initialQuery);
  const [fetched, setFetched] = useState<SearchAnswer>(
    initialQuery.trim() ? { kind: "loading" } : { kind: "idle" },
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const [activeTask, setActiveTask] = useState<PresentedTaskActivation | null>(null);
  const enrollment = heldEnrollment(enrollmentId);
  const trimmed = query.trim();
  const idle = trimmed.length === 0;
  const answer = useMemo<SearchAnswer>(
    () => (idle ? { kind: "idle" } : fetched),
    [idle, fetched],
  );

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    if (!onDismiss) return;
    const node = inputRef.current;
    if (!node) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Capture-phase so Chromium cannot clear type=search before we dismiss.
      event.preventDefault();
      onDismiss();
    };
    node.addEventListener("keydown", closeOnEscape, true);
    return () => node.removeEventListener("keydown", closeOnEscape, true);
  }, [onDismiss]);

  useEffect(() => {
    if (idle) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setFetched({ kind: "loading" });
      void fetchFederatedSearch(trimmed, { enrollmentId: enrollment, signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted) setFetched({ kind: "ready", result });
        })
        .catch((error: unknown) => {
          if (isAbort(error) || controller.signal.aborted) return;
          setFetched(classifyFailure(error));
        });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, idle, enrollment]);

  const groups = useMemo<readonly PresentedGroup[]>(() => {
    if (answer.kind !== "ready") return [];
    return presentFederatedHits(answer.result.hits, enrollment);
  }, [answer, enrollment]);

  const activatable = useMemo(() => {
    if (idle) {
      return [];
    }
    return [
      // The last point at which the domain of a hit is still known. Everything
      // downstream is kind-blind, so a Task must declare itself here or not at all.
      ...groups.flatMap((group) =>
        group.hits
          .filter((hit) => hit.href)
          .map((hit) =>
            group.domain === "tasks" && hit.task
              ? {
                  kind: "task" as const,
                  href: hit.href as string,
                  label: hit.label,
                  task: hit.task,
                }
              : { kind: "href" as const, href: hit.href as string, label: hit.label },
          ),
      ),
      { kind: "capture" as const, label: "Quick Capture" },
    ];
  }, [idle, groups]);

  const hitOptionIndex = useMemo(() => {
    const indices = new Map<string, number>();
    let index = 0;
    for (const group of groups) {
      for (const hit of group.hits) {
        if (!hit.href) continue;
        indices.set(hit.key, index);
        index += 1;
      }
    }
    return { indices, captureIndex: index };
  }, [groups]);

  const boundedIndex =
    activatable.length === 0 ? 0 : ((activeIndex % activatable.length) + activatable.length) % activatable.length;

  function go(href: string) {
    router.push(href);
    onDismiss?.();
  }

  function capture() {
    onDismiss?.();
    onCapture();
  }

  /** Result rows currently in the document, in the same order as `activatable`. */
  const resultElements = useCallback((): readonly HTMLElement[] => {
    const list = listRef.current;
    if (!list) return [];
    return Array.from(list.querySelectorAll<HTMLElement>('[data-search-result="true"]'));
  }, []);

  const openTask = useCallback(
    (task: PresentedTaskActivation, index: number, trigger: HTMLElement | null) => {
      taskTrigger.current = trigger ?? resultElements()[index] ?? null;
      taskTriggerIndex.current = index;
      setActiveTask(task);
    },
    [resultElements],
  );

  /**
   * Closing the sheet returns focus to the result that opened it. If a refresh
   * removed that row, fall back to the next result at the same position, then to
   * the previous result, then to the query field. Focus is never left on the body.
   */
  const closeTask = useCallback(() => {
    setActiveTask(null);
    requestAnimationFrame(() => {
      const trigger = taskTrigger.current;
      const index = taskTriggerIndex.current;
      taskTrigger.current = null;
      if (trigger && trigger.isConnected) {
        trigger.focus();
        return;
      }
      const results = resultElements();
      const fallback = results[index] ?? results[index - 1] ?? inputRef.current;
      fallback?.focus();
    });
  }, [resultElements]);

  function activate(index: number, event?: ReactMouseEvent<HTMLElement>) {
    const item = activatable[index];
    if (!item) return;
    if (item.kind === "capture") {
      capture();
      return;
    }
    if (item.kind === "task") {
      // The row stays a real link — role=link with the Task title as its
      // accessible name — and its navigation is intercepted, not removed.
      event?.preventDefault();
      const trigger = (event?.currentTarget as HTMLElement | undefined) ?? null;
      openTask(item.task, index, trigger);
      return;
    }
    go(item.href);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape" && onDismiss) {
      // Chromium clears a non-empty type=search field on Escape and does not
      // fire the native <dialog> cancel. Close Search instead of clearing.
      event.preventDefault();
      onDismiss();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % Math.max(activatable.length, 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex(
        (current) =>
          (current - 1 + Math.max(activatable.length, 1)) % Math.max(activatable.length, 1),
      );
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      activate(boundedIndex);
    }
  }

  function optionProps(index: number, extraClass = "") {
    return {
      id: `${listId}-opt-${index}`,
      "data-active": boundedIndex === index ? "true" : undefined,
      className: `flex min-h-11 w-full items-center rounded px-3 text-left ${
        boundedIndex === index ? "bg-interactive-subtle" : "hover:bg-surface-subtle"
      } ${extraClass}`.trim(),
      onMouseEnter: () => setActiveIndex(index),
      onClick: (event: ReactMouseEvent<HTMLElement>) => activate(index, event),
    };
  }

  return (
    <div>
      <p className="mb-3 text-sm text-text-secondary">
        Search tasks, people, notes, and reports.
      </p>
      <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-text-primary">
        Search
      </label>
      <Input
        ref={inputRef}
        id={inputId}
        type="search"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActiveIndex(0);
        }}
        onKeyDown={onKeyDown}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        aria-controls={listId}
        aria-describedby={`${inputId}-hint`}
        data-testid="search-command-input"
        placeholder="Search my-pa"
      />
      <p id={`${inputId}-hint`} className="mt-1 text-xs text-muted">
        Type to search. Destinations are in navigation.
      </p>
      <div
        ref={listRef}
        id={listId}
        data-testid="search-command-list"
        aria-busy={answer.kind === "loading" || undefined}
        className="mt-3 max-h-80 space-y-1 overflow-y-auto"
      >
        {idle ? (
          <p className="px-3 py-2 text-sm text-muted">Start typing to search.</p>
        ) : null}
        {answer.kind === "loading" ? (
          <p role="status" className="px-3 py-2 text-sm text-muted">
            Searching…
          </p>
        ) : null}
        {answer.kind === "not_implemented" ? (
          <SurfaceState
            kind="not_implemented"
            title="Search is not available in this build"
            detail={answer.message}
            testId="search-not-implemented"
          />
        ) : null}
        {answer.kind === "unavailable" ||
        (answer.kind === "ready" &&
          federatedZeroHitKind(answer.result.coverage, answer.result.hits.length) === "unavailable") ? (
          <SurfaceState
            kind="unavailable"
            title="Search could not be read"
            error={answer.kind === "unavailable" ? answer.message : undefined}
            detail={
              answer.kind === "unavailable"
                ? undefined
                : "No domain could be searched. That is not a fact about what you hold."
            }
            testId="search-unavailable"
          />
        ) : null}
        {answer.kind === "ready" &&
        federatedZeroHitKind(answer.result.coverage, answer.result.hits.length) === "empty" &&
        groups.length === 0 ? (
          <SurfaceState
            kind="empty"
            title="No matches in the domains that were searched"
            detail="Omitted and unavailable sources are listed below."
            testId="search-empty"
          />
        ) : null}
        {answer.kind === "ready" &&
        federatedZeroHitKind(answer.result.coverage, answer.result.hits.length) !== "unavailable"
          ? groups.map((group) => (
              <section
                key={group.domain}
                data-testid={`search-group-${group.domain}`}
                className="mb-3"
              >
                <h3 className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
                  {group.heading}
                </h3>
                <ul className="space-y-1">
                  {group.hits.map((hit) => (
                    <li key={hit.key}>
                      {hit.href ? (
                        <Link
                          href={hit.href}
                          data-search-result="true"
                          data-result-key={hit.key}
                          {...optionProps(hitOptionIndex.indices.get(hit.key) ?? 0)}
                        >
                          <span className="flex min-w-0 flex-1 flex-col items-start py-1">
                            <span className="flex w-full items-center justify-between gap-2">
                              <span>{hit.label}</span>
                              {group.domain === "knowledge" && hit.rank ? (
                                <Badge tone="neutral">{hit.rank}</Badge>
                              ) : null}
                            </span>
                            {hit.detail ? (
                              <span className="text-xs text-muted">{hit.detail}</span>
                            ) : null}
                          </span>
                        </Link>
                      ) : (
                        <div
                          data-testid={`search-hit-${group.domain}-static`}
                          className="rounded px-3 py-2"
                        >
                          <p className="text-sm">{hit.label}</p>
                          {group.domain === "knowledge" && hit.rank ? (
                            <Badge tone="neutral">{hit.rank}</Badge>
                          ) : null}
                          {hit.detail ? <p className="text-xs text-muted">{hit.detail}</p> : null}
                          <p className="mt-1 text-xs text-muted">
                            No truthful address is available for this hit.
                          </p>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ))
          : null}
        {!idle ? (
          <button type="button" {...optionProps(hitOptionIndex.captureIndex, "font-medium text-interactive")}>
            Quick Capture
          </button>
        ) : null}
        {answer.kind === "ready" ? <CoverageList coverage={answer.result.coverage} /> : null}
      </div>
      {activeTask ? (
        <TaskCompactSheet
          taskId={activeTask.taskId}
          open
          onOpenChange={(open) => {
            if (!open) closeTask();
          }}
          seed={activeTask.seed}
        />
      ) : null}
    </div>
  );
}

function CoverageList({ coverage }: { coverage: readonly SearchCoverage[] }) {
  return (
    <ul data-testid="search-coverage" className="mt-3 space-y-1 border-t pt-3 text-xs text-muted">
      {coverage.map((row) => (
        <li
          key={`${row.domain}:${row.state}:${row.reason ?? ""}`}
          data-domain={row.domain}
          data-coverage-state={row.state}
        >
          {row.domain}: {row.state}
          {row.reason ? ` (${row.reason})` : ""}
          {row.hitCount > 0 ? ` · ${row.hitCount}` : ""}
        </li>
      ))}
    </ul>
  );
}

export function CommandPalette({
  open,
  onOpenChange,
  onCapture,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCapture: () => void;
}) {
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpenChange, open]);

  return (
    <Dialog open={open} onClose={() => onOpenChange(false)} title="Search">
      {open ? (
        <SearchCommandPanel
          autoFocus
          onCapture={onCapture}
          onDismiss={() => onOpenChange(false)}
        />
      ) : null}
    </Dialog>
  );
}
