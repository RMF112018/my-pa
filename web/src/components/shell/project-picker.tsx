"use client";

/**
 * The visible Project Picker (Phase 3, `PC-CM-SCOPE-AC-002/007/008/009`).
 *
 * A native `<select>`, the same established pattern
 * `capture-project-selector.tsx` uses for a Project-choosing control: fully
 * keyboard-operable for free, and its closed/collapsed state shows the
 * selected `<option>`'s own text — which is how this component satisfies
 * "collapsed value shows the exact current scope value" without inventing a
 * custom listbox. The accessible name is the fixed string `"Project Picker"`,
 * via `aria-label`.
 *
 * **The displayed value is always the committed scope, never an optimistic
 * one.** The `<select>` is controlled by `useProjectScope().resolution` —
 * never by a locally-held "the user just clicked this" value — so there is no
 * intermediate render where the collapsed value could show a name that
 * conflicts with what is actually applied. A refused or failed switch simply
 * leaves `resolution` (and therefore the rendered value) untouched.
 *
 * **Paging** reuses `GET /api/projects?after=<cursor>` exactly as it is,
 * fixed at the route's own page size; this component sends only `after`.
 * `All Projects` is not part of that paged list — it is always synthesized
 * as the first option, so it is never degraded-state-only.
 *
 * **The scope-change barrier.** The real barrier (an in-flight Constraint
 * mutation, or unsaved authored state) lives in a mutation-coordinator that
 * does not exist yet (Phase 4, a different worker). This component accepts
 * an injected `canSwitchScope` — `() => boolean | Promise<boolean>` — and
 * calls it before ever sending the write; `false` refuses the switch with no
 * request sent and no scope/route change. It defaults to always-allowed, so
 * Phase 4 can pass the real check later without this component changing.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { apiGet, apiPost } from "@/lib/api/client";
import { isProjectId } from "@/lib/project-scope/scope";
import type { CanonicalProjectState } from "@/lib/project-scope/resolver";
import {
  projectScopeLabel,
  useProjectScope,
} from "@/components/shell/project-scope-provider";
import { constraintsRoute } from "@/app/(app)/work/projects/[projectId]/constraints/constraint-url-state";

export const PROJECT_PICKER_LABEL = "Project Picker";
export const PROJECT_PICKER_PAGE_SIZE = 25;
export const PROJECT_PICKER_MAX_VISITED_CURSORS = 100;
export const PROJECT_PICKER_ALL_VALUE = "ALL_PROJECTS";
export const PROJECT_PICKER_ALL_LABEL = "All Projects";
export const PROJECT_PICKER_UNAVAILABLE =
  "Could not switch Projects — your current selection is unchanged.";
export const PROJECT_PICKER_PAGE_BOUND =
  "No more Project pages can be loaded here. Your selection is unchanged.";
export const PROJECT_PICKER_BLOCKED =
  "Finish or discard what you're doing before switching Projects.";

/** The canonical Project-neutral destination a scope change to All Projects lands on. */
const ALL_PROJECTS_ROUTE = "/work";

/**
 * The additive integration seam for Phase 4's scope-change barrier.
 *
 * `true` (or a Promise resolving `true`) allows the switch; anything else
 * refuses it before any request is sent. Defaults to always-allowed.
 */
export type CanSwitchProjectScope = () => boolean | Promise<boolean>;

const ALWAYS_ALLOWED: CanSwitchProjectScope = () => true;

interface ProjectOption {
  readonly projectId: string;
  readonly name: string;
}

interface ProjectsPage {
  readonly projects?: readonly { readonly projectId?: unknown; readonly name?: unknown }[];
  readonly nextCursor?: unknown;
}

interface ProjectScopeWriteResponse {
  readonly scope?: unknown;
  readonly project?: {
    readonly id?: unknown;
    readonly name?: unknown;
    readonly state?: unknown;
    readonly version?: unknown;
  };
}

function readOptions(body: ProjectsPage | undefined): readonly ProjectOption[] {
  if (!body || !Array.isArray(body.projects)) return [];
  const options: ProjectOption[] = [];
  for (const row of body.projects) {
    if (isProjectId(row?.projectId) && typeof row?.name === "string" && row.name.length > 0) {
      options.push({ projectId: row.projectId, name: row.name });
    }
  }
  return options;
}

const PROJECT_STATES: readonly CanonicalProjectState[] = ["active", "on_hold", "closed"];

function isCanonicalProjectState(value: unknown): value is CanonicalProjectState {
  return typeof value === "string" && (PROJECT_STATES as readonly string[]).includes(value);
}

/** The `POST /api/project-scope` success body, decoded into a resolution the provider accepts. */
function acceptedResolution(body: ProjectScopeWriteResponse | null):
  | { readonly kind: "all" }
  | { readonly kind: "project"; readonly id: string; readonly name: string; readonly state: CanonicalProjectState; readonly version: number }
  | { readonly kind: "invalid" } {
  if (!body) return { kind: "invalid" };
  if (body.scope === "ALL_PROJECTS") return { kind: "all" };
  if (body.scope !== "PROJECT") return { kind: "invalid" };
  const project = body.project;
  if (
    !isProjectId(project?.id) ||
    typeof project?.name !== "string" ||
    !isCanonicalProjectState(project.state) ||
    typeof project.version !== "number" ||
    !Number.isSafeInteger(project.version)
  ) {
    return { kind: "invalid" };
  }
  return { kind: "project", id: project.id, name: project.name, state: project.state, version: project.version };
}

