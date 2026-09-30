---
name: reproduction
description: Run bounded, traceable experiments and retain negative results without imposing a fixed research sequence.
---

Inspect project constraints and existing jobs before proposing an experiment. Establish baseline, dataset split, seeds, metrics and expected resource use with the user. Use run_experiment with an explicit request_id and argv. Reuse the same request_id if a request may already have run. Inspect job_status after reconnecting; never equate interrupted_unknown with failure to start. Use a new request_id only for an intentional new run. Save source/commit associations, snapshot hash, parameters, outputs and negative results. A passing smoke test does not establish paper reproduction. A completed job only establishes process completion; inspect its actual metrics. Cancellation and timeouts must remain visible in the ledger.
