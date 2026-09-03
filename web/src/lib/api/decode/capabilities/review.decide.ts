import type { Decoder } from "../types";

/** Fail-closed stub. Workers C/D replace this module with the real capability guard. */
export const decodeReviewDecide: Decoder<unknown> = () => ({
  ok: false,
  code: "capability_decoder_pending",
  message: "the capability result was rejected as uncontracted",
});
