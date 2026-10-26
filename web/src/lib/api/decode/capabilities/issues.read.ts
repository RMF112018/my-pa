import { closed } from "../primitives";
import type { Decoder } from "../types";
import { strictObject, nullable, arrayOf, checked, text, boolean, enumeration, identifier, integer, timestamp, type Decoded } from "./continuity.projects.create";
import { ACCEPTANCE_BASES, ISSUE_STATES, assertingClientId, association, evidenceAnchor, issueTitle } from "./records.lineage";

/*
 * `issues.read` (record lineage S1 contract section 7.1, S2 section 7.1 and S3
 * section 6.4), decoded strictly: one Issue, its native Project links (at most
 * 100, never a Project name), its closure basis while it is `closed`, and
 * `restricted` (whether anything was withheld from this reader). With
 * `include_members` the answer also carries the active memberships; the two
 * answers are two closed shapes and any other key refuses the whole answer.
 * The Python models are `IssueView`, `ProjectLinkView` and `IssueClosureView`
 * in `contracts/v1/issues.py`.
 *
 * S3.1 (section 7.6): a Project link's `acceptance_basis` admits
 * `client_identified`, and it states `user_directed_claim` and
 * `asserting_client_id`, as an association does.
 */
const invalid = () => closed("upstream_contract_invalid", "Invalid capability success contract");

const MAX_ISSUE_DESCRIPTION_CHARACTERS = 10000;
const MAX_LINEAGE_REASON_CHARACTERS = 2000;

const projectLink = strictObject({
  project_id: identifier("prj"),
  project_situation_id: identifier("psit"),
  state: enumeration(["active", "ended"]),
  membership_revision_no: integer(1),
  acceptance_basis: enumeration(ACCEPTANCE_BASES),
  user_directed_claim: boolean,
  asserting_client_id: assertingClientId,
  evidence_anchor_id: nullable(identifier("ian")),
  recorded_at: timestamp,
});

const closure = strictObject({
  version: integer(1),
  closed_at: timestamp,
  outcome: text(1, MAX_LINEAGE_REASON_CHARACTERS),
  evidence: checked(arrayOf(evidenceAnchor, 32), (value) => value.length >= 1),
});

const issue = checked(strictObject({
  issue_id: identifier("sit"),
  kind: enumeration(["issue_workstream"]),
  version: integer(1),
  state: enumeration(ISSUE_STATES),
  title: issueTitle,
  description: nullable(text(0, MAX_ISSUE_DESCRIPTION_CHARACTERS)),
  opened_at: timestamp,
  created_at: timestamp,
  updated_at: timestamp,
  project_links: arrayOf(projectLink, 100),
  project_links_truncated: boolean,
  closure: nullable(closure),
}), (value) => (value.state === "closed") === (value.closure !== null));

const withoutMembers = strictObject({ issue, restricted: boolean });
const withMembers = checked(strictObject({
  issue,
  memberships: arrayOf(association, 100),
  memberships_truncated: boolean,
  restricted: boolean,
}), (value) => value.memberships.every((member) =>
  member.kind === "issue_membership" && member.from.family === "situation" &&
  member.from.record_id === value.issue.issue_id));

export type IssueView = Decoded<typeof issue>;
export type IssueProjectLink = Decoded<typeof projectLink>;
export type IssuesReadResult = Decoded<typeof withoutMembers> & {
  readonly memberships?: Decoded<typeof association>[];
  readonly memberships_truncated?: boolean;
};
export const decodeIssuesRead: Decoder<IssuesReadResult> = (input) => {
  if (input === null || typeof input !== "object" || Array.isArray(input)) return invalid();
  return Object.hasOwn(input, "memberships") ? withMembers(input) as ReturnType<Decoder<IssuesReadResult>> : withoutMembers(input);
};
