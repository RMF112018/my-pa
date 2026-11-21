# SDCR file-workspace closed placement — bounded implementation candidate

**Issue:** [#369](https://github.com/RMF112018/my-pa/issues/369)  
**Design:** `SDCR-PATH-CONTROL-20261121-001`  
**Status:** `CODE_CANDIDATE / DEFAULT_OFF / NOT_COMMISSIONED`  
**Authority:** Existing repository governance and ADR-019 continue to apply. This proposal does not ratify any change to the frozen Files contract, alter NAS permissions, or activate the SDCR authority cutover.

## Purpose

The new SDCR storage must not reproduce Google Drive's miscellaneous root folders and cross-project evidence dumping. A caller may not create arbitrary directories under `mcp:SDCR` or place files outside the governed work-item taxonomy. **No new file is migrated, moved, deleted, or reclassified by this code candidate.**

## How enforcement is composed

`Settings.files_sdcr_policy_file` (`MY_PA_FILES_SDCR_POLICY_FILE`) is empty by default. With it unset, the existing Files plane behaves as before, including pre-cutover historical paths. When the operator supplies a trusted absolute configuration file:

1. `bootstrap.gateway.files_workspaces` loads the policy and exact work-item owner registrations **outside every configured workspace and source/managed/report root**. The loader refuses symlinks, an unsafe writable config or immediate parent, unapproved policy status, unknown owner mappings, a missing file, and an invalid schema. A configured failure prevents startup; it does not silently disable enforcement.
2. `ComposedFileWorkspace` carries a snapshot of the `mcp` SDCR gate. `FileWorkspaceApplication._upload_begin` applies it before an ordinary or native `source_file` upload ticket is issued.
3. `FilesystemFileWorkspaceStore` rechecks at the *actual* write boundary for `mkdir` including all missing parents, `write_text`, `publish_upload`, and the transitions `copy`, `move/rename`, `trash`, `restore`. `restore` also checks the recorded original path at the application boundary.
4. The same gate is supplied to the operator apply-root store if one is composed. All denials are translated into the existing public `invalid_path` refusal, without exposing private owner data. The domain gate uses internal `PlacementDenied` reasons; these are not new public capability names.
5. Everything outside `SDCR/` remains governed by the existing Files contract. No new process, database table, network listener, capability, write purpose, or secret is introduced.

### Structural limits of v1

- Program/workstream IDs come from the fixed proposed policy `sdcc-placement-policy.v1.json`; work-item owner IDs come from a separate trusted operator-managed `registrations` map, never a client-submitted path. A change to that map requires an approved update and process restart; trusted **automatic registration of new GitHub Issues/Abacus work items has not yet been built**. The sample file is `PROPOSED_NOT_ACTIVE`, and cannot enable the gate without explicitly changing its status for a synthetic qualification.
- Accepted session artifacts are named `<artifact-id>__<safe-filename>` inside exactly one approved `artifacts/<role>/` subfolder. The server validates the **structural category** from the pathname. It cannot independently infer the true semantic classification of arbitrary opaque bytes. The Issue #365 publisher must derive and independently verify the real artifact role, source eligibility and ownership before publication; direct client writes cannot assert that a mislabeled PDF really is evidence.
- SDCR transitions (`copy`, `move`, `rename`, `trash`, `restore`) are **denied** through the normal Files mutation API. A separately governed, explicit migration mechanism is required for any historical refiling. Normal immutable artifact bytes cannot be overwritten. An approved version-matching update is possible only for typed indexes/canonical JSON pointers.
- `00-Control` policy/control content cannot be written by normal Files writers. Operator provisioning is distinct from ordinary publication.
- This restriction covers API-mediated writes **within the `SDCR/` subtree**, not arbitrary paths elsewhere in the broader `mcp` workspace. Client-wide root isolation requires separate path-scoped grant or NAS ACL qualification. It also cannot prevent direct SMB/NAS writes by identities with filesystem privileges: watcher-based detection is not prevention.

## Acceptance and qualification gates

- **Synthetic (in-scope this PR):** deny unknown root/program/stream/work-item/role, malformed paths and deep rogue parent creation; deny direct Files bypass at store and upload-begin/finalize boundaries; immutable authoring; safe configuration and mixed-workspace isolation; preserve unrelated Files behavior. Execute current-head FAST/security/contract checks and report every failure.
- **Separate qualified client integration:** ChatGPT, ChatLLM, local code agent and reviewer using actual authenticated writes against a disposable SDCR test subtree, including a bypass attempt from each capability. Confirm controls survive process restart and cannot be evaded via a second OAuth client/profile.
- **Before authority cutover:** update Issue #365 publisher to emit the approved typed layout, complete deterministic classification/owner registration, approved policy registration and immutable pointer publication; independently verify NAS ACL boundaries or record external writers as detection-only, run full corpus inventory/crosswalk and rollback proof. **Do not claim `PATH_GOVERNANCE_ENFORCED_AND_TESTED` until these pass.**

## Deployment and rollback

No live configuration is installed by this PR. Commissioning is reserved to a separately authorized operator-governed change: verify root, trusted policy file, exact registered owners, configuration hash, client grants, and NAS ACLs; mount control file read-only from outside all Files-authoring roots; set `MY_PA_FILES_SDCR_POLICY_FILE`; restart affected service through the existing deployment runbook. Keep an unchanged rollback image/config and preserve the storage bytes. Removing the option during rollback returns the old path behavior **only after the authority decision allows it**; do not disable enforcement silently after cutover.

**Important dependency:** The current Issue #365 publisher (PR #366) uses nested original output paths under `artifacts/` and is not yet aligned with this strict type/id layout. That incompatibility is a **cutover blocker**, not permission to loosen the guard or fold Issue #369 into the concurrent corrective PR.
