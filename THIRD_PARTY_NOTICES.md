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
