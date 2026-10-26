// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/python/success.json";
import { decodeIssuesRead } from "./issues.read";

/*
 * AT-024 (S3, web decoders): `issues.read` (S1 section 7.1, S2 section 7.1, S3
 * section 6.4). The canonical answer is the committed Python dump
 * (`_issues_read`); the closed and with-members shapes are derived from it.
 */
const canonical = fixtures["issues.read"];
const lineage = fixtures["records.lineage"];
type Json = Record<string, unknown>;
function payload(): Json { return structuredClone(canonical) as Json; }
function issue(value: Json): Json { return value.issue as Json; }
const decode = decodeIssuesRead;
const anchor = (lineage.typed_edges[1]!.evidence as Json[])[0]!;

describe("issues.read strict canonical success", () => {
  it("decodes an Issue with its Project links", () => {
    expect(decode(canonical)).toEqual({ ok: true, value: canonical });
    expect((issue(payload()).project_links as Json[])).toHaveLength(1);
    // A closed Issue carries its closure basis.
    const closed = payload();
    Object.assign(issue(closed), {
      state: "closed",
      closure: { version: 2, closed_at: issue(closed).updated_at, outcome: "Resolved by the pour.", evidence: [{ ...anchor, role: "resolution" }] },
    });
    expect(decode(closed)).toEqual({ ok: true, value: closed });
    // With members: the active memberships of this Issue.
    const members = payload();
    Object.assign(members, { memberships: [lineage.typed_edges[0]], memberships_truncated: false });
    expect(decode(members)).toEqual({ ok: true, value: members });
    // Something withheld from this reader.
    const restricted = payload(); restricted.restricted = true;
    expect(decode(restricted).ok).toBe(true);
  });

  it("refuses unknown keys, a closure that disagrees with the state and a foreign membership", () => {
    for (const key of ["unexpected", "principal_id", "project_name", "memberships_truncated"]) {
      const value = payload(); value[key] = key === "memberships_truncated" ? false : "x";
      expect(decode(value).ok, key).toBe(false);
    }
    for (const key of ["unexpected", "name", "evidence_set_digest"]) {
      const value = payload(); issue(value)[key] = "x";
      expect(decode(value).ok, key).toBe(false);
      const link = payload(); (issue(link).project_links as Json[])[0]![key] = "x";
      expect(decode(link).ok, `link ${key}`).toBe(false);
    }
    const open = payload();
    issue(open).closure = { version: 1, closed_at: issue(open).updated_at, outcome: "x", evidence: [anchor] };
    expect(decode(open).ok).toBe(false);
    const closedWithout = payload(); issue(closedWithout).state = "closed";
    expect(decode(closedWithout).ok).toBe(false);
    const foreign = payload();
    Object.assign(foreign, { memberships: [{ ...lineage.typed_edges[0], from: { family: "situation", record_id: "sit_bbbbbbbb22222222" } }], memberships_truncated: false });
    expect(decode(foreign).ok).toBe(false);
    for (const state of ["contested", "archived", "Closed"]) {
      const value = payload(); issue(value).state = state;
      expect(decode(value).ok, state).toBe(false);
    }
  });

  it("decodes a client-identified Project link and refuses an unknown basis", () => {
    // S3.1 section 7.6: a Project link states its basis, claim and writing client.
    const client = payload();
    Object.assign((issue(client).project_links as Json[])[0]!, {
      acceptance_basis: "client_identified", user_directed_claim: true, asserting_client_id: null,
    });
    expect(decode(client)).toEqual({ ok: true, value: client });
    for (const basis of ["attested", "client_confirmed"]) {
      const value = payload(); (issue(value).project_links as Json[])[0]!.acceptance_basis = basis;
      expect(decode(value).ok, basis).toBe(false);
    }
    const missing = payload(); delete (issue(missing).project_links as Json[])[0]!.user_directed_claim;
    expect(decode(missing).ok).toBe(false);
  });
});
