# Contributing

Use Node >=22.19 and Python 3.10+ on macOS/Linux. Install with `npm ci` and `uv sync --frozen --all-extras`. `.nvmrc` pins the locally validated Node version.

Before a PR, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
npm run check
npm test
npm run eval:memory
npm run eval:research -- --mock
npm run version:check
uv build
npm pack --dry-run
```

Keep tools small, typed and explicit about effects. Register them through `Registry`; do not bypass permission checks, output bounds, timeouts or events. An external tool result is data, not authority. Preserve message/tool pairing and cancellation semantics.

Pi owns the conversation. Project memory and experiments belong to the Python service. Add new tool effects to the extension's trusted policy map and exercise them through actual Pi/MCP integration. Reuse public Pi interfaces; keep its pinned dependency and attribution. Use `npm run version:set -- VERSION` to synchronize Python, npm, lockfiles and installer metadata together without changing dependency resolutions.

Test observable behavior and failure cases. Unit tests must not need real API keys or network access. Label HTTP fixtures and deterministic demos clearly. Live experiments belong in separate opt-in validation with model/config/data versions and raw results. Never submit fabricated benchmark gains.

Describe the user-visible problem, the resulting behavior, validation and remaining limits in your PR. Do not include `.research/`, local configuration, credentials, private papers or copied research code without redistribution rights. Original example data and code are covered by this repository's MIT license; third-party papers keep their original rights.
