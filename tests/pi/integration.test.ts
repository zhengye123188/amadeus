import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mockEndpoint, ResearchProcess, toolResults, type Reply } from "./harness.ts";
import { MEMORY_MARKER } from "../../pi/memory.ts";

test("real Pi: MCP tools, exact evidence, memory, compaction and session resume", { timeout: 90000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-pi-")), workspace = join(root, "work"), agentDir = join(root, "agent");
  mkdirSync(workspace); mkdirSync(agentDir);
  writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ compaction: { enabled: false, reserveTokens: 4096, keepRecentTokens: 100 }, retry: { enabled: false } }));
  writeFileSync(join(workspace, "paper.txt"), "Fixture paper: Negative results must be recorded. Code: https://github.com/example/baseline");
  let phase = "tools", step = 0;
  const endpoint = await mockEndpoint(req => {
    if (!req.tools?.length) return { text: "Fixture summary intentionally omits project constraints." };
    if (phase !== "tools") return { text: "Fixture continuation." };
    const results = toolResults(req);
    const next = step++;
    if (next === 0) {
      assert(req.tools.some(t => t.function.name === "mcp__research__import_document"), "MCP tools are model-visible");
      assert(req.tools.some(t => t.function.name === "mcp__research__search_code"), "Workspace search is model-visible");
      return { tool: "mcp__research__import_document", args: { path: "paper.txt" } };
    }
    if (next === 1) return { tool: "mcp__research__search_library", args: { query: "negative results" } };
    if (next === 2) return { tool: "mcp__research__save_evidence", args: { chunk_id: results[1].result.matches[0].chunk_id, quote: "Negative results must be recorded.", claim: "Retain negative results", relation: "context" } };
    if (next === 3) return { tool: "mcp__research__remember_research", args: { kind: "constraint", status: "active", text: "Use CPU only. Do not upload private data.", evidence_ids: [results[2].result.evidence_id] } };
    return { text: "Fixture completed: actual Pi tool loop and MCP backend ran." };
  });
  let app = new ResearchProcess(workspace, agentDir, endpoint.url);
  try {
    await app.prompt("Import paper.txt, record the exact evidence and remember the CPU constraint.");
    const results = app.events.filter(e => e.type === "tool_execution_end");
    assert.equal(results.length, 4, JSON.stringify(app.events));
    assert(results.every(e => !e.isError), JSON.stringify(results));
    const state = await app.command("get_state");
    phase = "continue";
    const compacted = await app.command("compact");
    assert(JSON.stringify(compacted).includes("CPU only"), JSON.stringify(compacted));
    assert(JSON.stringify(compacted).includes("quote_verified"));
    await app.prompt("Continue after compaction.");
    assert(JSON.stringify(endpoint.requests.at(-1)).includes(MEMORY_MARKER));
    assert(JSON.stringify(endpoint.requests.at(-1)).includes("CPU only"));
    await app.close();
    app = new ResearchProcess(workspace, agentDir, endpoint.url, ["--session", state.sessionFile]);
    await app.prompt("Resume and recover the evidence.");
    assert(JSON.stringify(endpoint.requests.at(-1)).includes("Negative results must be recorded."));
    assert(JSON.stringify(endpoint.requests.at(-1)).includes("quote_verified"));
    const commands = await app.command("get_commands");
    assert(commands.commands.some((c: any) => c.name === "memory"));
    assert(commands.commands.some((c: any) => c.name === "skill:research-evidence"), JSON.stringify(commands));
    const forkable = await app.command("get_fork_messages");
    assert(forkable.messages.length);
    const fork = await app.command("fork", { entryId: forkable.messages.at(-1).entryId });
    assert.equal(fork.cancelled, false);
    await app.prompt("Continue on the new branch; recover shared project evidence.");
    assert(JSON.stringify(endpoint.requests.at(-1)).includes("quote_verified"));
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: approved experiment, retry deduplication, cancellation and loop budget", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-jobs-"));
  let n = 0;
  let id = "";
  const endpoint = await mockEndpoint(req => {
    const results = toolResults(req);
    if (n++ < 2) return { tool: "mcp__research__run_experiment", args: { request_id: "same-request", argv: ["/bin/sh", "-c", "sleep 30"], cwd: ".", timeout_seconds: 40 } };
    if (n === 3) {
      assert(results[0].ok && results[1].ok, JSON.stringify(results));
      id = results[0].result.job_id;
      assert.equal(results[1].result.job_id, id);
      assert.equal(results[1].result.deduplicated, true);
      return { tool: "mcp__research__cancel_job", args: { job_id: id } };
    }
    if (n === 4) { assert.equal(results[2].result.status, "cancelled"); return { text: "Actual local process cancelled." }; }
    // A second prompt intentionally requests tools forever; max-turns must stop it.
    return { tool: "mcp__research__project_status", args: {} };
  });
  const app = new ResearchProcess(root, join(root, ".pi-test-agent"), endpoint.url, ["--execution", "local", "--approve-experiments", "--max-turns", "6"]);
  try {
    await app.prompt("Run the cancellation fixture.");
    assert(id.startsWith("job_"));
    const count = endpoint.requests.length;
    await app.prompt("Exercise the bounded tool loop fixture.");
    assert(endpoint.requests.length - count <= 7, "The step budget bounds provider requests");
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: headless write denial and builtin path guard", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-deny-"));
  writeFileSync(join(root, ".env"), "PRIVATE_FIXTURE_DO_NOT_READ");
  let n = 0;
  const endpoint = await mockEndpoint((): Reply => {
    if (n++ === 0) return { tool: "read", args: { path: ".env" } };
    if (n === 2) return { tool: "mcp__research__remember_research", args: { kind: "constraint", status: "active", text: "Must be denied" } };
    return { text: "Finished denial fixture" };
  });
  const app = new ResearchProcess(root, join(root, "agent"), endpoint.url, ["--permission", "read-only"]);
  try {
    await app.prompt("Exercise permission guards.");
    const results = app.events.filter(e => e.type === "tool_execution_end");
    assert.equal(results.length, 2);
    assert(results.every(e => e.isError));
    assert(!JSON.stringify(endpoint.requests).includes("PRIVATE_FIXTURE_DO_NOT_READ"));
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: approval dialogs bind to the requested write and respect rejection", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-approval-"));
  let n = 0;
  const endpoint = await mockEndpoint((): Reply => {
    if (n++ < 2) return { tool: "mcp__research__remember_research", args: { kind: "constraint", status: "active", text: n === 1 ? "Approved CPU constraint" : "Rejected GPU constraint" } };
    return { text: "Approval fixture completed." };
  });
  const app = new ResearchProcess(root, join(root, ".test-agent"), endpoint.url, ["--permission", "ask"]);
  try {
    const prompted = app.prompt("Exercise approval and rejection.");
    const first = await app.wait(e => e.type === "extension_ui_request" && e.method === "confirm");
    assert(first.message.includes("Approved CPU constraint"));
    app.child.stdin.write(JSON.stringify({ type: "extension_ui_response", id: first.id, confirmed: true }) + "\n");
    const second = await app.wait(e => e.type === "extension_ui_request" && e.method === "confirm" && e.id !== first.id);
    assert(second.message.includes("Rejected GPU constraint"));
    app.child.stdin.write(JSON.stringify({ type: "extension_ui_response", id: second.id, confirmed: false }) + "\n");
    await prompted;
    const results = app.events.filter(e => e.type === "tool_execution_end");
    assert.equal(results.length, 2);
    assert.equal(results[0].isError, false);
    assert.equal(results[1].isError, true);
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});
