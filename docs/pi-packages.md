# Reusing Pi packages

Research CLI uses Pi packages for document parsing, OCR, delegated agent execution, web access and current library documentation. It keeps the research records that connect papers, source passages, hypotheses, repositories and experiments. A generic memory or background-process extension does not implement those relationships.

Document parsing, web access and Context7 were introduced in v0.4.0. Delegation and local OCR are available from v0.5.0, whose publication is in progress; see the [README](../README.md) for the public distribution status. Updating the source does not update an installed distribution; install the corresponding npm version or standalone release and check `research --version`.

The [Pi package catalog](https://pi.dev/packages) is a discovery directory for independently published packages. Catalog inclusion does not mean that the Pi maintainers wrote, reviewed or guaranteed a package. The decisions below are based on maintainer source, published manifests and the actual npm package contents, checked on 2026-10-01 against the project's Pi **0.99.1**.

## Packages used by the project

These dependencies are pinned in the npm lockfile and installed with Research CLI. Users do not need a separate global Pi installation or a separate MCP server for these native extensions.

| Package | Version / license | Reused capability | Relationship to the research service |
| --- | --- | --- | --- |
| [pi-subagents](https://github.com/nicobailon/pi-subagents) | 0.74.0 / MIT | Foreground in-process child executor, lifecycle/results, cancellation and timeout | A dedicated adapter supplies controlled Pi child sessions. Six role allowlists, shared parent tools/model/budget and management commands replace ambient discovery. The internal runner API is version/file-hash pinned and requires re-audit on upgrades. |
| [pi-docparser](https://github.com/maxedapps/pi-docparser) | 4.0.0 / MIT | Local document parsing through LiteParse 2.10.1 | Replaces the PDF extraction engine. Research CLI still saves durable source records, page/chunk locations, document hashes and evidence links. Parsing a document does not register a paper or confirm a research claim. |
| [pi-web-access](https://github.com/nicobailon/pi-web-access) | 0.35.0 / MIT | Web search, readable page retrieval and bounded retrieval from its content cache | Supplies general web tools directly in Pi. Its temporary cache and passage results do not replace the local paper library, Crossref/arXiv identities, pinned repository inspection or saved research evidence. |
| [@upstash/context7-pi](https://github.com/upstash/context7/tree/master/packages/pi) | 0.1.2 / MIT | Current library documentation and examples | Adds `resolve-library-id` and `query-docs` directly. Useful when reproducing code with version-sensitive APIs; separate from paper discovery and scientific literature comparison. |

The upstream `pi-docparser` package offers `document_parse`, `document_search` and `document_screenshot`; **Research CLI does not expose those three tools**. It reuses the package's native PDF executor through `import_document` and `download_arxiv`. OCR is optional for explicitly imported PDFs, with local verified English/Chinese language data; it remains off by default. Extraction preserves page positions and temporary parser outputs are removed after import. Source hashes, chunks, OCR provenance and evidence references remain research records. Ordinary PDF import limits are 20 MB, 200 pages and two million extracted characters; OCR is limited to 20 pages. Partial page extraction is rejected.

The adapter exposes exactly six native package tools, without an MCP prefix:

| Tool | Package | Local effect | Network |
| --- | --- | --- | --- |
| `web_search` | pi-web-access | `external` | Yes |
| `fetch_content` | pi-web-access | `external` | Yes |
| `get_search_content` | pi-web-access | `read` | No; reads cached results |
| `source_check` | pi-web-access | `external` | Yes |
| `resolve-library-id` | Context7 | `read` | Yes |
| `query-docs` | Context7 | `read` | Yes |

The default research MCP service still exposes **53 tools**; PDF extraction changed implementation, not its public import tool names. Alongside three Pi file tools, six package tools and four collaboration tools, v0.5.0 has **66 tools** online. Configured embeddings add two research MCP tools. Offline configuration and user-selected packages change the visible set.

`web_search` runs in the foreground with at most four queries, no summary-generation workflow and no background content fetching. `source_check` gathers search leads without automatically fetching result pages. `fetch_content` accepts one to five public HTTP(S) URLs in readable or raw mode. The adapter rejects curator, cookie/auth, model-answer, video and per-call proxy options, GitHub source URLs and explicit PDF/arXiv PDF URLs. Use `inspect_repository` / `read_repository_file` for pinned GitHub code, and `import_document` / `download_arxiv` for PDF evidence. General retrieval may encounter redirects or URLs whose content type is not indicated by their path; its output remains a lead rather than a saved page-aware research source. These restrictions do not turn the interactive CLI into a fixed research workflow.

### Accounts and runtime dependencies

| Component | Requirements and limits |
| --- | --- |
| Context7 | Native HTTP requests; no local server. `CONTEXT7_API_KEY` is optional for the upstream extension but recommended for authenticated quotas. Queries go to Context7; availability and quota are controlled by that service. |
| Web search | Provider availability, rate limits and charges depend on configuration. Upstream offers a keyless Exa route, which is still a remote service with limits. A DeepSeek model key does not grant access to unrelated search providers. |
| Local PDF/OCR parsing | LiteParse uses platform-specific native packages and needs no model key, external Tesseract executable or LibreOffice. Run `research ocr install` explicitly to install verified local data for optional OCR. Parsing never downloads missing data or invokes a cloud OCR server. |
| Other upstream document features | Many Office formats require LibreOffice. Those features and the native document tools are not enabled by this integration. |

Search results are leads. Import the source, read the relevant passage and save evidence before treating a result as support for a scientific claim. `source_check` structures retrieved leads and any supplied excerpts for review; it does not establish that a claim is true or that an experiment reproduces a paper.

## Reviewed alternatives

Versions in this table are the published versions examined during the audit. They are not automatic upgrade targets.

| Package | Version / license | Actual overlap | Decision and reason |
| --- | --- | --- | --- |
| [@ff-labs/pi-fff](https://github.com/dmtrKovalenko/fff/tree/main/packages/pi-fff) | 0.11.0 / MIT | `ffgrep`, `fffind` and `fff-multi-grep` overlap local file/content search. | Requires a dedicated adapter before replacement. Native dependencies need distribution testing; startup/lifecycle initialization is not supported by the generic tool-only loader. Default symlink, home-directory and outside-workspace scanning also need workspace limits. |
| [pi-cymbal](https://github.com/raphapr/pi-cymbal) | 0.7.0 / MIT | Code maps, symbols, references and impact analysis overlap `inspect_symbols` and add deeper navigation. | Optional candidate. Requires a separately installed Cymbal binary; the audited package documents v0.15.0. Cross-repository paths and index writes need explicit handling. Keep the Python symbol-inspection fallback. |
| [pi-lens](https://github.com/apmantza/pi-lens) | 4.3.0 / MIT | LSP, diagnostics and structural analysis overlap code inspection and parts of project checking. | Requires a dedicated adapter. Its TUI peer range covers 0.84–0.85 rather than 0.99.1, and lifecycle hooks run checks and formatting outside individual tool calls. Generic installation does not enable those hooks. It does not replace experiment protocols or metrics. |
| [pi-memory](https://github.com/jayzeng/pi-memory) | 0.4.2 / MIT | Markdown preferences, daily logs and optional qmd search resemble generic memory lookup. | Not a replacement for the research ledger. It lacks the project's evidence/job relationships, research record revisions and explicit human-review state. Default global storage, background qmd and exit-summary model calls require adaptation for project scope and budgets. |
| [pi-background-tasks](https://github.com/ismailsaleekh/pi-background-tasks) | 2.6.9 / ISC | Background process status, output and cancellation resemble experiment jobs. | Keep the research job implementation. The package's Pi/TUI peer ranges end at 0.84; ordinary `bg_run` is a local shell command rather than the project's structured experiment execution and result comparison. |
| [pi-subagents](https://github.com/nicobailon/pi-subagents) | 0.74.0 / MIT | Delegation is additional capability; background agents are not scientific experiment jobs. | Foreground executor is integrated through a dedicated controlled-session adapter. Background fleets, nested delegation, upstream ambient agents and workflows are not exposed. See [collaboration](collaboration.md). |
| [@juicesharp/rpiv-ask-user-question](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-ask-user-question) | 2.12.0 / MIT | `ask_user_question` adds structured terminal questions. | Candidate for explicitly selected tool use, after testing its UI path. No equivalent research MCP tool needs removal. Generic installation does not enable sibling hooks, commands or providers. Consider optional i18n and external-editor behavior during review. |
| [@juicesharp/rpiv-todo](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-todo) | 2.12.0 / MIT | `todo` and `/todos` provide a session task overlay upstream. | Needs an adapter for the full session overlay: generic loading suppresses commands and lifecycle hooks. A checklist does not replace durable reproduction plans, stage updates or experiment records. |
| [@langfuse/pi-observability-plugin](https://github.com/langfuse/pi-observability-plugin) | 0.1.2 / MIT | Tracing overlaps viewing usage, but includes much more conversation and tool data. | Requires a dedicated opt-in adapter, not generic tool installation. Telemetry uses lifecycle hooks, which the generic loader suppresses. Requires credentials and uploads trace data. Keep local usage records and budget enforcement. |

A permissive peer dependency such as `"*"` expresses an installation range, not a compatibility test. The project must verify an extension with its pinned Pi version and supported operating systems before making it a default dependency. The [upstream package documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md) explains Pi's package mechanism.

## What remains in the research service

The service retains paper identity and deduplication, source imports and page-aware evidence, paper/repository associations, revisioned research memory, reproduction plans, structured experiment protocols and results, data migration and backup. These are research data operations rather than general-purpose Pi UI features.

Replacing an extraction engine or adding web search does not invalidate existing `.research` records. Preserve IDs and source references when changing an implementation. Do not delete a public record-management tool merely because another package uses words such as “memory”, “research” or “background”.

## Installation and explicit activation

Research CLI manages user-selected packages separately from ambient Pi configuration. Its package commands use Pi's package manager with `--ignore-scripts`: npm lifecycle scripts are skipped. Packages that require an install-time build or binary download may therefore need additional preparation. The built-in packages are managed with the Research CLI version and cannot be replaced or removed through the user-package command.

Install an exact version first. **A new package installed without a policy is disabled.** Reinstalling the same already configured source without `--policy` preserves its existing policy; use the manifest's `enabled: false` to disable that entry.

```sh
research packages list
research packages install npm:@juicesharp/rpiv-ask-user-question@2.12.0
```

For a reviewed questionnaire extension, an example `ask-user-policy.json` selects its declared entry and exact tool:

```json
{
  "extensions": ["index.ts"],
  "skills": [],
  "effects": { "ask_user_question": "read" },
  "networkTools": []
}
```

The empty `networkTools` list is an explicit assertion about the reviewed tool, not a general default for third-party packages. Confirm the package's current behavior before adopting that policy.

```sh
research packages install npm:@juicesharp/rpiv-ask-user-question@2.12.0 --policy ./ask-user-policy.json
research packages list
research
research packages remove npm:@juicesharp/rpiv-ask-user-question@2.12.0
```

Restart Research CLI after changing package selection. Removal drops the selected manifest entry and managed installation; explicitly selected local source directories are preserved.

Accepted sources are `npm:package@1.2.3`, `git:https://host/owner/repository@FULL_40_CHARACTER_COMMIT` and explicit local directories such as `./my-extension`. npm tags/ranges and mutable Git branch names are rejected. Selecting a local directory does not freeze its contents.

### Manifest format

The default user manifest is `~/.config/research-cli/packages.json`, respecting `XDG_CONFIG_HOME`. Its exact schema is:

```json
{
  "version": 1,
  "packages": [
    {
      "source": "npm:@juicesharp/rpiv-ask-user-question@2.12.0",
      "enabled": true,
      "extensions": ["index.ts"],
      "skills": [],
      "effects": { "ask_user_question": "read" },
      "networkTools": []
    }
  ]
}
```

Only those fields are accepted; at most 16 user packages may be selected. `extensions` and `skills` contain exact package-relative resource paths, without globs or traversal. Extension files must be declared by the package's Pi manifest. Each enabled extension needs an exact `effects` allowlist, and duplicate/core/MCP tool names are rejected.

When `networkTools` is omitted, **every allowlisted tool is treated as networked**. `--offline` excludes those tools and prevents their wrappers from running; declaring `networkTools: []` is only appropriate after verifying that the selected tools do not contact a service. `read` and `network` are independent: the built-in Context7 tools are read operations that still use the network.

Select a different installed-package manifest explicitly with:

```sh
research --package-config /absolute/path/to/packages.json
```

`RESEARCH_PACKAGE_CONFIG` is the equivalent environment variable. This flag selects launch-time configuration; `research packages install/list/remove` manage the default user manifest. Startup resolves already installed packages and never downloads a missing package automatically.

Effects use the research categories `read`, `write`, `execute` and `external`. Each tool requires an exact entry; execution also requires the Research CLI execution mode. Native tools do not need an additional MCP server definition. Package calls receive a 60-second cancellation scope and selected remote/service calls append usage events; unknown third-party cost remains unknown.

### Tool-only compatibility

The generic adapter captures selected tools. It suppresses package slash commands, shortcuts, flags, providers, MCP server registration, dynamic tool registration and generic lifecycle hooks. Only reviewed session/cache cleanup hooks from bundled `pi-web-access` are retained. Installing an extension does not enable an upstream `/todos` UI, multi-agent workflow, provider integration or telemetry plugin automatically. Packages that rely on those interfaces require a dedicated adapter.

Pi packages still run code in the CLI process. The API adapter and effect declarations do not sandbox arbitrary JavaScript imports or direct filesystem/network access. Review source and configuration before activation; a false `read` declaration cannot make a mutating implementation read-only. Keep credentials in environment variables or private user configuration, and preserve dependency lockfiles and upstream license files in distributions.

Running `pi install` changes a separate Pi installation's configuration. Research CLI only loads its built-in adapters and explicitly selected package manifest; an ambient Pi installation alone does not activate an extension in `research`.

## Managed state and existing sessions

The default Pi state and managed package directory is `~/.local/share/research-cli/pi-packages`, respecting `XDG_DATA_HOME`. This separates Research CLI's sessions, authentication and package runtime from an ordinary Pi installation. Research data remains in the selected workspace's `.research` directory.

Older Research CLI sessions under `~/.pi/agent` are retained but are not copied or automatically listed in the new state directory. Open a known old session file explicitly:

```sh
research --session /absolute/path/to/old-session.jsonl
```

Alternatively, use the old Pi state for a launch:

```sh
PI_CODING_AGENT_DIR="$HOME/.pi/agent" research
```

The explicit environment override changes Pi state discovery; user-package installation still uses the Research CLI managed package directory. Ambient extension loading remains disabled.

## Source and license records

The adopted versions are recorded in `package.json` and `package-lock.json`. Attribution and redistribution information is in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). In particular, `pi-docparser` is MIT but its parser dependency [LiteParse 2.10.1](https://github.com/run-llama/liteparse) is Apache-2.0. The dependency's license and notices remain applicable to its native runtime and distribution.