export function ProjectPicker({
  canSwitchScope = ALWAYS_ALLOWED,
}: {
  readonly canSwitchScope?: CanSwitchProjectScope;
}) {
  const router = useRouter();
  const { resolution, applyResolution } = useProjectScope();
  const [options, setOptions] = useState<readonly ProjectOption[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<readonly (string | null)[]>([null]);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const cursor = cursorStack[cursorStack.length - 1] ?? null;

  useEffect(() => {
    let cancelled = false;
    const path =
      cursor === null
        ? "/api/projects"
        : `/api/projects?after=${encodeURIComponent(cursor)}`;
    void (async () => {
      let result: Awaited<ReturnType<typeof apiGet<ProjectsPage>>>;
      try {
        result = await apiGet<ProjectsPage>({ hasSession: true }, path);
      } catch {
        if (!cancelled) setNotice(PROJECT_PICKER_UNAVAILABLE);
        return;
      }
      if (cancelled) return;
      if (!result.ok || !result.data) {
        setNotice(PROJECT_PICKER_UNAVAILABLE);
        return;
      }
      setOptions(readOptions(result.data));
      setNextCursor(typeof result.data.nextCursor === "string" ? result.data.nextCursor : null);
      setNotice(null);
    })();
    return () => {
      cancelled = true;
    };
  }, [cursor]);

  const currentProjectId = resolution.scope.kind === "PROJECT" ? resolution.scope.projectId : null;
  const currentValue = currentProjectId ?? PROJECT_PICKER_ALL_VALUE;
  // The current selection is always offerable, even off the loaded page, so
  // paging can never make the collapsed value disagree with the option list.
  const onPage = currentProjectId !== null && options.some((o) => o.projectId === currentProjectId);
  const offered =
    currentProjectId !== null && !onPage
      ? [{ projectId: currentProjectId, name: projectScopeLabel(resolution) }, ...options]
      : options;

  function goNext() {
    if (nextCursor === null) return;
    if (cursorStack.length >= PROJECT_PICKER_MAX_VISITED_CURSORS) {
      setNotice(PROJECT_PICKER_PAGE_BOUND);
      return;
    }
    setNotice(null);
    setCursorStack((stack) => [...stack, nextCursor]);
  }

  function goPrevious() {
    setNotice(null);
    setCursorStack((stack) => (stack.length > 1 ? stack.slice(0, -1) : stack));
  }

  async function handleSelect(nextValue: string) {
    if (nextValue === currentValue || pending) return;
    const invoker = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const allowed = await Promise.resolve(canSwitchScope());
    if (!allowed) {
      setNotice(PROJECT_PICKER_BLOCKED);
      invoker?.focus();
      return;
    }

    setNotice(null);
    setPending(true);
    const body =
      nextValue === PROJECT_PICKER_ALL_VALUE
        ? { scope: "ALL_PROJECTS" as const }
        : { scope: "PROJECT" as const, projectId: nextValue };

    let result: Awaited<ReturnType<typeof apiPost<ProjectScopeWriteResponse>>>;
    try {
      result = await apiPost<ProjectScopeWriteResponse>(
        { hasSession: true },
        "/api/project-scope",
        body,
      );
    } catch {
      setPending(false);
      setNotice(PROJECT_PICKER_UNAVAILABLE);
      invoker?.focus();
      return;
    }
    setPending(false);
    if (!result.ok) {
      setNotice(PROJECT_PICKER_UNAVAILABLE);
      invoker?.focus();
      return;
    }

    const accepted = acceptedResolution(result.data);
    if (accepted.kind === "invalid") {
      setNotice(PROJECT_PICKER_UNAVAILABLE);
      invoker?.focus();
      return;
    }

    if (accepted.kind === "all") {
      applyResolution({
        scope: { kind: "ALL_PROJECTS" },
        source: "preference",
        project: null,
        normalized: false,
      });
      router.push(ALL_PROJECTS_ROUTE);
      return;
    }

    applyResolution({
      scope: { kind: "PROJECT", projectId: accepted.id },
      source: "preference",
      project: {
        project_id: accepted.id,
        name: accepted.name,
        state: accepted.state,
        version: accepted.version,
      },
      normalized: false,
    });
    router.push(constraintsRoute(accepted.id));
  }

  return (
    <div className="flex items-center gap-2" data-testid="project-picker">
      <Select
        aria-label={PROJECT_PICKER_LABEL}
        value={currentValue}
        disabled={pending}
        data-testid="project-picker-select"
        onChange={(event) => void handleSelect(event.target.value)}
      >
        <option value={PROJECT_PICKER_ALL_VALUE}>{PROJECT_PICKER_ALL_LABEL}</option>
        {offered.map((option) => (
          <option key={option.projectId} value={option.projectId}>
            {option.name}
          </option>
        ))}
      </Select>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={pending || cursorStack.length <= 1}
        data-testid="project-picker-previous"
        onClick={goPrevious}
      >
        Previous
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={pending || nextCursor === null}
        data-testid="project-picker-next"
        onClick={goNext}
      >
        Next
      </Button>
      {notice ? (
        <p role="status" data-testid="project-picker-notice" className="text-xs text-muted">
          {notice}
        </p>
      ) : null}
    </div>
  );
}
