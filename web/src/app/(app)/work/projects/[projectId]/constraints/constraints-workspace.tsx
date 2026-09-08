"use client";

/**
 * The Constraint workspace: Project context, two tabs, and one Inspector.
 *
 * **The URL is the state, not a mirror of it.** View state is read from
 * `useSearchParams()` on every render and written back through the router, so
 * Back genuinely returns to the previous meaningful view and a link genuinely
 * reproduces one. Nothing durable is held in a second place that could drift
 * from the address bar. High-frequency updates — typing in the search box —
 * replace rather than push, because a history entry per keystroke makes Back
 * useless; tab, KPI and selection transitions push, because those are the
 * steps a reader expects to walk back through (`02` §13).
 *
 * **Detail is read lazily, after selection.** A Register row carries list-level
 * identity and that is what appears the instant a row is picked; the canonical
 * record is read for the selected Constraint alone. History and evidence are
 * read with it and for nothing else, which is what keeps a fifty-row page from
 * being fifty detail reads (`CM-FE-AC-092`).
 *
 * **Selection is published to the shell's Inspector, and the shell renders it.**
 * `useInspectorContent` hands `UtilityRegion` a body for the `constraint`
 * selection kind; there is no second drawer in this feature and no overlay of
 * its own. Closing detail removes only the `constraint` parameter and returns
 * focus to the row that opened it.
 */
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { PageHeader } from "@/components/shell/page-header";
import { LiveAnnouncement } from "@/components/ui/live-region";
import { useInspectorContent, useInspectorSelection } from "@/components/shell/inspector-selection";
import type {
  ConstraintHistoryEntry,
  ConstraintListEntry,
  ConstraintView,
} from "@/contracts/constraints";
import type { ConstraintWorkspaceFixture, ConstraintFixtureProject } from "@/lib/fixtures/constraints";
import {
  categoryRegisterState,
  constraintsHref,
  constraintsRoute,
  kpiRegisterState,
  parseConstraintUrlSearchParams,
  projectSwitchState,
  serializeConstraintUrlState,
  type ConstraintKpiTarget,
  type ConstraintUrlState,
} from "./constraint-url-state";
import { ConstraintsOverview } from "./constraints-overview";
import { ConstraintsRegister } from "./constraints-register";
import { ConstraintInspector, inspectorTitle, type ConstraintLifecycleAction } from "./constraint-inspector";
import { CategoryPanel, ConstraintFormDialog, LifecycleDialog } from "./constraint-lifecycle";
import { rowTriggerId } from "./register-table";
import { useConstraintViewport } from "./use-viewport";

export interface ConstraintsWorkspaceProps {
  readonly workspace: ConstraintWorkspaceFixture;
  readonly projects: readonly ConstraintFixtureProject[];
  readonly initialState: ConstraintUrlState;
}

