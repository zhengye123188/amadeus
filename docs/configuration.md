# Model configuration and endpoint diagnosis

`research configure` saves an OpenAI-compatible endpoint, API key, model ID and protocol in the user configuration directory. The key is entered without echo and saved in an owner-readable file. Environment variables override saved API settings.

```sh
research configure
research doctor
research doctor --check-api
```

The default doctor command checks local runtimes and backend imports. `--check-api` explicitly sends a `GET /models` to the configured base URL with the configured key. It does not generate text. It checks endpoint access and, if a model list is returned, whether the configured model is listed. A provider may not implement this endpoint or may list only part of its catalog. Passing this check does not validate tool calling, image input, reasoning or model quality. Error response bodies and keys are not printed; authenticated redirects are not followed.

## Model capability profiles

Select a JSON file explicitly with `--model-profile FILE` or `RESEARCH_MODEL_PROFILE`. A profile describes the capabilities and prices of the chosen model; it does not grant capabilities that the provider lacks. Verify values against your provider's documentation.

```json
{
  "model": "your-model-id",
  "contextWindow": 65536,
  "maxTokens": 8192,
  "reasoning": false,
  "input": ["text"],
  "prices": {
    "input": null,
    "output": null,
    "cacheRead": null,
    "cacheWrite": null
  }
}
```

```sh
research --model-profile /path/to/model.json
research doctor --model-profile /path/to/model.json
```

Prices are USD per million tokens. Omitted or `null` prices mean **unknown**. A value of `0` means an explicitly configured zero price. Partial price configuration can produce an estimate only for usage categories whose prices are known. Provider bills and external embedding/reranking charges remain separate. Pi requires numeric provider prices; an adapter fallback of zero does not prove that a call is free.

Defaults are a 32768-token context, a 4096-token output limit, text input and no reasoning capability. Override individual values with:

| Environment variable | Meaning |
| --- | --- |
| `RESEARCH_CONTEXT_WINDOW` | Context capacity, 8192–2000000 tokens |
| `RESEARCH_MAX_OUTPUT_TOKENS` | Maximum output tokens, at most context capacity |
| `RESEARCH_REASONING` | `true` or `false` |
| `RESEARCH_INPUT` | `text` or `text,image` |
| `RESEARCH_INPUT_PRICE` | Input token price |
| `RESEARCH_OUTPUT_PRICE` | Output token price |
| `RESEARCH_CACHE_READ_PRICE` | Cache-read token price |
| `RESEARCH_CACHE_WRITE_PRICE` | Cache-write token price |

`RESEARCH_MODEL` and the model saved by `research configure` take precedence over the profile's optional `model`. Use `RESEARCH_MODEL` to change the active model explicitly. A Pi `--model` argument also selects the active model. Endpoint credentials belong in environment variables or `research configure`, rather than a model profile committed to a repository.

## Explicit external MCP configuration

Use `research --mcp-config /path/to/mcp.json` or `RESEARCH_MCP_CONFIG`. Ambient project MCP discovery remains disabled. This is a trusted user-selected configuration: a stdio server starts a process with the current user's access, so review its command and source before selecting the file.

```json
{
  "mcpServers": {
    "papers": {
      "command": "node",
      "args": ["/path/to/papers-server.mjs"],
      "env": { "PAPERS_TOKEN": "${PAPERS_TOKEN}" },
      "timeout": 60,
      "effects": {
        "search": "read",
        "download": "external"
      }
    },
    "docs": {
      "url": "https://example.org/mcp",
      "headers": { "Authorization": "Bearer ${DOCS_TOKEN}" },
      "effects": { "lookup": "read" }
    }
  }
}
```

Every callable tool requires an exact local `effects` entry: `read`, `write`, `execute` or `external`. Tools outside this allowlist remain hidden and unauthorized. Remote tool annotations do not set local permissions. The permission mode applies to allowlisted tools; `execute` also requires execution to be enabled. Label a tool `read` only if you trust it to have that effect; the declaration cannot sandbox a remote server or process.

The name `research` is reserved. Wildcard effects, command-based `!cmd` value interpolation and ambiguous tool-name aliases are rejected. Environment/header values support `${NAME}` for present environment variables. Keep tokens outside the JSON file. HTTP and stdio connection management uses Pi's native MCP adapter and `/mcp` interface.

## Usage, budgets and selected project instructions

`/usage` summarizes local model usage and separately recorded embedding/Jev usage. Unknown prices remain unknown. Model requests, including custom compaction calls, append numeric entries to `.research/usage.jsonl`; prompts and credentials are excluded. External MCP billing is not automatically available. Local estimates are not provider invoices.

`--max-tokens N` (default 60000) and `--max-cost-usd N` are soft per-prompt limits. A completed/in-flight request can exceed the limit; the CLI cancels further model requests after recording its usage. A cost limit requires all four profile prices. These limits do not cap external service bills.

Use `--instructions ./AGENTS.md` to select project guidance and `--skill ./skills/my-skill` to select a skill. Ambient discovery stays disabled. Explicit configuration files are protected from model file tools. Instructions apply alongside the user's current question and never turn the CLI into a fixed workflow.

Use `/review-memory mem_...` to inspect a record and explicitly confirm it or request revision. The action requires an interactive writable session and the displayed revision; it is not exposed as a model tool. Later edits reset that confirmation. Human confirmation records a review decision, not independent scientific replication.

## Version management

From the source checkout:

```sh
node scripts/version.mjs --check
node scripts/version.mjs 0.3.0
uv lock --check
npm run check
npm test
```

The synchronization command updates npm metadata, the root npm lock record, Python metadata and module version, the local project record in `uv.lock`, and the standalone downloader version. Dependency resolutions remain unchanged. CI checks all versions and derives the npm tarball filename from `npm pack --json` metadata.

Updating GitHub source, publishing npm, publishing PyPI and building standalone release assets are distinct actions. A version bump prepares metadata; it does not publish a package or update an existing user's installation.
