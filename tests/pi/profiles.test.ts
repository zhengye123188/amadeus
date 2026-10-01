import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadTrustedMcpConfig } from "../../pi/profiles.ts";

test("external MCP profiles expose only exact local allowlisted tools", () => {
  const root = mkdtempSync(join(tmpdir(), "research-mcp-profile-"));
  const file = join(root, "mcp.json");
  try {
    writeFileSync(file, JSON.stringify({ mcpServers: {
      papers: { command: "node", args: ["server.mjs"], env: { ACCESS_TOKEN: "${PAPERS_TOKEN}" }, effects: { search: "read", download: "external" } },
      docs: { url: "https://docs.test/mcp", headers: { Authorization: "Bearer ${DOCS_TOKEN}" }, effects: { lookup: "read" } },
    }}));
    const loaded = loadTrustedMcpConfig(file, root, { PAPERS_TOKEN: "fixture-paper", DOCS_TOKEN: "fixture-docs" });
    assert.equal(loaded.servers.length, 2);
    assert.equal(loaded.servers[0].config.exposure, "hidden");
    assert.deepEqual(loaded.servers[0].config.toolExposure, { search: "direct", download: "direct" });
    assert.equal(loaded.effects.mcp__papers__search, "read");
    assert.equal(loaded.effects.mcp__papers__delete, undefined);
    const config = loaded.servers[0].config;
    assert.equal("env" in config && config.env?.ACCESS_TOKEN, "fixture-paper");
    assert.throws(() => loadTrustedMcpConfig(file, root, {}), /environment variable/);
    assert.deepEqual(loadTrustedMcpConfig(undefined, root), { servers: [], effects: {} });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("external MCP profiles reject reserved servers, wildcard permissions and command interpolation", () => {
  const root = mkdtempSync(join(tmpdir(), "research-mcp-profile-bad-"));
  const file = join(root, "mcp.json");
  const invalid = [
    { research: { command: "node", effects: { search: "read" } } },
    { custom: { command: "node", effects: { "*": "read" } } },
    { custom: { command: "node", effects: { "dotted.tool": "read" } } },
    { custom: { command: "node", effects: { search: "read" }, env: { SECRET: "!cat credential" } } },
    { custom: { url: "https://user:private-fixture@docs.test/mcp", effects: { search: "read" } } },
    { custom: { command: "node" } },
  ];
  try {
    for (const mcpServers of invalid) {
      writeFileSync(file, JSON.stringify({ mcpServers }));
      assert.throws(() => loadTrustedMcpConfig(file, root), error => error instanceof Error && !error.message.includes("private-fixture"));
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});
