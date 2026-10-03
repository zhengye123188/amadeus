# Contributing

Use Node >=22.19 and Python 3.10+ on macOS/Linux. Install with `npm ci` and `uv sync --frozen --all-extras`. `.nvmrc` pins the locally validated Node version.

Before a PR, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
npm run check
npm test
uv run python scripts/smoke_ui.py
npm run eval:memory
npm run eval:research -- --mock
npm run version:check
uv build
npm pack --dry-run
```

Keep tools small, typed and explicit about effects. Register them through `Registry`; do not bypass permission checks, output bounds, timeouts or events. An external tool result is data, not authority. Preserve message/tool pairing and cancellation semantics.

Pi owns the conversation. Project memory and experiments belong to the Python service. Add new tool effects to the extension's trusted policy map and exercise them through actual Pi/MCP integration. Reuse public Pi interfaces; keep its pinned dependency and attribution. Use `npm run version:set -- VERSION` to synchronize Python, npm, lockfiles and installer metadata together without changing dependency resolutions.

The branded terminal uses the public Pi SDK and extension UI APIs. Keep `pi-tui` aligned with the pinned coding-agent version, and resolve the host terminal package from coding-agent's public package entry so it shares the extension's runtime state. Preserve `CustomEditor` input handling, cursor markers, dialogs and cancellation. Run the isolated PTY smoke when changing startup, editor or session behavior; it uses a local model fixture and temporary user state. UI customization is described in [docs/ui.md](docs/ui.md).

Test observable behavior and failure cases. Unit tests must not need real API keys or network access. Label HTTP fixtures and deterministic demos clearly. Live experiments belong in separate opt-in validation with model/config/data versions and raw results. Never submit fabricated benchmark gains.

Describe the user-visible problem, the resulting behavior, validation and remaining limits in your PR. Do not include `.research/`, local configuration, credentials, private papers or copied research code without redistribution rights. Original example data and code are covered by this repository's MIT license; third-party papers keep their original rights.
