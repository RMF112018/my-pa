import type { Decoder } from "../types";
import {
  decodeCommitmentListPage,
  type CommitmentListEntry,
  type CounterpartyProjection,
} from "./_read-helpers";

export type { CommitmentListEntry, CounterpartyProjection };

export type CommitmentsListResult = {
  readonly commitments: readonly CommitmentListEntry[];
  readonly counterparty_options: readonly CounterpartyProjection[];
  readonly counterparty_options_truncated: boolean;
};

export const decodeCommitmentsList: Decoder<CommitmentsListResult> = decodeCommitmentListPage;
