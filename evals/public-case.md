# Real public CPU case and agent-evaluation boundary

There are two independent evaluations:

1. `scripts/eval-research.ts` evaluates the actual Pi CLI/MCP/artifact path over 12 original synthetic research tasks. `--mock` scripts the model behavior; `--live` uses a real paid model only when explicitly requested.
2. `examples/public_research_case/run.py` executes real author code and a public dataset. It uses no model and does not measure agent quality.

## Research task suite

```sh
node --import tsx scripts/eval-research.ts --mock \
  --output evals/results/research-mock.json
```

The suite covers exact quotations, abstract/full-text boundaries, unverified repository authorship, active constraints, hypothesis status, measured baseline comparison, negative results, incompatible protocols, retry deduplication, malicious source text, code parameters and exported comparison reports. Papers and repository associations in these tasks are explicitly synthetic. Experiment metrics are produced by actual local Python runs rather than fabricated result records.

Memory off/on uses identical cloned initial state, model, tools, task prompts, permissions and budgets. Both arms can retrieve project memory explicitly. Arm order reverses on alternate repetitions. The mock plans call the same tools in both arms and are intended to pass equally. Any difference in mock scores is an implementation defect, not evidence of quality improvement.

The grader checks the final `evaluation-answer.json`, reference IDs, actual measured numerical values, constraints, duplicate experiment count and exported artifact provenance/hash. Suggested retrieval paths are recorded as advisory trajectory information; a correct answer may use already injected memory or choose another valid retrieval path. Explicit file-reading tasks still require the requested code/source to be read, and the retry task requires an observed successful deduplicated call. It saves raw events, mock request traces, project state, source files and final artifacts beside the report in a `.traces` directory. Expected answer values are held by the harness; the model-visible project guide contains record IDs only. Automatic field checks do not replace human citation/semantic review.

For actual model evaluation, set `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `RESEARCH_MODEL`, then explicitly run:

```sh
node --import tsx scripts/eval-research.ts --live --repetitions 3 \
  --output evals/results/research-live.json
```

This makes billable model requests and enables local execution in disposable fixture workspaces. Backend network tools remain disabled. It defaults to three repetitions and rejects smaller live reports. Specify capability/pricing profile values through the documented environment variables. Unknown model prices remain unknown in the report; Pi's numeric fallback cost is not reported as verified free usage. Provider billing and external-tool billing are distinct. No live-model score has been produced for this release.

Use `--cases exact-quote,baseline-comparison` for a selected subset. Reports publish attempted cases and repetitions, success counts, raw failures, tokens and elapsed times. A success rate from these synthetic tasks is not a general科研 success rate or a comparison against a tool-less agent.

## Public LIBSVM computation

The selected publication is Chang and Lin's 2011 [LIBSVM paper](https://doi.org/10.1145/1961189.1961199). The [authors' project page](https://www.csie.ntu.edu.tw/~cjlin/libsvm/) links the paper and the [author repository](https://github.com/cjlin1/libsvm). The case fixes commit `557d85749aaf0ca83fd229af0f00e4f4cb7be85c` and downloads only seven files with pinned SHA-256 values.

Code uses BSD-3-Clause and the downloaded COPYRIGHT file is retained. `heart_scale` is the small classification example bundled in the repository. This project asserts no separate dataset license and does not redistribute the dataset. URLs, code/data hashes, license and scope are recorded in [provenance.json](../examples/public_research_case/provenance.json).

Python 3.10+ and a C++ compiler are needed for this developer case:

```sh
python examples/public_research_case/run.py --download \
  --workdir /tmp/research-public-case
```

The runner verifies downloaded files, compiles the author's C++ training/prediction programs, and uses three stratified seeds with 189 training, 40 validation and 41 test rows per seed. Baseline uses an RBF kernel, C=1 and gamma=1/13. Candidate searches a fixed 16-pair grid using validation accuracy only; test scores are computed after selection. A deliberately poor parameter variant supplies a real negative result. No new algorithm or source-code improvement is claimed.

Actual local execution on Python 3.12.13/macOS arm64 produced:

| Variant | Test accuracy mean | Sample standard deviation | Seeds |
| --- | ---: | ---: | --- |
| Baseline | 0.8617886179 | 0.0372567130 | 0, 1, 2 |
| Validation-selected candidate | 0.8617886179 | 0.0372567130 | 0, 1, 2 |
| Deliberately poor parameters | 0.5609756098 | 0 | 0, 1, 2 |

The candidate yielded **no observed gain** on these splits. The result is retained rather than described as an improvement. [The observed result record](../examples/public_research_case/observed-results.json) stores per-seed metrics, parameters and data/code/model/split/prediction hashes. These are descriptive results on a tiny dataset; they do not establish statistical significance, clinical usefulness, novelty or reproduction of every result in the publication. In particular, this hold-out protocol does not reproduce the paper's Figure 3 cross-validation result.

The output directory contains commands, chosen parameters, all validation-grid scores, test predictions/models, split indices and hashes, per-run metrics, build information and `public-case-results.json`. Re-running without `--download` uses and re-verifies local cached source files. Use a fresh work directory when archiving another run.
