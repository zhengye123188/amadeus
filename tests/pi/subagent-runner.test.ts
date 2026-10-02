import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runDelegatedAgent, resolveSubagentEngineDirectory, SUBAGENT_ENGINE_VERSION,
  type DelegatedChildLaunch, type DelegatedChildSession, type DelegatedChildSessionFactory,
  type DelegatedRunInput } from "../../pi/subagent-runner.ts";

function assistant(text: string, stopReason = "stop") {
  return { role: "assistant", content: [{ type: "text", text }], model: "inherited-model",
    provider: "parent-endpoint", api: "openai-completions", stopReason, timestamp: Date.now(),
    usage: { input: 12, output: 5, cacheRead: 3, cacheWrite: 2, totalTokens: 22,
      cost: { input: 0.001, output: 0.002, cacheRead: 0, cacheWrite: 0, total: 0.003 } } };
}

class ScriptedFactory implements DelegatedChildSessionFactory {
  launches: DelegatedChildLaunch[] = [];
  messages: any[] = [];
  listeners = new Set<(event: Record<string, any>) => void>();
  prompts: string[] = [];
  steers: string[] = [];
  followUps: string[] = [];
  aborts = 0;
  childDisposals = 0;
  factoryDisposals = 0;
  finishPrompt?: () => void;
  constructor(readonly script: (factory: ScriptedFactory) => Promise<void>) {}
  emit(event: Record<string, any>) {
    if (event.type === "message_end") this.messages.push(event.message);
    for (const listener of this.listeners) listener(event);
  }
  async create(launch: DelegatedChildLaunch): Promise<DelegatedChildSession> {
    this.launches.push(launch);
    const owner = this;
    return {
      subscribe(listener) { owner.listeners.add(listener); return () => { owner.listeners.delete(listener); }; },
      async prompt(text) { owner.prompts.push(text); await owner.script(owner); },
      async steer(text) { owner.steers.push(text); },
      async followUp(text) { owner.followUps.push(text); },
      async abort() { owner.aborts++; owner.finishPrompt?.(); },
      async dispose() { owner.childDisposals++; },
      hasQueuedMessages() { return false; },
      get messages() { return owner.messages; },
      sessionFile: undefined, sessionId: "child-fixture", modelId: "inherited-model",
    };
  }
  async dispose() { this.factoryDisposals++; }
}

function options(cwd: string, factory: ScriptedFactory, overrides: Partial<DelegatedRunInput> = {}): DelegatedRunInput {
  return { role: "literature", task: "Inspect only the delegated question", systemPrompt: "HOST_PROMPT",
    runId: "runner_test", cwd, model: "parent-endpoint/inherited-model", tools: ["read", "mcp__research__search_papers"],
    childSessionFactory: factory, timeoutMs: 10_000, ...overrides };
}

function snapshot(root: string, prefix = ""): Record<string, string> {
  const files: Record<string, string> = {};
  for (const item of readdirSync(join(root, prefix))) {
    const relative = join(prefix, item);
    if (statSync(join(root, relative)).isDirectory()) Object.assign(files, snapshot(root, relative));
    else files[relative] = readFileSync(join(root, relative), "utf8");
  }
  return files;
}

