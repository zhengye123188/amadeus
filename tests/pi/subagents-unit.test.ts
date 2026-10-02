import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mockEndpoint, ResearchProcess, toolResults, type Reply } from "./harness.ts";

test("real Pi: a human cancels an active child while the parent is waiting, then reuses its history", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-agent-human-cancel-"));
  let release: ((reply: Reply) => void) | undefined;
  let started!: () => void;
  const childStarted = new Promise<void>(resolve => { started = resolve; });
  let childCalls = 0;
  let cancelledId = "";
  const endpoint = await mockEndpoint(async req => {
    const system = JSON.stringify(req.messages.filter(message => message.role === "system"));
    if (system.includes("Research child role:")) {
      if (++childCalls === 1) {
        started();
        return new Promise<Reply>(resolve => { release = resolve; });
      }
      const content = JSON.stringify(req.messages);
      assert(content.includes("Inspect the evidence before cancellation"), "The original child question is retained");
      assert(content.includes("Retry after human cancellation"), "The follow-up reaches that child's history");
      assert(!content.includes("LATE_RESPONSE_MUST_NOT_APPEAR"), "A cancelled request cannot contribute a late completion");
      return { text: "The same child resumed after cancellation." };
    }
    const results = toolResults(req);
    if (!results.length) return { tool: "agent_tasks", args: { tasks: [{ role: "review", task: "Inspect the evidence before cancellation" }] } };
    if (results.length === 1) {
      assert.equal(results[0].agents[0].status, "cancelled", JSON.stringify(results));
      assert.equal(results[0].agents[0].id, cancelledId);
      return { tool: "agent_followup", args: { id: cancelledId, task: "Retry after human cancellation" } };
    }
    assert.equal(results[1].id, cancelledId);
    assert.equal(results[1].status, "completed", JSON.stringify(results));
    return { text: "Human cancellation and retained-history follow-up completed." };
  });
  const app = new ResearchProcess(root, join(root, "agent-runtime"), endpoint.url);
  try {
    const completed = app.prompt("Delegate a review. Resume it after the human cancels the first request.");
    const update = await app.wait(event => event.type === "tool_execution_update" && event.partialResult?.details?.agents?.some((agent: any) => agent.status === "running"));
    cancelledId = update.partialResult.details.agents[0].id;
    await childStarted;
    const result = await app.command("prompt", { message: `/agents cancel ${cancelledId}` });
    assert.equal(result.disposition, "handled", JSON.stringify(result));
    await completed;
    assert.equal(childCalls, 2);
    const cancellationNotice = app.events.find(event => event.type === "message_end" && event.message?.customType === "research-agents");
    assert.equal(JSON.parse(cancellationNotice.message.content).cancellation_requested, true);
  } finally {
    release?.({ text: "LATE_RESPONSE_MUST_NOT_APPEAR" });
    await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true });
  }
});

test("real Pi: parallel children cannot bypass the shared model-step limit", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-agent-step-limit-"));
  const endpoint = await mockEndpoint(req => {
    const system = JSON.stringify(req.messages.filter(message => message.role === "system"));
    if (system.includes("Research child role:")) return { tool: "mcp__research__project_status", args: {} };
    return { tool: "agent_tasks", args: { tasks: [{ role: "memory", task: "Inspect constraints" }, { role: "review", task: "Review evidence" }] } };
  });
  const app = new ResearchProcess(root, join(root, "agent-runtime"), endpoint.url, ["--max-turns", "2"]);
  try {
    await app.prompt("Delegate two analyses and enforce two total model steps, including the parent.");
    assert(endpoint.requests.length >= 1 && endpoint.requests.length <= 2, `Shared model-step cap exceeded: ${endpoint.requests.length}`);
    assert(app.events.some(event => JSON.stringify(event).includes("shared model-step budget")), "The shared limit must report why all requests stopped");
    const state = await app.command("get_state");
    assert.equal(state.isStreaming, false, "The parent settles after cancelling sibling agents");
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: child records do not leak into a new parent session", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-agent-session-isolation-"));
  let nextSession = false;
  let previousId = "";
  const endpoint = await mockEndpoint(req => {
    const system = JSON.stringify(req.messages.filter(message => message.role === "system"));
    if (system.includes("Research child role:")) return { text: "Initial child evidence analysis." };
    const results = toolResults(req);
    if (!nextSession) {
      if (!results.length) return { tool: "agent_tasks", args: { tasks: [{ role: "memory", task: "Inspect initial session" }] } };
      previousId = results[0].agents[0].id;
      assert.equal(results[0].agents[0].status, "completed");
      return { text: "Initial child completed." };
    }
    if (!results.length) return { tool: "agent_status", args: {} };
    assert.deepEqual(results[0].agents, [], "A new parent session begins without previous child records");
    assert(!JSON.stringify(req).includes(previousId), "Prior child IDs are not in the new parent model context");
    return { text: "New session contains no prior children." };
  });
  const app = new ResearchProcess(root, join(root, "agent-runtime"), endpoint.url);
  try {
    await app.prompt("Analyze initial session constraints with a child.");
    assert(previousId.startsWith("agent_"));
    const next = await app.command("new_session");
    assert.equal(next.cancelled, false);
    nextSession = true;
    await app.prompt("Inspect the new session child records.");
  } finally { await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true }); }
});

test("real Pi: the parent elapsed-time budget cancels a waiting child and settles", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-agent-time-limit-"));
  let release: ((reply: Reply) => void) | undefined;
  const endpoint = await mockEndpoint(req => {
    const system = JSON.stringify(req.messages.filter(message => message.role === "system"));
    if (system.includes("Research child role:")) return new Promise<Reply>(resolve => { release = resolve; });
    return { tool: "agent_tasks", args: { tasks: [{ role: "memory", task: "Inspect constraints under the shared deadline" }] } };
  });
  const app = new ResearchProcess(root, join(root, "agent-runtime"), endpoint.url, ["--max-seconds", "3"]);
  try {
    await app.prompt("Delegate a read-only child and enforce a three-second turn budget.");
    assert(endpoint.requests.some(req => JSON.stringify(req.messages).includes("Research child role:")), "The child model request actually starts");
    assert(app.events.some(event => JSON.stringify(event).includes("shared time budget")));
    assert.equal((await app.command("get_state")).isStreaming, false);
  } finally {
    release?.({ text: "Late completion after elapsed limit." });
    await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true });
  }
});

test("real Pi: shutdown cancels an active child without waiting for the model response", { timeout: 60000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-agent-shutdown-"));
  let release: ((reply: Reply) => void) | undefined;
  let started!: () => void;
  const childStarted = new Promise<void>(resolve => { started = resolve; });
  const endpoint = await mockEndpoint(req => {
    const system = JSON.stringify(req.messages.filter(message => message.role === "system"));
    if (system.includes("Research child role:")) {
      started();
      return new Promise<Reply>(resolve => { release = resolve; });
    }
    return { tool: "agent_tasks", args: { tasks: [{ role: "review", task: "Review evidence while the session remains open" }] } };
  });
  const app = new ResearchProcess(root, join(root, "agent-runtime"), endpoint.url);
  try {
    await app.command("prompt", { message: "Delegate one read-only review." });
    await childStarted;
    await app.close();
    assert.equal(app.child.exitCode, 0, "Graceful EOF shutdown finishes without the harness SIGTERM fallback");
    assert.equal(app.child.signalCode, null);
  } finally {
    release?.({ text: "Late completion after session shutdown." });
    await app.close(); await endpoint.close(); rmSync(root, { recursive: true, force: true });
  }
});
