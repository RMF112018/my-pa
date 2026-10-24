import { existsSync } from "node:fs";
import type { TestInfo } from "@playwright/test";

const CASES = [
  { id: "light", snapshot: "shell-light-unavailable.png" },
  { id: "dark", snapshot: "shell-dark-inspector.png" },
  { id: "launcher", snapshot: "shell-command-menu.png" },
  { id: "zoom", snapshot: "shell-zoom-200.png" },
] as const;
type VisualCase = typeof CASES[number]["id"];
type Outcome = "absent-created-error" | "hard-throw" | "matched-no-delta" | "unknown";

/** Observe only fixed screenshot assertions; never inspect an error or image. */
export async function witnessVisualAssertion(
  info: TestInfo, caseId: VisualCase, assertion: () => Promise<unknown>,
): Promise<void> {
  const admitted = CASES.find((entry) => entry.id === caseId);
  if (process.env.CI !== "true" || process.env.CI_VISUAL_DIAGNOSTIC !== "1" || !admitted) {
    await assertion();
    return;
  }
  let desktop = false;
  try { desktop = info.project.name === "desktop"; } catch { /* No project proof, no observation. */ }
  if (!desktop) {
    await assertion();
    return;
  }
  const id = admitted.id;
  let before: { exists: boolean; count: number } | undefined;
  let snapshot: string | undefined;
  try {
    snapshot = info.snapshotPath(admitted.snapshot, { kind: "screenshot" });
    const count = info.errors.length;
    if (Number.isSafeInteger(count) && count >= 0) before = { exists: existsSync(snapshot), count };
  } catch { /* An unavailable observation must not change the assertion. */ }

  function record(outcome: Outcome): void {
    try {
      const prefix = `${id}:`;
      const descriptions = new Set(["absent-created-error", "hard-throw", "matched-no-delta", "unknown"].map((value) => prefix + value));
      const previous = info.annotations.findIndex((item) => item.type === "my-pa-ci-visual-witness"
        && item.description !== undefined && descriptions.has(item.description));
      const description = prefix + outcome;
      if (previous < 0) info.annotations.push({ type: "my-pa-ci-visual-witness", description });
      else if (info.annotations[previous].description !== description) {
        info.annotations[previous] = { type: "my-pa-ci-visual-witness", description: prefix + "unknown" };
      }
    } catch { /* Diagnostic metadata cannot replace success or the original failure. */ }
  }

  try {
    await assertion();
  } catch (error) {
    record("hard-throw");
    throw error;
  }
  let outcome: Outcome = "unknown";
  try {
    if (before && snapshot !== undefined) {
      const exists = existsSync(snapshot);
      const count = info.errors.length;
      if (Number.isSafeInteger(count) && count >= 0) {
        if (!before.exists && exists && count > before.count) outcome = "absent-created-error";
        else if (before.exists && exists && count === before.count) outcome = "matched-no-delta";
      }
    }
  } catch { /* Partial observations remain unknown. */ }
  record(outcome);
}