test("pinned Pi executor uses the host factory, inherited model/tool ceiling and no ambient resources", { timeout: 30_000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "research-child-runner-"));
  try {
    mkdirSync(join(root, ".pi", "extensions"), { recursive: true });
    mkdirSync(join(root, ".pi", "skills", "surprise"), { recursive: true });
    writeFileSync(join(root, "AGENTS.md"), "AMBIENT_INSTRUCTIONS_MUST_NOT_APPEAR");
    writeFileSync(join(root, ".pi", "settings.json"), JSON.stringify({ extensions: ["./extensions/surprise.ts"] }));
    writeFileSync(join(root, ".pi", "extensions", "surprise.ts"), "throw new Error('Ambient extension executed');");
    writeFileSync(join(root, ".pi", "skills", "surprise", "SKILL.md"), "AMBIENT_SKILL_MUST_NOT_APPEAR");
    const before = snapshot(root);
    const updates: Record<string, any>[] = [];
    const factory = new ScriptedFactory(async child => {
      child.emit({ type: "agent_start" });
      child.emit({ type: "turn_start" });
      child.emit({ type: "tool_execution_start", toolName: "read", toolCallId: "r1", args: { path: "README.md" } });
      child.emit({ type: "tool_execution_end", toolName: "read", toolCallId: "r1", result: { content: [{ type: "text", text: "Found README" }] } });
      child.emit({ type: "message_end", message: assistant("Checked the delegated sources") });
      child.emit({ type: "agent_end", messages: child.messages });
    });
    assert.equal(JSON.parse(readFileSync(join(resolveSubagentEngineDirectory(), "package.json"), "utf8")).version, SUBAGENT_ENGINE_VERSION);
    const result = await runDelegatedAgent(options(root, factory, { onUpdate: update => updates.push(update) }));
    assert.equal(result.exitCode, 0, JSON.stringify(result));
    assert.equal(result.finalOutput, "Checked the delegated sources");
    assert.equal(factory.launches.length, 1);
    const launch = factory.launches[0];
    assert.equal(launch.model, "parent-endpoint/inherited-model:off");
    assert.equal(launch.ambientExtensions, false);
    assert.deepEqual(launch.extensionPaths, []);
    assert.deepEqual(launch.hooks, []);
    assert.deepEqual(launch.storage, { kind: "memory" });
    assert.equal(launch.noSkills, true);
    assert.equal(launch.noContextFiles, true);
    assert.deepEqual(launch.tools, ["read", "mcp__research__search_papers"]);
    assert.equal(launch.systemPrompt, '<active_agent name="literature"/>\n\nHOST_PROMPT');
    assert(!JSON.stringify(launch).includes("AMBIENT_"));
    assert.equal(factory.prompts[0], "Task: Inspect only the delegated question");
    assert.equal(factory.childDisposals, 1);
    assert.equal(factory.factoryDisposals, 1);
    assert.equal(factory.listeners.size, 0);
    assert.deepEqual(result.usage, { input: 12, output: 5, cacheRead: 3, cacheWrite: 2, cost: 0.003, turns: 1 });
    assert.equal(result.progressSummary?.toolCount, 1);
    assert(updates.length > 0);
    assert(updates.every(update => !JSON.stringify(update).includes("AMBIENT_")));
    assert.deepEqual(snapshot(root), before, "Upstream must not write artifacts, sessions, supervisor files or settings");
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("pinned Pi executor passes steering/follow-up to the controlled child and releases it", async () => {
  const root = mkdtempSync(join(tmpdir(), "research-child-steer-"));
  const factory = new ScriptedFactory(async child => { child.emit({ type: "message_end", message: assistant("Updated") }); });
  try {
    const result = await runDelegatedAgent(options(root, factory, { onSession: controls => {
      void controls.steer("Prioritize reproducibility");
      void controls.followUp("Check the repository license");
    } }));
    assert.equal(result.exitCode, 0, JSON.stringify(result));
    assert.deepEqual(factory.steers, ["Prioritize reproducibility"]);
    assert.deepEqual(factory.followUps, ["Check the repository license"]);
    assert.equal(factory.factoryDisposals, 1);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("pinned Pi executor aborts the child on caller cancellation without launching a replacement", async () => {
  const root = mkdtempSync(join(tmpdir(), "research-child-abort-"));
  const controller = new AbortController();
  const factory = new ScriptedFactory(async child => {
    child.emit({ type: "agent_start" });
    await new Promise<void>(resolve => { child.finishPrompt = resolve; controller.abort(); });
  });
  try {
    const result = await runDelegatedAgent(options(root, factory, { signal: controller.signal }));
    assert.equal(result.exitCode, 1);
    assert.equal(result.stopped, true);
    assert.match(result.error || "", /stopped before completion/);
    assert.equal(factory.launches.length, 1);
    assert.equal(factory.aborts, 1);
    assert.equal(factory.childDisposals, 1);
    assert.equal(factory.factoryDisposals, 1);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("pinned Pi executor enforces its elapsed timeout and bounds returned output", async () => {
  const root = mkdtempSync(join(tmpdir(), "research-child-bounds-"));
  try {
    const hanging = new ScriptedFactory(async child => {
      await new Promise<void>(resolve => { child.finishPrompt = resolve; });
    });
    // Keep the test alive while the upstream watchdog correctly uses unref timers.
    const keepAlive = setTimeout(() => undefined, 1000);
    try {
      const timedOut = await runDelegatedAgent(options(root, hanging, { timeoutMs: 20 }));
      assert.equal(timedOut.timedOut, true);
      assert.equal(timedOut.exitCode, 1);
      assert.equal(hanging.aborts, 1);
      assert.equal(hanging.factoryDisposals, 1);
    } finally { clearTimeout(keepAlive); }
    const verbose = new ScriptedFactory(async child => { child.emit({ type: "message_end", message: assistant("信息".repeat(60_000)) }); });
    const result = await runDelegatedAgent(options(root, verbose));
    assert.equal(result.exitCode, 0, JSON.stringify(result));
    assert.equal(result.truncation?.truncated, true);
    assert((result.finalOutput || "").length < 60_000);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("delegation rejects malformed model, roles, timeout and tool selectors before creating a child", async () => {
  const root = mkdtempSync(join(tmpdir(), "research-child-invalid-"));
  const factory = new ScriptedFactory(async () => {});
  try {
    for (const patch of [{ model: "unqualified" }, { role: "../other" }, { timeoutMs: 0 }, { tools: ["../evil-extension.ts"] }]) {
      await assert.rejects(runDelegatedAgent(options(root, factory, patch)), /required|Invalid/);
    }
    assert.equal(factory.launches.length, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
