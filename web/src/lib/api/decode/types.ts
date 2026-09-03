/**
 * Decoder contracts for the BFF capability registry.
 *
 * `CapabilityResults` is a placeholder: every capability is `unknown` until
 * Workers C and D replace the stub modules with real result types.
 */
import contract from "@/contracts/gateway.json";
import type { DecodeResult } from "./primitives";

export type { DecodeResult } from "./primitives";

export type Decoder<T> = (input: unknown) => DecodeResult<T>;

/** Same keys as `gateway.json`; kept here so the registry does not import `gateway.ts`. */
export type GatewayCapability = keyof typeof contract.capabilities;

export type CapabilityResults = {
  readonly [K in GatewayCapability]: unknown;
};
