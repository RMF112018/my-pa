/**
 * Deployed source identity, from image labels only.
 *
 * `MYPA_SOURCE_COMMIT` is 40–64 hex (SHA-1 or SHA-256). `MYPA_SOURCE_TREE` is
 * exactly 40 hex. Unset, empty, or any other value — a branch name, a working
 * directory, a short SHA — is reported as `unknown`. This module never reads
 * git, never uses `process.cwd()`, and never invents `"main"`.
 */
const SOURCE_COMMIT = /^[0-9a-f]{40,64}$/i;
const SOURCE_TREE = /^[0-9a-f]{40}$/i;

export type RuntimeIdentity = {
  sourceCommit: string;
  sourceTree: string;
};

function labelledHex(value: string | undefined, pattern: RegExp): string {
  const trimmed = value?.trim() ?? "";
  if (!pattern.test(trimmed)) return "unknown";
  return trimmed.toLowerCase();
}

export function runtimeIdentity(): RuntimeIdentity {
  return {
    sourceCommit: labelledHex(process.env.MYPA_SOURCE_COMMIT, SOURCE_COMMIT),
    sourceTree: labelledHex(process.env.MYPA_SOURCE_TREE, SOURCE_TREE),
  };
}
