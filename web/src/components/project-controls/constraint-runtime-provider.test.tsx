/**
 * `ConstraintRuntimeProvider` — R02-WP10 Phase 4.
 *
 * Three things carry the weight here: it is the sole shared Constraint
 * runtime a page mounts (`PC-CM-UX-AC-014`); it mints a fresh runtime
 * identity — not an in-place mutation — on every Project-scope epoch change
 * (SP3.5); and its `useCanSwitchProjectScope()` export correctly implements
 * both halves of the SP3 scope-switch barrier (§5a: hard block, soft
 * block-with-confirm-discard).
 *
 * `ConstraintRuntimeProvider` isn't mounted anywhere in the running app yet
 * (the `app-shell.tsx` wiring is an Integrator-only patch — see this
 * dispatch's §7), so every test here exercises it directly, wrapped in the
 * same `ProjectScopeProvider` test harness Impl-2's own
 * `project-scope-provider.test.tsx` / `project-picker.test.tsx` use, plus
 * the real (already-mounted-in-production) `MutationFeedbackProvider` this
 * provider is documented to sit under.
 */
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  ConstraintRuntimeProvider,
  useCanSwitchProjectScope,
  useConstraintRuntime,
  type ConstraintRuntimeValue,
} from "@/components/project-controls/constraint-runtime-provider";
import { ProjectScopeProvider, useProjectScope } from "@/components/shell/project-scope-provider";
import { MutationFeedbackProvider } from "@/components/ui/mutation-feedback";
import type { ResolvedProjectScope } from "@/lib/project-scope/resolver";
import { constraintLockKey } from "@/lib/constraint/mutation-coordinator";

afterEach(cleanup);

const ALL_PROJECTS_RESOLUTION: ResolvedProjectScope = {
  scope: { kind: "ALL_PROJECTS" },
  source: "default",
  project: null,
  normalized: false,
};

const PROJECT_B_RESOLUTION: ResolvedProjectScope = {
  scope: { kind: "PROJECT", projectId: "prj_bbbbbbbb22222222" },
  source: "preference",
  project: { project_id: "prj_bbbbbbbb22222222", name: "Harbor Migration", state: "active", version: 1 },
  normalized: false,
};

function Harness({
  children,
  initialResolution = ALL_PROJECTS_RESOLUTION,
}: {
  readonly children: ReactNode;
  readonly initialResolution?: ResolvedProjectScope;
}) {
  return (
    <ProjectScopeProvider
      principalId="prn_aaaaaaaa11111111"
      sessionEpoch="session:a"
      initialResolution={initialResolution}
    >
      <MutationFeedbackProvider>
        <ConstraintRuntimeProvider principalId="prn_aaaaaaaa11111111" sessionEpoch="session:a">
          {children}
        </ConstraintRuntimeProvider>
      </MutationFeedbackProvider>
    </ProjectScopeProvider>
  );
}

/** Applies whatever `applyResolution` scope change the test asks for, on click. */
function ScopeChangeButton({ next }: { readonly next: ResolvedProjectScope }) {
  const { applyResolution } = useProjectScope();
  return (
    <button type="button" data-testid="change-scope" onClick={() => applyResolution(next)}>
      change scope
    </button>
  );
}

