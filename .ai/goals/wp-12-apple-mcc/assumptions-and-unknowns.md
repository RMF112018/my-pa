# WP-12 assumptions and unknowns

## Assumptions selected for synthetic repository work

- The operator's current instruction supersedes only WP-12's provisional sequencing/implementation hold. It does not reactivate WP-10/WP-11 or authorize any live action.
- The Apple source configuration frontend is part of WP-12, but Capture PWA/offline behavior remains WP-10 and is excluded.
- A single native-host protocol can support Mail, Calendar and Contacts, while each adapter, permission and bucket remains independent.
- Existing `knowledge.sources`, `source_objects`, `source_object_versions`, audit, proposal and Review planes remain the canonical evidence path. New tables form a control plane, not an Apple-specific canonical domain silo.
- Synthetic defaults may be conservative: exact bucket selection; no dynamic future inclusion; bounded text; attachments excluded; external models denied; no physical purge; no live activation.
- Exact capability names and numeric limits are reversible implementation choices until external plan review freezes them.
- A simulation is test evidence only. The current build creates `WatcherSimulation`, `SimulationReceipt`, and their identifier/table families, but does not create `VerifiedLiveAttestation`, `AuthoritativeWatcherRegistration`, `ActivationReceipt`, or their tables. Those live types and tables remain future, separately operator-authorized work; no conversion path is assumed or permitted.

## Unknowns that do not block synthetic implementation

- Final supported macOS floor.
- Final Mail acquisition API and sandbox boundary.
- Exact live accounts and buckets.
- TCC permission grants and dedicated non-personal canary identities.
- Code-signing/notarization identity.
- Live performance/freshness.
- Operator-approved maximum historical range and live payload limits.
- Physical retention/purge policy.

## Fail-closed treatment

- No configured live adapter means discovery reports `unavailable`, never an empty inventory.
- No signing/registration attestation means live bridge admission is denied.
- No exact account/bucket authorization means baseline creation is denied.
- No external-disclosure decision means Apple content stays local and model-ineligible.
- No retention authorization means removal stops reads and preserves evidence.
- No activation authorization means watchers can be simulated in tests but cannot be installed or started on a real Mac.
- No separately authorized and verified live attestation means authoritative `watching` is unrepresentable; a completed simulation remains `simulation_complete` and cannot be presented as `watching`.

## Contradictions requiring reviewer attention

1. Canonical `19_ACCEPTANCE_CRITERIA_CROSSWALK.md` summarizes baseline as AC-015–022, but exact feature AC-015 is membership separation. The plan maps each exact criterion, not the summary ranges.
2. Feature package `11`/`12` has 14 open prompts and 25 decisions; canonical v2.3 has 10/15 after integration. Canonical v2.3 controls current product decisions, while the feature package remains the detailed acceptance source.
3. Repository plan still records WP-12 as provisional after WP-10/WP-11. `AUTH-WP12-20260804-OPERATOR-001` is later authority and promotes WP-12; the durable plan should be reconciled in the first implementation/governance PR.