function ConstraintsWorkspaceInner({
  workspace,
  projects,
  initialState,
}: ConstraintsWorkspaceProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const viewport = useConstraintViewport();
  const { setSelection, shellSelection } = useInspectorSelection();

  const state = useMemo(
    () => (searchParams === null ? initialState : parseConstraintUrlSearchParams(searchParams)),
    [searchParams, initialState],
  );

  const projectId = workspace.project.projectId;
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState<false | "create" | "edit">(false);
  const [lifecycleAction, setLifecycleAction] = useState<ConstraintLifecycleAction | null>(null);
  const [categoriesOpen, setCategoriesOpen] = useState(false);
  const registerHeadingEl = useRef<HTMLHeadingElement | null>(null);
  const pendingRegisterFocus = useRef(false);

  /**
   * Move focus onto the Register once every commit has settled.
   *
   * On a macrotask deliberately: the panel the reader came from unmounts a
   * commit after the one that mounts the Register, and an unmount that removes
   * the focused element resets focus to the body. Focusing before that would be
   * silently undone.
   */
  const focusRegisterSoon = useCallback(() => {
    window.setTimeout(() => {
      if (!pendingRegisterFocus.current) return;
      const heading = registerHeadingEl.current;
      if (heading === null) return;
      pendingRegisterFocus.current = false;
      heading.focus();
    }, 0);
  }, []);

  /**
   * A callback ref rather than an effect, because the tab panel is mounted by
   * Radix's own state and that mount does not re-render this component: an
   * effect here would look for a heading that does not exist yet and never look
   * again.
   */
  const attachRegisterHeading = useCallback(
    (node: HTMLHeadingElement | null) => {
      registerHeadingEl.current = node;
      if (node !== null) focusRegisterSoon();
    },
    [focusRegisterSoon],
  );

  const navigate = useCallback(
    (next: ConstraintUrlState, options?: { readonly replace?: boolean }) => {
      const href = constraintsHref(projectId, next);
      if (options?.replace) router.replace(href);
      else router.push(href);
    },
    [projectId, router],
  );

  const selected = useMemo(
    () =>
      state.selectedConstraintId === null
        ? null
        : (workspace.entries.find(
            (entry) => entry.constraintId === state.selectedConstraintId,
          ) ?? null),
    [state.selectedConstraintId, workspace.entries],
  );

  /**
   * The canonical detail read, which happens only for the selected record.
   *
   * `undefined` while the read is outstanding; `null` when it failed. The
   * failure is a real branch here, not a hypothetical: the corpus names the
   * identifiers whose detail read refuses, so the Inspector's own unavailable
   * state is reachable without the Register losing a row.
   */
  const [read, setRead] = useState<{
    readonly constraintId: string;
    readonly detail: ConstraintView | null;
    readonly history: readonly ConstraintHistoryEntry[] | undefined;
  } | null>(null);

  useEffect(() => {
    const id = state.selectedConstraintId;
    if (id === null) return;
    let cancelled = false;
    // A microtask stands in for the read. The point it proves is ordering:
    // list identity renders first, canonical detail arrives after. The result
    // is stored with the identity it belongs to, so a result that arrives for
    // a Constraint the reader has already moved off is simply not the current
    // one rather than being applied to the wrong record.
    void Promise.resolve().then(() => {
      if (cancelled) return;
      if (workspace.unreadableDetailIds.includes(id)) {
        setRead({ constraintId: id, detail: null, history: undefined });
        return;
      }
      setRead({
        constraintId: id,
        detail: workspace.details[id] ?? null,
        history: workspace.history[id],
      });
    });
    return () => {
      cancelled = true;
    };
  }, [state.selectedConstraintId, workspace]);

  const current = read !== null && read.constraintId === state.selectedConstraintId ? read : null;
  const detail = current === null ? undefined : current.detail;
  const history = current === null ? undefined : current.history;

  /** Publish the selection to the shell so its one Inspector opens. */
  useEffect(() => {
    if (state.selectedConstraintId === null) {
      if (shellSelection !== null && shellSelection.kind === "constraint") setSelection(null);
      return;
    }
    if (
      shellSelection !== null &&
      shellSelection.kind === "constraint" &&
      shellSelection.constraintId === state.selectedConstraintId
    ) {
      return;
    }
    setSelection({
      kind: "constraint",
      constraintId: state.selectedConstraintId,
      projectId,
    });
  }, [state.selectedConstraintId, shellSelection, setSelection, projectId]);

  const closeDetail = useCallback(() => {
    const opener = state.selectedConstraintId;
    navigate({ ...state, selectedConstraintId: null });
    // Focus returns to the row that opened the Inspector. Without this a
    // keyboard reader is dropped at the top of the document after every read.
    if (opener !== null) {
      window.setTimeout(() => {
        document.getElementById(rowTriggerId(opener))?.focus();
      }, 0);
    }
  }, [navigate, state]);

  const selectConstraint = useCallback(
    (constraintId: string) => {
      navigate({ ...state, view: "register", selectedConstraintId: constraintId });
    },
    [navigate, state],
  );

  const inspectorRender = useCallback(
    () => (
      <ConstraintInspector
        entry={selected}
        detail={detail}
        history={history}
        onClose={closeDetail}
        onNavigateToConstraint={selectConstraint}
        onLifecycleAction={(action) => {
          if (action === "edit") setFormOpen("edit");
          else setLifecycleAction(action);
        }}
      />
    ),
    [selected, detail, history, closeDetail, selectConstraint],
  );

  useInspectorContent("constraint", {
    title: inspectorTitle(selected),
    render: inspectorRender,
  });

  function onKpiNavigate(target: ConstraintKpiTarget) {
    pendingRegisterFocus.current = true;
    navigate(kpiRegisterState(state, target));
    focusRegisterSoon();
  }

  const oldestOpen = useMemo(
    () =>
      // The backend's own ordering of the longest-open active records. Bounded
      // to five; this is a projection to render, not a scan of the Register.
      workspace.entries
        .filter(
          (entry) =>
            entry.status !== null &&
            ["IDENTIFIED", "PENDING", "IN_PROGRESS", "ON_HOLD"].includes(entry.status) &&
            entry.daysElapsed !== null,
        )
        .sort((left, right) => (right.daysElapsed ?? 0) - (left.daysElapsed ?? 0))
        .slice(0, 5),
    [workspace.entries],
  );

  return (
    <div className="grid gap-4" data-testid="constraints-workspace">
      <PageHeader
        title="Constraints"
        description={`Project Controls · ${workspace.project.name}`}
      />
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="project-context">
        <Badge tone="neutral">{workspace.project.reference}</Badge>
        <span className="text-muted">Project {projectId}</span>
        <Badge tone="synthetic">Fixture data</Badge>
        <label className="ml-auto flex items-center gap-1">
          <span className="text-muted">Project</span>
          <Select
            value={projectId}
            data-testid="project-selector"
            onChange={(event) => {
              // A Project switch is a route change, and Project-specific filter
              // identities do not travel with it.
              const next = projectSwitchState(state);
              const query = serializeConstraintUrlState(next);
              const base = constraintsRoute(event.target.value);
              router.push(query.length === 0 ? base : `${base}?${query}`);
            }}
          >
            {projects.map((project) => (
              <option key={project.projectId} value={project.projectId}>
                {project.name}
              </option>
            ))}
          </Select>
        </label>
        <Button size="sm" variant="secondary" data-testid="open-categories" onClick={() => setCategoriesOpen(true)}>
          Categories
        </Button>
      </div>

      {announcement ? (
        <LiveAnnouncement tone="alert" testId="workspace-live">
          {announcement}
        </LiveAnnouncement>
      ) : null}

      <Tabs
        value={state.view}
        onValueChange={(view) =>
          navigate({ ...state, view: view as ConstraintUrlState["view"] })
        }
      >
        <TabsList aria-label="Constraint workspace">
          <TabsTrigger value="overview" data-testid="tab-overview">
            Overview
          </TabsTrigger>
          <TabsTrigger value="register" data-testid="tab-register">
            Register
          </TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="mt-4">
          <h2 className="sr-only">Overview</h2>
          <ConstraintsOverview
            overview={workspace.overview}
            categoryOpenCounts={workspace.categoryOpenCounts}
            oldestOpen={oldestOpen}
            state={state}
            onKpiNavigate={onKpiNavigate}
            onCategoryNavigate={(categoryId) => {
              pendingRegisterFocus.current = true;
              navigate(categoryRegisterState(state, categoryId));
              focusRegisterSoon();
            }}
            onSelect={selectConstraint}
          />
        </TabsContent>
        <TabsContent value="register" className="mt-4">
          <h2 ref={attachRegisterHeading} tabIndex={-1} className="sr-only" data-testid="register-heading">
            Register
          </h2>
          <ConstraintsRegister
            projectId={projectId}
            entries={workspace.entries}
            categories={workspace.categories}
            partyOptions={workspace.partyOptions}
            state={state}
            viewport={viewport}
            onStateChange={navigate}
            onSelect={selectConstraint}
            onNewConstraint={() => setFormOpen("create")}
          />
        </TabsContent>
      </Tabs>

      <ConstraintFormDialog
        open={formOpen !== false}
        mode={formOpen === "edit" ? "edit" : "create"}
        entry={formOpen === "edit" ? selected : null}
        categories={workspace.categories}
        onClose={() => setFormOpen(false)}
        onSyntheticOutcome={setAnnouncement}
      />
      <LifecycleDialog
        action={lifecycleAction}
        entry={selected}
        onClose={() => setLifecycleAction(null)}
        onSyntheticOutcome={setAnnouncement}
      />
      <CategoryPanel
        open={categoriesOpen}
        categories={workspace.categories}
        onClose={() => setCategoriesOpen(false)}
        onSyntheticOutcome={setAnnouncement}
      />
    </div>
  );
}

/**
 * `useSearchParams` makes this subtree dynamic, and Next requires a Suspense
 * boundary around a client component that reads it.
 */
export function ConstraintsWorkspace(props: ConstraintsWorkspaceProps) {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading the Constraint workspace…</p>}>
      <ConstraintsWorkspaceInner {...props} />
    </Suspense>
  );
}

export type { ConstraintListEntry };
