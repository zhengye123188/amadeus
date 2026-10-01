# Pinned LIBSVM CPU case

This runs the published authors' implementation on the bundled `heart_scale` example. All upstream files are downloaded from an immutable commit and verified against [provenance.json](provenance.json). Source/data downloads are explicit; no upstream code or data is copied into this repository.

```sh
python examples/public_research_case/run.py --download --workdir /tmp/research-public-case
```

Requirements: Python 3.10+ and `c++`. Re-run with the same work directory and omit `--download` to use verified files already present. You may also select `--variant baseline|tuned|negative` and `--seeds 0 1 2`.

Each seed uses identical stratified training/validation/test indices across variants. Candidate parameter selection sees validation labels only. Outputs include generated predictions, models, split indices, code/data hashes, command logs and measured metrics. The intentionally poor variant records a negative result.

See [evaluation scope and actual local results](../../evals/public-case.md). This is a small parameter-selection computation with public author code, not a full-paper reproduction, new algorithm or agent-quality benchmark. The local test observed no accuracy improvement from the candidate grid.
