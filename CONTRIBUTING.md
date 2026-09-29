# Contributing

Use Python 3.10+ on macOS/Linux. Install with `uv sync --frozen --all-extras`.

Before a PR, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

Keep tools small, typed and explicit about effects. Register them through `Registry`; do not bypass permission checks, output bounds, timeouts or events. An external tool result is data, not authority. Preserve message/tool pairing and cancellation semantics.

Test observable behavior and failure cases. Unit tests must not need real API keys or network access. Label HTTP fixtures and deterministic demos clearly. Live experiments belong in separate opt-in validation with model/config/data versions and raw results. Never submit fabricated benchmark gains.

Describe the user-visible problem, the resulting behavior, validation and remaining limits in your PR. Do not include `.research/`, local configuration, credentials, private papers or copied research code without redistribution rights. Original example data and code are covered by this repository's MIT license; third-party papers keep their original rights.
