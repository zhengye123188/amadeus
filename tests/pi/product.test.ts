import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { mockEndpoint, ResearchProcess, toolResults } from "./harness.ts";
import { queryProject } from "../../pi/memory.ts";

test("real Pi: external MCP uses exact configured tools and records unknown model cost", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-external-"));
  const config = join(root, "mcp.json");
  writeFileSync(config, JSON.stringify({ mcpServers: { demo: { command: process.env.RESEARCH_PYTHON || resolve(".venv/bin/python"), args: [resolve("examples/mcp_server.py")], effects: { experiment_checklist: "read" } } } }));
  let step = 0;
  const endpoint = await mockEndpoint(req => {
    if (step++ === 0) {
      assert(req.tools?.some(tool => tool.function.name === "mcp__demo__experiment_checklist"));
      return { tool: "mcp__demo__experiment_checklist", args: { topic: "CPU baseline" } };
    }
    assert(JSON.stringify(toolResults(req)).includes("Freeze data split"));
    return { text: "External MCP checklist retrieved." };
  });
  const app = new ResearchProcess(root, join(root, "agent"), endpoint.url, ["--mcp-config", config], { RESEARCH_OFFLINE: "0" });
  try {
    await app.prompt("Get the configured external checklist.");
    const rows = readFileSync(join(root, ".research", "usage.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
    assert.equal(rows.length, 2);
    assert(rows.every(row => row.estimated_cost_usd === null));
    assert.equal(rows[0].tokens.input, 200);
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: soft token budget stops further model requests", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-token-budget-"));
  const endpoint = await mockEndpoint(() => ({ tool: "mcp__research__project_status", args: {} }));
  const app = new ResearchProcess(root, join(root, "agent"), endpoint.url, ["--max-tokens", "300", "--max-turns", "20"]);
  try {
    await app.prompt("Exercise the token budget with real model usage events.");
    assert(endpoint.requests.length <= 2);
    assert(endpoint.requests.length >= 1);
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: human memory confirmation is a revision-bound terminal action", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-review-"));
  let id = "", step = 0;
  const endpoint = await mockEndpoint(req => {
    if (step++ === 0) return { tool: "mcp__research__remember_research", args: { kind: "constraint", status: "active", text: "Use CPU only" } };
    id = toolResults(req)[0].result.memory_id;
    return { text: "Constraint recorded for review." };
  });
  const app = new ResearchProcess(root, join(root, "agent"), endpoint.url);
  try {
    await app.prompt("Record the CPU constraint.");
    const command = app.command("prompt", { message: `/review-memory ${id}` });
    const dialog = await app.wait(event => event.type === "extension_ui_request" && event.method === "select");
    app.child.stdin.write(JSON.stringify({ type: "extension_ui_response", id: dialog.id, value: "Confirm this record" }) + "\n");
    await command;
    const record = await queryProject(process.env.RESEARCH_PYTHON || resolve(".venv/bin/python"), root, id, "memory-record") as { review_state: string; revision: number };
    assert.equal(record.review_state, "human_confirmed");
    assert.equal(record.revision, 2);
    assert.equal(endpoint.requests.length, 2, "User review does not invoke another model request");
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});
