// @vitest-environment node
/**
 * The allowlist that governs limitations, pinned against its sources of truth.
 *
 * `safe-detail.ts` used to shape-check limitations, on the premise that they are
 * free prose. They are not: `application/disclosure.py` publishes a closed
 * `Limitation` StrEnum of unbroken snake_case tokens, which this tier renders
 * verbatim, and the shape check's run-length rule withheld eight of the thirteen
 * because each token is one long "word". The field is governed by an allowlist
 * now, which restores the disclosure and is genuinely closed.
 *
 * An allowlist carries one risk a shape check did not: **drift**. A token added
 * to the Python enum and not added here would be withheld — a legitimate
 * limitation silently replaced by a notice saying one was withheld, which is
 * exactly the regression this corrective exists to remove, arriving later and
 * quieter. So the pin is asserted mechanically. This is a source-scanning test
 * for the same reason `no-bypass.test.ts` is: the contract is a statement about
 * two trees, and only a test that reads both can hold it.
 *
 * Python is parsed rather than executed. The web package has no Python runtime,
 * the enum members are plain string literals on one line each, and a parse that
 * finds nothing fails loudly below rather than passing vacuously.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  CONTEXT_CARD_LIMITATIONS,
  PROFILE_LIMITATIONS,
} from "@/lib/api/decode/capabilities/_entity-read-helpers";
import {
  AGGREGATE_LIMITATION_REASONS,
  BACKEND_LIMITATIONS,
  WEB_LIMITATIONS,
  WITHHELD_LIMITATION,
  safeLimitations,
} from "@/lib/diagnostics/safe-detail";

const here = dirname(fileURLToPath(import.meta.url));
/** `web/src/lib/diagnostics` -> the repository root. */
const repoRoot = join(here, "../../../..");

function pythonSource(relative: string): string {
  return readFileSync(join(repoRoot, relative), "utf8");
}

/**
 * The string values of one `StrEnum` body.
 *
 * Anchored on the `class <name>(StrEnum):` line and stopped at the next
 * top-level `class`/`def`, so a later enum in the same module cannot bleed in.
 * Only `NAME = "value"` at member indentation is taken, which is how every
 * member in both files is written.
 */
function strEnumValues(source: string, className: string): readonly string[] {
  const start = source.indexOf(`class ${className}(StrEnum):`);
  expect(start, `${className} not found — has the enum moved or been renamed?`).toBeGreaterThan(-1);
  const rest = source.slice(start);
  const end = rest.slice(1).search(/\n(?:class |def |@)/);
  const body = end === -1 ? rest : rest.slice(0, end + 1);
  return [...body.matchAll(/^ {4}[A-Z][A-Z0-9_]*\s*=\s*"([^"]+)"/gm)].map((match) => match[1]);
}

describe("the limitation allowlist matches the backend vocabulary", () => {
  it("carries exactly the tokens `application/disclosure.py` can publish", () => {
    const tokens = strEnumValues(pythonSource("src/my_pa/application/disclosure.py"), "Limitation");
    // Guards against a parse that silently found nothing and made the
    // comparison below trivially true against an empty set.
    expect(tokens.length).toBeGreaterThan(10);
    expect([...tokens].sort()).toEqual([...BACKEND_LIMITATIONS].sort());
  });

  it("carries exactly the reasons `AggregateLimitation` can name", () => {
    const reasons = strEnumValues(
      pythonSource("src/my_pa/domain/extraction/coverage.py"),
      "LimitationReason",
    );
    expect(reasons.length).toBeGreaterThan(0);
    expect([...reasons].sort()).toEqual([...AGGREGATE_LIMITATION_REASONS].sort());
  });

  it("renders every backend token rather than withholding it", () => {
    const tokens = strEnumValues(pythonSource("src/my_pa/application/disclosure.py"), "Limitation");
    expect(safeLimitations(tokens).items).toEqual(tokens);
  });

  it("renders a parameterised aggregate disclosure", () => {
    // `AggregateLimitation.disclosure` is `f"{reason.value}:{affected_count}"`.
    for (const reason of AGGREGATE_LIMITATION_REASONS) {
      expect(safeLimitations([`${reason}:1`, `${reason}:4096`]).items).toEqual([
        `${reason}:1`,
        `${reason}:4096`,
      ]);
    }
  });

  it("admits nothing else after the colon", () => {
    const [reason] = AGGREGATE_LIMITATION_REASONS;
    for (const forged of [
      `${reason}:`,
      `${reason}:12 extra`,
      `${reason}:1:2`,
      `${reason}:AKIAIOSFODNN7EXAMPLE`,
      `not_a_reason:4`,
    ]) {
      expect(safeLimitations([forged]).items).toEqual([WITHHELD_LIMITATION]);
    }
  });
});

describe("the allowlist matches the vocabularies this tier decodes", () => {
  it("renders every context-card and profile limitation", () => {
    const decoded = [...CONTEXT_CARD_LIMITATIONS, ...PROFILE_LIMITATIONS];
    expect(decoded.length).toBeGreaterThan(10);
    expect(safeLimitations(decoded).items).toEqual(decoded);
  });
});

describe("the allowlist matches the sentences this tier authors", () => {
  it("renders every web-authored limitation", () => {
    const authored = Object.values(WEB_LIMITATIONS);
    expect(authored.length).toBeGreaterThan(10);
    expect(safeLimitations(authored).items).toEqual(authored);
  });

  it("is the definition site for every one of them", async () => {
    // The drift an allowlist of literal sentences would otherwise invite: a
    // callsite that writes its own copy of the string. The callsites import
    // these instead, so this is a statement about the module graph, asserted by
    // checking the re-export the one server-only module needs.
    const { LOCAL_OPERATOR_LIMITATION } = await import("@/lib/api/gateway");
    expect(LOCAL_OPERATOR_LIMITATION).toBe(WEB_LIMITATIONS.localOperator);
  });
});

describe("what the allowlist withholds", () => {
  it("withholds credential- and infrastructure-shaped values outright", () => {
    // NB-01. The prose-shape check admitted every one of these, because each is
    // ordinary punctuation with no run longer than 32 characters, and no
    // threshold could have excluded them without excluding real tokens. An
    // allowlist excludes them for the only reason that generalises: they are not
    // in the set.
    const forged = [
      "0123456789abcdef0123456789abcdef",
      "AKIAIOSFODNN7EXAMPLE",
      "sk_live_4eC39HqLyjWDarjt",
      "db-prod-01.internal.example.com",
      "/var/lib/mypa/secrets/app.key",
      "the read failed",
      "",
    ];
    expect(safeLimitations(forged).items).toEqual(forged.map(() => WITHHELD_LIMITATION));
  });

  it("replaces rather than drops, so the count is preserved", () => {
    const [token] = BACKEND_LIMITATIONS;
    expect(safeLimitations([token, "not in the set"]).items).toEqual([token, WITHHELD_LIMITATION]);
  });
});
