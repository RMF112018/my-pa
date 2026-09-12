import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { StrictMode, useEffect, useState } from "react";
import {
  MutationFeedbackEvent,
  useMutationFeedback,
} from "@/components/ui/mutation-feedback";
import {
  TaskRuntimeProvider,
  useTaskRuntime,
  type TaskMutationCoordinatorHandle,
} from "@/components/work/task-runtime-provider";
import { buildTaskQueryKey } from "@/lib/task/query-key";

afterEach(() => {
  cleanup();
});

const PRINCIPAL_A = "aaaa0001-0000-0000-0000-000000000001";
const PRINCIPAL_B = "bbbb0002-0000-0000-0000-000000000002";

function RuntimeProbe() {
  const runtime = useTaskRuntime();
  return (
    <div>
      <span data-testid="session-key">{runtime.sessionKey}</span>
      <span data-testid="principal-id">{runtime.principalId}</span>
    </div>
  );
}

describe("TaskRuntimeProvider", () => {
  it("exposes session-scoped create-intent store and read coordinator", () => {
    const captured: { runtime: ReturnType<typeof useTaskRuntime> | null } = { runtime: null };

    function Capture() {
      const runtime = useTaskRuntime();
      useEffect(() => {
        captured.runtime = runtime;
      }, [runtime]);
      return <RuntimeProbe />;
    }

    render(
      <TaskRuntimeProvider principalId={PRINCIPAL_A} sessionEpoch="epoch-1">
        <Capture />
      </TaskRuntimeProvider>,
    );

    expect(captured.runtime).not.toBeNull();
    expect(captured.runtime!.principalId).toBe(PRINCIPAL_A);
    expect(captured.runtime!.sessionKey).toBe(`${PRINCIPAL_A}::epoch-1`);
    expect(captured.runtime!.createIntents.openSession({ title: "One" }).intentId).toBeTruthy();
    expect(captured.runtime!.readCoordinator).toBeTruthy();
    expect(captured.runtime!.mutationCoordinator.coordinator).toBeTruthy();
    expect(captured.runtime!.feedback).toBeTruthy();
    expect(Object.prototype.hasOwnProperty.call(captured.runtime, "principal")).toBe(false);
  });

  it("remints a disposed read coordinator under Strict Mode remount", () => {
    const key = buildTaskQueryKey({
      mode: "list",
      workView: "today",
      workDate: "2026-09-11",
      timezone: "UTC",
      archiveMode: "exclude",
      sessionEpoch: "epoch-1",
    });
    const captured: { runtime: ReturnType<typeof useTaskRuntime> | null } = { runtime: null };

    function Capture() {
      const runtime = useTaskRuntime();
      useEffect(() => {
        captured.runtime = runtime;
      }, [runtime]);
      return <RuntimeProbe />;
    }

    render(
      <StrictMode>
        <TaskRuntimeProvider principalId={PRINCIPAL_A} sessionEpoch="epoch-1">
          <Capture />
        </TaskRuntimeProvider>
      </StrictMode>,
    );

    expect(captured.runtime).not.toBeNull();
    expect(captured.runtime!.readCoordinator.isDisposed()).toBe(false);
    expect(() => captured.runtime!.readCoordinator.retain(key)).not.toThrow();
    captured.runtime!.readCoordinator.release(key);
  });

  it("clears shared Task state when Principal or session epoch changes", () => {
    const disposed: string[] = [];

    function factoryFor(label: string): () => TaskMutationCoordinatorHandle {
      return () =>
        ({
          coordinator: {} as TaskMutationCoordinatorHandle["coordinator"],
          dispose: () => {
            disposed.push(label);
          },
        }) satisfies TaskMutationCoordinatorHandle;
    }

    function CreateStoreMarker() {
      const runtime = useTaskRuntime();
      useEffect(() => {
        if (runtime.createIntents.getActiveSession() == null) {
          runtime.createIntents.openSession({ title: "seed" });
        }
      }, [runtime]);
      return <span data-testid="runtime-session">{runtime.sessionKey}</span>;
    }

    function Outer() {
      const [principalId, setPrincipalId] = useState(PRINCIPAL_A);
      const [epoch, setEpoch] = useState("epoch-1");

      return (
        <TaskRuntimeProvider
          principalId={principalId}
          sessionEpoch={epoch}
          createMutationCoordinator={factoryFor(`${principalId}:${epoch}`)}
        >
          <CreateStoreMarker />
          <button type="button" onClick={() => setPrincipalId(PRINCIPAL_B)}>
            Switch principal
          </button>
          <button type="button" onClick={() => setEpoch("epoch-2")}>
            Switch epoch
          </button>
        </TaskRuntimeProvider>
      );
    }

    render(<Outer />);
    expect(screen.getByTestId("runtime-session")).toHaveTextContent(`${PRINCIPAL_A}::epoch-1`);

    act(() => {
      screen.getByRole("button", { name: "Switch principal" }).click();
    });
    expect(screen.getByTestId("runtime-session")).toHaveTextContent(`${PRINCIPAL_B}::epoch-1`);
    expect(disposed).toContain(`${PRINCIPAL_A}:epoch-1`);

    act(() => {
      screen.getByRole("button", { name: "Switch epoch" }).click();
    });
    expect(screen.getByTestId("runtime-session")).toHaveTextContent(`${PRINCIPAL_B}::epoch-2`);
    expect(disposed).toContain(`${PRINCIPAL_B}:epoch-1`);
  });

  it("keeps mutation feedback after a nested source unmounts", () => {
    function Source() {
      const feedback = useMutationFeedback();
      useEffect(() => {
        feedback.publish({
          eventId: MutationFeedbackEvent.createConfirmed("runtime-intent"),
          kind: "success",
          message: "Create confirmed",
        });
      }, [feedback]);
      return <div>source</div>;
    }

    function Harness() {
      const [showSource, setShowSource] = useState(true);
      return (
        <TaskRuntimeProvider principalId={PRINCIPAL_A} sessionEpoch="epoch-1">
          {showSource ? <Source /> : null}
          <button type="button" onClick={() => setShowSource(false)}>
            Unmount source
          </button>
        </TaskRuntimeProvider>
      );
    }

    render(<Harness />);
    expect(screen.getByRole("status")).toHaveTextContent("Create confirmed");

    act(() => {
      screen.getByRole("button", { name: "Unmount source" }).click();
    });
    expect(screen.queryByText("source")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Create confirmed");
  });

  it("clears feedback queue when the session key remounts feedback provider", () => {
    function OncePublisher({ armed }: { readonly armed: boolean }) {
      const feedback = useMutationFeedback();
      useEffect(() => {
        if (!armed) return;
        feedback.publish({
          eventId: "session-feedback",
          kind: "success",
          message: "Create confirmed",
        });
      }, [armed, feedback]);
      return null;
    }

    function Outer() {
      const [epoch, setEpoch] = useState("epoch-1");
      const [armed, setArmed] = useState(true);
      return (
        <TaskRuntimeProvider principalId={PRINCIPAL_A} sessionEpoch={epoch}>
          <OncePublisher armed={armed} />
          <button
            type="button"
            onClick={() => {
              setArmed(false);
              setEpoch("epoch-2");
            }}
          >
            Next epoch
          </button>
        </TaskRuntimeProvider>
      );
    }

    render(<Outer />);
    expect(screen.getByRole("status")).toHaveTextContent("Create confirmed");

    act(() => {
      screen.getByRole("button", { name: "Next epoch" }).click();
    });
    // New session remounts MutationFeedbackProvider via key=sessionKey; publisher is disarmed.
    expect(screen.queryByText("Create confirmed")).toBeNull();
  });

  it("allows pending controls to publish feedback without focus steal", () => {
    function Pending() {
      const { feedback } = useTaskRuntime();
      return (
        <button
          type="button"
          onClick={() =>
            feedback.publish({
              eventId: MutationFeedbackEvent.mutationFailure("task-1", "intent-x"),
              kind: "error",
              message: "The Task could not be updated.",
            })
          }
        >
          Save
        </button>
      );
    }

    render(
      <TaskRuntimeProvider principalId={PRINCIPAL_A}>
        <Pending />
      </TaskRuntimeProvider>,
    );

    const button = screen.getByRole("button", { name: "Save" });
    act(() => {
      button.focus();
      button.click();
    });

    expect(screen.getByRole("alert")).toHaveTextContent("The Task could not be updated.");
    expect(document.activeElement).toBe(button);
  });
});
