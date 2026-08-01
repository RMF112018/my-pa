# Runtime Git Identity Resolution Contract

```yaml
authority: RUNTIME_GIT
branch: main
exact_current_sha_persisted: false
exact_current_tree_persisted: false
required_resolution:
  - git rev-parse main
  - "git rev-parse main^{tree}"
  - git ls-remote --heads origin main
external_evidence_required: true
rule: Every future authorization must resolve and bind the current repository identity at authorization time. No committed predecessor SHA is current authority.
```

Entry-gate resolution (pre-write):

```text
local/remote main = 178a7e243cbc6100c6937144ff10a7987206c04a
tree = 25131169d7bbe7846569c2a3cb5afa2712bd3c96
```

That identity is the historical `record_base` of this correction, not continuously current authority after the correction commit exists.
