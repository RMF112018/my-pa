# Canonical TypeScript contracts

**Status:** `IMPLEMENTING` (WP-02 / R1)

Parity mirror of the canonical object, state, error, span, Situation, Frame, Trace,
ReviewCase, Receipt, and Disclosure vocabulary defined by the ratified v4.0 product
package (`09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md`) and implemented on the Python side
under `src/my_pa/contracts` and `src/my_pa/domain`.

Parity rules:

1. State vocabularies are closed sets copied from the domain model — never extended
   locally. A divergence from the Python vocabulary is a defect.
2. Every durable object contract carries `principalId`. There is no unpartitioned
   contract.
3. Python `snake_case` maps to TypeScript `camelCase`; wire payloads use the Python
   spelling and are translated at the BFF boundary only.
4. `ErrorEnvelope` never carries content, tokens, or cross-principal confirmation.
