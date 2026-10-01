# Measured experiments

Research CLI exposes these capabilities as interactive tools. You can inspect a paper,
modify code, start a run, compare earlier runs, or investigate a failure in any order.
There is no mandatory research pipeline.

## Run a measured experiment

`run_experiment` retains its existing `argv`, `cwd`, timeout and request ID arguments.
An optional `spec` describes the experiment. Runs without a spec remain ordinary process
records and cannot serve as verified metric evidence.

```json
{
  "argv": ["python3", "run.py", "--variant", "baseline", "--seed", "7"],
  "cwd": "examples/experiment_lab",
  "timeout_seconds": 30,
  "request_id": "quadratic-baseline-seed-7",
  "spec": {
    "group": "offline-quadratic-regression",
    "variant": "baseline",
    "dataset": {
      "dataset_id": "synthetic-quadratic-v1",
      "files": ["data.csv"],
      "split": "fixed-train-test-csv-column-v1",
      "protocol": "Fit on 40 training rows sampled with the recorded seed; evaluate only the fixed test rows."
    },
    "seed": 7,
    "parameters": {"degree": 1, "training_rows": 40},
    "metrics": {
      "mse": {
        "direction": "minimize",
        "unit": "squared target units",
        "definition": "Mean squared prediction error over the fixed test rows"
      }
    },
    "primary_metric": "mse",
    "metrics_file": "metrics.json",
    "artifacts": ["predictions.json"]
  }
}
```

Execution still requires the configured permission and execution backend. Commands run in
an isolated project snapshot. Local execution is an explicitly enabled host process;
Docker uses the prepared image and existing network/resource restrictions.

Paths in a spec are relative to `cwd`. Dataset inputs must exist in the snapshot and stay
unchanged during the run. The backend computes their SHA-256 values and records the
snapshot, command and bounded host/launcher environment facts. Declare relevant input,
preprocessing and split/configuration files to make their contents part of this identity.
The backend cannot establish that a supplied protocol description is truthful; reviewing
code and data usage remains necessary.

Metrics and declared artifacts must be **new output paths**: pre-existing snapshot files
are rejected. Output paths cannot overlap input files. Do not commit generated outputs
into the source directory used for new runs.

The metrics file must contain a UTF-8 JSON object with finite numeric values for every
declared metric, for example `{"mse": 1.23}`. Booleans, missing fields, duplicate JSON keys,
non-finite values, symlinks and escaped paths are rejected. The metrics file is limited to
2 MB; each declared artifact to 20 MB. Extra JSON fields are not treated as measured
metrics unless declared in the spec.

`job_status` distinguishes process completion from measured output:

- `completed` / exit code `0` describes the process only.
- `experimental_results.status = verified` means fresh metrics and artifact files were
  captured, finite metric values parsed, and unchanged declared dataset inputs checked.
- `invalid` records why a measured run failed validation, even if its command exited zero.
- `not_requested` describes a run without a structured spec.

Verified output does not prove scientific correctness, causal attribution, novelty,
statistical significance, or support for a hypothesis. These need additional review.
The recorded environment is host/launcher metadata; package versions, GPU details and
container content need explicit artifacts or further environment inspection.

## Compare runs

```json
{
  "baseline_job_ids": ["job_baseline_seed7", "job_baseline_seed19"],
  "candidate_job_ids": ["job_quadratic_seed7", "job_quadratic_seed19"]
}
```

`compare_experiments` rechecks completion, metric contents and dataset/artifact hashes
before reporting results. Changed output files are rejected. Runs must share the group,
dataset identity and hashes, split, protocol, metric definitions/units/directions and
primary metric. Each side must have one variant, fixed parameters and unique seeds.
Different algorithm parameters are allowed between baseline and candidate variants.

Incompatible conditions return `comparable: false` with the reasons and condition records.
Compatible runs return per-metric values, means, sample standard deviations, signed deltas,
direction-aware observed changes and deltas for matched seeds. Single runs and differing
seed sets receive warnings. Differences in recorded environments are also flagged.
These are descriptive comparisons; the tool does not infer significance or causation.

Snapshot hashes, parameters, environment facts and output hashes remain in the report.
They help users assess whether the comparison is appropriate; matching declared metadata
alone cannot guarantee the same actual evaluation implementation.

## Find and export results

`list_experiments` optionally filters by `group` and bounds the number of returned records.
`report_export` accepts the same baseline/candidate job IDs, plus `format` (`markdown` or
`json`) and optional `title`. It checks the comparison again, then writes a content-addressed
artifact under the project's `.research/artifacts` directory. It requires write permission
and returns the artifact ID, SHA-256, size and a bounded content preview. Use `read_artifact`
to read longer reports. Noncomparable reports preserve the rejection reasons.

## Validate code in the current project

`run_project_check` runs an approved test, build or lint command in the **original project
directory**. This makes an existing `.venv` or `node_modules` available. It accepts `argv`,
`cwd`, `kind` (`test`, `build`, `lint`, or `custom`), `timeout_seconds` and a required stable
`request_id`. It does not accept a scientific experiment spec.

```json
{
  "argv": [".venv/bin/python", "-m", "pytest", "tests"],
  "cwd": ".",
  "kind": "test",
  "timeout_seconds": 120,
  "request_id": "pytest-after-parser-change-1"
}
```

The command can modify the project and still needs execution opt-in and host approval;
read-only mode rejects it. Local mode uses the host environment with credential variables
filtered as for other jobs. Docker mode mounts the original directory and keeps its
existing network/resource restrictions; host-installed dependencies may not be compatible
with the container image. The backend retains a pre-run code snapshot and manifest while
excluding private state and dependency directories from that snapshot.

These jobs share status, logging, timeout, cancellation and idempotence with experiments.
`execution_mode = workspace_check` distinguishes them from `snapshot` runs. A successful
test/build is a process result, not scientific metric evidence. `read_job_file` reads the
retained pre-run snapshot; inspect generated workspace outputs through the project file
tools. Use a checkpoint or an isolated Git worktree before commands whose changes need
to be recoverable.

## Offline acceptance example

[`examples/experiment_lab`](../examples/experiment_lab) provides a dependency-free synthetic
regression lab with a linear baseline, a quadratic candidate and a deliberate negative
variant. Use the same seeds (for example 7 and 19) on each side. Automated tests execute the
actual programs, verify generated metrics, observe the candidate's improvement and the
negative variant's deterioration, then check tampering and incompatible-condition cases.

This fixture validates experiment mechanics. It is not a paper reproduction or a benchmark
of model research quality. Real paper cases and independently reviewed claims remain a
separate evaluation task.

## Current execution boundaries

Jobs remain owned by the foreground CLI/MCP process. Closing it cancels owned jobs;
unexpected exits mark unfinished records as `interrupted_unknown`. No saved PID is blindly
signalled or replayed. Background workers, reattachment, GPU/remote scheduling and checkpoint
recovery are not yet implemented. Snapshot limits and execution deadlines still apply.
