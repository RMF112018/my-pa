import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeCommitmentView,
  decodeCounterpartyOptions,
  decodeTaskListEntry,
  fail,
  pick,
  requiredBoolean,
  type CommitmentView,
  type CounterpartyProjection,
  type TaskListEntry,
} from "./_read-helpers";

export type { CommitmentView, CounterpartyProjection, TaskListEntry };

export interface CommitmentsReadResult {
  readonly commitment: CommitmentView;
  readonly follow_up_task: TaskListEntry | null;
  readonly counterparty_options: readonly CounterpartyProjection[];
  readonly counterparty_options_truncated: boolean;
}

export const decodeCommitmentsRead: Decoder<CommitmentsReadResult> = (input) => {
  const known = pick(input, [
    "commitment",
    "follow_up_task",
    "counterparty_options",
    "counterparty_options_truncated",
  ]);
  if (!known.ok) return known;
  if (known.value.commitment === undefined) return fail("a required field was missing");
  const commitment = decodeCommitmentView(known.value.commitment);
  if (!commitment.ok) return commitment;
  if (known.value.follow_up_task === undefined) return fail("a required field was missing");
  let followUp: TaskListEntry | null = null;
  if (known.value.follow_up_task !== null) {
    const decoded = decodeTaskListEntry(known.value.follow_up_task);
    if (!decoded.ok) return decoded;
    followUp = decoded.value;
  }
  if (known.value.counterparty_options === undefined) {
    return fail("a required array was omitted");
  }
  const options = decodeCounterpartyOptions(known.value.counterparty_options);
  if (!options.ok) return options;
  const truncated = requiredBoolean(known.value.counterparty_options_truncated);
  if (!truncated.ok) return truncated;
  return ok({
    commitment: commitment.value,
    follow_up_task: followUp,
    counterparty_options: options.value,
    counterparty_options_truncated: truncated.value,
  });
};
