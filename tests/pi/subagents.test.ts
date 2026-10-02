import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { agentRoles, roleTools } from "../../pi/agent-roles.ts";
import { effects } from "../../pi/policy.ts";
import { mockEndpoint, ResearchProcess, toolResults } from "./harness.ts";

test("role capabilities match research policies and exclude writes, execution and nested delegation", () => {
  for (const role of Object.keys(agentRoles) as (keyof typeof agentRoles)[]) {
    const names = roleTools(role, agentRoles[role].tools);
    assert(names.length > 3);
    assert(!names.some(name => ["write", "edit", "bash", "agent_tasks"].includes(name)));
    for (const name of names.filter(name => name.startsWith("mcp__research__"))) {
      assert.equal(effects[name.slice("mcp__research__".length)], "read", `${role}: ${name}`);
    }
    assert.deepEqual(roleTools(role, []), []);
  }
});

test("real Pi: parallel category agents share the parent model and guarded MCP, with follow-up history and usage", { timeout: 90000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-agents-"));
  writeFileSync(join(root, "code.py"), "print('fixture code')\n");
  writeFileSync(join(root, ".env"), "SECRET_MUST_NOT_REACH_CHILD");
  mkdirSync(join(root, ".pi", "agents"), { recursive: true });
  writeFileSync(join(root, "AGENTS.md"), "AMBIENT_INSTRUCTION_MUST_NOT_LOAD");
  writeFileSync(join(root, ".pi", "agents", "code.md"), "AMBIENT_AGENT_MUST_NOT_LOAD");
  let parentStep = 0;
  let codeId = "";
  let childrenActive = 0, peakActive = 0;
  const endpoint = await mockEndpoint(async req => {
    const payload = JSON.stringify(req);
    assert(!payload.includes("SECRET_MUST_NOT_REACH_CHILD"));
    assert(!payload.includes("AMBIENT_INSTRUCTION_MUST_NOT_LOAD"));
    assert(!payload.includes("AMBIENT_AGENT_MUST_NOT_LOAD"));
    const system = req.messages.filter(message => message.role === "system").map(message => String(message.content)).join("\n");
    if (system.includes("Research child role:")) {
      assert(req.tools?.length);
      const names = req.tools!.map(tool => tool.function.name);
      assert(!names.some(name => ["write", "edit", "bash", "agent_tasks", "mcp__research__run_experiment"].includes(name)));
      const results = toolResults(req);
      if (system.includes("Research child role: code")) {
        assert(names.includes("read"));
        assert(!names.includes("mcp__research__search_papers"));
        if (payload.includes("Follow-up question")) {
          assert(payload.includes("Code analysis complete"), "The same child's history is retained");
          return { text: "Follow-up uses the retained code analysis." };
        }
        if (!results.length) return { tool: "read", args: { path: ".env" } };
        if (results.length === 1) {
          assert(JSON.stringify(results).includes("blocked"));
          return { tool: "mcp__research__list_files", args: {} };
        }
        assert(JSON.stringify(results).includes("code.py"), "The child uses the parent's live research backend");
      } else {
        assert(system.includes("Research child role: experiments"));
        assert(!names.includes("read"));
        if (!results.length) return { tool: "mcp__research__project_status", args: {} };
        assert(results[0].ok, JSON.stringify(results));
      }
      childrenActive++; peakActive = Math.max(peakActive, childrenActive);
      await new Promise(resolve => setTimeout(resolve, 100));
      childrenActive--;
      return { text: system.includes("role: code") ? "Code analysis complete." : "Experiment analysis complete." };
    }
    const results = toolResults(req);
    if (parentStep++ === 0) return { tool: "agent_tasks", args: { tasks: [{ role: "code", task: "Inspect workspace code and protection." }, { role: "experiments", task: "Inspect existing project experiments." }] } };
    if (parentStep === 2) {
      assert.equal(results[0].agents.length, 2, JSON.stringify(results));
      assert(results[0].agents.every((agent: any) => agent.status === "completed"), JSON.stringify(results));
      codeId = results[0].agents.find((agent: any) => agent.role === "code").id;
      assert(results[0].agents.every((agent: any) => agent.provider === "research-endpoint" && agent.model === "fixture"));
      return { tool: "agent_followup", args: { id: codeId, task: "Follow-up question: summarize the prior analysis." } };
    }
    assert.equal(results[1].id, codeId);
    assert.equal(results[1].status, "completed", JSON.stringify(results));
    return { text: "Parallel analyses and follow-up completed." };
  });
  const app = new ResearchProcess(root, join(root, "agent-runtime"), endpoint.url);
  try {
    await app.prompt("Delegate independent code and experiment analysis by role, then ask the code agent a follow-up.");
    assert(codeId.startsWith("agent_"));
    assert.equal(peakActive, 2, "Child provider calls overlap");
    assert.equal(endpoint.authFailures(), 0, "Children inherit custom endpoint authentication");
    const rows = readFileSync(join(root, ".research", "usage.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
    assert.equal(rows.length, endpoint.requests.length, "Each parent/child provider response is counted once");
    assert.equal(rows.filter(row => row.agent_id).length, 6);
    assert(rows.filter(row => row.agent_id).every(row => row.parent_session_id === row.session_id && row.estimated_cost_usd === null));
    const commands = await app.command("get_commands");
    assert(commands.commands.some((command: any) => command.name === "agents"));
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: parent and children consume the same token budget", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-agent-budget-"));
  const endpoint = await mockEndpoint(req => {
    const system = JSON.stringify(req.messages.filter(message => message.role === "system"));
    if (system.includes("Research child role:")) return { tool: "mcp__research__project_status", args: {} };
    return { tool: "agent_tasks", args: { tasks: [{ role: "memory", task: "Inspect constraints" }, { role: "review", task: "Review current evidence" }] } };
  });
  const app = new ResearchProcess(root, join(root, "agent-runtime"), endpoint.url, ["--max-tokens", "300"]);
  try {
    await app.prompt("Exercise the shared usage limit with parallel agents.");
    assert(endpoint.requests.length >= 2 && endpoint.requests.length <= 3, `Unexpected requests: ${endpoint.requests.length}`);
    const rows = readFileSync(join(root, ".research", "usage.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
    assert(rows.some(row => row.agent_id), "Child usage contributes to the shared ledger");
    assert(app.events.some(event => JSON.stringify(event).includes("shared token/cost budget")));
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});
