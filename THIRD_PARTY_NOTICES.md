# Third-party attribution

Research CLI is an independent project built on **Pi**, maintained by Mario Zechner and the Pi contributors.

- Upstream: https://github.com/earendil-works/pi
- Package: `@earendil-works/pi-coding-agent`, pinned to `0.99.1`
- License: MIT (see the upstream repository and installed package notices)
- Reused: terminal UI, model/provider integration, agent loop, session management and native MCP integration.

Pi is installed as an npm dependency. This repository does not vendor its implementation. Upstream functionality is not claimed as original Research CLI work. Original work here includes the Python research service, evidence/memory model, extension policy and context integration, experiment ledger and evaluations.

Python and other npm dependencies retain their own licenses; inspect `uv.lock`, `package-lock.json` and the installed distributions for the complete dependency set. User-imported papers, datasets and third-party repository code remain subject to their own licenses and access conditions. Synthetic evaluation fixtures in this repository are original project material, not copied publications or empirical scientific results.

Standalone installers redistribute the official Node.js binary distribution (including its LICENSE), an Astral python-build-standalone CPython distribution (including its license files), and the locked npm/Python runtime packages with their distribution metadata and license files. Runtime versions, source URLs and SHA-256 checksums are recorded in `packaging/runtimes.json` and each bundle's `bundle.json`. Sources: https://nodejs.org/ and https://github.com/astral-sh/python-build-standalone. These components remain third-party work and are not relicensed as original Research CLI code.

Intel Mac bundles build the locked cryptography source distribution with a statically linked, checksum-pinned OpenSSL. Its Apache-2.0 license is included as `licenses/openssl.txt`; source version and digest appear in the bundle manifest. OpenSSL source: https://github.com/openssl/openssl.

The optional [public CPU case](examples/public_research_case/README.md) downloads selected files from the authors' LIBSVM repository at a pinned commit. LIBSVM code is BSD-3-Clause; the runner retains its COPYRIGHT file. The upstream `heart_scale` dataset is downloaded separately, with no separate dataset license asserted here. No upstream source or dataset is redistributed in this repository or its packages. See [case provenance](examples/public_research_case/provenance.json) for URLs, hashes and scope.

## Reused Pi packages

Research CLI reuses the following independently maintained npm packages. Listing a package in the Pi catalog does not make it Pi-authored or imply an endorsement by Pi's maintainers.

| Package | Pinned version | Author / source | License | Reused work |
| --- | --- | --- | --- | --- |
| `pi-subagents` | 0.74.0 | Nico Bailon / [nicobailon/pi-subagents](https://github.com/nicobailon/pi-subagents) | MIT | Foreground in-process child executor, lifecycle/results, cancellation and timeouts, through a version/file-hash-pinned internal API adapter. Upstream full extension and workflows are not loaded. |
| `pi-docparser` | 4.0.0 | Maximilian Schwarzmüller / [maxedapps/pi-docparser](https://github.com/maxedapps/pi-docparser) | MIT | Native PDF executor and isolated LiteParse worker implementation; the package's three document tools are not exposed by Research CLI. |
| `pi-web-access` | 0.35.0 | Nico Bailon / [nicobailon/pi-web-access](https://github.com/nicobailon/pi-web-access) | MIT | Native Pi web search, content retrieval and search-content cache tools. |
| `@upstash/context7-pi` | 0.1.2 | Upstash / [upstash/context7, packages/pi](https://github.com/upstash/context7/tree/master/packages/pi) | MIT | Native library ID resolution and current documentation tools. |

These packages and their dependency implementations remain upstream work. Research CLI supplies the selected-package configuration, tool-only adapter, research policy integration and durable research records around them. No upstream package is claimed as an original Research CLI implementation. Exact resolved dependencies are recorded in `package-lock.json`; installed runtime distributions retain their bundled licenses and notices. These source-tree integrations do not imply that a new Research CLI distribution has already been published.

### LiteParse

`pi-docparser` 4.0.0 depends on **`@llamaindex/liteparse` 2.10.1**, developed by LlamaIndex and distributed under the **Apache License 2.0**. Research CLI uses that dependency for local document extraction through the upstream worker; the dependency includes platform-specific native packages. LiteParse and its native dependencies are not relicensed under Research CLI's MIT license.

- Source: https://github.com/run-llama/liteparse
- License: https://github.com/run-llama/liteparse/blob/main/LICENSE
- Upstream adapter notices: https://github.com/maxedapps/pi-docparser/blob/main/THIRD_PARTY_NOTICES.md
- Adapter-distributed Apache-2.0 license copy: `node_modules/pi-docparser/licenses/LiteParse-APACHE-2.0.txt`

Redistributions must retain the applicable upstream license files and any notices supplied by these distributions, including the license files in `pi-docparser`, `@llamaindex/liteparse` and the selected native package. Standalone bundles include the locked installed npm runtime tree with those files. Inspect each installed distribution for its additional native-library attribution; this summary does not replace its full notices.

Optional user-installed packages are governed by their own licenses. Research CLI's package audit and selection rationale are documented in [docs/pi-packages.md](docs/pi-packages.md).

### Tesseract language data

Optional OCR uses official [tesseract-ocr/tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) language models at commit `87416418657359cb625c412a48b6e1d6d41c29bd`, under Apache-2.0. Explicit `research ocr install` downloads `eng`, `chi_sim` and/or `chi_tra` with pinned size/SHA-256 verification. Standalone builds include all three models, model provenance and the pinned upstream license in `licenses/tessdata-fast.txt`. The npm package contains the downloader and manifest rather than the model data. Parsing does not download missing models. Full model/license hashes are recorded in `bin/ocr.mjs` and the standalone manifest; the Apache-2.0 license is not replaced by this project's MIT license.
