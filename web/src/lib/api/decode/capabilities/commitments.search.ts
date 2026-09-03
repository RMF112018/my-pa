import type { Decoder } from "../types";
import {
  decodeCommitmentListPage,
  type CommitmentListEntry,
  type CounterpartyProjection,
} from "./_read-helpers";

export type { CommitmentListEntry, CounterpartyProjection };

export type CommitmentsSearchResult = {
  readonly commitments: readonly CommitmentListEntry[];
  readonly counterparty_options: readonly CounterpartyProjection[];
  readonly counterparty_options_truncated: boolean;
};

export const decodeCommitmentsSearch: Decoder<CommitmentsSearchResult> = decodeCommitmentListPage;