function CaptureRuntime({ onRuntime }: { readonly onRuntime: (runtime: ConstraintRuntimeValue) => void }) {
  const runtime = useConstraintRuntime();
  onRuntime(runtime);
  return null;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("ConstraintRuntimeProvider — one shared runtime (PC-CM-UX-AC-014)", () => {
  it("gives two mounted consumers the exact same coordinator instances, not a competitor each", () => {
    const captured: ConstraintRuntimeValue[] = [];
    render(
      <Harness>
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
      </Harness>,
    );

    expect(captured).toHaveLength(2);
    expect(captured[0].mutationCoordinator).toBe(captured[1].mutationCoordinator);
    expect(captured[0].readCoordinator).toBe(captured[1].readCoordinator);
    expect(captured[0].focusReturn).toBe(captured[1].focusReturn);

    // Behavioral proof, not just reference equality: a write through one
    // consumer's handle is visible through the other's.
    captured[0].mutationCoordinator.reportDirtyState("probe", true);
    expect(captured[1].mutationCoordinator.hasDirtyAuthoredState()).toBe(true);
  });

  it("throws a clear error when used outside the provider", () => {
    function Bare() {
      useConstraintRuntime();
      return null;
    }
    expect(() => render(<Bare />)).toThrow(/only valid inside ConstraintRuntimeProvider/);
  });
});

describe("ConstraintRuntimeProvider — fresh runtime identity per Project-scope epoch (SP3.5)", () => {
  it("disposes the old coordinators and mints new ones when the scope epoch changes", async () => {
    const user = userEvent.setup();
    const captured: ConstraintRuntimeValue[] = [];
    render(
      <Harness>
        <ScopeChangeButton next={PROJECT_B_RESOLUTION} />
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
      </Harness>,
    );

    const before = captured[captured.length - 1];
    expect(before.scopeEpoch).toBe(0);
    expect(before.readCoordinator.isDisposed()).toBe(false);

    await user.click(screen.getByTestId("change-scope"));

    await waitFor(() => {
      const after = captured[captured.length - 1];
      expect(after.scopeEpoch).toBe(1);
    });

    const after = captured[captured.length - 1];
    expect(after.readCoordinator).not.toBe(before.readCoordinator);
    expect(after.mutationCoordinator).not.toBe(before.mutationCoordinator);
    expect(after.focusReturn).not.toBe(before.focusReturn);
    // A fresh identity, not a mutable in-place reset: the old instance is
    // actually disposed, not merely superseded in the context value.
    expect(before.readCoordinator.isDisposed()).toBe(true);
    expect(before.mutationCoordinator.isDisposed()).toBe(true);
    expect(after.readCoordinator.isDisposed()).toBe(false);
  });

  it("keeps the same runtime identity across a re-render that does not change the epoch", () => {
    const captured: ConstraintRuntimeValue[] = [];
    const { rerender } = render(
      <Harness>
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
      </Harness>,
    );
    rerender(
      <Harness>
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
      </Harness>,
    );
    expect(captured[0].mutationCoordinator).toBe(captured[captured.length - 1].mutationCoordinator);
  });
});

function ScopeGuardProbe() {
  const canSwitchScope = useCanSwitchProjectScope();
  const [result, setResult] = useState<string>("unset");
  return (
    <div>
      <button
        type="button"
        data-testid="check-switch"
        onClick={async () => {
          const allowed = await Promise.resolve(canSwitchScope());
          setResult(String(allowed));
        }}
      >
        check
      </button>
      <output data-testid="switch-result">{result}</output>
    </div>
  );
}

describe("useCanSwitchProjectScope — §5a hard block", () => {
  it("refuses synchronously (no dialog) while a Constraint mutation is pending", async () => {
    const user = userEvent.setup();
    const captured: ConstraintRuntimeValue[] = [];
    const gate = deferred<{ version: number }>();
    render(
      <Harness>
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
        <ScopeGuardProbe />
      </Harness>,
    );

    const runtime = captured[captured.length - 1];
    void runtime.mutationCoordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: {},
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      dispatch: async () => gate.promise,
    });

    await user.click(screen.getByTestId("check-switch"));
    await waitFor(() => expect(screen.getByTestId("switch-result")).toHaveTextContent("false"));
    expect(screen.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();

    gate.resolve({ version: 2 });
  });

  it("refuses while a mutation is ambiguous (not just while dispatch is in flight)", async () => {
    const user = userEvent.setup();
    const captured: ConstraintRuntimeValue[] = [];
    render(
      <Harness>
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
        <ScopeGuardProbe />
      </Harness>,
    );

    const runtime = captured[captured.length - 1];
    await runtime.mutationCoordinator.mutate({
      kind: "constraintUpdate",
      lockRequest: { kind: "constraint-record", key: constraintLockKey("cst_1") },
      idempotencyKey: "idem-1",
      expectedVersion: 1,
      request: {},
      epoch: runtime.scopeEpoch,
      isCurrentEpoch: runtime.isCurrentEpoch,
      dispatch: async () => {
        throw new TypeError("Failed to fetch");
      },
    });
    expect(runtime.mutationCoordinator.hasPendingOrAmbiguousMutation()).toBe(true);

    await user.click(screen.getByTestId("check-switch"));
    await waitFor(() => expect(screen.getByTestId("switch-result")).toHaveTextContent("false"));
  });
});

describe("useCanSwitchProjectScope — §5a soft block (confirm/discard)", () => {
  it("allows the switch immediately, with no dialog, when nothing is dirty or pending", async () => {
    const user = userEvent.setup();
    render(
      <Harness>
        <ScopeGuardProbe />
      </Harness>,
    );

    await user.click(screen.getByTestId("check-switch"));
    await waitFor(() => expect(screen.getByTestId("switch-result")).toHaveTextContent("true"));
    expect(screen.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();
  });

  it("opens the confirm/discard dialog for dirty authored state, and resolves true on explicit Discard", async () => {
    const user = userEvent.setup();
    const captured: ConstraintRuntimeValue[] = [];
    render(
      <Harness>
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
        <ScopeGuardProbe />
      </Harness>,
    );
    const runtime = captured[captured.length - 1];
    runtime.mutationCoordinator.reportDirtyState("constraint-authoring:instance-1", true);

    await user.click(screen.getByTestId("check-switch"));
    await screen.findByText("Discard unsaved changes?");
    // The barrier is still unresolved: no premature answer.
    expect(screen.getByTestId("switch-result")).toHaveTextContent("unset");

    await user.click(screen.getByTestId("constraint-scope-discard-confirm"));
    await waitFor(() => expect(screen.getByTestId("switch-result")).toHaveTextContent("true"));
    expect(screen.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();
  });

  it("resolves false and leaves state untouched when the person cancels (Keep editing)", async () => {
    const user = userEvent.setup();
    const captured: ConstraintRuntimeValue[] = [];
    render(
      <Harness>
        <CaptureRuntime onRuntime={(r) => captured.push(r)} />
        <ScopeGuardProbe />
      </Harness>,
    );
    const runtime = captured[captured.length - 1];
    runtime.mutationCoordinator.reportDirtyState("constraint-authoring:instance-1", true);

    await user.click(screen.getByTestId("check-switch"));
    await screen.findByText("Discard unsaved changes?");

    await user.click(screen.getByTestId("constraint-scope-discard-cancel"));
    await waitFor(() => expect(screen.getByTestId("switch-result")).toHaveTextContent("false"));
    expect(screen.queryByText("Discard unsaved changes?")).not.toBeInTheDocument();

    // Cancelling must leave dirty-state bookkeeping (and therefore the
    // form's own unsaved edits) completely unchanged.
    expect(runtime.mutationCoordinator.hasDirtyAuthoredState()).toBe(true);
  });
});
