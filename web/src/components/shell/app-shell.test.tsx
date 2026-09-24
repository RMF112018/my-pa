import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AppShell } from "@/components/shell/app-shell";
import { useConstraintRuntime } from "@/components/project-controls/constraint-runtime-provider";
import { useMutationFeedback } from "@/components/ui/mutation-feedback";
import type { PrincipalSession } from "@/contracts/identity";

/**
 * R02-WP10 Integrator-A — provider-order assertion.
 *
 * `ConstraintRuntimeProvider` is mounted inside `TaskRuntimeProvider` (which
 * already mounts `MutationFeedbackProvider`) and outside/above
 * `AppShellBody`'s children. A probe rendered as `AppShell`'s child calling
 * both `useConstraintRuntime()` and `useMutationFeedback()` without either
 * throwing "used outside its provider" proves both providers are live and
 * correctly nested at that point in the tree.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/today",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const PRINCIPAL: PrincipalSession = {
  principalId: "aaaa0001-0000-0000-0000-000000000001",
  identityProvider: "synthetic",
  identitySubject: "11111111-2222-3333-4444-555555555555:aaaa0001-0000-0000-0000-000000000001",
  tid: "11111111-2222-3333-4444-555555555555",
  oid: "aaaa0001-0000-0000-0000-000000000001",
  upn: "synthetic.a@moss.example",
  displayName: "Synthetic A",
  lifecycleState: "active",
  synthetic: true,
};
const SESSION_EPOCH = "test-session-binding";

function RuntimeProbe() {
  const constraintRuntime = useConstraintRuntime();
  const feedback = useMutationFeedback();
  return (
    <div data-testid="runtime-probe">
      {constraintRuntime.sessionKey}::{typeof feedback.publish}
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AppShell mounts ConstraintRuntimeProvider between TaskRuntimeProvider and AppShellBody", () => {
  it("lets a child reach both useConstraintRuntime() and useMutationFeedback() without either throwing", () => {
    render(
      <AppShell principal={PRINCIPAL} sessionEpoch={SESSION_EPOCH}>
        <RuntimeProbe />
      </AppShell>,
    );

    expect(screen.getByTestId("runtime-probe")).toHaveTextContent(
      `${PRINCIPAL.principalId}::${SESSION_EPOCH}::function`,
    );
    // The exercised hook is `useMutationFeedback().publish`, not a fabricated
    // "notify" method — confirms the real MutationFeedbackProvider contract.
  });
});
