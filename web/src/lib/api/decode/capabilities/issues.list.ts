import type { Decoder } from "../types";
import { strictObject, nullable, arrayOf, boolean, enumeration, identifier, integer, timestamp, type Decoded } from "./continuity.projects.create";
import { ISSUE_STATES, issueTitle } from "./records.lineage";

/*
 * `issues.list` (record lineage S1 contract section 7.1; S3 section 6.4 adds
 * `restricted`), decoded strictly: one keyset page of Issues, newest first.
 * A row carries no description and no link; `next_cursor` is the last
 * `issue_id` of the page while more remain. The Python models are
 * `IssueListEntry` in `contracts/v1/issues.py` and `_issues_list`'s payload.
 */
const entry = strictObject({
  issue_id: identifier("sit"),
  version: integer(1),
  state: enumeration(ISSUE_STATES),
  title: issueTitle,
  updated_at: timestamp,
});

const list = strictObject({
  issues: arrayOf(entry, 100),
  next_cursor: nullable(identifier("sit")),
  restricted: boolean,
});

export type IssueListEntry = Decoded<typeof entry>;
export type IssuesListResult = Decoded<typeof list>;
export const decodeIssuesList: Decoder<IssuesListResult> = list;
