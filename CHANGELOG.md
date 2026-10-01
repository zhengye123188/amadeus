# Changelog

## 0.3.0 — 2026-10-01

### Batch 1: project data

- Add database schema versioning with a nondestructive v0.2 migration and rejection of newer schemas.
- Add checksummed project archives using SQLite's backup API, plus restore into an empty workspace.
- Expose `backup_project` and `project_data_info` through the permission-controlled research MCP service.
- Verify WAL backup, restored evidence/job files, version compatibility, archive tampering, traversal and symlink rejection.

### Batch 2: evidence, experiments and project validation

- Add experiment specs, generated finite metric/artifact capture, comparable baseline/candidate runs and reports.
- Add an offline CPU case with baseline, improvement and negative results across repeated seeds.
- Require explicit claim assessments and verified metric conditions for hypothesis verdicts; separate execution observations from scientific results.
- Add canonical DOI/arXiv paper identities, evidence-backed research maps and pinned-code reproduction plans.
- Add project checks using prepared dependencies, bounded search/Python symbols and conflict-checked code checkpoints.
- Harden archive schema validation and validate all checkpoint payloads before restoration.

### Batch 3: configuration and accountable CLI use

- Add model capability/pricing profiles and an explicit, redacted `/models` diagnostic.
- Add native Pi external MCP configuration with per-tool local effect allowlists.
- Add numeric usage ledgers and soft model token/cost budgets; unknown prices remain unknown.
- Add explicit project instructions/skills and revision-bound human memory review from the terminal.
- Synchronize release metadata and derive npm smoke paths from package metadata.

### Batch 4: durable jobs and reproducible evaluation

- Add detached local workers with authenticated status/cancel, live logs, cross-process concurrency limits and explicit checkpoint-file continuation as a new run.
- Add configurable Docker CPU/memory/GPU requests and longer detached time limits; physical Docker/GPU validation remains outstanding.
- Add 12 synthetic research tasks evaluated through real Pi/MCP with final artifacts, resolvable references and measured experiment values. Suggested tool paths are advisory; both memory arms have the same task and tools.
- Add a pinned author-code LIBSVM CPU case with actual three-seed results. Validation-selected parameters did not improve held-out accuracy; the negative result and provenance are preserved.
- Harden backup schema validation, bounded search, file restoration and reproduction-stage checks.
- Document configuration, data upgrades and the separate npm, Python and standalone release channels.

## 0.2.0

Interactive Pi CLI with project-scoped research MCP tools, evidence and memory, bounded experiment jobs, npm distribution and standalone installers. See [release notes](docs/releases/v0.2.0.md).
