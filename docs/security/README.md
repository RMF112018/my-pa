# Security Documentation

Owning index for security analysis in `RMF112018/my-pa`. Repository-wide policy is [`SECURITY.md`](/SECURITY.md); repository-wide routing is [`docs/00_REPOSITORY_SOURCE_INDEX.md`](/docs/00_REPOSITORY_SOURCE_INDEX.md).

| Document | Status |
|---|---|
| [`threat-model.md`](threat-model.md) | Present — proposed for repository review |

The threat model records entry points, abuse cases, controls, required tests, and residual risk. Recording a residual risk is not risk acceptance; only the repository owner may accept risk.

Documents here describe intended behavior. They do not authorize runtime implementation, credentials, source-system access, database changes, background scheduling, deployment, or production activation.

New implementation must use the neutral `my_pa` / `MY_PA_` namespace. Legacy identities may appear only in explicit compatibility or evidence records.
