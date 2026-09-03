import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeCounterparty,
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredNullableString,
  requiredString,
  COMMITMENT_STATES,
  type CommitmentState,
  type CounterpartyProjection,
} from "./_read-helpers";

export interface WaitingOnEntry {
  readonly commitment_id: string;
  readonly title: string;
  readonly counterparty_person_id: string | null;
  readonly due_date: string | null;
  readonly state: CommitmentState;
  readonly follow_up_task_id: string | null;
  readonly follow_up_task_title: string | null;
  readonly follow_up_task_state: string | null;
  readonly counterparty: CounterpartyProjection | null;
}

export interface CommitmentsWaitingOnResult {
  readonly waiting_on: readonly WaitingOnEntry[];
}

const ENTRY_KEYS = [
  "commitment_id",
  "title",
  "counterparty_person_id",
  "due_date",
  "state",
  "follow_up_task_id",
  "follow_up_task_title",
  "follow_up_task_state",
  "counterparty",
] as const;

function decodeEntry(input: unknown): DecodeResult<WaitingOnEntry> {
  const known = pick(input, ENTRY_KEYS);
  if (!known.ok) return known;
  const commitmentId = requiredString(known.value.commitment_id);
  if (!commitmentId.ok) return commitmentId;
  const title = requiredString(known.value.title);
  if (!title.ok) return title;
  const counterpartyPersonId = requiredNullableString(known.value.counterparty_person_id);
  if (!counterpartyPersonId.ok) return counterpartyPersonId;
  const dueDate = requiredNullableString(known.value.due_date);
  if (!dueDate.ok) return dueDate;
  const state = oneOf(known.value.state, COMMITMENT_STATES);
  if (!state.ok) return state;
  const followUpId = requiredNullableString(known.value.follow_up_task_id);
  if (!followUpId.ok) return followUpId;
  const followUpTitle = requiredNullableString(known.value.follow_up_task_title);
  if (!followUpTitle.ok) return followUpTitle;
  const followUpState = requiredNullableString(known.value.follow_up_task_state);
  if (!followUpState.ok) return followUpState;
  const counterparty = decodeCounterparty(known.value.counterparty);
  if (!counterparty.ok) return counterparty;
  return ok({
    commitment_id: commitmentId.value,
    title: title.value,
    counterparty_person_id: counterpartyPersonId.value,
    due_date: dueDate.value,
    state: state.value,
    follow_up_task_id: followUpId.value,
    follow_up_task_title: followUpTitle.value,
    follow_up_task_state: followUpState.value,
    counterparty: counterparty.value,
  });
}

export const decodeCommitmentsWaitingOn: Decoder<CommitmentsWaitingOnResult> = (input) => {
  const known = pick(input, ["waiting_on"]);
  if (!known.ok) return known;
  if (known.value.waiting_on === undefined) return fail("a required array was omitted");
  const entries = decodeItems(known.value.waiting_on, decodeEntry);
  if (!entries.ok) return entries;
  return ok({ waiting_on: entries.value });
};
