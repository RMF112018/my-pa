"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SurfaceState } from "@/components/ui/surface-state";
import { DESTINATIONS, UTILITY_DESTINATIONS } from "@/components/shell/destinations";
import {
  admittedEnrollmentId,
  fetchFederatedSearch,
  type FederatedSearchResponse,
} from "@/lib/search/client";
import { presentFederatedHits, type PresentedGroup, type SearchCoverage } from "@/lib/search/presentation";
import type { ApiFailure } from "@/lib/api/work-client";

const COMMANDS = [...DESTINATIONS, ...UTILITY_DESTINATIONS];

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
        "The synthetic provider has no federated search fixture. Federated search requires the executable Python search capabilities.",
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
  const inputId = useId();
  const listId = useId();
  const [query, setQuery] = useState(initialQuery);
  const [fetched, setFetched] = useState<SearchAnswer>(
    initialQuery.trim() ? { kind: "loading" } : { kind: "idle" },
  );
  const [activeIndex, setActiveIndex] = useState(0);
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
      return [
        ...COMMANDS.map((item) => ({ kind: "href" as const, href: item.href, label: item.label })),
        { kind: "capture" as const, label: "Quick Capture" },
      ];
    }
    return [
      ...groups.flatMap((group) =>
        group.hits
          .filter((hit) => hit.href)
          .map((hit) => ({ kind: "href" as const, href: hit.href as string, label: hit.label })),
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

  function activate(index: number) {
    const item = activatable[index];
    if (!item) return;
    if (item.kind === "capture") capture();
    else go(item.href);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
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
      onClick: () => activate(index),
    };
  }

  return (
    <div>
      <p className="mb-3 text-sm text-text-secondary">
        Type to search Work, Capture, Intelligence, People, and Knowledge. An empty query lists
        destinations and Quick Capture. Coverage tokens stay visible when a domain was omitted or
        unavailable.
      </p>
      <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-moss-slate">
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
        placeholder="Search or jump to a destination"
      />
      <p id={`${inputId}-hint`} className="mt-1 text-xs text-muted">
        Results keep each domain&rsquo;s upstream order. Knowledge rank is shown only inside
        Knowledge.
      </p>
      <div
        id={listId}
        data-testid="search-command-list"
        aria-busy={answer.kind === "loading" || undefined}
        className="mt-3 max-h-80 space-y-1 overflow-y-auto"
      >
        {idle ? (
          <ul className="space-y-1">
            {COMMANDS.map((item, index) => (
              <li key={item.href}>
                <button type="button" {...optionProps(index)}>
                  {item.label}
                </button>
              </li>
            ))}
            <li>
              <button type="button" {...optionProps(COMMANDS.length, "font-medium text-interactive")}>
                Quick Capture
              </button>
            </li>
          </ul>
        ) : null}
        {answer.kind === "loading" ? (
          <p role="status" className="px-3 py-2 text-sm text-muted">
            Searching…
          </p>
        ) : null}
        {answer.kind === "not_implemented" ? (
          <SurfaceState
            kind="not_implemented"
            title="Federated search is not in this build"
            detail={answer.message}
            testId="search-not-implemented"
          />
        ) : null}
        {answer.kind === "unavailable" ? (
          <SurfaceState
            kind="unavailable"
            title="Search could not be read"
            detail={answer.message}
            testId="search-unavailable"
          />
        ) : null}
        {answer.kind === "ready" && groups.length === 0 ? (
          <SurfaceState
            kind="empty"
            title="No matches in the domains that were searched"
            detail="That is a fact about this query, not a missing search. Omitted and unavailable domains are listed below."
            testId="search-empty"
          />
        ) : null}
        {answer.kind === "ready"
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
                        <Link href={hit.href} {...optionProps(hitOptionIndex.indices.get(hit.key) ?? 0)}>
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
    <Dialog open={open} onClose={() => onOpenChange(false)} title="Command menu">
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
